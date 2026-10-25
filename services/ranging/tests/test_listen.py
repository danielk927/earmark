"""Calibrate-then-listen: self-timed beacons, one recording phone. Pure tests first, then the service over a socket."""
import asyncio
import contextlib
import json
import math
import time

import numpy as np
import pytest
from websockets.asyncio.server import serve

from earmark_ranging.chirp import ChirpSpec
from earmark_ranging.config import load_anchors
from earmark_ranging.detect import Detector
from earmark_ranging.listen import Calibrator, ChirpFeed, Detection, Tracker, known_distances, speed_of_sound
from earmark_ranging.service import FS, AudioBuffer, BusPublisher
from earmark_ranging.service_listen import ListenService
from earmark_ranging.sim_listen import CHUNK, SelfTimedWorld, VirtualTargetPhone

SPEC = ChirpSpec(12000.0, 16000.0)
C = speed_of_sound(20.0)
T0 = 1_700_000_000.0  # a pretend unix time the beacons were switched on
B1 = {1: (-1.6, 1.5, 0.75)}
FOUR = {1: (-1.6, 1.5, 0.75), 2: (1.6, 1.5, 0.75), 3: (-1.2, -1.7, 0.75), 4: (1.4, -1.5, 0.75)}
SPOT = (-1.6, 0.5, 0.75)  # exactly 1 m from B1


def walk_from(spot, start_true, toward, d0, d1, seconds):
    """Still at `spot` until `start_true`, then straight toward/away from `toward` so the distance goes d0 -> d1."""
    p, q = np.array(spot), np.array(toward)
    u = (p - q) / np.linalg.norm(p - q)

    def path(t):
        if t <= start_true:
            return spot
        f = min((t - start_true) / seconds, 1.0)
        return tuple(float(v) for v in q + u * (d0 + f * (d1 - d0)))

    return path


def run_offline(beacons, world_beacons, path, known, noise=0.03, echo=False, cal_s=10.0, total_s=24.0, seed=5, cal_at=1.0):
    """The whole pure pipeline on synthetic audio: chunks into an AudioBuffer, ChirpFeed, Calibrator, then Tracker."""
    world = SelfTimedWorld(world_beacons, path, SPEC, T0, c=C, seed=seed, echo=echo)
    phone = VirtualTargetPhone(world, T0 + 0.7, seed=seed, noise_rms=noise)
    k0 = phone.start_count
    feed, buf = ChirpFeed(Detector(SPEC, FS), FS), AudioBuffer()

    def wall(t_rec):  # what the service gets from the chunk lag: right to a few tens of ms
        return phone.t_start + t_rec / (1 + phone.drift) + 0.04

    cal = Calibrator(known, C, cal_s, wall_time=wall)
    tracker, report, ranges = None, None, []
    k = 0
    while k < total_s * FS:
        buf.write(k0 + k, phone.chunk(k).astype(np.float32))
        k += CHUNK
        dets = [Detection(d.t - k0 / FS, d.shape, d.score, d.snr) for d in feed.poll(buf)]
        if feed.cursor_s is None:
            continue
        cur = feed.cursor_s - k0 / FS
        if cal.started_at is None and cur >= cal_at:
            cal.start(cur)
        if tracker is None:
            for d in dets:
                cal.add(d)
            cal.seen_up_to(cur)
            if cal.done():
                report = cal.fit()
                if report.ok:
                    tracker = Tracker(report.schedules, C, beacons)
                else:
                    break
        else:
            ranges.extend(tracker.add(dets, cur))
    return report, ranges, phone, world


def true_schedule(phone, world, beacon):
    """The beacon's real play times on the recording, and the real period there."""
    rec = [phone.rec_time(world.emission_time(beacon, m)) for m in range(0, 80)]
    return rec, rec[1] - rec[0]


def cycle_offset(schedule, rec_times):
    """Which real cycle the fitted schedule calls n = 0."""
    return int(np.argmin([abs(schedule.a - t) for t in rec_times]))


def test_one_beacon_calibration_is_exact():
    report, _, phone, world = run_offline(B1, B1, SPOT, known_distances(B1, distance=1.0), total_s=12.0)
    assert report.ok, report.lines()
    s = report.schedules[1]
    rec, period = true_schedule(phone, world, 1)
    m0 = cycle_offset(s, rec)
    assert abs(s.b / period - 1) * 1e6 < 2.0, f"period off by {(s.b / period - 1) * 1e6:.2f} ppm"
    assert abs(s.a - rec[m0]) < 20e-6, f"play time off by {(s.a - rec[m0]) * 1e6:.1f} us"
    assert report.beacons[1].kept >= 18 and report.beacons[1].residual_ms < 0.05


