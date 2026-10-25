"""Setting up the room with no tape measure on the beacons: stand on a few marks, and the Mac works out the rest.

The user's phone stands still on three or more marks whose floor positions are known (the mat, plus taped marks a
short step away). At every mark it hears each beacon's chirps on its own timeline. For one beacon, every chirp heard
at mark j obeys

    t = a + b*n + |p_j - q| / c

with n the cycle number, (a, b) the beacon's schedule on the phone's timeline (unknown), p_j the mark (known) and q
the beacon (unknown). That is four unknowns per beacon (a, b and q's floor position; its height is a fixed number),
and every mark adds one distance, so three marks pin it down and a fourth checks it. Counting cycles across the
whole walk also measures the period b over a minute or more, far better than ten seconds on one spot.

The result is the same thing a tape measure plus a calibration gives: each beacon's position and its schedule.
"""
from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass, field

import numpy as np
from scipy.optimize import least_squares

from .listen import CYCLE_S, SLOT_S, BeaconSchedule, Calibrator, Detection, Pos, fit_schedule

PHONE_HEIGHT_M = 1.25  # the user's phone, held at chest height on every mark
BEACON_HEIGHT_M = 0.75  # the beacon phones, on tables or chairs
# The mat, then a step forward, back right and back left: spread out so no beacon sits on a line through them.
DEFAULT_MARKS: list[tuple[float, float]] = [(0.0, 0.0), (0.0, 0.8), (0.7, -0.5), (-0.7, -0.5)]
DEFAULT_MARK_LABELS = ["the mat", "a step forward", "back right", "back left"]
MIN_MARKS = 3  # marks a beacon must be heard at
MIN_PER_MARK = 8  # chirps from one beacon at one mark, for that mark to count
MAX_SURVEY_RESIDUAL_S = 0.0004  # how ragged the whole fit may be (0.4 ms is about 14 cm)
AMBIGUOUS_RATIO = 3.0  # a second, different answer must fit at least this much worse
DISTINCT_M = 0.3  # answers closer than this are the same answer


@dataclass
class BeaconPlacement:
    beacon: int
    position: Pos | None = None
    schedule: BeaconSchedule | None = None
    marks_heard: int = 0
    kept: int = 0
    residual_ms: float | None = None
    period_s: float | None = None
    note: str | None = None
    problems: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.problems and self.position is not None


@dataclass
class SurveyReport:
    ok: bool
    positions: dict[int, Pos]
    schedules: dict[int, BeaconSchedule]
    beacons: dict[int, BeaconPlacement]
    problems: list[str]

    def lines(self) -> list[str]:
        out = [f"room setup {'ok' if self.ok else 'FAILED'}"]
        for k, r in sorted(self.beacons.items()):
            if r.position is not None:
                x, y, z = r.position
                ppm = (r.period_s / CYCLE_S - 1) * 1e6 if r.period_s else 0.0
                out.append(f"  B{k}: at x {x:5.2f}  y {y:5.2f}  z {z:4.2f} m   heard at {r.marks_heard} marks, "
                           f"{r.kept} chirps, residual {r.residual_ms:.3f} ms, clock {ppm:+.1f} ppm")
            else:
                out.append(f"  B{k}: heard at {r.marks_heard} marks")
            if r.note:
                out.append(f"     note: {r.note}")
            out.extend(f"     problem: {p}" for p in r.problems)
        out.extend(f"  problem: {p}" for p in self.problems)
        return out


def _solve_one(
    t: np.ndarray, n: np.ndarray, marks: np.ndarray, c: float, beacon_z: float, starts: list[tuple[float, float]],
) -> list[tuple[float, np.ndarray]]:
    """Fit (a, b, qx, qy) from every start; returns (cost, params) per start, best first. a and b are offsets."""
    b0, a0 = np.polyfit(n, t, 1)

    def resid(p: np.ndarray) -> np.ndarray:
        a, b = a0 + p[0] / 1000.0, b0 + p[1] * 1e-6
        d = np.sqrt((marks[:, 0] - p[2]) ** 2 + (marks[:, 1] - p[3]) ** 2 + (marks[:, 2] - beacon_z) ** 2)
        return (t - (a + b * n + d / c)) * 1000.0  # milliseconds

    out = []
    for sx, sy in starts:
        d0 = math.dist((sx, sy), (0.0, 0.0))
        p0 = np.array([-1000.0 * d0 / c, 0.0, sx, sy])
        sol = least_squares(resid, p0, loss="soft_l1", f_scale=0.3, x_scale=[1.0, 1.0, 0.5, 0.5])
        out.append((float(np.sum(resid(sol.x) ** 2)), sol.x))
    out.sort(key=lambda r: r[0])
    return [(cost, np.array([a0 + x[0] / 1000.0, b0 + x[1] * 1e-6, x[2], x[3]])) for cost, x in out]


