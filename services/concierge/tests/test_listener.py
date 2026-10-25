"""Listener-aware guidance (UWB-PRD 11.1): phrasing by mode, lost/frozen announcements, voice commands."""
import pytest

from conftest import SPOT_POS
from earmark_concierge.grammar import parse
from earmark_concierge.phrasing import LOST_MESSAGE, direction_phrase, meters_phrase, relative_direction
from earmark_concierge.tools import tool_schemas, validate_llm_call
from earmark_concierge.world import HEAD_YAW_FRESH_S
from earmark_contracts import HeadPose, ListenerPose, Pickup


def pose(x=0.0, y=0.0, mode="tracked") -> ListenerPose:
    return ListenerPose(position=[x, y, 0.0], mode=mode, source="uwb", residual_m=0.05,
                        anchors_used=3, blocked=[])


# ---------------------------------------------------------------- phrasing

@pytest.mark.parametrize("dx,dy,text", [
    (0, 3, "ahead of you"), (0.5, 3, "ahead of you"),
    (1, 2, "ahead of you, a little to the right"), (-1, 2, "ahead of you, a little to the left"),
    (2, 0.2, "to your right"), (-2, 0, "to your left"),
    (2, -1.5, "behind you, a little to the right"), (-2, -1.5, "behind you, a little to the left"),
    (0, -3, "behind you"), (0.3, -3, "behind you"),
])
def test_relative_direction_words(dx, dy, text):
    assert relative_direction(dx, dy) == text


@pytest.mark.parametrize("d,text", [
    (1.3, "about 1 and a half meters"), (1.24, "about 1 meter"), (2.0, "about 2 meters"),
    (2.74, "about 2 and a half meters"), (2.75, "about 3 meters"), (3.2, "about 3 meters"),
    (3.3, "about 3 and a half meters"), (6.0, "about 6 meters"),
])
def test_meters_round_to_half(d, text):
    assert meters_phrase(d) == text


def test_tracked_far_uses_plain_words_relative_to_listener():
    # Sugar (spot 3) seen from 3.5 m back and well to the left of the counter.
    assert direction_phrase(SPOT_POS[3], [-1.6, -3.0, 0], "tracked") == \
        "ahead of you, a little to the right, about 4 meters"
    assert direction_phrase([0, 3, 0], [0, 0, 0], "tracked") == "ahead of you, about 3 meters"
    assert direction_phrase([0, 0, 0], [0, 3, 0], "tracked") == "behind you, about 3 meters"


# Target 3 m due ahead in the room frame (+y).
@pytest.mark.parametrize("yaw,text", [
    (0, "ahead of you"), (90, "to your left"), (-90, "to your right"),
    (40, "ahead of you, a little to the left"), (-40, "ahead of you, a little to the right"),
    (180, "behind you"), (-180, "behind you"), (135, "behind you, a little to the left"),
])
def test_yaw_rotates_ahead_into_left_and_right(yaw, text):
    assert relative_direction(0, 3, yaw) == text
    assert direction_phrase([0, 3, 0], [0, 0, 0], "tracked", yaw) == f"{text}, about 3 meters"


@pytest.mark.parametrize("yaw,dx,dy,text", [
    (350, 0, 3, "ahead of you"),                         # 0 - 350 wraps to +10, not -350
    (-350, 0, 3, "ahead of you"),                        # 0 + 350 wraps to -10
    (270, 0, 3, "to your right"),                        # 0 - 270 wraps to +90
    (-270, 0, 3, "to your left"),                        # 0 + 270 wraps to -90
    (170, 0, -3, "ahead of you"),                        # 180 - 170 = 10 off the heading
    (-170, 0, -3, "ahead of you"),                       # 180 + 170 = 350 wraps to -10
    (170, 0, 3, "behind you"),                           # 0 - 170 = -170
    (170, -3, 0, "to your right"),                       # -90 - 170 = -260 wraps to +100
    (720 + 90, 0, 3, "to your left"),                    # multiple turns reduce
])
def test_yaw_wraps_to_plus_minus_180(yaw, dx, dy, text):
    assert relative_direction(dx, dy, yaw) == text


async def test_core_uses_fresh_yaw_and_ignores_stale(h):
    await h.feed(pose(0, -3), HeadPose(yaw=90, pitch=0))
    out = await h.say("Where's the sugar?")
    [text] = h.spoken(out)
    assert text.startswith("The sugar is to your left, about ") and text.endswith("meters.")
    # Stale yaw falls back to the room frame.
    h.core.world.head_yaw_t -= HEAD_YAW_FRESH_S + 0.5
    out = await h.say("Where's the sugar?")
    assert h.spoken(out)[0].startswith("The sugar is ahead of you")
    # A new reading makes it fresh again.
    await h.feed(HeadPose(yaw=-90, pitch=0))
    out = await h.say("Where's the sugar?")
    assert h.spoken(out)[0].startswith("The sugar is to your right")


async def test_yaw_never_changes_the_clock_face(h):
    await h.feed(HeadPose(yaw=90, pitch=0), pose(0, 0, "frozen"))
    out = await h.say("Where's the sugar?")
    assert h.spoken(out) == ["The sugar is at your one o'clock, about an arm's length away."]


def test_tracked_but_close_falls_back_to_clock_face():
    assert direction_phrase([0, 1.2, 0], [0, 0, 0], "tracked") == "at your twelve o'clock, about a step away"


