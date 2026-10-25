"""Calibrate-then-listen: the beacons chirp on their own clocks and only the user's phone records.

Every beacon plays the same chirp every 0.5 s, for ever, with nothing telling it when: beacon N starts its chirp
(N-1)*0.125 s into each half second of wall-clock time, lined up once when it starts, and from then on exactly
periodic in its own audio clock. On the user's phone's recording those chirps land at t = a + b*n: b is very
nearly 0.5 s (off by the two clocks' rate difference, tens of parts per million) and a is unknown.

Calibration learns a and b while the phone sits still at a known distance from each beacon. After that each
chirp heard gives a distance on its own: how late it is against the schedule, times the speed of sound.

Nothing in here talks to the network; the service feeds it detections and prints what comes out.
"""
from __future__ import annotations

import math
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass, field, replace

import numpy as np
from earmark_contracts import ListenerPose

from .config import EAR_OFFSET_M, HEIGHT_PRIOR
from .detect import Detector
from .solve import Fix, locate, locate_two

CYCLE_S = 0.5  # every beacon chirps this often
SLOT_S = 0.125  # beacon N chirps (N-1) slots into each cycle
MAX_BEACONS = 4
MIN_KEPT = 12  # chirps a calibration needs from each beacon
MAX_RESIDUAL_S = 0.0003  # how ragged the fitted schedule may be
MAX_PERIOD_PPM = 150.0  # two phone clocks differ by tens of ppm; more than this means the phone was moving
MAX_FIX_MPS = 1.5  # a position may move this fast at most; a faster fix is thrown away
FIX_SLACK_M = 0.10  # plus this much measurement wobble
MAX_REJECTS = 3  # after this many thrown-away fixes in a row, believe the next one so we can recover
FIX_FORGET_S = 1.5  # after this long without a fix, start fresh (no speed check, no smoothing)
TWO_BEACON_HOLD_S = 8.0  # after a good fix, two beacons are enough for this long if a third drops out
SMOOTH_FIXES = 3  # the published x and y are the middle value of this many recent fixes
MAX_WALK_MPS = 1.2  # a distance may change this fast at most (a blindfolded user walks slowly)
JUMP_SLACK_M = 0.3  # plus this much measurement wobble
JUMP_FORGET_S = 2.0  # after this long without a good distance, believe the next one

Pos = tuple[float, float, float]


def speed_of_sound(temperature_c: float = 20.0) -> float:
    """Meters per second in air at this temperature (degrees C)."""
    return 331.3 + 0.606 * temperature_c


def beacon_shape(beacon: int) -> str:
    """Odd beacons sweep up, even ones sweep down."""
    return "up" if beacon % 2 == 1 else "down"


def beacon_phase(beacon: int, slot_s: float = SLOT_S) -> float:
    """Where in each cycle (seconds after the cycle starts, wall clock) this beacon starts its chirp."""
    return (beacon - 1) * slot_s


def identify_beacon(shape: str, wall: float | None, cycle_s: float = CYCLE_S, slot_s: float = SLOT_S) -> list[int]:
    """Which beacon numbers (1 to 4) make a chirp of this shape; one number when a wall-clock time pins it down."""
    same = [k for k in range(1, MAX_BEACONS + 1) if beacon_shape(k) == shape]
    if wall is None:
        return same
    return [min(same, key=lambda k: _phase_distance(wall % cycle_s, beacon_phase(k, slot_s), cycle_s))]


def _phase_distance(x: float, y: float, cycle_s: float) -> float:
    d = (x - y) % cycle_s
    return min(d, cycle_s - d)


@dataclass(frozen=True)
class Detection:
    """A chirp heard on the target's recording."""

    t: float  # seconds on the recording's timeline
    shape: str  # "up" or "down"
    score: float
    snr: float


@dataclass(frozen=True)
class BeaconSchedule:
    """When a beacon's chirps leave its speaker, on the target's recording timeline: cycle n plays at a + b*n."""

    a: float
    b: float

    def play_time(self, n: int) -> float:
        return self.a + self.b * n

    def cycle_of(self, t: float) -> int:
        return int(round((t - self.a) / self.b))


@dataclass(frozen=True)
class Range:
    """One distance from one chirp."""

    beacon: int
    distance_m: float
    t: float  # when the chirp was heard, on the recording
    cycle: int
    snr: float


