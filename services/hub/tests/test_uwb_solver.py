"""UWB solver math (docs/project/UWB-PRD.md 5 and 8.2): trilateration, outliers, two-anchor fixes, gates, smoothing."""
from __future__ import annotations

import math
import random
import statistics

import pytest

from earmark_hub.uwb.solver import (
    AlphaBeta,
    circle_intersections,
    facing_from_yaw,
    head_from_phone,
    horizontal,
    solve,
    solve_pair,
    speed_ok,
)


@pytest.fixture
def anchors(space) -> dict[str, tuple[float, float]]:
    return {a.anchor: (a.position[0], a.position[1]) for a in space.space.anchors}


@pytest.fixture
def anchor_z(space) -> dict[str, float]:
    return {a.anchor: a.position[2] for a in space.space.anchors}


@pytest.fixture
def counter_y(space) -> float:
    return min(s.position[1] for s in space.space.spots)


# The walking area in front of the counter (start mark at y = -3, counter line y = 0.42).
GRID = [(x / 10, y / 10) for x in range(-10, 11, 2) for y in range(-30, 1, 3)]


def exact(p, anchors):
    return {a: math.dist(p, q) for a, q in anchors.items()}


def test_exact_ranges_give_the_exact_position(anchors, counter_y):
    """Noise-free ranges from anywhere in the walking area solve to within 1 mm, with no prediction or with one
    up to 0.1 m off in any direction."""
    for p in GRID:
        preds = [None, p] + [(p[0] + 0.1 * math.cos(math.radians(a)), p[1] + 0.1 * math.sin(math.radians(a)))
                             for a in range(0, 360, 45)]
        for prev in preds:
            sol = solve(exact(p, anchors), anchors, prev, counter_y=counter_y, outlier_rms_m=0.25)
            assert math.dist(sol.position, p) < 1e-3, (p, prev, sol)
            assert sol.used == sorted(anchors) and sol.blocked == [] and sol.residual_m < 1e-3


def test_slant_ranges_from_3d_distances_solve_exactly(anchors, anchor_z, counter_y):
    """3D phone-to-anchor distances, slant-corrected with each anchor's dz, give the phone's 2D position."""
    phone_z = -0.35
    for p in GRID:
        raw = {a: math.dist((*p, phone_z), (*anchors[a], anchor_z[a])) for a in anchors}
        h = {a: horizontal(d, anchor_z[a] - phone_z) for a, d in raw.items()}
        assert math.dist(solve(h, anchors, None, counter_y=counter_y, outlier_rms_m=0.25).position, p) < 1e-3


def test_gaussian_noise_median_error_under_10_cm(anchors, counter_y):
    """sigma = 0.07 m noise on every range: median position error < 0.10 m (PRD 12.1)."""
    rng = random.Random(1234)
    errors = []
    for p in GRID:
        for _ in range(20):
            noisy = {a: max(h + rng.gauss(0.0, 0.07), 0.0) for a, h in exact(p, anchors).items()}
            errors.append(math.dist(solve(noisy, anchors, None, counter_y=counter_y, outlier_rms_m=0.25).position, p))
    assert statistics.median(errors) < 0.10


@pytest.mark.parametrize("bad", ["uwb_1", "uwb_2", "uwb_3"])
def test_one_anchor_body_block_is_rejected_and_flagged(anchors, counter_y, bad):
    """+0.4 m on one anchor: dropped, listed in `blocked`, and the other two give the true position (to 1 mm with
    an exact prediction; a few cm with one a few cm off, near a pair's baseline where its intersections nearly
    coincide). Where the remaining pair's two intersections are under ~0.35 m apart, a biased range can agree
    with the other one and the block is indistinguishable from a lagging prediction; those few are excluded."""
    checked = 0
    for p in GRID:
        ranges = exact(p, anchors)
        ranges[bad] += 0.4
        keep = sorted(set(anchors) - {bad})
        both = circle_intersections(anchors[keep[0]], ranges[keep[0]], anchors[keep[1]], ranges[keep[1]])
        if len(both) == 2 and math.dist(*both) < 0.35:
            continue
        checked += 1
        for prev, tol in ((p, 1e-3), ((p[0] + 0.05, p[1] - 0.03), 0.04)):
            sol = solve(ranges, anchors, prev, counter_y=counter_y, outlier_rms_m=0.25)
            assert sol.blocked == [bad], (p, prev, sol)
            assert sol.used == keep
            assert math.dist(sol.position, p) < tol, (p, prev, sol)
    assert checked >= 0.85 * len(GRID)


