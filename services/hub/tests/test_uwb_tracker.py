"""Listener tracker (docs/UWB-PRD.md 8.2-8.5): modes, freeze/unfreeze, voice override, NFC re-anchor, lost/fixed.

The Tracker is driven directly at 10 Hz with explicit `now` values and noise-free ranges computed from a head
position and the anchors in config/space.json, exactly as the wearer app would send them.
"""
from __future__ import annotations

import math
import random

import pytest
from earmark_contracts import UwbRange

from earmark_hub.config import UwbCfg
from earmark_hub.uwb.tracker import FORWARD, Tracker, wearer_geometry

DT = 0.1  # solve_hz = 10


class Rig:
    """A Tracker plus a simulated wearer: `step()` advances 0.1 s, sends motion + ranges, and ticks."""

    def __init__(self, space, t0: float = 100.0, noise: float = 0.0, seed: int = 0, **cfg) -> None:
        self.cfg = UwbCfg(**cfg)
        self.tr = Tracker(self.cfg, space, t0)
        self.t0, self.k, self.seq = t0, 0, 0
        self.anchors = {a.anchor: a.position for a in space.space.anchors}
        self.phone_z, self.offset = wearer_geometry(self.cfg, space)
        self.noise, self.rng = noise, random.Random(seed)

    @property
    def now(self) -> float:
        return self.t0 + self.k * DT

    def ranges(self, head, facing=FORWARD, only=None, bias=None, source="uwb") -> None:
        phone = (head[0] + facing[0] * self.offset, head[1] + facing[1] * self.offset, self.phone_z)
        for a, pos in self.anchors.items():
            if only is not None and a not in only:
                continue
            d = math.dist(phone, pos) + (bias or {}).get(a, 0.0) + (self.rng.gauss(0.0, self.noise) if self.noise else 0.0)
            self.tr.on_range(UwbRange(anchor=a, distance_m=max(d, 0.0), seq=self.seq, t=self.now), self.now, source)
        self.seq += 1

    def step(self, head=None, *, motion=None, **kw):
        """Advance 0.1 s, send `motion` and ranges from `head` (None sends nothing), tick. Returns the poses."""
        self.k += 1
        if motion is not None:
            self.tr.on_motion(motion, self.now)
        if head is not None:
            self.ranges(head, **kw)
        return self.tr.tick(self.now)

    def run(self, seconds, head=None, **kw):
        out = []
        for _ in range(round(seconds / DT)):
            out += self.step(head, **kw)
        return out

    def until(self, mode, head=None, limit=10.0, **kw):
        """Step until the tracker is in `mode`; returns (poses, time it entered `mode`)."""
        out = []
        for _ in range(round(limit / DT)):
            out += self.step(head, **kw)
            if self.tr.mode == mode:
                return out, self.now
        raise AssertionError(f"never reached {mode}; stuck in {self.tr.mode}")

    def walk(self, a, b, speed, facing=None, **kw):
        """Walk the head from a to b at `speed` m/s, facing the direction of travel unless `facing` is given."""
        n = max(1, round(math.dist(a, b) / speed / DT))
        facing = facing or ((b[0] - a[0]) / math.dist(a, b), (b[1] - a[1]) / math.dist(a, b))
        out = []
        for i in range(1, n + 1):
            p = (a[0] + (b[0] - a[0]) * i / n, a[1] + (b[1] - a[1]) * i / n)
            out += self.step(p, facing=facing, **kw)
        return out


def xy(pose):
    return (pose.position[0], pose.position[1])


def frozen_at(rig, head, **kw):
    """Track at `head` (still), then wait for the automatic freeze."""
    rig.step(head, motion="still", **kw)
    rig.until("frozen", head, motion="still", **kw)
    return rig


# ---------------------------------------------------------------- fixed / tracked