# ---------------------------------------------------------------------------------------------- live detection


class ChirpFeed:
    """Runs the detector over audio as it arrives, reporting every chirp exactly once with its time on the recording.

    `poll` looks at everything after the last point it finished with (plus some earlier context so the filters
    settle), and holds back the last `tail_s` so a chirp that has only half arrived is left for the next poll.
    """

    def __init__(self, detector: Detector, fs: float, stride_s: float = 0.1, context_s: float = 0.3, tail_s: float = 0.05):
        self.detector, self.fs = detector, fs
        self.stride, self.context, self.tail = int(stride_s * fs), int(context_s * fs), int(tail_s * fs)
        self.cursor: int | None = None  # first sample not yet reported on

    @property
    def cursor_s(self) -> float | None:
        return None if self.cursor is None else self.cursor / self.fs

    def poll(self, buf) -> list[Detection]:
        """`buf` is an AudioBuffer (service.py) or anything with `started`, `end`, `n` and `get(a, b)`."""
        if not buf.started:
            return []
        end, first = buf.end, getattr(buf, "first", 0)
        if self.cursor is None:
            self.cursor = max(end - self.stride - self.tail, end - buf.n + self.context, first)
        if self.cursor < end - buf.n + self.context:  # fell behind: skip to what is still in the buffer
            self.cursor = end - buf.n + self.context
        if end - self.tail - self.cursor < self.stride:
            return []
        a = max(self.cursor - self.context, end - buf.n, first)
        audio = buf.get(a, end)
        if audio is None:
            return []
        upto = end - self.tail
        lo, hi = self.cursor / self.fs, upto / self.fs
        out = [
            Detection(a / self.fs + e.t, e.shape, e.score, e.snr)
            for e in self.detector.find(audio, prefer="earliest")
            if lo <= a / self.fs + e.t < hi
        ]
        self.cursor = upto
        return out


def _earliest_strong(dets: list[Detection], ratio: float = 0.5) -> Detection:
    """Echoes are always late: take the first peak that is not far weaker than the strongest."""
    strongest = max(d.score for d in dets)
    return min((d for d in dets if d.score >= ratio * strongest), key=lambda d: d.t)


# ---------------------------------------------------------------------------------------------- calibration


@dataclass
class BeaconReport:
    beacon: int
    heard: int = 0  # detections assigned to it
    kept: int = 0  # detections the fit kept
    residual_ms: float | None = None
    period_s: float | None = None
    phase_error_ms: float | None = None  # measured wall-clock phase minus expected, if a wall clock was available
    problems: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.problems


@dataclass
class CalibrationReport:
    ok: bool
    schedules: dict[int, BeaconSchedule]
    beacons: dict[int, BeaconReport]
    problems: list[str]

    def lines(self) -> list[str]:
        out = [f"calibration {'ok' if self.ok else 'FAILED'}"]
        for k, r in sorted(self.beacons.items()):
            if r.period_s is not None:
                ppm = (r.period_s / CYCLE_S - 1) * 1e6
                s = (f"  B{k}: {r.kept}/{r.heard} chirps kept, residual {r.residual_ms:.3f} ms, "
                     f"period {r.period_s:.6f} s ({ppm:+.1f} ppm)")
                if r.phase_error_ms is not None:
                    s += f", phase off by {r.phase_error_ms:+.0f} ms"
            else:
                s = f"  B{k}: {r.heard} chirps heard"
            out.append(s)
            out.extend(f"     problem: {p}" for p in r.problems)
        out.extend(f"  problem: {p}" for p in self.problems)
        return out