def test_body_blocks_are_caught_almost_everywhere(anchors, counter_y):
    """Over the whole walking area, every anchor, and predictions 5 cm off in 8 directions: >= 98% flagged."""
    hits = total = 0
    for p in GRID:
        for bad in anchors:
            ranges = exact(p, anchors)
            ranges[bad] += 0.4
            for a in range(0, 360, 45):
                prev = (p[0] + 0.05 * math.cos(math.radians(a)), p[1] + 0.05 * math.sin(math.radians(a)))
                total += 1
                hits += solve(ranges, anchors, prev, counter_y=counter_y, outlier_rms_m=0.25).blocked == [bad]
    assert hits >= 0.98 * total


def test_a_lagging_prediction_never_drops_a_healthy_anchor(anchors, counter_y):
    """Regression: clean ranges with the prediction 0.3 m behind (fast walk or a turn) used to pick a pair's mirror
    intersection, drop a healthy anchor, and lock onto the wrong point (e.g. 0.33 m off at the counter)."""
    for p in [(0.0, 0.0), (0.2, -0.3), (-0.6, -1.2), (0.0, -1.5)]:
        for a in range(0, 360, 30):
            prev = (p[0] + 0.3 * math.cos(math.radians(a)), p[1] + 0.3 * math.sin(math.radians(a)))
            sol = solve(exact(p, anchors), anchors, prev, counter_y=counter_y, outlier_rms_m=0.25)
            assert sol.blocked == [] and math.dist(sol.position, p) < 1e-3, (p, prev, sol)


def test_clean_ranges_with_a_prediction_block_nothing(anchors, counter_y):
    rng = random.Random(5)
    for p in GRID:
        ranges = {a: h + rng.gauss(0.0, 0.02) for a, h in exact(p, anchors).items()}
        assert solve(ranges, anchors, p, counter_y=counter_y, outlier_rms_m=0.25).blocked == []


def test_two_anchors_pick_the_walking_area_intersection(anchors, counter_y):
    """uwb_1 and uwb_2 sit on the counter line: one intersection is behind the counter and is never chosen,
    even when the prediction is right next to it."""
    pair = {k: anchors[k] for k in ("uwb_1", "uwb_2")}
    p = (0.2, -1.0)
    mirror = (0.2, 2 * 0.75 - p[1])  # reflection across the anchors' line y = 0.75
    for prefer in (p, mirror, (0.0, 0.0)):
        sol = solve(exact(p, pair), pair, prefer, counter_y=counter_y, outlier_rms_m=0.25)
        assert math.dist(sol.position, p) < 1e-3, prefer
        assert sol.used == ["uwb_1", "uwb_2"] and sol.blocked == []


def test_two_anchors_both_in_area_pick_the_one_closest_to_the_prediction(anchors, counter_y):
    a, b = anchors["uwb_1"], anchors["uwb_3"]
    p = (0.3, -0.8)
    ra, rb = math.dist(p, a), math.dist(p, b)
    cands = circle_intersections(a, ra, b, rb)
    assert len(cands) == 2 and all(c[1] < counter_y for c in cands)
    other = max(cands, key=lambda c: math.dist(c, p))
    assert math.dist(other, p) > 0.5
    assert math.dist(solve_pair(a, ra, b, rb, (p[0] + 0.2, p[1]), counter_y), p) < 1e-6
    assert math.dist(solve_pair(a, ra, b, rb, (other[0] - 0.2, other[1]), counter_y), other) < 1e-6
    sol = solve({"uwb_1": ra, "uwb_3": rb}, anchors, p, counter_y=counter_y, outlier_rms_m=0.25)
    assert math.dist(sol.position, p) < 1e-3 and sol.used == ["uwb_1", "uwb_3"]


def test_two_anchors_both_outside_area_pick_the_closest():
    a, b = (-1.0, 0.0), (1.0, 0.0)
    cands = circle_intersections(a, 2.0, b, 2.0)
    assert sorted(round(c[1], 6) for c in cands) == [round(-math.sqrt(3), 6), round(math.sqrt(3), 6)]
    assert solve_pair(a, 2.0, b, 2.0, (0.0, 1.0), counter_y=-5.0)[1] == pytest.approx(math.sqrt(3))
    assert solve_pair(a, 2.0, b, 2.0, (0.0, -1.0), counter_y=-5.0)[1] == pytest.approx(-math.sqrt(3))


