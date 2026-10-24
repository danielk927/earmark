"""The fixture serves contract-valid responses that tell the brief's seed story."""
from __future__ import annotations

from datetime import date, datetime
from zoneinfo import ZoneInfo

import pytest

import earmark_contracts as ec
from earmark_memory.fixture import FIXTURE_NOW_T, FixtureData, compute_doses

from .conftest import convex_validator

TZ = ZoneInfo("America/Los_Angeles")
YESTERDAY, TODAY = "2025-10-23", "2025-10-24"


def _valid(definition: str, model) -> None:
    errors = sorted(convex_validator(definition).iter_errors(ec.to_dict(model)), key=str)
    assert not errors, "\n".join(e.message for e in errors)


def test_every_fixture_response_matches_the_json_schema(data: FixtureData):
    for o in data.registry.objects:
        _valid("object_lookup_response", data.object_lookup(o.name))
        _valid("history_response", data.history(o.object_id))
    _valid("object_lookup_response", data.object_lookup("unicorn"))
    _valid("objects_response", data.objects_response())
    for day in (YESTERDAY, TODAY, None):
        _valid("adherence_response", data.adherence(day))
        _valid("daily_summary_response", data.daily_summary(day))


def test_fixed_now_is_friday_5pm_household_time(data: FixtureData):
    assert data.clock.now.isoformat() == "2025-10-24T17:00:00-07:00"
    assert data.adherence().date == TODAY


def test_two_days_of_history_with_exactly_one_missed_dose(data: FixtureData):
    y = {d.scheduled_local_time: d for d in data.adherence(YESTERDAY).doses}
    t = {d.scheduled_local_time: d for d in data.adherence(TODAY).doses}
    assert (y["08:00"].status, y["08:00"].taken_local) == ("taken", "2025-10-23T08:05:00-07:00")
    assert (y["20:00"].status, y["20:00"].taken_t) == ("missed", None)
    assert (t["08:00"].status, t["08:00"].taken_local) == ("taken", "2025-10-24T08:15:00-07:00")
    assert t["20:00"].status == "pending"
    statuses = [d.status for day in (YESTERDAY, TODAY) for d in data.adherence(day).doses]
    assert statuses.count("missed") == 1
    assert {e.event_id for e in data.events} >= {y["08:00"].evidence_event_id, t["08:00"].evidence_event_id}


def test_object_states_match_the_seed(data: FixtureData):
    objs = {o.object_id: o for o in data.objects_response().objects}
    assert (objs["salt"].state.status, objs["salt"].state.spot) == ("on_spot", 2)
    assert (objs["sugar"].state.status, objs["sugar"].state.spot_label) == ("on_spot", "center right")
    assert objs["bp_meds"].state.spot == 4
    assert objs["pepper"].state is None and objs["pepper"].last_touched_t is None
    keys = objs["keys"].state
    assert (keys.status, keys.near, keys.distance_class, keys.precision) == ("roaming", "hub", "near", "proximity")
    assert objs["keys"].last_touched_t is None


def test_lookup_order_name_then_alias_then_substring(data: FixtureData):
    assert [m.object_id for m in data.object_lookup("Keys").matches] == ["keys"]
    assert [m.object_id for m in data.object_lookup("pills").matches] == ["bp_meds"]
    assert [m.object_id for m in data.object_lookup("key").matches] == ["keys"]
    assert data.object_lookup("unicorn").matches == []


def test_daily_summary(data: FixtureData):
    s = data.daily_summary(YESTERDAY)
    assert s.untouched_7d == ["pepper"]  # tagged objects only, like convex/; fob-only keys are excluded
    assert s.pickup_count == 6
    assert "20:00 dose was missed (no pickup between 19:00 and 22:00)" in s.text


def test_history_newest_first_and_unknown_object(data: FixtureData):
    events = data.history("salt").events
    assert [e.t for e in events] == sorted((e.t for e in events), reverse=True)
    assert events[0].detail == "Put down on the center left spot."
    with pytest.raises(Exception, match="unknown objectId"):
        data.history("unicorn")


# ---------------------------------------------------------------- adherence rule (contracts/README.md)

MED = ec.Medication(object_id="m", schedule_times=["08:00", "20:00"], window_minutes=60)


def _t(hhmm: str, day: str = TODAY) -> float:
    return datetime.fromisoformat(f"{day}T{hhmm}:00").replace(tzinfo=TZ).timestamp()


def _status(pickups: list[str], now: str = "23:59") -> dict[str, tuple[str, str | None]]:
    doses = compute_doses(medication=MED, name="m", pickups=[(f"e{i}", _t(p)) for i, p in enumerate(pickups)],
                          day=date.fromisoformat(TODAY), tz=TZ, now_t=_t(now))
    return {d.scheduled_local_time: (d.status, d.evidence_event_id) for d in doses}


@pytest.mark.parametrize(
    "pickups,now,expected",
    [
        (["07:00"], "23:59", {"08:00": ("taken", "e0"), "20:00": ("missed", None)}),  # exactly -W
        (["09:00"], "23:59", {"08:00": ("taken", "e0"), "20:00": ("missed", None)}),  # exactly +W
        (["09:01"], "23:59", {"08:00": ("late", "e0"), "20:00": ("missed", None)}),
        (["10:00"], "23:59", {"08:00": ("late", "e0"), "20:00": ("missed", None)}),  # exactly 2W
        (["10:01"], "23:59", {"08:00": ("missed", None), "20:00": ("missed", None)}),
        ([], "09:30", {"08:00": ("pending", None), "20:00": ("pending", None)}),
        ([], "10:01", {"08:00": ("missed", None), "20:00": ("pending", None)}),
        (["09:30", "08:10"], "23:59", {"08:00": ("taken", "e1"), "20:00": ("missed", None)}),  # taken beats late
        (["14:30"], "23:59", {"08:00": ("missed", None), "20:00": ("missed", None)}),  # nearest is 20:00, too early
        (["20:30"], "20:45", {"08:00": ("missed", None), "20:00": ("taken", "e0")}),
        (["21:00"], "20:45", {"08:00": ("missed", None), "20:00": ("pending", None)}),  # future pickups ignored
    ],
)
def test_adherence_rule(pickups, now, expected):
    assert _status(pickups, now) == expected


def test_fixture_now_constant():
    assert FIXTURE_NOW_T == _t("17:00")
