"""Calibrate-then-listen: self-timed beacons, one recording phone. Pure tests first, then the service over a socket."""
import asyncio
import contextlib
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