def fit_schedule(
    dets: list[Detection], cycle_s: float = CYCLE_S, passes: int = 3
) -> tuple[BeaconSchedule, list[Detection], float] | None:
    """Robust straight line through one beacon's detections: t = a + b*n, n counted from the first kept chirp.

    Returns (schedule, kept detections, residual standard deviation) or None if there was nothing to fit.
    """
    if len(dets) < 2:
        return None
    ref = max(dets, key=lambda d: d.score).t  # a strong chirp is a safe reference for counting cycles
    by_cycle: dict[int, list[Detection]] = {}
    for d in dets:
        by_cycle.setdefault(int(round((d.t - ref) / cycle_s)), []).append(d)
    chosen = {n: _earliest_strong(group) for n, group in by_cycle.items()}
    n = np.array(sorted(chosen), dtype=float)
    t = np.array([chosen[int(k)].t for k in n])
    if len(n) < 2:
        return None
    keep = np.ones(len(n), dtype=bool)
    a, b = float(np.median(t - cycle_s * n)), cycle_s
    for _ in range(passes):
        r = t - (a + b * n)
        med = np.median(r[keep])
        mad = np.median(np.abs(r[keep] - med))
        keep = np.abs(r - med) <= max(3 * 1.4826 * mad, 50e-6)
        if keep.sum() < 2:
            return None
        b, a = np.polyfit(n[keep], t[keep], 1)
    r = t - (a + b * n)
    resid = float(np.std(r[keep])) if keep.sum() > 2 else float("inf")
    n0 = n[keep].min()
    kept = [chosen[int(k)] for k in n[keep]]
    return BeaconSchedule(float(a + b * n0), float(b)), kept, resid


class Calibrator:
    """Collects chirps while the phone sits still at a known spot, then works out every beacon's schedule.

    `known_distance` is beacon -> how far the phone is from it during calibration (meters).
    `wall_time` turns a recording time into a wall-clock (unix) time, good to a few tens of ms; it is only needed
    when two beacons share a shape (B1 and B3, or B2 and B4), which chirp a quarter second apart.
    """

    def __init__(
        self,
        known_distance: dict[int, float],
        c: float,
        duration_s: float = 10.0,
        cycle_s: float = CYCLE_S,
        slot_s: float = SLOT_S,
        wall_time: Callable[[float], float | None] | None = None,
    ) -> None:
        self.known, self.c, self.duration = dict(known_distance), c, duration_s
        self.cycle, self.slot, self.wall_time = cycle_s, slot_s, wall_time
        self.detections: list[Detection] = []
        self.started_at: float | None = None  # recording time
        self.latest: float | None = None

    @property
    def beacons(self) -> list[int]:
        return sorted(self.known)

    def start(self, t_rec: float) -> None:
        self.started_at, self.latest, self.detections = t_rec, t_rec, []

    def cancel(self) -> None:
        self.started_at, self.latest, self.detections = None, None, []

    def add(self, det: Detection) -> None:
        if self.started_at is not None and det.t >= self.started_at:
            self.detections.append(det)

    def seen_up_to(self, t_rec: float) -> None:
        self.latest = max(self.latest or t_rec, t_rec)

    def remaining(self) -> float:
        if self.started_at is None or self.latest is None:
            return self.duration
        return max(0.0, self.duration - (self.latest - self.started_at))

    def done(self) -> bool:
        return self.started_at is not None and self.remaining() <= 0.0

    def assign(self, det: Detection) -> int | None:
        """Which beacon this chirp came from: its shape, and if that leaves two, where in the cycle it fell."""
        candidates = [k for k in self.beacons if beacon_shape(k) == det.shape]
        if not candidates:
            return None
        if len(candidates) == 1:
            return candidates[0]
        if self.wall_time is None:
            return None
        wall = self.wall_time(det.t)
        if wall is None:
            return None
        return min(candidates, key=lambda k: _phase_distance(wall % self.cycle, beacon_phase(k, self.slot), self.cycle))

    def fit(self) -> CalibrationReport:
        per: dict[int, list[Detection]] = {k: [] for k in self.beacons}
        reports = {k: BeaconReport(k) for k in self.beacons}
        problems: list[str] = []
        shapes = {beacon_shape(k) for k in self.beacons}
        for s in shapes:
            same = [k for k in self.beacons if beacon_shape(k) == s]
            if len(same) > 1 and self.wall_time is None:
                problems.append(f"cannot tell {' from '.join(f'B{k}' for k in same)} apart without a wall clock")
        for d in self.detections:
            k = self.assign(d)
            if k is not None:
                per[k].append(d)
        schedules: dict[int, BeaconSchedule] = {}
        for k, dets in per.items():
            rep = reports[k]
            rep.heard = len(dets)
            fit = fit_schedule(dets, self.cycle)
            if fit is None:
                rep.problems.append(f"B{k}: heard {len(dets)} chirps, need {MIN_KEPT} (is it on, loud, facing the phone?)")
                continue
            sched, kept, resid = fit
            rep.kept, rep.residual_ms, rep.period_s = len(kept), resid * 1000, sched.b
            if len(kept) < MIN_KEPT:
                rep.problems.append(f"B{k}: only {len(kept)} usable chirps, need {MIN_KEPT}")
            if resid > MAX_RESIDUAL_S:
                rep.problems.append(
                    f"B{k}: chirps are {resid * 1000:.2f} ms ragged, limit {MAX_RESIDUAL_S * 1000:.1f} ms (echoes? moving?)")
            ppm = (sched.b / self.cycle - 1) * 1e6
            if abs(ppm) > MAX_PERIOD_PPM:
                rep.problems.append(
                    f"B{k}: period {sched.b:.6f} s is {ppm:+.0f} ppm off; clocks differ by tens of ppm, so the phone was moving")
            a_play = sched.a - self.known[k] / self.c
            if self.wall_time is not None:
                wall = self.wall_time(a_play)
                if wall is not None:
                    err = (wall - beacon_phase(k, self.slot) + self.cycle / 2) % self.cycle - self.cycle / 2
                    rep.phase_error_ms = err * 1000
            if rep.ok:
                schedules[k] = BeaconSchedule(a_play, sched.b)
        ok = not problems and all(r.ok for r in reports.values()) and bool(schedules)
        return CalibrationReport(ok, schedules, reports, problems)


