"""Chirp detection, slot assignment, distances, and position, with no network."""
import math

import numpy as np
import pytest

from earmark_ranging.chirp import SPEED_OF_SOUND_M_S as C
from earmark_ranging.chirp import ChirpSpec, direction_for_slot, synth_at
from earmark_ranging.cycle import all_pair_distances, assign_slots, pair_distances
from earmark_ranging.detect import Detector
from earmark_ranging.solve import locate, pair_distance

FS = 48000
SPEC = ChirpSpec()
ANCHORS = {"B1": (-1.5, 1.5, 1.8), "B2": (1.5, 1.5, 0.3), "B3": (1.5, -1.5, 1.8), "B4": (-1.5, -1.5, 0.3), "B5": (-1.8, 0.0, 1.0)}


def place(audio: np.ndarray, start_s: float, direction: str, amp: float) -> None:
    i0 = int(start_s * FS) - 2
    t = (np.arange(i0, i0 + int(0.02 * FS)) / FS) - start_s
    audio[i0 : i0 + len(t)] += synth_at(SPEC, direction, t, amp)


@pytest.mark.parametrize("noise", [0.0, 0.02, 0.05])
def test_detector_finds_a_chirp_between_samples(noise):
    rng = np.random.default_rng(1)
    audio = rng.normal(0, noise, FS)
    true = 0.30001234
    place(audio, true, "up", 0.3)
    [e] = Detector(SPEC, FS).find(audio)
    assert e.shape == "up"
    assert abs(e.t - true) * FS < 0.25  # within a quarter of a sample (under 2 mm of sound travel)


def test_rising_and_falling_chirps_are_told_apart_and_ordered():
    audio = np.zeros(FS)
    place(audio, 0.20, "up", 0.5)
    place(audio, 0.26, "down", 0.5)
    place(audio, 0.32, "up", 0.5)
    events = Detector(SPEC, FS).find(audio)
    assert [(e.shape, round(e.t, 3)) for e in events] == [("up", 0.2), ("down", 0.26), ("up", 0.32)]


def test_quiet_chirp_in_loud_noise_is_still_found():
    rng = np.random.default_rng(2)
    audio = rng.normal(0, 0.05, FS)  # hiss louder than the chirp's own peak
    place(audio, 0.4, "down", 0.04)
    events = Detector(SPEC, FS).find(audio)
    assert len(events) == 1 and abs(events[0].t - 0.4) < 0.0005


def test_slots_are_assigned_by_order_and_shape():
    from earmark_ranging.detect import Event

    gap = 0.06
    ev = [Event(1.0 + 0.06 * k, direction_for_slot(k), 1.0 if k == 2 else 0.2, 20.0) for k in range(6) if k != 4]
    slots = assign_slots(ev, own_slot=2, gap_s=gap)
    assert sorted(slots) == [0, 1, 2, 3, 5]
    assert slots[5] == pytest.approx(1.3)


def test_distance_without_a_shared_clock():
    # A and B are 2.5 m apart; each plays at its own time, and each only knows its own recording's timeline.
    d = 2.5
    ta, tb = 10.000, 10.071  # true play times
    a_own, a_hears_b = ta + 0.03 / C, tb + d / C  # on A's timeline (shifted by an unknown offset we add below)
    b_own, b_hears_a = tb + 0.03 / C, ta + d / C
    offset_a, offset_b = 5.0, -123.4
    est = pair_distance((a_hears_b + offset_a) - (a_own + offset_a), (b_hears_a + offset_b) - (b_own + offset_b))
    assert est == pytest.approx(d, abs=0.002)


def test_all_distances_from_one_round():
    pos = {0: (0.2, 0.4, 1.2), **{i + 1: p for i, p in enumerate(ANCHORS.values())}}
    play = {s: 3.0 + 0.06 * s for s in pos}
    offsets = {s: 100.0 * s for s in pos}  # every phone's clock is somewhere else
    heard = {
        i: {j: play[j] + math.dist(pos[i], pos[j]) / C + offsets[i] if i != j else play[j] + 0.03 / C + offsets[i] for j in pos}
        for i in pos
    }
    got = pair_distances(heard)
    for s in range(1, 6):
        assert got[s] == pytest.approx(math.dist(pos[0], pos[s]), abs=0.002)
    assert len(all_pair_distances(heard)) == 15


def _dists(p, noise=0.0, seed=0):
    rng = np.random.default_rng(seed)
    return {n: math.dist(p, a) + rng.normal(0, noise) for n, a in ANCHORS.items()}


def test_locate_exact_and_noisy():
    truth = (0.4, -0.3, 1.2)
    assert locate(ANCHORS, _dists(truth)).position == pytest.approx(truth, abs=0.005)
    errs = [math.dist(locate(ANCHORS, _dists(truth, 0.03, s)).position, truth) for s in range(20)]
    assert np.median(errs) < 0.08


def test_locate_with_only_three_phones_uses_the_height_prior():
    truth = (0.4, -0.3, 1.2)
    d = {k: v for k, v in _dists(truth).items() if k in ("B1", "B2", "B3")}
    assert math.dist(locate(ANCHORS, d, start=(0, 0, 1)).position, truth) < 0.15


def test_locate_throws_out_one_echo():
    truth = (0.0, 0.5, 1.2)
    d = _dists(truth)
    d["B3"] += 1.4  # this phone's direct sound was missed and an echo was heard instead
    fix = locate(ANCHORS, d)
    assert fix.dropped == ("B3",) and math.dist(fix.position, truth) < 0.02


def test_locate_gives_up_when_distances_make_no_sense():
    d = _dists((0, 0, 1.2))
    d = {"B1": 0.5, "B2": 6.0, "B3": 0.4, "B4": 5.0, "B5": 0.3}
    assert locate(ANCHORS, d) is None
    assert locate(ANCHORS, {"B1": 1.0, "B2": 1.0}) is None