def place_beacon(
    per_mark: list[list[Detection]], marks: list[Pos], c: float, beacon_z: float = BEACON_HEIGHT_M,
    hint: Pos | None = None, cycle_s: float = CYCLE_S,
) -> BeaconPlacement:
    """Where one beacon is and when it chirps, from the chirps it made while the phone stood on each mark."""
    rep = BeaconPlacement(0)
    rows: list[tuple[float, int]] = []  # (heard time, mark)
    fits = []
    for j, dets in enumerate(per_mark):
        got = fit_schedule(dets, cycle_s)
        if got is None or len(got[1]) < MIN_PER_MARK:
            continue
        fits.append((j, got))
        rows.extend((d.t, j) for d in got[1])
    rep.marks_heard = len(fits)
    if len(fits) < MIN_MARKS:
        rep.problems.append(f"heard clearly at {len(fits)} marks, need {MIN_MARKS} (too far, too quiet, or blocked?)")
        return rep
    _, (ref, ref_kept, _) = max(fits, key=lambda f: len(f[1][1]))
    t = np.array([r[0] for r in rows])
    n = np.round((t - ref.a) / ref.b)  # one cycle count for the whole walk: drift and distance are far below half a cycle
    m = np.array([marks[r[1]] for r in rows], dtype=float)

    starts = [(r * math.cos(th), r * math.sin(th)) for r in (0.8, 1.4, 2.0) for th in np.radians(np.arange(0, 360, 45))]
    if hint is not None:
        starts.insert(0, (hint[0], hint[1]))
    keep = np.ones(len(t), dtype=bool)
    for _ in range(2):  # fit, drop the chirps that disagree (echoes), fit again
        sols = _solve_one(t[keep], n[keep], m[keep], c, beacon_z, starts)
        a, b, qx, qy = sols[0][1]
        d = np.sqrt((m[:, 0] - qx) ** 2 + (m[:, 1] - qy) ** 2 + (m[:, 2] - beacon_z) ** 2)
        r = t - (a + b * n + d / c)
        med = np.median(r[keep])
        mad = np.median(np.abs(r[keep] - med))
        keep = np.abs(r - med) <= max(3 * 1.4826 * mad, 100e-6)

    best_cost, (a, b, qx, qy) = sols[0]
    rival = next((s for s in sols[1:] if math.dist(s[1][2:], (qx, qy)) > DISTINCT_M), None)
    if rival is not None and rival[0] < AMBIGUOUS_RATIO * max(best_cost, 1e-9):
        rx, ry = rival[1][2:]
        if hint is not None and math.dist((rx, ry), hint[:2]) < math.dist((qx, qy), hint[:2]):
            a, b, qx, qy = rival[1]
            rx, ry = sols[0][1][2:]
        rep.note = (f"another spot also fits (x {rx:.2f}, y {ry:.2f}); picked the one nearer where this beacon was "
                    "said to be" if hint is not None else None)
        if hint is None:
            rep.problems.append(f"two spots fit equally well ({qx:.2f}, {qy:.2f}) and ({rx:.2f}, {ry:.2f}); "
                                "use marks further apart")

    d = np.sqrt((m[:, 0] - qx) ** 2 + (m[:, 1] - qy) ** 2 + (m[:, 2] - beacon_z) ** 2)
    r = (t - (a + b * n + d / c))[keep]
    resid = float(np.std(r)) if len(r) > 2 else float("inf")
    rep.position = (round(float(qx), 3), round(float(qy), 3), beacon_z)
    rep.schedule = BeaconSchedule(float(a), float(b))
    rep.kept, rep.residual_ms, rep.period_s = int(keep.sum()), resid * 1000, float(b)
    if resid > MAX_SURVEY_RESIDUAL_S:
        rep.problems.append(f"chirps are {resid * 1000:.2f} ms ragged, limit {MAX_SURVEY_RESIDUAL_S * 1000:.1f} ms "
                            "(moving during a stop? a mark in the wrong place?)")
    return rep


