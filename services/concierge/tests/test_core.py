"""Core flows: ambiguity, labels, pickups while guiding, stop, reset, trials, feedback, timeout."""
import asyncio
import time

from conftest import Harness, make_settings, snapshot, state
from earmark_contracts import (
    GuideFeedback, Pickup, Playback, RegistryUpdate, Reset, TrialEnd, TrialStart, UnknownTag,
)


async def test_something_for_my_eggs_asks_salt_or_pepper_then_resolves(h):
    out = await h.say("I need something for my eggs.")
    assert h.spoken(out) == ["Do you mean the salt or the pepper?"]
    assert not h.of("guide_start", out)
    out = await h.say("The salt.")
    [g] = h.of("guide_start", out)
    assert g["object_id"] == "salt"
    assert h.spoken(out) == ["The salt is at your eleven o'clock, about an arm's length away."]


async def test_clarification_follow_up_variants(h):
    await h.say("something for my eggs")
    out = await h.say("pepper please")
    assert h.spoken(out)[0].startswith("I haven't detected the pepper yet. Its notes say:")
    await h.say("something for my eggs")
    out = await h.say("the first one")
    assert h.of("guide_start", out)[0]["object_id"] == "salt"


async def test_unrelated_follow_up_is_a_fresh_request(h):
    await h.say("something for my eggs")
    out = await h.say("Where's the sugar?")
    assert h.of("guide_start", out)[0]["object_id"] == "sugar"
    await h.say("something for my eggs")
    out = await h.say("stop")
    assert h.of("speak_cached", out)[0]["phrase_id"] == "stopping"


async def test_label_flow_after_unknown_tag(h):
    out = await h.say("This is honey.")
    assert h.of("speak_cached", out)[0]["phrase_id"] == "no_new_tag"
    assert not h.of("label", out)
    await h.feed(UnknownTag(tag="04A1B2C3D4E5FF", spot=1))
    out = await h.say("This is honey.")
    [lb] = h.of("label", out)
    assert (lb["tag"], lb["name"], lb["aliases"], lb["spot"]) == ("04A1B2C3D4E5FF", "honey", [], 1)
    assert h.spoken(out) == ["Okay, I'll remember this as honey."]


async def test_stale_unknown_tag_is_not_used(h):
    await h.feed(UnknownTag(tag="04A1B2C3D4E5FF", spot=1, t=time.time() - h.settings.label_window_s - 1))
    out = await h.say("this is honey")
    assert h.of("speak_cached", out)[0]["phrase_id"] == "no_new_tag"


async def test_registry_update_makes_new_label_resolvable(h):
    from conftest import OBJECTS
    from earmark_contracts import RegistryObject
    honey = RegistryObject(object_id="honey", name="honey", aliases=[], notes="", description="",
                           tag="04A1B2C3D4E5FF", home_spot=1, is_medication=False, fob_id=None)
    await h.feed(RegistryUpdate(objects=[*OBJECTS, honey], registry_version=2), state("honey", spot=1))
    out = await h.say("where's the honey")
    assert h.of("guide_start", out)[0]["object_id"] == "honey"


async def test_target_pickup_confirms_and_stops(h):
    await h.say("Where's the sugar?")
    h.clear()
    await h.feed(Pickup(object_id="sugar", from_spot=3))
    assert h.of("guide_stop")[0]["reason"] == "found"
    assert h.of("pickup_result")[0] | {"t": 0} == {"type": "pickup_result", "expected": "sugar",
                                                   "actual": "sugar", "correct": True, "t": 0}
    assert h.spoken(h.out) == ["Got it, that's the sugar."]
    assert h.core.guiding is None


async def test_wrong_pickup_corrects_with_relative_spot(h):
    await h.say("Where's the sugar?")
    h.clear()
    await h.feed(Pickup(object_id="salt", from_spot=2), state("salt", status="held", precision="none"))
    [r] = h.of("pickup_result")
    assert (r["expected"], r["actual"], r["correct"]) == ("sugar", "salt", False)
    assert h.spoken(h.out) == ["That's the salt. The sugar is one spot to your right."]
    assert not h.of("guide_stop") and h.core.guiding.object_id == "sugar"


async def test_wrong_pickup_two_spots_left(h):
    await h.say("where is the salt")
    h.clear()
    await h.feed(Pickup(object_id="bp_meds", from_spot=4))
    assert h.spoken(h.out) == ["That's the blood pressure pills. The salt is two spots to your left."]


async def test_wrong_pickup_when_target_is_not_on_a_spot(settings):
    h = Harness(settings)
    await h.feed(snapshot())
    await h.say("Where's the sugar?")
    h.clear()
    # Sugar becomes known only by position (e.g. a camera adapter), not on a spot.
    from earmark_contracts import Location, ObjectState
    await h.feed(ObjectState(object_id="sugar", location=Location(position=[0.6, 0.0, 0.0]), precision="exact",
                             status="roaming", home_spot=3, last_seen_t=time.time(), source="camera"))
    await h.feed(Pickup(object_id="salt", from_spot=2))
    assert h.spoken(h.out) == ["That's the salt. The sugar is at your three o'clock, about an arm's length away."]
    h.clear()
    await h.feed(state("sugar", precision="none", status="missing"), Pickup(object_id="bp_meds", from_spot=4))
    assert h.spoken(h.out) == ["That's the blood pressure pills. I'm not sure where the sugar is right now."]


async def test_moving_the_target_retargets_guidance(h):
    await h.say("Where's the sugar?")
    h.clear()
    await h.feed(state("sugar", spot=1))
    [g] = h.of("guide_start")
    assert g["target_position"] == [-0.42, 0.42, 0.0]


