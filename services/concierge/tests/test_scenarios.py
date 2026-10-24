"""Scenario acceptance (BUILD_BRIEF 5.D, section 8 items 1-6) with no keys and the LLM disabled.

The hub is not available here, so each scenario's detection timeline is replaced by the
equivalent hub output (state_update / pickup / unknown_tag); the typed transcripts come
straight from scenarios/*.jsonl.
"""
import json

import pytest

from conftest import SPOT_POS, Harness, snapshot, state
from earmark_concierge.config import REPO_ROOT
from earmark_contracts import Pickup, UnknownTag

SUGAR_SPOT3 = "The sugar is at your one o'clock, about an arm's length away."
SUGAR_SPOT1 = "The sugar is at your ten o'clock, about an arm's length away."


def transcripts(name: str) -> list[str]:
    lines = [json.loads(l) for l in (REPO_ROOT / "scenarios" / f"{name}.jsonl").read_text().splitlines()]
    return [m["text"] for m in sorted(lines, key=lambda m: m["t"]) if m["type"] == "transcript"]


@pytest.fixture
async def h(settings):
    assert not settings.llm_enabled and not settings.cartesia_enabled and not settings.moss_enabled
    harness = Harness(settings)
    await harness.feed(snapshot())
    harness.clear()
    return harness


def guide(h, out):
    [g] = h.of("guide_start", out)
    return g["object_id"], g["target_position"], g["precision"]


async def test_where_is_the_sugar(h):
    [ask] = transcripts("wrong_jar")
    out = await h.say(ask)
    assert guide(h, out) == ("sugar", SPOT_POS[3], "exact")
    assert h.spoken(out) == [SUGAR_SPOT3]


async def test_wrong_jar(h):
    [ask] = transcripts("wrong_jar")
    await h.say(ask)
    h.clear()
    await h.feed(Pickup(object_id="salt", from_spot=2), state("salt", status="held", precision="none"))
    [r] = h.of("pickup_result")
    assert (r["expected"], r["actual"], r["correct"]) == ("sugar", "salt", False)
    assert h.spoken(h.out) == ["That's the salt. The sugar is one spot to your right."]
    h.clear()
    await h.feed(state("salt", spot=2), Pickup(object_id="sugar", from_spot=3))
    assert h.of("guide_stop")[0]["reason"] == "found" and h.of("pickup_result")[0]["correct"] is True
    assert h.spoken(h.out) == ["Got it, that's the sugar."]


async def test_moved_item(h):
    [ask] = transcripts("moved_item")
    await h.feed(Pickup(object_id="sugar", from_spot=3), state("sugar", status="held", precision="none"),
                 state("sugar", spot=1))
    out = await h.say(ask)
    assert guide(h, out) == ("sugar", SPOT_POS[1], "exact")
    assert h.spoken(out) == [SUGAR_SPOT1]


async def test_roaming_keys(h):
    [ask] = transcripts("roaming_keys")
    await h.feed(state("keys", near="hub", distance_class="mid"))
    out = await h.say(ask)
    [c] = h.of("chirp", out)
    assert (c["fob_id"], c["action"]) == ("fob_keys", "start")
    assert h.spoken(out) == ["The keys are near the counter. I'll make them beep."]


async def test_roaming_keys_asked_before_the_fob_is_heard(h):
    """The scenario asks at t=3, before the fob's first read at t=5: still chirp."""
    [ask] = transcripts("roaming_keys")
    out = await h.say(ask)
    assert h.of("chirp", out)[0]["fob_id"] == "fob_keys"
    assert h.spoken(out) == ["I haven't detected the keys yet. I'll make them beep."]


async def test_something_for_my_eggs(h):
    ask = transcripts("full_demo")[-1]
    assert "eggs" in ask
    out = await h.say(ask)
    assert h.spoken(out) == ["Do you mean the salt or the pepper?"]
    assert not h.of("guide_start", out) and not h.of("chirp", out)


async def test_label_new_item(h):
    [ask] = transcripts("label_new_item")
    await h.feed(UnknownTag(tag="04A1B2C3D4E5FF", spot=1))
    out = await h.say(ask)
    [lb] = h.of("label", out)
    assert (lb["tag"], lb["name"], lb["spot"]) == ("04A1B2C3D4E5FF", "honey", 1)


@pytest.mark.parametrize("word", ["stop", "cancel", "Stop.", "Cancel that."])
async def test_stop_cancel(h, word):
    await h.say("Where's the sugar?")
    out = await h.say(word)
    assert h.of("guide_stop", out)[0]["reason"] == "cancelled"
    assert h.of("speak_cached", out)[0]["phrase_id"] == "stopping"


async def test_full_demo_in_order(h):
    asks = transcripts("full_demo")
    assert len(asks) == 4
    # 1. Where's the sugar? -> spot 3
    out = await h.say(asks[0])
    assert guide(h, out)[1] == SPOT_POS[3] and h.spoken(out) == [SUGAR_SPOT3]
    # 2. salt lifted -> correction; 3. salt back
    h.clear()
    await h.feed(Pickup(object_id="salt", from_spot=2), state("salt", status="held", precision="none"))
    assert h.spoken(h.out) == ["That's the salt. The sugar is one spot to your right."]
    await h.feed(state("salt", spot=2))
    # 4. sugar lifted -> confirmation; 5. sugar put down on spot 1
    h.clear()
    await h.feed(Pickup(object_id="sugar", from_spot=3), state("sugar", status="held", precision="none"))
    assert h.spoken(h.out) == ["Got it, that's the sugar."]
    await h.feed(state("sugar", spot=1))
    # 6. Where's the sugar? -> spot 1; 7. lifted -> confirmation, back home
    out = await h.say(asks[1])
    assert guide(h, out)[1] == SPOT_POS[1] and h.spoken(out) == [SUGAR_SPOT1]
    h.clear()
    await h.feed(Pickup(object_id="sugar", from_spot=1))
    assert h.spoken(h.out) == ["Got it, that's the sugar."]
    await h.feed(state("sugar", spot=3))
    # 8. Where are my keys? -> chirp (fob first heard right after, as in the scenario)
    out = await h.say(asks[2])
    assert h.of("chirp", out)[0]["fob_id"] == "fob_keys"
    await h.feed(state("keys", near="hub", distance_class="far"))
    # 9. something for my eggs -> asks which one
    out = await h.say(asks[3])
    assert h.spoken(out) == ["Do you mean the salt or the pepper?"]