def test_four_beacons_are_all_told_apart():
    at = (0.2, 0.1, 1.2)
    report, _, phone, world = run_offline(FOUR, FOUR, at, known_distances(FOUR, at=at), total_s=12.0)
    assert report.ok, report.lines()
    assert sorted(report.schedules) == [1, 2, 3, 4]
    for k, s in report.schedules.items():
        rec, period = true_schedule(phone, world, k)
        assert abs(s.b / period - 1) * 1e6 < 2.0
        assert abs(s.a - rec[cycle_offset(s, rec)]) < 20e-6, f"B{k} was mixed up with another beacon"
        assert report.beacons[k].kept >= 18
        assert abs(report.beacons[k].phase_error_ms) < 100  # it also chirps in its own wall-clock slot


@pytest.mark.parametrize("echo", [False, True])
def test_walking_away_gives_a_distance_every_chirp(echo):
    # still 11 s for calibration, then 0.5 m -> 3.0 m over 10 s, in noise loud enough that chirps are only ~15-45x
    # above the background in the detector's measure
    path = walk_from(SPOT, T0 + 12.0, B1[1], 0.5, 3.0, 10.0)
    report, ranges, phone, world = run_offline(B1, B1, path, known_distances(B1, distance=1.0), noise=0.3, echo=echo)
    assert report.ok, report.lines()
    rec, _ = true_schedule(phone, world, 1)
    m0 = cycle_offset(report.schedules[1], rec)
    moving = [r for r in ranges if world.emission_time(1, m0 + r.cycle) > T0 + 12.0]
    assert len(moving) >= 18  # about two a second for ten seconds (the last second or so is past the audio)
    errs = np.array([abs(r.distance_m - world.distance(1, world.emission_time(1, m0 + r.cycle))) for r in moving])
    assert np.median(errs) < 0.02, errs
    assert np.percentile(errs, 95) < 0.05, errs
    assert np.mean(errs < 0.10) >= 0.95  # the direct sound was chosen, not an echo
    span = moving[-1].t - moving[0].t
    assert len(moving) - 1 == pytest.approx(span / 0.5, abs=1)  # one per cycle, none doubled


def test_a_missing_beacon_is_named():
    report, _, _, _ = run_offline(FOUR, {1: FOUR[1], 3: FOUR[3]}, SPOT, known_distances(FOUR, at=SPOT), total_s=12.0)
    assert not report.ok
    assert 1 in report.schedules and 3 in report.schedules
    assert any("B2" in p for p in report.beacons[2].problems) and any("B4" in p for p in report.beacons[4].problems)


def test_fit_rejects_a_moving_phone():
    # Creeping away at 0.1 m/s during calibration looks like a 290 ppm clock, far more than phone clocks differ by.
    path = walk_from(SPOT, T0, B1[1], 1.0, 2.0, 10.0)
    report, _, _, _ = run_offline(B1, B1, path, known_distances(B1, distance=1.0), total_s=12.0)
    assert not report.ok and any("moving" in p for p in report.beacons[1].problems)
    # Waving it about is ragged instead.
    wobble = lambda t: (SPOT[0], SPOT[1] + 0.2 * math.sin(7 * (t - T0)), SPOT[2])  # noqa: E731
    report, _, _, _ = run_offline(B1, B1, wobble, known_distances(B1, distance=1.0), total_s=12.0)
    assert not report.ok and any("ragged" in p for p in report.beacons[1].problems)


def test_known_distances_needs_the_right_inputs():
    with pytest.raises(ValueError):
        known_distances(FOUR, distance=1.0)
    assert known_distances(FOUR, at=(0, 0, 0.75))[2] == pytest.approx(math.hypot(1.6, 1.5))


# ------------------------------------------------------------------------------------------------- over the socket


@contextlib.asynccontextmanager
async def running(beacons, target, known, cal_s=7.0, noise=0.03, auto_after=1.0, **phone_kw):
    svc = ListenService(beacons, known, SPEC, c=C, calibration_s=cal_s, publisher=BusPublisher(None))
    ranges, fixes, reports = [], [], []
    svc.on_range = lambda r, wall: ranges.append((time.monotonic(), r, wall))
    svc.on_fix = lambda fix, pose: fixes.append((time.monotonic(), fix, pose))
    svc.on_report = reports.append
    t0 = time.time()
    world = SelfTimedWorld(beacons, target, SPEC, t0, c=C, seed=3)
    phone = VirtualTargetPhone(world, t0 + 0.3, seed=3, noise_rms=noise, **phone_kw)
    stop = asyncio.Event()
    async with serve(svc.handler, "127.0.0.1", 0, max_size=2**22) as server:
        port = server.sockets[0].getsockname()[1]
        tasks = [asyncio.create_task(svc.run(auto_after)), asyncio.create_task(phone.run(f"ws://127.0.0.1:{port}", stop))]
        try:
            yield svc, ranges, fixes, reports, world
        finally:
            stop.set()
            for t in tasks:
                t.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)