class Surveyor:
    """Collects chirps while the phone stands on each mark in turn, then places every beacon."""

    def __init__(
        self,
        beacons: list[int],
        marks: list[tuple[float, float]] | None,
        c: float,
        stop_s: float = 10.0,
        cycle_s: float = CYCLE_S,
        slot_s: float = SLOT_S,
        wall_time: Callable[[float], float | None] | None = None,
        phone_z: float = PHONE_HEIGHT_M,
        beacon_z: float = BEACON_HEIGHT_M,
        hints: dict[int, Pos] | None = None,
    ) -> None:
        self.beacon_ids = sorted(beacons)
        self.marks: list[Pos] = [(x, y, phone_z) for x, y in (marks or DEFAULT_MARKS)]
        self.c, self.stop_s, self.cycle, self.beacon_z, self.hints = c, stop_s, cycle_s, beacon_z, dict(hints or {})
        self._tell = Calibrator({k: 0.0 for k in self.beacon_ids}, c, cycle_s=cycle_s, slot_s=slot_s, wall_time=wall_time)
        self.per_mark: list[list[Detection]] = [[] for _ in self.marks]
        self.current: int | None = None  # the mark being recorded
        self.finished: set[int] = set()
        self.started_at: float | None = None
        self.latest: float | None = None

    @property
    def next_mark(self) -> int | None:
        left = [j for j in range(len(self.marks)) if j not in self.finished]
        return left[0] if left else None

    def start_mark(self, j: int, t_rec: float) -> None:
        self.current, self.started_at, self.latest = j, t_rec, t_rec
        self.per_mark[j] = []

    def assign(self, det: Detection) -> int | None:
        return self._tell.assign(det)

    def add(self, det: Detection) -> None:
        if self.current is not None and self.started_at is not None and det.t >= self.started_at:
            self.per_mark[self.current].append(det)

    def seen_up_to(self, t_rec: float) -> None:
        self.latest = max(self.latest or t_rec, t_rec)
        if self.current is not None and self.remaining() <= 0.0:
            self.finished.add(self.current)
            self.current = None

    def remaining(self) -> float:
        if self.current is None or self.started_at is None or self.latest is None:
            return 0.0
        return max(0.0, self.stop_s - (self.latest - self.started_at))

    def done(self) -> bool:
        return self.current is None and self.next_mark is None

    def solve(self) -> SurveyReport:
        problems: list[str] = []
        for s in {"up", "down"}:
            same = [k for k in self.beacon_ids if (k % 2 == 1) == (s == "up")]
            if len(same) > 1 and self._tell.wall_time is None:
                problems.append(f"cannot tell {' from '.join(f'B{k}' for k in same)} apart without a wall clock")
        split: dict[int, list[list[Detection]]] = {k: [[] for _ in self.marks] for k in self.beacon_ids}
        for j, dets in enumerate(self.per_mark):
            for d in dets:
                k = self.assign(d)
                if k is not None:
                    split[k][j].append(d)
        placed: dict[int, BeaconPlacement] = {}
        for k in self.beacon_ids:
            rep = place_beacon(split[k], self.marks, self.c, self.beacon_z, self.hints.get(k), self.cycle)
            rep.beacon = k
            rep.problems = [f"B{k}: {p}" for p in rep.problems]
            placed[k] = rep
        good = {k: r for k, r in placed.items() if r.ok}
        if len(good) < 3:
            problems.append(f"{len(good)} beacons placed, need 3 for a position")
        ok = not problems and all(r.ok for r in placed.values())
        return SurveyReport(
            ok, {k: r.position for k, r in good.items()}, {k: r.schedule for k, r in good.items()}, placed, problems,
        )
