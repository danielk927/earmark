"""Response policy by precision, driven through the core with the grammar (no keys)."""
import time

from conftest import SPOT_POS, snapshot, state
from earmark_contracts import Pickup


async def test_exact_guides_and_speaks_clock_face(h):
    out = await h.say("Where's the sugar?")
    [g] = h.of("guide_start", out)
    assert g["object_id"] == "sugar" and g["target_position"] == SPOT_POS[3] and g["precision"] == "exact"
    [sp] = h.of("speak_text", out)
    assert sp["text"] == "The sugar is at your one o'clock, about an arm's length away."
    assert sp["utterance_id"] == g["utterance_id"]
    assert out.index(g) < out.index(sp)  # the ping starts before the speech


async def test_proximity_with_fob_chirps(h):
    await h.feed(state("keys", near="hub", distance_class="mid"))
    out = await h.say("Where are my keys?")
    assert h.of("chirp", out) == [{"type": "chirp", "fob_id": "fob_keys", "action": "start", "t": h.of("chirp", out)[0]["t"]}]
    assert h.spoken(out) == ["The keys are near the counter. I'll make them beep."]
    assert not h.of("guide_start", out)


async def test_area_without_fob(h):
    await h.feed(state("salt", area="kitchen_counter"))
    out = await h.say("where is the salt")
    assert h.spoken(out) == ["The salt is near the counter."]
    assert not h.of("chirp", out)


async def test_none_reports_last_sighting(settings):
    from conftest import Harness
    h = Harness(settings)
    t_seen = time.time() - 120
    await h.feed(snapshot([state("sugar", spot=1, last_seen_t=t_seen)]),
                 state("sugar", precision="none", status="missing", last_seen_t=t_seen))
    out = await h.say("Where's the sugar?")
    [text] = h.spoken(out)
    assert text.startswith("I last saw the sugar on the far left spot at ")
    assert "202" not in text  # never a date for today
    assert not h.of("guide_start", out)


async def test_stale_proximity_is_treated_as_last_seen(h):
    old = time.time() - h.settings.stale_s - 5
    await h.feed(state("keys", near="hub", distance_class="near", last_seen_t=old))
    out = await h.say("where are my keys")
    [text] = h.spoken(out)
    assert text.startswith("I last saw the keys near the counter at ") and text.endswith("I'll make them beep.")
    assert h.of("chirp", out)


async def test_never_seen_fob_object_still_chirps(h):
    out = await h.say("Where are my keys?")
    assert h.spoken(out) == ["I haven't detected the keys yet. I'll make them beep."]
    assert h.of("chirp", out)[0]["fob_id"] == "fob_keys"


async def test_unknown_object_uses_cached_phrase(h):
    out = await h.say("Where is my passport?")
    [c] = h.of("speak_cached", out)
    assert c["phrase_id"] == "unknown_object"


async def test_held_object_says_when_it_was_picked_up(h):
    await h.feed(Pickup(object_id="salt", from_spot=2),
                 state("salt", status="held", precision="none"))
    out = await h.say("Where's the salt?")
    [text] = h.spoken(out)
    assert text.startswith("The salt was picked up from the center left spot at ")
    assert text.endswith("and I haven't seen it put down since.")
    assert not h.of("guide_start", out)


async def test_not_understood(h):
    out = await h.say("blah blah")
    assert h.of("speak_cached", out)[0]["phrase_id"] == "not_understood"


async def test_list_objects(h):
    out = await h.say("what do you know")
    assert h.spoken(out) == ["I know about five items: the salt, the sugar, the pepper, "
                             "the blood pressure pills, and the keys."]


async def test_medication_reports_events_only(h):
    out = await h.say("Did I take my pills?")
    [text] = h.spoken(out)
    assert text.startswith("The blood pressure pills are on the far right spot. "
                           "I haven't seen them picked up since I started at ")
    await h.feed(Pickup(object_id="bp_meds", from_spot=4), state("bp_meds", spot=4))
    out = await h.say("Should I take my pills again?")
    [text] = h.spoken(out)
    assert text.startswith("I can't give medical advice, but I can tell you what the sensors saw. "
                           "The blood pressure pills were last picked up from the far right spot at ")
    assert text.endswith("They're on the far right spot now.")


async def test_chirp_without_fob_falls_back_to_locate(h):
    out = await h.say("make the salt beep")
    assert h.spoken(out) == ["The salt doesn't have a beeper. The salt is at your eleven o'clock, "
                             "about an arm's length away."]
    assert h.of("guide_start", out)[0]["object_id"] == "salt"
    assert not h.of("chirp", out)


async def test_chirp_with_fob_uses_cached_phrase(h):
    out = await h.say("make my keys beep")
    assert h.of("speak_cached", out)[0]["phrase_id"] == "chirping"
    assert h.of("chirp", out)[0]["action"] == "start"