def test_starts_fixed_at_the_origin_with_source_none(space):
    tr = Tracker(UwbCfg(), space, 50.0)
    p = tr.pose
    assert p.mode == "fixed" and p.position == [0.0, 0.0, 0.0] and p.source == "none" and p.t == 50.0
    assert p.residual_m is None and p.anchors_used == 0 and p.blocked == []
    assert [(h.anchor, h.online, h.distance_m) for h in p.anchors] == [
        ("uwb_1", False, None), ("uwb_2", False, None), ("uwb_3", False, None)]
    assert tr.tick(50.1) == []  # nothing ranged: fixed publishes nothing per tick


def test_first_ranges_track_at_once_and_every_tick_publishes(space):
    rig = Rig(space)
    poses = rig.step((0.3, -1.5), motion="moving")
    assert len(poses) == 1 and poses[0].mode == "tracked" and poses[0].t == rig.now
    assert math.dist(xy(poses[0]), (0.3, -1.5)) < 1e-3
    assert poses[0].source == "uwb" and poses[0].anchors_used == 3 and poses[0].blocked == []
    assert poses[0].residual_m == pytest.approx(0.0, abs=1e-3)
    assert [p.mode for p in rig.run(1.0, (0.3, -1.5), motion="moving")] == ["tracked"] * 10


def test_ranges_older_than_freshness_are_ignored(space):
    rig = Rig(space)
    rig.ranges((0.3, -1.5))
    rig.k += 6  # 0.6 s later: older than freshness_s = 0.5
    assert rig.tr.tick(rig.now) == [] and rig.tr.mode == "fixed"


def test_one_anchor_never_tracks(space):
    rig = Rig(space)
    assert rig.run(1.0, (0.3, -1.5), only={"uwb_1"}) == [] and rig.tr.mode == "fixed"


def test_source_follows_the_range_origin(space):
    rig = Rig(space)
    rig.ranges((0.0, -1.0), source="sim")
    assert rig.tr.tick(rig.now)[0].source == "sim"


def test_speed_gate_ignores_a_jump_until_it_becomes_possible(space):
    rig = Rig(space)
    rig.run(0.5, (0.0, -1.0), motion="moving")
    poses = rig.run(0.3, (0.0, -2.5), motion="moving")  # 1.5 m in 0.1 s: rejected (needs >= 0.6 s at 2.5 m/s)
    assert all(math.dist(xy(p), (0.0, -1.0)) < 1e-3 for p in poses)
    poses = rig.run(1.0, (0.0, -2.5), motion="moving")
    assert xy(poses[-1])[1] < -1.5  # accepted once 1.5 m / dt <= 2.5 m/s


def test_head_offset_uses_airpods_yaw_then_falls_back(space):
    """Listener = phone shifted back head_offset_m along the facing: yaw 90 (facing +x) puts the head 0.2 m left."""
    rig = Rig(space)
    phone = (0.5, -1.5)
    head_forward = (phone[0], phone[1] - 0.2)  # the rig places the phone 0.2 m forward of this head
    rig.step(head_forward, motion="still")
    rig.tr.on_head_pose(90.0, rig.now + DT)
    p = rig.step(head_forward, motion="still")[0]
    assert math.dist(xy(p), (phone[0] - 0.2, phone[1])) < 1e-3
    rig.run(1.0, head_forward, motion="still")  # yaw now older than head_pose_max_age_s: keeps the last facing
    assert math.dist(xy(rig.tr.pose), (phone[0] - 0.2, phone[1])) < 1e-3
    rig.tr.on_head_pose(0.0, rig.now + DT)
    assert math.dist(xy(rig.step(head_forward, motion="still")[0]), head_forward) < 1e-3


# ---------------------------------------------------------------- freeze