async def test_one_beacon_over_the_socket_calibrates_then_ranges_twice_a_second():
    known = known_distances(B1, distance=1.0)
    async with running(B1, SPOT, known) as (svc, ranges, fixes, reports, world):
        for _ in range(200):  # until calibration is done, at most 20 s
            await asyncio.sleep(0.1)
            if reports:
                break
        assert reports and reports[0].ok, reports[0].lines() if reports else "never calibrated"
        assert svc.state == "tracking"
        await asyncio.sleep(5.0)
    assert 8 <= len(ranges) <= 12, f"{len(ranges)} distances in 5 s"
    ds = [r.distance_m for _, r, _ in ranges]
    assert np.median(np.abs(np.array(ds) - 1.0)) < 0.03, ds
    walls = [w for _, _, w in ranges]
    assert all(w is not None for w in walls)
    gaps = np.diff(walls)
    assert np.allclose(gaps, 0.5, atol=0.01), gaps  # chirps really are half a second apart on the wall clock
    assert not fixes  # one beacon gives distances, never a position


async def test_three_beacons_over_the_socket_give_a_position():
    anchors = load_anchors()
    me = (0.3, 0.5, 1.2)
    async with running(anchors, me, known_distances(anchors, at=me)) as (svc, ranges, fixes, reports, world):
        for _ in range(200):
            await asyncio.sleep(0.1)
            if reports:
                break
        assert reports and reports[0].ok, reports[0].lines() if reports else "never calibrated"
        await asyncio.sleep(4.0)
    assert sorted({r.beacon for _, r, _ in ranges}) == sorted(anchors)
    assert len(fixes) >= 5
    _, fix, pose = fixes[-1]
    assert math.dist(fix.position, me) < 0.2
    assert pose.position == pytest.approx((me[0], me[1], me[2] + 0.35), abs=0.2)
    assert pose.quality in ("ok", "degraded") and pose.beacons_heard == 3 and pose.source == "beacons"


def _jump_tracker():
    from earmark_ranging.listen import BeaconSchedule

    return Tracker({1: BeaconSchedule(a=0.0, b=0.5)}, C, {1: (0.0, 0.0, 0.0)})


def _range(t, d, n):
    from earmark_ranging.listen import Range

    return Range(1, d, t, n, 30.0)


def test_one_wild_distance_is_ignored_but_a_real_move_is_followed():
    tr = _jump_tracker()
    tr.latest[1] = _range(10.0, 1.00, 20)
    assert not tr._jumped(1, _range(10.5, 1.08, 21))  # ordinary wobble
    tr.latest[1] = _range(10.5, 1.08, 21)
    assert tr._jumped(1, _range(11.0, 2.20, 22))  # a lone echo
    assert not tr._jumped(1, _range(11.5, 1.12, 23))  # back to normal: the echo is forgotten
    tr.latest[1] = _range(11.5, 1.12, 23)
    assert tr._jumped(1, _range(12.0, 3.00, 24))  # first far reading: held back
    assert not tr._jumped(1, _range(12.5, 3.05, 25))  # second agrees: the phone really went there


def test_a_long_silence_resets_the_filter():
    tr = _jump_tracker()
    tr.latest[1] = _range(10.0, 1.00, 20)
    assert not tr._jumped(1, _range(14.0, 4.00, 28))


def _hears_both(tracker, true_xy, z, beacons, cycle=40):
    """Feed the tracker exactly the chirps a phone at `true_xy` would hear from each beacon (schedules a=0, b=0.5)."""
    dets = []
    for k, p in beacons.items():
        d = math.dist((*true_xy, z), p)
        dets.append(Detection(cycle * 0.5 + d / C, "up" if k % 2 else "down", 1.0, 100.0))
    tracker.add(dets, cycle * 0.5 + 1.0)
    return tracker.fix(cycle * 0.5 + 0.2)


TWO = {1: (0.0, 1.2, 0.75), 2: (1.2, 0.0, 0.75)}  # ahead and to the right; the user stands behind-left of their line


