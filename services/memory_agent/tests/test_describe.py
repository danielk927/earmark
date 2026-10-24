"""Location sentences for the walking room, plus the fob (proximity) path kept for the stretch."""

from __future__ import annotations

import earmark_contracts as ec

from earmark_memory.describe import SpaceLabels, describe_location
from earmark_memory.fixture import FixtureData

LABELS = SpaceLabels.load()
CLOCK = FixtureData().clock
NOW = "2025-10-24T16:52:00-07:00"


def _obj(name: str, state: ec.SummaryState | None, *, home: int | None, touched: str | None = NOW, fob: str | None = None):
    return ec.ObjectSummary(
        object_id=name,
        name=name,
        aliases=[],
        notes="",
        description="",
        home_spot=home,
        home_spot_label=None,
        is_medication=False,
        fob_id=fob,
        state=state,
        last_touched_t=None,
        last_touched_local=touched,
    )


def _on(spot: int) -> ec.SummaryState:
    return ec.SummaryState(
        status="on_spot",
        spot=spot,
        spot_label=LABELS.spots[spot].label,
        area=None,
        near=None,
        distance_class=None,
        precision="exact",
        last_seen_t=None,
        last_seen_local=NOW,
    )


def test_spot_phrasing_names_the_container():
    assert LABELS.spot_place(1, None) == "in the drawer"
    assert LABELS.spot_place(4, None) == "in the box"  # not "the box behind you": the caregiver isn't on the mat
    assert LABELS.spot_place(6, None) == "on the setup spot"
    assert LABELS.spot_place(9, "center right") == "on the center right spot"  # unknown spot, Convex label
    assert LABELS.spot_detail(5) == "In the front pocket."
    assert LABELS.spot_detail(2) == "Top shelf, front left."


def test_moved_item_says_it_is_not_in_its_usual_place():
    text = describe_location(_obj("sugar", _on(6), home=3), CLOCK, LABELS)
    assert text == (
        "The sugar was last put down on the setup spot at 4:52 PM today. On the setup pad next to the laptop. "
        "That isn't its usual place (in the cupboard)."
    )


def test_on_spot_without_a_touch_time_uses_last_seen():
    text = describe_location(_obj("keys", _on(1), home=1, touched=None), CLOCK, LABELS)
    assert text == "The keys are in the drawer. Last confirmed there at 4:52 PM today. At the front."


def test_fob_proximity_path():
    state = ec.SummaryState(
        status="roaming",
        spot=None,
        spot_label=None,
        area=None,
        near="hub",
        distance_class="near",
        precision="proximity",
        last_seen_t=None,
        last_seen_local=NOW,
    )
    text = describe_location(_obj("keys", state, home=None, touched=None, fob="fob_keys"), CLOCK, LABELS)
    assert text == (
        "The keys' fob was last detected close to the laptop at 4:52 PM today. "
        "That position is approximate: the fob only reports how close it is to a receiver."
    )
