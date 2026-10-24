from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from conftest import SPACE
from earmark_concierge.phrasing import (
    Grammar, clock_hour, direction_phrase, distance_phrase, relative_spot_phrase, the, time_phrase,
)
from earmark_concierge.world import World

TZ = "America/Los_Angeles"


@pytest.mark.parametrize("spot,hour,text", [
    (1, 10, "at your ten o'clock, about an arm's length away"),
    (2, 11, "at your eleven o'clock, about an arm's length away"),
    (3, 1, "at your one o'clock, about an arm's length away"),
    (4, 2, "at your two o'clock, about an arm's length away"),
])
def test_seed_spots_clock_face(spot, hour, text):
    pos = next(s.position for s in SPACE.spots if s.spot == spot)
    assert clock_hour(pos[0], pos[1]) == hour
    assert direction_phrase(pos) == text


@pytest.mark.parametrize("x,y,hour", [
    (0, 1, 12), (1, 0, 3), (0, -1, 6), (-1, 0, 9), (0.5, -0.866, 5), (-0.01, 1, 12),
    (0.42, 0.42, 2), (-0.42, 0.42, 10),  # exact half hours round away from 12 on both sides
])
def test_clock_hour(x, y, hour):
    assert clock_hour(x, y) == hour


@pytest.mark.parametrize("d,text", [
    (0.3, "within easy reach"), (0.449, "within easy reach"), (0.45, "about an arm's length away"),
    (0.6, "about an arm's length away"), (0.8, "about a step away"), (1.49, "about a step away"),
    (1.5, "about two steps away"), (3.0, "about four steps away"),
])
def test_distance_bands(d, text):
    assert distance_phrase(d) == text


def test_relative_spot_phrases_by_azimuth_order():
    w = World()
    w.space = SPACE
    order = [s.spot for s in w.spots_left_to_right()]
    assert order == [1, 2, 3, 4]
    idx = order.index
    assert relative_spot_phrase(idx(2), idx(3)) == "one spot to your right"
    assert relative_spot_phrase(idx(4), idx(2)) == "two spots to your left"
    assert relative_spot_phrase(idx(1), idx(4)) == "three spots to your right"
    assert relative_spot_phrase(idx(3), idx(3)) is None


def test_time_phrase_never_says_a_date_for_today():
    zone = ZoneInfo(TZ)
    now = datetime(2026, 10, 24, 21, 0, tzinfo=zone).timestamp()
    assert time_phrase(datetime(2026, 10, 24, 20, 12, tzinfo=zone).timestamp(), now, TZ) == "at 8:12 PM"
    assert time_phrase(datetime(2026, 10, 24, 0, 5, tzinfo=zone).timestamp(), now, TZ) == "at 12:05 AM"
    assert time_phrase(datetime(2026, 10, 23, 8, 0, tzinfo=zone).timestamp(), now, TZ) == "yesterday at 8:00 AM"
    assert time_phrase(datetime(2026, 10, 20, 8, 0, tzinfo=zone).timestamp(), now, TZ) == "on Tuesday at 8:00 AM"
    assert time_phrase(datetime(2026, 9, 1, 8, 0, tzinfo=zone).timestamp(), now, TZ) == "on September 1 at 8:00 AM"


def test_names_and_agreement():
    assert the("sugar") == "the sugar"
    assert the("my keys") == "the keys"
    assert Grammar("keys").is_ == "are" and Grammar("keys").it == "them"
    assert Grammar("blood pressure pills").plural
    assert not Grammar("glass").plural and not Grammar("hummus").plural and not Grammar("salt").plural
