"""Room setup with no tape measure: walk the marks in a pretend room, then check where the beacons were placed."""
import math

import numpy as np

from earmark_ranging.chirp import ChirpSpec
from earmark_ranging.detect import Detector
from earmark_ranging.listen import ChirpFeed, Detection, Tracker, speed_of_sound
from earmark_ranging.service import FS, AudioBuffer
from earmark_ranging.sim_listen import CHUNK, SelfTimedWorld, VirtualTargetPhone, tour
from earmark_ranging.survey import DEFAULT_MARKS, PHONE_HEIGHT_M, Surveyor, place_beacon

SPEC = ChirpSpec(12000.0, 16000.0)
C = speed_of_sound(20.0)
T0 = 1_700_000_000.0
THREE = {1: (0.1, 1.25, 0.75), 2: (1.15, -0.1, 0.75), 3: (-1.2, 0.15, 0.75)}  # roughly ahead, right, left
HINTS = {1: (0.0, 1.2, 0.75), 2: (1.2, 0.0, 0.75), 3: (-1.2, 0.0, 0.75)}
DWELL, WALK = 10.0, 4.0


def run_survey(beacons, noise=0.03, echo=False, seed=3, hints=HINTS, walk_after=True, jitter=0.0):
    """Stand on every mark for DWELL s (walking WALK s between), solve, then track a short walk."""
    marks = [(x, y, PHONE_HEIGHT_M) for x, y in DEFAULT_MARKS]
    t_start = T0 + 3.0
    path, arrivals, t_end = tour(marks, t_start, DWELL, WALK, then_walk=walk_after)
    world = SelfTimedWorld(beacons, path, SPEC, T0, c=C, seed=seed, echo=echo, jitter_s=jitter)
    phone = VirtualTargetPhone(world, T0 + 0.7, seed=seed, noise_rms=noise)
    k0 = phone.start_count
    feed, buf = ChirpFeed(Detector(SPEC, FS), FS), AudioBuffer()

    def wall(t_rec):
        return phone.t_start + t_rec / (1 + phone.drift) + 0.04

    sv = Surveyor(sorted(beacons), DEFAULT_MARKS, C, stop_s=DWELL - 1.0, wall_time=wall, hints=hints)
    starts = [phone.rec_time(t + 0.5) for t in arrivals]  # the user presses Enter just after arriving
    report, tracker, ranges = None, None, []
    k = 0
    while k < (t_end + 8.0 - phone.t_start) * FS:
        buf.write(k0 + k, phone.chunk(k).astype(np.float32))
        k += CHUNK
        dets = [Detection(d.t - k0 / FS, d.shape, d.score, d.snr) for d in feed.poll(buf)]
        if feed.cursor_s is None:
            continue
        cur = feed.cursor_s - k0 / FS
        if report is None:
            j = sv.next_mark
            if sv.current is None and j is not None and cur >= starts[j]:
                sv.start_mark(j, cur)
            for d in dets:
                sv.add(d)
            sv.seen_up_to(cur)
            if sv.done():
                report = sv.solve()
                if report.ok:
                    tracker = Tracker(report.schedules, C, report.positions)
        elif tracker is not None:
            for r in tracker.add(dets, cur):
                true_t = phone.t_start + r.t / (1 + phone.drift)
                ranges.append((r, world.distance(r.beacon, true_t - world.distance(r.beacon, true_t) / C)))
    return report, ranges


def test_three_beacons_are_placed_without_a_tape_measure():
    report, _ = run_survey(THREE)
    assert report.ok, report.lines()
    for k, true in THREE.items():
        assert math.dist(report.positions[k][:2], true[:2]) < 0.08, report.lines()


def test_distances_after_setup_match_the_truth():
    report, ranges = run_survey(THREE)
    assert report.ok, report.lines()
    assert len(ranges) > 20
    errs = [abs(r.distance_m - true) for r, true in ranges]
    assert np.median(errs) < 0.05, f"median distance error {np.median(errs):.3f} m"


def test_setup_survives_echoes():
    report, _ = run_survey(THREE, echo=True, seed=8)
    assert report.ok, report.lines()
    for k, true in THREE.items():
        assert math.dist(report.positions[k][:2], true[:2]) < 0.12, report.lines()


def test_a_beacon_heard_at_too_few_marks_is_reported():
    t = [Detection(0.5 * i + 0.003, "up", 10.0, 20.0) for i in range(20)]
    rep = place_beacon([t, [], [], []], [(x, y, PHONE_HEIGHT_M) for x, y in DEFAULT_MARKS], C)
    assert not rep.ok and "need 3" in rep.problems[0]


def test_setup_with_real_phone_timing_wobble_is_good_to_a_few_centimeters():
    report, ranges = run_survey(THREE, jitter=0.15e-3, seed=4)  # real phones: about 0.15 ms per chirp
    assert report.ok, report.lines()
    for k, true in THREE.items():
        assert math.dist(report.positions[k][:2], true[:2]) < 0.15, report.lines()
    assert np.median([abs(r.distance_m - t) for r, t in ranges]) < 0.08


def test_the_service_reports_where_the_setup_put_the_beacons():
    from earmark_ranging.listen import BeaconSchedule
    from earmark_ranging.service_listen import ListenService
    from earmark_ranging.survey import BeaconPlacement, SurveyReport

    svc = ListenService(HINTS, {}, SPEC, c=C, surveyor=Surveyor([1, 2, 3], None, C))
    assert svc.status().info is None and "not set up" in svc.status().detail
    placed = {1: (0.1, 1.3, 0.75), 2: (1.2, 0.0, 0.75), 3: (-1.3, 0.1, 0.75)}
    sched = {k: BeaconSchedule(0.1 * k, 0.5) for k in placed}
    svc._finish_survey(SurveyReport(True, placed, sched, {k: BeaconPlacement(k) for k in placed}, []))
    st = svc.status()
    assert st.ok and (st.info["B1_x"], st.info["B1_y"], st.info["B3_x"]) == (0.1, 1.3, -1.3)
    assert svc.beacons == placed


def test_the_found_positions_are_saved_back_to_the_beacons_file(tmp_path):
    import json

    from earmark_ranging.config import save_beacons

    f = tmp_path / "beacons.json"
    f.write_text(json.dumps({"note": "x", "beacons": [{"id": "B1", "label": "ahead", "position": [0, 1.2, 0.75]}]}))
    save_beacons(f, {1: (0.034, 1.317, 0.75)}, "2026-10-24T23:00:00")
    data = json.loads(f.read_text())
    assert data["beacons"][0] == {"id": "B1", "label": "ahead", "position": [0.03, 1.32, 0.75]}
    assert data["note"] == "x" and data["set_up"] == "2026-10-24T23:00:00"


def test_two_beacons_are_enough_for_room_setup():
    two = {1: THREE[1], 2: THREE[2]}
    report, _ = run_survey(two, hints={1: HINTS[1], 2: HINTS[2]})
    assert report.ok, report.lines()
    for k, true in two.items():
        assert math.dist(report.positions[k][:2], true[:2]) < 0.08, report.lines()