def test_two_beacons_give_a_position_on_the_users_side():
    from earmark_ranging.listen import BeaconSchedule

    sched = {1: BeaconSchedule(0.0, 0.5), 2: BeaconSchedule(0.0, 0.5)}
    for true in [(0.0, 0.0), (-0.4, 0.3), (0.3, -0.6)]:
        tr = Tracker(sched, C, TWO, side_ref=(0.0, 0.0))
        got = _hears_both(tr, true, 1.25, TWO)
        assert got is not None
        fix, pose = got
        assert fix.used == 2 and pose.quality == "degraded"
        assert math.dist(fix.position[:2], true) < 0.02, (fix.position, true)
        assert abs(pose.position[2] - (1.25 + 0.35)) < 1e-6


def test_two_beacons_with_the_other_side_as_reference_pick_the_mirror_image():
    from earmark_ranging.listen import BeaconSchedule

    sched = {1: BeaconSchedule(0.0, 0.5), 2: BeaconSchedule(0.0, 0.5)}
    tr = Tracker(sched, C, TWO, side_ref=(1.5, 1.5))  # the far side of the line x + y = 1.2
    got = _hears_both(tr, (0.0, 0.0), 1.25, TWO)
    assert got is not None and got[0].position[0] > 0.6  # the mirror image of the origin across the line is (1.2, 1.2)


def test_one_beacon_alone_gives_no_position():
    from earmark_ranging.listen import BeaconSchedule

    tr = Tracker({1: BeaconSchedule(0.0, 0.5)}, C, {1: TWO[1]})
    assert _hears_both(tr, (0.0, 0.0), 1.25, {1: TWO[1]}) is None


def test_a_beacon_phone_set_to_the_wrong_number_is_named():
    svc = ListenService({1: TWO[1]}, {1: 1.0}, SPEC, c=C)
    clear_down_chirp = Detection(10.0, "down", 2.5, 400.0)
    for _ in range(5):
        svc._note_heard(clear_down_chirp, svc.calibrator.assign(clear_down_chirp))
    hint = svc.wrong_beacon_hint()
    assert hint is not None and "Beacon 2" in hint and "B1" in hint and "--only B2" in hint
    assert svc.missing_beacons() == [1]


THREE = {1: (0.0, 1.2, 0.75), 2: (1.2, -0.6, 0.75), 3: (-1.2, -0.6, 0.75)}


def _three_tracker():
    from earmark_ranging.listen import BeaconSchedule

    return Tracker({k: BeaconSchedule((k - 1) * 0.125, 0.5) for k in THREE}, C, THREE)  # each beacon chirps in its own slot


def _hear(tracker, k, true_xy, z, t_cycle):
    """Give the tracker the one chirp beacon `k` would have produced in cycle `t_cycle`; returns the ranges."""
    d = math.dist((*true_xy, z), THREE[k])
    det = Detection(t_cycle * 0.5 + (k - 1) * 0.125 + d / C, "up" if k % 2 else "down", 1.0, 100.0)
    return tracker.add([det], t_cycle * 0.5 + 1.0)


def _step(tracker, true_xy, cycle, beacons=(1, 2, 3)):
    for k in beacons:
        _hear(tracker, k, true_xy, 1.25, cycle)
    return tracker.fix(cycle * 0.5 + 0.2)


def test_with_three_beacons_configured_two_fresh_distances_publish_nothing():
    # With no good fix to lean on, two beacons would flip between answers, so three are required.
    tr = _three_tracker()
    assert _step(tr, (0.1, 0.2), 40, beacons=(1, 2)) is None
    assert _step(tr, (0.1, 0.2), 60, beacons=(1, 3)) is None  # B2's old distance is long stale
    assert _step(tr, (0.1, 0.2), 61) is not None


def test_one_beacon_dropping_out_keeps_a_degraded_fix_for_a_few_seconds_only():
    from earmark_ranging.listen import TWO_BEACON_HOLD_S

    tr = _three_tracker()
    true = (0.1, 0.2)
    for cycle in range(40, 44):
        assert _step(tr, true, cycle) is not None
    # B2 falls silent (a body in the way): the other two carry on, on the same side as before
    for cycle in range(44, 47):  # by the last of these, B2's old distance has gone stale
        got = _step(tr, true, cycle, beacons=(1, 3))
    assert got is not None and got[1].quality == "degraded" and got[1].beacons_heard == 2
    assert math.dist(got[0].position[:2], true) < 0.1
    # ... but not forever
    late = 44 + int(TWO_BEACON_HOLD_S / 0.5) + 4
    assert _step(tr, true, late, beacons=(1, 3)) is None


