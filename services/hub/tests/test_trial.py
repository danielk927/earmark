"""Trial session metrics and pseudonym rules (brief 5.I)."""
from __future__ import annotations

import random

import pytest
from earmark_contracts import Pickup, PickupResult, TrialEnd, TrialStart

from earmark_hub.trial import TrialSession, suggest, validate_pseudonym

T0 = 1_761_350_400.0


def start(mode="earmark", target="sugar"):
    return TrialStart(trial_id="trial-1", mode=mode, target_object_id=target, tester="tester-A", t=T0)


def pickup(oid, t, spot=2):
    return Pickup(object_id=oid, from_spot=spot, t=T0 + t)


def test_baseline_ends_on_target_pickup_and_counts_wrong_picks():
    s = TrialSession(start("baseline"))
    assert s.on_message(pickup("salt", 4.0), T0 + 4.0) is None
    assert s.on_message(pickup("pepper", 6.0), T0 + 6.0) is None
    end = s.on_message(pickup("sugar", 9.25, spot=3), T0 + 9.3)
    assert isinstance(end, TrialEnd)
    assert (end.outcome, end.seconds_to_find, end.wrong_picks, end.started_t) == ("found", 9.25, 2, T0)
    assert (end.trial_id, end.mode, end.target_object_id, end.tester) == ("trial-1", "baseline", "sugar", "tester-A")


def test_earmark_waits_for_confirmation():
    s = TrialSession(start("earmark"))
    assert s.on_message(pickup("salt", 2.0), T0 + 2.0) is None
    assert s.on_message(pickup("sugar", 5.0), T0 + 5.0) is None
    assert s.poll(T0 + 5.5) is None
    end = s.on_message(PickupResult(expected="sugar", actual="sugar", correct=True, t=T0 + 5.2), T0 + 5.6)
    assert end.outcome == "found" and end.seconds_to_find == 5.0 and end.wrong_picks == 1
    assert s.confirmed


def test_earmark_falls_back_to_pickup_after_one_second():
    s = TrialSession(start("earmark"))
    s.on_message(pickup("sugar", 5.0), T0 + 5.0)
    assert s.poll(T0 + 5.9) is None
    end = s.poll(T0 + 6.0)
    assert end.outcome == "found" and end.seconds_to_find == 5.0 and not s.confirmed


def test_wrong_result_does_not_end_trial():
    s = TrialSession(start("earmark"))
    s.on_message(pickup("salt", 2.0), T0 + 2.0)
    assert s.on_message(PickupResult(expected="sugar", actual="salt", correct=False, t=T0 + 2.1), T0 + 2.1) is None
    assert s.poll(T0 + 10) is None


def test_events_before_start_are_ignored():
    s = TrialSession(start("baseline"))
    assert s.on_message(pickup("sugar", -1.0), T0) is None and s.wrong_picks == 0


def test_gave_up_and_aborted_have_no_time():
    s = TrialSession(start("baseline"))
    s.on_message(pickup("salt", 1.0), T0 + 1)
    end = s.give_up(T0 + 30)
    assert (end.outcome, end.seconds_to_find, end.wrong_picks) == ("gave_up", None, 1)
    assert TrialSession(start()).abort(T0 + 3).outcome == "aborted"


@pytest.mark.parametrize("name", ["John Smith", "jane doe", "john.smith", "Mary-Jane Watson", "a@b.com",
                                  "Jo Ann Lee"])
def test_rejects_real_looking_names(name):
    assert validate_pseudonym(name) is not None


@pytest.mark.parametrize("name", ["tester-A", "tester-B", "Tester B", "T1", "alpha", "participant 3", "p-07"])
def test_accepts_pseudonyms(name):
    assert validate_pseudonym(name) is None


def test_rejects_empty_and_long():
    assert validate_pseudonym("  ") and validate_pseudonym("x" * 40)


def test_suggest_alternates_and_avoids_last_target(objects):
    rng = random.Random(1)
    mode, target = suggest([], objects, rng)
    assert mode == "earmark" and target in {"salt", "sugar", "bp_meds"}
    last = TrialEnd(trial_id="t", mode="earmark", target_object_id="sugar", tester="tester-A", outcome="found",
                    started_t=T0, seconds_to_find=3.0, wrong_picks=0, t=T0 + 3)
    for _ in range(20):
        mode, target = suggest([last], objects, rng)
        assert mode == "baseline" and target != "sugar"