def test_freezes_when_still_for_still_for_s_inside_the_radius(space):
    rig = Rig(space)
    head = (0.2, -0.5)
    rig.run(1.0, head, motion="moving")
    poses = rig.step(head, motion="still")
    still_t = rig.now
    more, t = rig.until("frozen", head, motion="still")
    poses += more
    assert 0.6 - 1e-6 <= t - still_t <= 0.7 + 1e-6
    assert [p.mode for p in poses] == ["tracked"] * (len(poses) - 1) + ["frozen"]
    assert poses[-1].t == t  # the transition is published in the same tick
    assert math.dist(xy(poses[-1]), head) < 1e-3  # average of the (constant) still estimates, facing the counter


def test_freezes_with_two_fresh_anchors(space):
    rig = Rig(space)
    head = (0.2, -0.5)
    rig.step(head, motion="still", only={"uwb_1", "uwb_2"})
    rig.until("frozen", head, motion="still", only={"uwb_1", "uwb_2"})
    assert math.dist(xy(rig.tr.pose), head) < 1e-3 and rig.tr.pose.anchors_used == 2


def test_no_freeze_while_moving_or_outside_the_radius(space):
    rig = Rig(space)
    assert {p.mode for p in rig.run(5.0, (0.2, -0.5), motion="moving")} == {"tracked"}
    rig = Rig(space)
    assert {p.mode for p in rig.run(5.0, (0.0, -1.5), motion="still")} == {"tracked"}  # 1.5 m > freeze_enter_m
    rig = Rig(space)
    assert {p.mode for p in rig.run(5.0, (0.2, -0.5))} == {"tracked"}  # no motion_state at all


def test_no_freeze_with_fewer_than_two_fresh_anchors(space):
    rig = Rig(space)
    rig.run(0.5, (0.2, -0.5), motion="moving")
    poses = rig.run(2.0, (0.2, -0.5), motion="still", only={"uwb_1"})
    assert "frozen" not in {p.mode for p in poses}


def test_freeze_mode_snap_vs_average(space):
    head = (0.3, -0.4)
    snap = frozen_at(Rig(space, freeze_mode="snap"), head)
    assert xy(snap.tr.pose) == (0.0, 0.0)
    avg = frozen_at(Rig(space, freeze_mode="average"), head)
    assert math.dist(xy(avg.tr.pose), head) < 1e-3


@pytest.mark.parametrize("t0", [0.0, 1_761_350_400.0])
def test_average_freeze_is_the_mean_fix_over_the_still_window(space, t0):
    """Noisy ranges: the landing point is the mean of the accepted phone solutions since `still` (within
    average_window_s), moved back by the head offset facing the counter. Also from a clock that starts at 0
    (`still_since == 0.0` used to be treated as "not still" and only the last fix was used)."""
    rig = Rig(space, t0=t0, noise=0.07, seed=3)
    head = (0.2, -0.4)
    rig.tr.on_motion("still", rig.now)
    still_t, fixes = rig.now, []
    while rig.tr.mode != "frozen":
        before = rig.tr.last_fix
        rig.step(head, motion="still")
        if rig.tr.last_fix is not before:
            fixes.append(rig.tr.last_fix)
        assert rig.now - t0 < 3.0
    window = [p for p, t in fixes if t >= max(rig.now - rig.cfg.average_window_s, still_t) - 1e-9]
    assert len(window) >= 6
    mean = (sum(p[0] for p in window) / len(window), sum(p[1] for p in window) / len(window))
    assert math.dist(xy(rig.tr.pose), (mean[0], mean[1] - rig.offset)) < 1e-3
    assert math.dist(xy(rig.tr.pose), head) < 0.15