def test_steady_input_converges_to_the_truth():
    tr = _three_tracker()
    true = (0.2, 0.1)
    got = None
    for cycle in range(40, 50):
        got = _step(tr, true, cycle) or got
    assert got is not None and math.dist(got[0].position[:2], true) < 0.02


def test_jumpy_input_stays_under_the_speed_limit():
    from earmark_ranging.listen import FIX_SLACK_M, MAX_FIX_MPS

    tr = _three_tracker()
    published = []
    for cycle in range(40, 80):
        # every third reading is a wild one, far from where the user stands
        true = (1.0, -0.4) if cycle % 3 == 0 else (0.1, 0.2)
        got = _step(tr, true, cycle)
        if got is not None:
            published.append((cycle * 0.5 + 0.2, got[0].position))
    assert len(published) > 10
    assert all(abs(p[1][0] - 0.1) < 0.05 and abs(p[1][1] - 0.2) < 0.05 for p in published)
    for (t0, p0), (t1, p1) in zip(published, published[1:], strict=False):
        assert math.dist(p0, p1) <= FIX_SLACK_M + MAX_FIX_MPS * (t1 - t0)


def test_a_real_move_is_followed_after_a_few_rejected_fixes():
    tr = _three_tracker()
    for cycle in range(40, 45):
        _step(tr, (0.0, 0.0), cycle)
    got = None
    for cycle in range(45, 60):  # the user is now somewhere else for good
        got = _step(tr, (0.9, 0.5), cycle) or got
    assert got is not None and math.dist(got[0].position[:2], (0.9, 0.5)) < 0.05


# ------------------------------------------------------------------------------------------------- reconnects


class _Socket:
    """Just enough of a websocket for ListenService.handler: hands over the messages, keeps what was sent."""

    def __init__(self, *msgs):
        self.msgs, self.sent = [json.dumps(m) for m in msgs], []

    async def __aiter__(self):
        for m in self.msgs:
            yield m

    async def send(self, s):
        self.sent.append(s)


class _Bus:
    def __init__(self):
        self.sent = []

    async def send(self, msg):
        self.sent.append(msg)


def _tracking_service():
    from earmark_ranging.listen import BeaconSchedule
    from earmark_ranging.solve import Fix

    anchors = load_anchors()
    bus = _Bus()
    svc = ListenService(anchors, known_distances(anchors, at=(0.0, 0.0, 1.25)), SPEC, c=C, publisher=bus)
    svc.tracker = Tracker({k: BeaconSchedule(a=0.0, b=0.5) for k in anchors}, C, anchors)
    svc.tracker.last_fix = Fix((0.3, 0.5, 1.2), 3, 0.01)
    svc.state, svc.feed.cursor = "tracking", 480_000
    notices = []
    svc.on_notice = notices.append
    return svc, bus, notices


async def test_the_users_phone_reconnecting_drops_the_calibration():
    svc, bus, notices = _tracking_service()
    await svc.handler(_Socket({"type": "join", "slot": 0, "name": "judge"}))
    # Its sample counter skipped the seconds it was offline, so the old schedules would give confident nonsense.
    assert svc.state == "idle" and svc.tracker is None and svc.feed.cursor is None
    [lost] = bus.sent
    assert lost.quality == "lost" and lost.beacons_heard == 0
    assert notices and "calibration spot" in notices[0]
    assert "phone reconnected" in svc.status_line()


async def test_the_first_join_forgets_nothing():
    anchors = load_anchors()
    bus = _Bus()
    svc = ListenService(anchors, known_distances(anchors, at=(0.0, 0.0, 1.25)), SPEC, c=C, publisher=bus)
    notices = []
    svc.on_notice = notices.append
    await svc.handler(_Socket({"type": "join", "slot": 0, "name": "judge"}))
    assert svc.state == "idle" and not bus.sent and not notices
    svc2, bus2, notices2 = _tracking_service()
    await svc2.handler(_Socket({"type": "join", "slot": 2, "name": "beacon"}))  # another slot: not the user's phone
    assert svc2.state == "tracking" and not bus2.sent and not notices2


async def test_a_solver_error_does_not_end_the_service():
    svc, _, _ = _tracking_service()
    calls = []

    def broken_fix(now_t):
        calls.append(now_t)
        raise ValueError("Residuals are not finite in the initial point")

    svc.step = lambda: [object()]  # a new distance on every pass
    svc.tracker.fix = broken_fix
    task = asyncio.create_task(svc.run())
    await asyncio.sleep(0.3)
    assert not task.done(), task.exception() if task.done() else None
    assert len(calls) >= 2
    task.cancel()
    await asyncio.gather(task, return_exceptions=True)