@pytest.mark.parametrize("mode", ["frozen", "fixed", "lost"])
def test_other_modes_use_clock_face_from_the_listener(mode):
    assert direction_phrase([0, 3, 0], [0, 0, 0], mode) == "at your twelve o'clock, about four steps away"
    assert direction_phrase([1, 1, 0], [1, 0, 0], mode) == "at your twelve o'clock, about a step away"


def test_default_args_are_todays_behavior():
    assert direction_phrase(SPOT_POS[3]) == "at your one o'clock, about an arm's length away"
    assert direction_phrase(SPOT_POS[3], None, "tracked").startswith("at your one o'clock")  # < 1.2 m


# ---------------------------------------------------------------- grammar and tools

@pytest.mark.parametrize("text,tool", [
    ("I'm here", "freeze_listener"), ("im here", "freeze_listener"), ("I am here.", "freeze_listener"),
    ("Okay, I’m here", "freeze_listener"), ("I'm here now", "freeze_listener"),
    ("recenter", "recenter_listener"), ("Re-center", "recenter_listener"),
    ("please recenter my audio", "recenter_listener"),
])
def test_grammar_routes_listener_commands(text, tool):
    call = parse(text)
    assert (call.name, call.args) == (tool, {})


def test_grammar_does_not_overreach():
    assert parse("I'm here to find my keys").name == "locate_object"
    assert parse("where is the recenter card").name == "locate_object"


def test_llm_tools_are_exposed_and_validated(h):
    names = {t["function"]["name"] for t in tool_schemas(h.core.world)}
    assert {"freeze_listener", "recenter_listener"} <= names
    for n in ("freeze_listener", "recenter_listener"):
        assert validate_llm_call(n, "{}", h.core.world).name == n


# ---------------------------------------------------------------- core

async def test_tracked_locate_uses_relative_words(h):
    await h.feed(pose(0, -3))  # three meters back from the counter
    out = await h.say("Where's the sugar?")
    [text] = h.spoken(out)
    assert text.startswith("The sugar is ahead of you") and text.endswith("meters.")
    assert "o'clock" not in text


async def test_no_pose_and_fixed_keep_clock_face(h):
    out = await h.say("Where's the sugar?")
    assert h.spoken(out) == ["The sugar is at your one o'clock, about an arm's length away."]
    await h.feed(pose(0, 0, "fixed"))
    out = await h.say("Where's the sugar?")
    assert h.spoken(out) == ["The sugar is at your one o'clock, about an arm's length away."]


async def test_lost_message_once_per_guidance(h):
    await h.say("Where's the sugar?")
    h.clear()
    await h.feed(pose(0, -2, "lost"))
    assert h.spoken(h.out) == [LOST_MESSAGE]
    await h.feed(pose(0, -2, "tracked"), pose(0, -2, "lost"), pose(0, -2, "lost"))
    assert h.spoken(h.out) == [LOST_MESSAGE]
    # A new guidance gets its own message.
    await h.feed(pose(0, -2, "tracked"))
    await h.say("Where's the salt?")
    h.clear()
    await h.feed(pose(0, -2, "lost"))
    assert h.spoken(h.out) == [LOST_MESSAGE]


async def test_lost_without_guidance_is_silent(h):
    await h.feed(pose(0, -2, "lost"))
    assert h.spoken(h.out) == []


async def test_locate_while_lost_says_it_once(h):
    await h.feed(pose(0, -2, "lost"))
    out = await h.say("Where's the sugar?")
    assert h.spoken(out) == [LOST_MESSAGE]
    assert h.of("guide_start", out)
    h.clear()
    await h.feed(pose(0, -2, "lost"))
    assert h.spoken(h.out) == []


async def test_frozen_transition_announces_once_per_transition(h):
    await h.say("Where's the sugar?")
    await h.feed(pose(0, -3, "tracked"))
    h.clear()
    await h.feed(pose(0, 0, "frozen"), pose(0, 0, "frozen"), pose(0, 0, "frozen"))
    assert h.spoken(h.out) == [
        "You're at the counter. The sugar is at your one o'clock, about an arm's length away."]
    h.clear()
    await h.feed(pose(0, -3, "tracked"), pose(0, 0, "frozen"))
    assert len(h.spoken(h.out)) == 1


async def test_frozen_transition_without_guidance_is_silent(h):
    await h.feed(pose(0, -3, "tracked"), pose(0, 0, "frozen"))
    assert h.spoken(h.out) == []


async def test_im_here_publishes_freeze_and_recenter_publishes_recenter(h):
    out = await h.say("I'm here")
    assert [m["action"] for m in h.of("listener_command", out)] == ["freeze"]
    assert h.spoken(out) == ["Okay, you're at the counter."]
    out = await h.say("recenter")
    assert [m["action"] for m in h.of("listener_command", out)] == ["recenter"]
    assert h.spoken(out) == ["Okay, recentered."]


async def test_im_here_while_guiding_defers_to_the_frozen_announcement(h):
    await h.say("Where's the sugar?")
    out = await h.say("I'm here")
    assert [m["action"] for m in h.of("listener_command", out)] == ["freeze"]
    assert h.spoken(out) == []
    assert h.core.guiding is not None


async def test_pickup_logic_ignores_the_pose(h):
    await h.feed(pose(2, -4, "tracked"))
    await h.say("Where's the sugar?")
    h.clear()
    await h.feed(Pickup(object_id="salt", from_spot=2))
    assert h.spoken(h.out) == ["That's the salt. The sugar is one spot to your right."]


def test_spot_order_does_not_depend_on_the_listener(h):
    h.core.world.listener = pose(5, 5)
    assert [s.spot for s in h.core.world.spots_left_to_right()] == [1, 2, 3, 4]
