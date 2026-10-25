"""LLM vs grammar: timeout, validation, label tag fill, and the real Claude client shape."""
import asyncio
import json

import httpx2  # the anthropic SDK's HTTP client
import pytest

from conftest import OBJECTS, Harness, snapshot
from earmark_contracts import UnknownTag
from earmark_concierge.intent import AnthropicChooser, IntentRouter
from earmark_concierge.tools import InvalidToolCall, system_prompt, validate_llm_call
from earmark_concierge.world import World


class FakeChooser:
    vendor = "anthropic"

    def __init__(self, calls=None, delay=0.0, error=None):
        self.calls = calls if calls is not None else []
        self.delay = delay
        self.error = error
        self.seen = []

    async def choose(self, text, world):
        self.seen.append(text)
        await asyncio.sleep(self.delay)
        if self.error:
            raise self.error
        return self.calls


def world():
    w = World()
    w.set_objects(OBJECTS)
    return w


async def test_llm_disabled_uses_grammar():
    d = await IntentRouter(None, 1.5).decide("where's the sugar", world())
    assert (d.path, d.llm_status, d.call.args) == ("grammar", "disabled", {"query": "sugar"})


async def test_valid_llm_call_wins():
    r = IntentRouter(FakeChooser([("guide_to_object", '{"object_id": "sugar"}')]), 1.5)
    d = await r.decide("I want to put sugar in my coffee", world())
    assert (d.path, d.llm_status, d.call.name, d.call.args) == ("llm", "ok", "guide_to_object",
                                                                 {"object_id": "sugar"})
    assert d.llm_ms is not None and d.vendor == "anthropic"


async def test_llm_timeout_falls_back_to_grammar():
    r = IntentRouter(FakeChooser([("list_objects", "{}")], delay=0.5), 0.1)
    d = await r.decide("Where's the sugar?", world())
    assert (d.path, d.llm_status, d.call.name) == ("grammar", "timeout", "locate_object")
    assert 90 <= d.llm_ms < 400


async def test_llm_error_falls_back_to_grammar():
    r = IntentRouter(FakeChooser(error=ConnectionError("down")), 1.5)
    d = await r.decide("stop", world())
    assert (d.path, d.llm_status, d.call.name) == ("grammar", "error", "stop_guidance")


@pytest.mark.parametrize("calls,status", [
    ([("guide_to_object", '{"object_id": "unicorn"}')], "invalid"),
    ([("teleport", "{}")], "invalid"),
    ([("chirp_fob", "not json")], "invalid"),
    ([("locate_object", '{"name": "sugar", "extra": 1}')], "invalid"),
    ([("locate_object", '{"name": ""}')], "declined"),
    ([("stop_guidance", "{}"), ("list_objects", "{}")], "invalid"),
    ([], "invalid"),
])
async def test_invalid_tool_calls_are_rejected(calls, status):
    d = await IntentRouter(FakeChooser(calls), 1.5).decide("where are my keys", world())
    assert (d.path, d.llm_status) == ("grammar", status)
    assert d.call.args == {"query": "keys"}


def test_label_validation_and_tag_rules():
    w = world()
    c = validate_llm_call("label_object", {"tag": "", "name": "The Honey", "aliases": ["Honey", "clover honey"]}, w)
    assert c.args == {"tag": "", "name": "honey", "aliases": ["clover honey"]}
    with pytest.raises(InvalidToolCall):
        validate_llm_call("label_object", {"tag": "DEADBEEF", "name": "honey"}, w)
    w.unknown_tag = UnknownTag(tag="DEADBEEF", spot=1)
    assert validate_llm_call("label_object", {"tag": "DEADBEEF", "name": "honey"}, w).args["tag"] == "DEADBEEF"
    with pytest.raises(InvalidToolCall):
        validate_llm_call("label_object", {"tag": "", "name": "  "}, w)