def test_unfreeze_when_moving_beyond_unfreeze_move_m(space):
    rig = frozen_at(Rig(space), (0.0, -0.3))
    landing = xy(rig.tr.pose)
    side = dict(facing=FORWARD, motion="moving")  # side-step, still facing the counter
    # Shuffle 0.25 m while "moving": under unfreeze_move_m, stays frozen at the landing point.
    poses = rig.walk((0.0, -0.3), (0.25, -0.3), 0.25, **side)
    poses += rig.run(1.0, (0.25, -0.3), motion="moving")
    assert {p.mode for p in poses} == {"frozen"} and all(xy(p) == landing for p in poses)
    # Keep going: once the phone is > 0.35 m from where it froze, tracked again, published at once.
    poses = rig.walk((0.25, -0.3), (0.6, -0.3), 0.25, **side)
    modes = [p.mode for p in poses]
    assert "tracked" in modes and modes[modes.index("tracked") - 1] == "frozen"
    first = poses[modes.index("tracked")]
    assert math.dist(xy(first), landing) > 0.3


def test_still_displacement_does_not_unfreeze(space):
    """Leaning or estimate drift while `still` (inside freeze_exit_m) keeps the landing point."""
    rig = frozen_at(Rig(space), (0.0, -0.3))
    landing = xy(rig.tr.pose)
    poses = rig.walk((0.0, -0.3), (0.0, -0.9), 0.3, motion="still") + rig.run(2.0, (0.0, -0.9), motion="still")
    assert {p.mode for p in poses} == {"frozen"} and all(xy(p) == landing for p in poses)


def test_exit_radius_hysteresis(space):
    """Frozen stays frozen between freeze_enter_m (1.0) and freeze_exit_m (1.3); outside 1.3 it unfreezes even
    while still; tracked at 1.2 never refreezes."""
    rig = frozen_at(Rig(space), (0.0, -0.8))
    back = dict(facing=FORWARD, motion="still")  # drifting backwards while still facing the counter
    poses = rig.walk((0.0, -0.8), (0.0, -1.2), 0.2, **back) + rig.run(3.0, (0.0, -1.2), motion="still")
    assert {p.mode for p in poses} == {"frozen"}
    poses = rig.walk((0.0, -1.2), (0.0, -1.45), 0.2, **back)
    modes = [p.mode for p in poses]
    assert "tracked" in modes and set(modes[:modes.index("tracked")]) == {"frozen"}
    assert math.dist(xy(poses[modes.index("tracked")]), (0.0, 0.0)) > 1.3  # unfroze once outside freeze_exit_m
    poses = rig.walk((0.0, -1.45), (0.0, -1.2), 0.2, **back) + rig.run(3.0, (0.0, -1.2), motion="still")
    assert {p.mode for p in poses} == {"tracked"}
    poses, _ = rig.until("frozen", (0.0, -0.9), motion="still")  # back inside freeze_enter_m: freezes again
    assert poses[-1].mode == "frozen"


def test_refreezes_after_walking_off_and_stopping_again(space):
    rig = frozen_at(Rig(space), (0.0, -0.3))
    rig.walk((0.0, -0.3), (0.6, -0.3), 0.4, motion="moving")
    assert rig.tr.mode == "tracked"
    poses, _ = rig.until("frozen", (0.6, -0.3), motion="still")
    assert math.dist(xy(poses[-1]), (0.6, -0.3)) < 0.02


PATH = [(0.4, -3.0), (0.1, -1.5), (0.0, 0.0)]  # uwb_sim's default walk: start mark -> counter


@pytest.mark.parametrize("speed", [0.6, 1.2, 1.8, 2.2])
def test_clean_walk_at_any_speed_never_blocks_and_lands_on_the_stop(space, speed):
    """Regression (fast walk): the speed gate compared fixes with the lagging alpha-beta output, so at 1.8 m/s
    good fixes were rejected, the stale prediction made leave-one-out drop a healthy anchor, and the freeze
    landed ~0.5 m short; and the landing averaged the filter's overshoot after the stop."""
    for seed in range(5):
        rig = Rig(space, noise=0.03, seed=seed)
        poses = rig.run(1.0, PATH[0], motion="still")
        for a, b in zip(PATH, PATH[1:], strict=False):
            poses += rig.walk(a, b, speed, motion="moving")
        more, _ = rig.until("frozen", PATH[-1], motion="still", limit=2.0)
        poses += more
        assert all(p.blocked == [] and p.anchors_used == 3 for p in poses), seed
        assert math.dist(xy(poses[-1]), PATH[-1]) < 0.2, (seed, poses[-1].position)