async def test_stop_and_cancel(h):
    for word in ("stop", "Cancel"):
        await h.say("Where's the sugar?")
        out = await h.say(word)
        assert h.of("guide_stop", out)[0]["reason"] == "cancelled"
        assert h.of("speak_cached", out)[0]["phrase_id"] == "stopping"


async def test_stop_also_stops_chirps(h):
    await h.feed(state("keys", near="hub", distance_class="far"))
    await h.say("where are my keys")
    out = await h.say("stop")
    assert [c["action"] for c in h.of("chirp", out)] == ["stop"]


async def test_reset_clears_everything_silently(h):
    await h.feed(state("keys", near="hub", distance_class="near"))
    await h.say("where are my keys")
    await h.say("Where's the sugar?")
    await h.say("something for my eggs")
    h.clear()
    await h.feed(Reset())
    assert h.of("guide_stop")[0]["reason"] == "reset"
    assert h.of("chirp")[0]["action"] == "stop"
    assert not h.spoken(h.out) and h.core.pending is None and h.core.guiding is None


async def test_baseline_trial_is_silent_until_trial_end(h):
    await h.say("Where's the sugar?")
    h.clear()
    await h.feed(TrialStart(trial_id="t1", mode="baseline", target_object_id="sugar", tester="p1"))
    assert h.of("guide_stop")[0]["reason"] == "cancelled"
    h.clear()
    out = await h.say("Where's the sugar?")
    assert [m["type"] for m in out] == ["transcript"]
    await h.feed(Pickup(object_id="salt", from_spot=2))
    assert not h.of("pickup_result")
    await h.feed(TrialEnd(trial_id="t1", mode="baseline", target_object_id="sugar", tester="p1",
                          outcome="found", started_t=0, seconds_to_find=4.0, wrong_picks=1))
    out = await h.say("Where's the sugar?")
    assert h.of("guide_start", out)


async def test_behind_feedback_is_rate_limited(h):
    await h.say("Where's the sugar?")
    h.clear()
    fb = dict(object_id="sugar", event="behind", error_deg=150.0)
    await h.feed(GuideFeedback(turn="left", **fb), GuideFeedback(turn="right", **fb))
    assert [m["phrase_id"] for m in h.of("speak_cached")] == ["behind_turn_left"]
    h.core._last_behind -= h.settings.behind_cooldown_s
    await h.feed(GuideFeedback(turn="right", **fb), GuideFeedback(object_id="salt", event="behind",
                                                                 turn="left", error_deg=120.0))
    assert [m["phrase_id"] for m in h.of("speak_cached")] == ["behind_turn_left", "behind_turn_right"]


async def test_guidance_times_out(tmp_path):
    h = Harness(make_settings(tmp_path, guide_timeout_s=0.05))
    await h.feed(snapshot())
    await h.say("Where's the sugar?")
    h.clear()
    await asyncio.sleep(0.1)
    await h.core.drain()
    assert h.of("guide_stop")[0]["reason"] == "timeout"
    assert h.spoken(h.out) == ["I've stopped the guide sound for the sugar."]


async def test_pronoun_follow_up(h):
    await h.say("Where's the sugar?")
    out = await h.say("make it beep")
    assert h.spoken(out)[0].startswith("The sugar doesn't have a beeper.")


async def test_latency_log_has_every_stage(h):
    import json
    out = await h.say("Where's the sugar?")
    uid = h.of("guide_start", out)[0]["utterance_id"]
    await h.feed(Playback(utterance_id=uid, event="started"))
    events = [json.loads(line)["event"] for line in h.settings.latency_log.read_text().splitlines()]
    for e in ("final_transcript", "intent", "resolve", "tool", "speech_out", "playback"):
        assert e in events, e


async def test_moss_mode_and_latency_published_in_status(settings):
    from test_resolver import FakeIndex
    from earmark_concierge.moss_index import Hit
    h = Harness(settings)
    h.core.resolver.index = FakeIndex({"something sweet for tea": [Hit("sugar", 0.7)]})
    await h.feed(snapshot())
    assert h.of("status")[-1]["info"]["resolver"] == "moss"
    out = await h.say("I need something sweet for tea")
    assert h.of("guide_start", out)[0]["object_id"] == "sugar"
    assert h.core.status_msg().info["moss_ms"] is not None


async def test_status_reports_modes(h):
    s = h.core.status_msg()
    assert s.component == "concierge" and s.info["stt_engine"] == "apple"
    assert s.info["intent_engine"] == "grammar" and s.info["resolver"] == "fallback"
    assert s.info["tts"] == "system"


def test_snapshot_household_sets_timezone_unless_pinned():
    from earmark_contracts import Household

    from earmark_concierge.world import World

    snap = snapshot().model_copy(update={"household": Household(name="h", timezone="Asia/Seoul")})
    w = World("America/Los_Angeles")
    w.apply_snapshot(snap)
    assert w.timezone == "Asia/Seoul"
    pinned = World("UTC", pinned=True)
    pinned.apply_snapshot(snap)
    assert pinned.timezone == "UTC"


async def test_mac_app_reporting_wrong_stt_engine_gets_stt_mode_resent(h):
    from earmark_contracts import StatusMsg

    engine = h.core.stt.engine
    wrong = "cartesia" if engine == "apple" else "apple"
    h.clear()
    await h.feed(StatusMsg(component="mac_app", ok=True, detail="x", info={"stt_engine": wrong}))
    modes = h.of("stt_mode")
    assert len(modes) == 1 and modes[0]["engine"] == engine
    h.clear()
    await h.feed(StatusMsg(component="mac_app", ok=True, detail="x", info={"stt_engine": engine}))
    assert not h.of("stt_mode")