async def test_llm_label_with_empty_tag_is_filled_from_unknown_tag(settings):
    h = Harness(settings)
    h.core.router = IntentRouter(FakeChooser([("label_object", '{"tag": "", "name": "honey"}')]), 1.5)
    await h.feed(snapshot(), UnknownTag(tag="04A1B2C3D4E5FF", spot=1))
    out = await h.say("so this one here is honey")
    [lb] = h.of("label", out)
    assert (lb["tag"], lb["name"], lb["spot"]) == ("04A1B2C3D4E5FF", "honey", 1)


async def test_eager_prefetch_is_reused_on_matching_final():
    ch = FakeChooser([("guide_to_object", '{"object_id": "sugar"}')], delay=0.05)
    r = IntentRouter(ch, 1.5)
    r.prefetch("Where's the sugar", world())
    d = await r.decide("where's the sugar?", world())
    assert d.path == "llm" and len(ch.seen) == 1


async def test_anthropic_chooser_request_shape():
    """The real client forces one tool, turns thinking off, and reads the tool_use block back."""
    captured = {}

    def handler(request: httpx2.Request) -> httpx2.Response:
        captured["url"] = str(request.url)
        captured["auth"] = request.headers["authorization"]
        captured["body"] = json.loads(request.content)
        return httpx2.Response(200, json={
            "id": "msg_x", "type": "message", "role": "assistant", "model": "claude-haiku-5-5",
            "content": [{"type": "tool_use", "id": "tu_1", "name": "locate_object", "input": {"name": "sugar"}}],
            "stop_reason": "tool_use", "stop_sequence": None,
            "usage": {"input_tokens": 10, "output_tokens": 5},
        })

    ch = AnthropicChooser("sk-test", "claude-haiku-5-5", 1.5)
    ch.client = ch.client.with_options(http_client=httpx2.AsyncClient(transport=httpx2.MockTransport(handler)))
    calls = await ch.choose("where's the sugar", world())
    assert calls == [("locate_object", '{"name": "sugar"}')]
    b = captured["body"]
    assert captured["url"] == "https://api.anthropic.com/v1/messages"
    assert captured["auth"] == "Bearer sk-test"
    assert b["model"] == "claude-haiku-5-5"
    assert b["tool_choice"] == {"type": "any", "disable_parallel_tool_use": True}
    assert b["thinking"] == {"type": "disabled"} and b["output_config"] == {"effort": "low"}
    assert "temperature" not in b
    assert [t["name"] for t in b["tools"]] == [
        "locate_object", "guide_to_object", "chirp_fob", "label_object", "last_seen",
        "put_in_place", "place_history", "stop_guidance", "list_objects"]
    assert all("input_schema" in t for t in b["tools"])


async def test_system_prompt_names_the_last_item_for_it():
    w = world()
    assert "Last item discussed" not in system_prompt(w)
    w.last_object = "keys"
    assert "Last item discussed: keys (keys)" in system_prompt(w)


async def test_make_it_beep_with_claude_on_uses_the_last_item(h):
    seen = []

    class Ch(FakeChooser):
        async def choose(self, text, world):
            seen.append(system_prompt(world))
            return [("chirp_fob", json.dumps({"object_id": world.last_object}))]

    h.core.router.chooser = Ch()
    await h.say("where are my keys")
    out = await h.say("make it beep")
    assert "Last item discussed: keys" in seen[-1]
    assert h.of("chirp", out)[0]["fob_id"] == "fob_keys"


async def test_put_in_place_takes_free_text_item_and_unknown_item_adds_it_here(h):
    from earmark_contracts import ListenerPose
    call = validate_llm_call("put_in_place", '{"name": "my glasses", "place": ""}', h.core.world)
    assert (call.name, call.args) == ("put_in_place", {"query": "my glasses", "area": ""})
    await h.feed(ListenerPose(position=[0.5, 0.5, 1.5], quality="ok", beacons_heard=5, source="beacons"))
    h.core.router.chooser = FakeChooser([("put_in_place", '{"name": "my glasses", "place": ""}')])
    out = await h.say("I'm leaving my glasses here")
    assert h.of("label", out)[0]["name"] == "glasses"
    assert h.of("place_item", out)[0]["object_id"] == "glasses"