def test_fast_walk_is_followed_without_speed_gate_stalls(space):
    rig = Rig(space, noise=0.03, seed=1)
    rig.run(1.0, PATH[0], motion="still")
    lag = []
    for a, b in zip(PATH, PATH[1:], strict=False):
        n = round(math.dist(a, b) / 1.8 / DT)
        for i in range(1, n + 1):
            head = (a[0] + (b[0] - a[0]) * i / n, a[1] + (b[1] - a[1]) * i / n)
            facing = ((b[0] - a[0]) / math.dist(a, b), (b[1] - a[1]) / math.dist(a, b))
            p = rig.step(head, facing=facing, motion="moving")[0]
            lag.append(math.dist(xy(p), head))
    assert max(lag[5:]) < 0.5  # never stuck a meter behind, as when every fix was gated out


def test_turning_while_frozen_and_walking_off_does_not_lock_onto_a_mirror_point(space):
    """Regression: turning 90 degrees moves the phone 0.28 m at once; the stale prediction used to drop uwb_1 and
    track the uwb_2/uwb_3 mirror intersection (0.85 m away) until it froze there."""
    rig = frozen_at(Rig(space), (0.0, -0.3))
    poses = rig.walk((0.0, -0.3), (0.6, -0.3), 0.4, motion="moving")
    assert all(p.blocked == [] for p in poses)
    poses, _ = rig.until("frozen", (0.6, -0.3), motion="still")
    assert math.dist(xy(poses[-1]), (0.6, -0.3)) < 0.02


# ---------------------------------------------------------------- voice override


def test_voice_freeze_outside_the_radius_holds_until_walking_away(space):
    rig = Rig(space)
    head = (0.5, -2.0)
    rig.run(0.5, head, motion="still")
    poses = rig.tr.on_command("freeze", rig.now)
    assert len(poses) == 1 and poses[0].mode == "frozen" and poses[0].t == rig.now
    assert math.dist(xy(poses[0]), head) < 1e-3  # average mode: the current smoothed estimate
    assert {p.mode for p in rig.run(3.0, head, motion="still")} == {"frozen"}  # outside exit radius: still frozen
    assert rig.tr.on_command("freeze", rig.now)[0].mode == "frozen"  # repeating it is harmless
    rig.walk(head, (0.5, -2.5), 0.5, motion="moving")
    assert rig.tr.mode == "tracked"


def test_voice_freeze_snap_mode_goes_to_counter_ref(space):
    rig = Rig(space, freeze_mode="snap")
    rig.run(0.5, (0.5, -2.0), motion="moving")
    assert xy(rig.tr.on_command("freeze", rig.now)[0]) == (0.0, 0.0)


def test_voice_freeze_before_any_range_is_ignored_and_recenter_is_not_ours(space):
    tr = Tracker(UwbCfg(), space, 10.0)
    assert tr.on_command("freeze", 10.0) == [] and tr.mode == "fixed"
    rig = Rig(space)
    rig.run(0.5, (0.5, -2.0))
    assert rig.tr.on_command("recenter", rig.now) == [] and rig.tr.mode == "tracked"


def test_voice_freeze_while_lost_or_fixed_lands_on_counter_ref(space):
    rig = Rig(space)
    rig.run(0.5, (0.5, -2.0), motion="moving")
    rig.until("lost")
    p = rig.tr.on_command("freeze", rig.now)[0]
    assert p.mode == "frozen" and xy(p) == (0.0, 0.0)
    rig = Rig(space)
    rig.run(0.5, (0.5, -2.0), motion="moving")
    rig.until("fixed")
    p = rig.tr.on_command("freeze", rig.now)[0]
    assert p.mode == "frozen" and xy(p) == (0.0, 0.0)
    # The next solve sets the reference for the unfreeze displacement; standing there keeps it frozen.
    assert {p.mode for p in rig.run(1.0, (0.5, -2.0), motion="moving")} == {"frozen"}
    rig.walk((0.5, -2.0), (0.5, -2.6), 0.5, motion="moving")
    assert rig.tr.mode == "tracked"