# ---------------------------------------------------------------------------------------------- tracking


class Tracker:
    """Turns every chirp heard into a distance, and three fresh distances into a position.

    A cycle is only judged once its whole arrival window has been seen, so the earliest strong peak in the window
    wins (echoes come later), not whichever peak happened to arrive in the first poll.
    """

    def __init__(
        self,
        schedules: dict[int, BeaconSchedule],
        c: float,
        beacons: dict[int, Pos],
        window_s: float = 0.06,
        max_age_s: float = 0.6,
        d_min: float = 0.05,
        d_max: float = 15.0,
        ear_offset: Pos = EAR_OFFSET_M,
        z_prior: tuple[float, float] | None = HEIGHT_PRIOR,
        side_ref: tuple[float, float] = (0.0, 0.0),
    ) -> None:
        self.schedules, self.c, self.beacons = dict(schedules), c, dict(beacons)
        self.side_ref = side_ref  # with two beacons: which side of the line between them the user stands on
        self.window, self.max_age, self.d_min, self.d_max = window_s, max_age_s, d_min, d_max
        self.ear_offset, self.z_prior = ear_offset, z_prior
        self.latest: dict[int, Range] = {}
        self.last_cycle: dict[int, int] = {}
        self.pending: dict[tuple[int, int], list[Detection]] = {}
        self.last_fix: Fix | None = None
        self.last_fix_t: float | None = None
        self.last_full_t: float | None = None  # last time all of three or more beacons were heard
        self._rejects = 0
        self._recent: deque[tuple[float, float]] = deque(maxlen=SMOOTH_FIXES)
        self._suspect: dict[int, Range] = {}  # a distance that jumped; believed only if the next one agrees

    def _jumped(self, k: int, r: Range) -> bool:
        """True for a distance that changed faster than a person can walk, unless the next one agrees with it."""
        prev = self.latest.get(k)
        if prev is None or r.t - prev.t > JUMP_FORGET_S:
            self._suspect.pop(k, None)
            return False
        if abs(r.distance_m - prev.distance_m) <= JUMP_SLACK_M + MAX_WALK_MPS * (r.t - prev.t):
            self._suspect.pop(k, None)
            return False
        sus = self._suspect.get(k)
        if sus is not None and abs(r.distance_m - sus.distance_m) <= JUMP_SLACK_M + MAX_WALK_MPS * (r.t - sus.t):
            self._suspect.pop(k, None)
            return False  # two in a row agree: the phone really went there
        self._suspect[k] = r
        return True

    def add(self, dets: list[Detection], seen_up_to: float) -> list[Range]:
        """Feed newly heard chirps; `seen_up_to` is how far the recording has been searched (seconds)."""
        for d in dets:
            best = None
            for k, s in self.schedules.items():
                if beacon_shape(k) != d.shape:
                    continue
                n = s.cycle_of(d.t)
                travel = d.t - s.play_time(n)
                if -0.01 <= travel <= self.window and (best is None or travel < best[2]):
                    best = (k, n, travel)
            if best is not None:
                self.pending.setdefault((best[0], best[1]), []).append(d)
        out: list[Range] = []
        for (k, n), group in sorted(self.pending.items(), key=lambda kv: kv[1][0].t):
            if self.schedules[k].play_time(n) + self.window > seen_up_to:
                continue  # the window is still open: a stronger, earlier peak may still show up
            del self.pending[(k, n)]
            d = _earliest_strong(group)
            dist = self.c * (d.t - self.schedules[k].play_time(n))
            if not self.d_min <= dist <= self.d_max or n <= self.last_cycle.get(k, -(10**9)):
                continue
            r = Range(k, dist, d.t, n, d.snr)
            if self._jumped(k, r):
                continue
            self.latest[k], self.last_cycle[k] = r, n
            out.append(r)
        return out

    def fresh(self, now_t: float) -> dict[int, Range]:
        return {k: r for k, r in self.latest.items() if now_t - r.t <= self.max_age}

    def fix(self, now_t: float) -> tuple[Fix, ListenerPose] | None:
        """A steady position from the fresh distances, or None.

        With three or more beacons configured it needs three fresh distances (two would flip between answers),
        except for a short while after a good fix: if one beacon drops out (a body in the way), the other two
        keep the position going, on the same side as the last fix, marked "degraded". With exactly two configured
        it uses both. A fix that implies moving faster than a person walks is dropped, and what is published is
        lightly smoothed.
        """
        fresh = self.fresh(now_t)
        anchors = {f"B{k}": p for k, p in self.beacons.items()}
        dists = {f"B{k}": r.distance_m for k, r in fresh.items()}
        if len(fresh) < min(len(self.beacons), 3):
            holding = self.last_full_t is not None and now_t - self.last_full_t < TWO_BEACON_HOLD_S
            if not (len(fresh) == 2 and holding):
                return None
        if len(fresh) == 2:
            prefer = self.last_fix.position[:2] if self.last_fix else self.side_ref
            fix = locate_two(anchors, dists, prefer, z=self.z_prior[0] if self.z_prior else 1.25)
        else:
            fix = locate(anchors, dists, start=self.last_fix.position if self.last_fix else None, z_prior=self.z_prior)
        if fix is None:
            return None
        if self.last_fix is not None and self.last_fix_t is not None and now_t - self.last_fix_t < FIX_FORGET_S:
            allowed = FIX_SLACK_M + MAX_FIX_MPS * max(now_t - self.last_fix_t, 0.0)
            if math.dist(fix.position, self.last_fix.position) > allowed:
                if self._rejects < MAX_REJECTS:
                    self._rejects += 1
                    return None
                self._recent.clear()  # we moved for real: do not average with where we were
        else:
            self._recent.clear()
        self._rejects = 0
        self.last_fix, self.last_fix_t = fix, now_t
        if len(fresh) >= min(len(self.beacons), 3):
            self.last_full_t = now_t
        self._recent.append(fix.position[:2])
        x = float(np.median([p[0] for p in self._recent]))
        y = float(np.median([p[1] for p in self._recent]))
        shown = replace(fix, position=(x, y, fix.position[2]))
        pos = [round(shown.position[i] + self.ear_offset[i], 3) for i in range(3)]
        quality = "ok" if fix.used >= 3 and fix.rms_m <= 0.10 else "degraded"  # two beacons cannot check themselves
        return shown, ListenerPose(position=pos, quality=quality, beacons_heard=fix.used, source="beacons")


def known_distances(beacons: dict[int, Pos], distance: float | None = None, at: Pos | None = None) -> dict[int, float]:
    """How far the calibration spot is from each beacon: one number for a single beacon, or a point in the room."""
    if at is not None:
        return {k: math.dist(at, p) for k, p in beacons.items()}
    if distance is None:
        raise ValueError("give either a distance (one beacon) or the calibration point")
    if len(beacons) != 1:
        raise ValueError(
            f"--calibrate-distance only works with one beacon; {len(beacons)} are configured (use --only or --calibrate-at)")
    return {k: distance for k in beacons}