def test_circles_that_miss_give_the_closest_approach_point():
    assert circle_intersections((0.0, 0.0), 0.4, (2.0, 0.0), 0.4) == [(1.0, 0.0)]
    assert circle_intersections((1.0, 1.0), 0.4, (1.0, 1.0), 0.6) == []


def test_fewer_than_two_known_anchors_gives_no_solution(anchors, counter_y):
    assert solve({"uwb_1": 1.0}, anchors, None, counter_y=counter_y, outlier_rms_m=0.25) is None
    assert solve({"uwb_1": 1.0, "nope": 2.0}, anchors, None, counter_y=counter_y, outlier_rms_m=0.25) is None
    assert solve({}, anchors, (0.0, 0.0), counter_y=counter_y, outlier_rms_m=0.25) is None


def test_speed_gate():
    assert speed_ok((0.25, 0.0), (0.0, 0.0), 0.1, 2.5)  # exactly 2.5 m/s
    assert not speed_ok((0.26, 0.0), (0.0, 0.0), 0.1, 2.5)
    assert speed_ok((1.0, 0.0), (0.0, 0.0), 0.5, 2.5)
    assert not speed_ok((0.1, 0.0), (0.0, 0.0), 0.0, 2.5)  # no time passed: any jump is too fast
    assert speed_ok((0.0, 0.0), (0.0, 0.0), 0.0, 2.5)


def test_horizontal_slant_correction():
    assert horizontal(5.0, 3.0) == pytest.approx(4.0)
    assert horizontal(5.0, -3.0) == pytest.approx(4.0)
    assert horizontal(2.0, 0.0) == pytest.approx(2.0)
    assert horizontal(0.3, 0.5) == 0.0  # d < |dz| (noise near an anchor): clamp, never NaN
    assert horizontal(0.3, -0.5) == 0.0
    assert horizontal(0.0, 0.0) == 0.0


def test_head_sits_behind_the_phone_along_facing():
    assert head_from_phone((0.5, -1.0), (0.0, 1.0), 0.2) == pytest.approx((0.5, -1.2))
    assert head_from_phone((0.5, -1.0), (1.0, 0.0), 0.2) == pytest.approx((0.3, -1.0))
    assert head_from_phone((0.5, -1.0), (0.0, 1.0), 0.0) == (0.5, -1.0)
    assert facing_from_yaw(0.0) == pytest.approx((0.0, 1.0))
    assert facing_from_yaw(90.0) == pytest.approx((1.0, 0.0))  # positive yaw turns right (+x)
    assert facing_from_yaw(-90.0) == pytest.approx((-1.0, 0.0))
    assert facing_from_yaw(180.0) == pytest.approx((0.0, -1.0), abs=1e-12)


def test_alpha_beta_converges_on_constant_velocity():
    f = AlphaBeta((0.0, -2.0), 0.0)
    for k in range(1, 151):
        t = k * 0.1
        f.update((0.5 * t, -2.0 + 0.3 * t), t, 0.5, 0.1)
    assert math.dist(f.pos, (7.5, 2.5)) < 1e-3
    assert math.dist(f.vel, (0.5, 0.3)) < 1e-3
    assert math.dist(f.predict(15.5), (7.75, 2.65)) < 1e-3


def test_alpha_beta_smooths_and_restarts_after_a_gap():
    f = AlphaBeta((0.0, 0.0), 0.0)
    assert f.update((1.0, 0.0), 0.1, 0.2, 0.1) == pytest.approx((0.2, 0.0))  # alpha of the residual
    assert f.vel == pytest.approx((1.0, 0.0))  # beta / dt of the residual
    assert f.predict(0.0) == f.pos  # never predicts backwards
    assert f.update((3.0, 3.0), 1.5, 0.2, 0.1) == (3.0, 3.0)  # > 1 s gap: restart at the measurement
    assert f.vel == (0.0, 0.0) and f.t == 1.5
    assert f.update((9.0, 9.0), 1.5, 0.2, 0.1) == (9.0, 9.0)  # dt <= 0: restart too