# ---------------------------------------------------------------- NFC re-anchor


def test_nfc_contact_pulls_the_frozen_point_to_exactly_reach_max_m(space):
    rig = frozen_at(Rig(space), (0.2, -0.5))
    spot = space.spot_position(3)[:2]
    old = rig.tr.position
    assert math.dist(old, spot) > 0.75
    poses = rig.tr.on_contact(3, rig.now, "pickup")
    assert len(poses) == 1 and poses[0].mode == "frozen" and poses[0].t == rig.now
    assert math.dist(rig.tr.position, spot) == pytest.approx(0.75, abs=1e-9)
    assert math.dist(xy(poses[0]), spot) == pytest.approx(0.75, abs=1e-3)
    # Moved straight toward the spot.
    u = ((old[0] - spot[0]) / math.dist(old, spot), (old[1] - spot[1]) / math.dist(old, spot))
    assert rig.tr.position == pytest.approx((spot[0] + 0.75 * u[0], spot[1] + 0.75 * u[1]))
    # Already within reach: no change, nothing published. Later ticks keep the corrected point and stay frozen.
    assert rig.tr.on_contact(3, rig.now, "placed") == []
    after = rig.run(2.0, (0.2, -0.5), motion="still")
    assert {p.mode for p in after} == {"frozen"} and all(xy(p) == xy(poses[0]) for p in after)


def test_nfc_contact_within_reach_or_unknown_spot_changes_nothing(space):
    rig = frozen_at(Rig(space), (0.1, 0.0))
    before = rig.tr.position
    assert math.dist(before, space.spot_position(3)[:2]) < 0.75
    assert rig.tr.on_contact(3, rig.now, "pickup") == [] and rig.tr.position == before
    assert rig.tr.on_contact(99, rig.now, "pickup") == [] and rig.tr.position == before


def test_no_reanchor_while_tracked_or_fixed(space):
    tr = Tracker(UwbCfg(), space, 10.0)
    assert tr.on_contact(3, 10.0, "pickup") == [] and tr.position == (0.0, 0.0)
    rig = Rig(space)
    rig.run(0.5, (0.5, -2.0), motion="moving")
    before = rig.tr.position
    assert rig.tr.on_contact(3, rig.now, "pickup") == [] and rig.tr.position == before
    assert rig.tr.mode == "tracked"


# ---------------------------------------------------------------- lost / fixed


def test_lost_after_lost_after_s_then_fixed_after_lost_hold_s(space):
    rig = Rig(space)
    head = (0.5, -2.0)
    rig.run(1.0, head, motion="moving")
    last_range_t = rig.now
    poses, lost_t = rig.until("lost")
    # Ranges are fresh for 0.5 s; lost once < 2 have been fresh for more than lost_after_s (2 s).
    assert 2.0 < lost_t - last_range_t <= 0.5 + 2.0 + 0.1 + 1e-6
    assert {p.mode for p in poses[:-1]} == {"tracked"} and poses[-1].mode == "lost" and poses[-1].t == lost_t
    lost = poses[-1]
    assert math.dist(xy(lost), head) < 1e-3  # holds the last good position
    assert lost.residual_m is None and lost.anchors_used == 0 and lost.blocked == []
    poses, fixed_t = rig.until("fixed")
    assert 3.0 - 1e-6 <= fixed_t - lost_t <= 3.1 + 1e-6
    assert {p.mode for p in poses[:-1]} == {"lost"} and all(xy(p) == xy(lost) for p in poses[:-1])
    fixed = poses[-1]
    assert fixed.mode == "fixed" and fixed.position == [0.0, 0.0, 0.0] and fixed.source == "none"
    assert fixed.t == fixed_t and rig.step() == []


