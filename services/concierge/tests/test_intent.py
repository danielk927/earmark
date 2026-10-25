"""LLM vs grammar: timeout, validation, label tag fill, and the real Bitdeer client shape."""
import asyncio
import json

import httpx2  # the openai SDK's HTTP client
import pytest

from conftest import OBJECTS, Harness, snapshot
from earmark_contracts import UnknownTag
from earmark_concierge.intent import BitdeerChooser, IntentRouter
from earmark_concierge.tools import InvalidToolCall, validate_llm_call
from earmark_concierge.world import World


class FakeChooser:
    vendor = "bitdeer"

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
    assert d.llm_ms is not None and d.vendor == "bitdeer"


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


async def test_bitdeer_chooser_request_shape():
    """The real client sends reasoning_effort none, tool_choice required, one tool per turn."""
    captured = {}

    def handler(request: httpx2.Request) -> httpx2.Response:
        captured["url"] = str(request.url)
        captured["auth"] = request.headers["authorization"]
        captured["body"] = json.loads(request.content)
        return httpx2.Response(200, json={
            "id": "x", "object": "chat.completion", "created": 0, "model": "m",
            "choices": [{"index": 0, "finish_reason": "tool_calls", "message": {
                "role": "assistant", "content": None,
                "tool_calls": [{"id": "c1", "type": "function",
                                "function": {"name": "locate_object", "arguments": '{"name": "sugar"}'}}]}}],
        })

    ch = BitdeerChooser("sk-test", "https://api-inference.bitdeer.ai/v1", "nvidia/test-model", 1.5)
    ch.client = ch.client.with_options(http_client=httpx2.AsyncClient(transport=httpx2.MockTransport(handler)))
    calls = await ch.choose("where's the sugar", world())
    assert calls == [("locate_object", '{"name": "sugar"}')]
    b = captured["body"]
    assert captured["url"] == "https://api-inference.bitdeer.ai/v1/chat/completions"
    assert captured["auth"] == "Bearer sk-test"
    assert b["model"] == "nvidia/test-model" and b["tool_choice"] == "required"
    assert b["reasoning_effort"] == "none" and b["parallel_tool_calls"] is False
    assert [t["function"]["name"] for t in b["tools"]] == [
        "locate_object", "guide_to_object", "chirp_fob", "label_object", "last_seen",
        "stop_guidance", "list_objects", "freeze_listener", "recenter_listener"]