def test_one_anchor_left_goes_lost(space):
    rig = Rig(space)
    rig.run(1.0, (0.5, -2.0), motion="moving")
    _, t = rig.until("lost", (0.5, -2.0), only={"uwb_3"})
    assert rig.tr.mode == "lost"


def test_lost_resumes_tracking_when_ranges_return(space):
    rig = Rig(space)
    rig.run(1.0, (0.5, -2.0), motion="moving")
    rig.until("lost")
    p = rig.step((0.2, -1.8), motion="moving")
    assert p[0].mode == "tracked" and math.dist(xy(p[0]), (0.2, -1.8)) < 1e-3


def test_fixed_after_lost_resumes_tracking_when_ranges_return(space):
    rig = Rig(space)
    rig.run(1.0, (0.5, -2.0), motion="moving")
    rig.until("fixed")
    p = rig.step((0.2, -1.8), motion="moving")
    assert p[0].mode == "tracked" and p[0].source == "uwb" and math.dist(xy(p[0]), (0.2, -1.8)) < 1e-3


def test_frozen_holds_when_ranges_stop(space):
    """As implemented (PRD 8.5: lost only "while tracked"): a frozen listener stays at the landing spot when
    the wearer stops ranging."""
    rig = frozen_at(Rig(space), (0.0, -0.3))
    poses = rig.run(10.0)
    assert {p.mode for p in poses} == {"frozen"} and all(xy(p) == xy(poses[0]) for p in poses)


# ---------------------------------------------------------------- reset / quality


def test_reset_forgets_everything(space):
    rig = frozen_at(Rig(space), (0.0, -0.3))
    poses = rig.tr.reset(rig.now)
    assert len(poses) == 1 and poses[0].mode == "fixed" and poses[0].position == [0.0, 0.0, 0.0]
    assert poses[0].source == "none" and poses[0].t == rig.now
    assert rig.step() == []  # the old ranges are gone
    assert rig.tr.on_command("freeze", rig.now) == []  # and so is "ever ranged"
    assert all(not h.online and h.distance_m is None for h in rig.tr.pose.anchors)
    assert rig.step((0.0, -0.3), motion="moving")[0].mode == "tracked"


def test_pose_quality_fields(space):
    rig = Rig(space)
    head = (0.2, -1.6)
    p = rig.run(0.5, head, motion="moving")[-1]
    assert (p.anchors_used, p.blocked) == (3, []) and p.residual_m == pytest.approx(0.0, abs=1e-3)
    assert all(h.online for h in p.anchors) and all(h.distance_m is not None for h in p.anchors)
    p = rig.step(head, motion="moving", bias={"uwb_3": 0.4})[0]  # body block on one anchor
    assert (p.anchors_used, p.blocked) == (2, ["uwb_3"]) and math.dist(xy(p), head) < 1e-3
    p = rig.run(0.6, head, motion="moving", only={"uwb_1", "uwb_2"})[-1]  # uwb_3's last range has aged out
    assert p.anchors_used == 2 and p.blocked == [] and [h.online for h in p.anchors] == [True, True, False]
    p = rig.run(1.0, head, motion="moving", only={"uwb_1"})[-1]  # one fresh anchor: no solve, last quality kept
    assert p.mode == "tracked" and [h.online for h in p.anchors] == [True, False, False]
    rows = rig.tr.ingest_anchors(rig.now)
    assert [(r.anchor, r.online) for r in rows] == [("uwb_1", True), ("uwb_2", False), ("uwb_3", False)]
    assert rows[0].position == [-0.9, 0.75, -0.25] and rows[0].last_seen_t == rig.now
