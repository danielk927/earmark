"""UWB position math (docs/UWB-PRD.md 5 and 8.2). Pure and deterministic; the tracker owns all state.

2D Earmark coordinates in meters: +x right, +y forward (toward the counter). Yaw in degrees
from calibrated forward, positive turning right.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

Point = tuple[float, float]


def horizontal(distance_m: float, dz: float) -> float:
    """Slant-range correction: h = sqrt(max(d^2 - dz^2, 0)), dz = anchor_z - phone_z."""
    return math.sqrt(max(distance_m * distance_m - dz * dz, 0.0))


def rms_residual(p: Point, anchors: list[Point], ranges: list[float]) -> float:
    return math.sqrt(sum((math.dist(p, a) - h) ** 2 for a, h in zip(anchors, ranges)) / len(anchors))


def gauss_newton(anchors: list[Point], ranges: list[float], init: Point, iters: int = 5) -> Point:
    """Least squares on sum (|p - a_i| - h_i)^2, at most `iters` Gauss-Newton steps from `init`."""
    x, y = init
    for _ in range(iters):
        a11 = a12 = a22 = b1 = b2 = 0.0
        for (ax, ay), h in zip(anchors, ranges):
            dx, dy = x - ax, y - ay
            d = math.hypot(dx, dy)
            if d < 1e-9:
                continue
            jx, jy, f = dx / d, dy / d, d - h
            a11 += jx * jx
            a12 += jx * jy
            a22 += jy * jy
            b1 += jx * f
            b2 += jy * f
        det = a11 * a22 - a12 * a12
        if abs(det) < 1e-12:
            break
        sx, sy = (a22 * b1 - a12 * b2) / det, (a11 * b2 - a12 * b1) / det
        x, y = x - sx, y - sy
        if math.hypot(sx, sy) < 1e-7:
            break
    return (x, y)


def circle_intersections(a: Point, ra: float, b: Point, rb: float) -> list[Point]:
    """Both intersections of two range circles. Circles that miss (noise) give the one closest-approach point
    on the line between the centers."""
    d = math.dist(a, b)
    if d < 1e-9:
        return []
    ux, uy = (b[0] - a[0]) / d, (b[1] - a[1]) / d
    along = (ra * ra - rb * rb + d * d) / (2 * d)
    off2 = ra * ra - along * along
    mx, my = a[0] + along * ux, a[1] + along * uy
    if off2 <= 0:
        return [(mx, my)]
    off = math.sqrt(off2)
    return [(mx - off * uy, my + off * ux), (mx + off * uy, my - off * ux)]


def solve_pair(a: Point, ra: float, b: Point, rb: float, prefer: Point, counter_y: float) -> Point | None:
    """Two-anchor fix: the intersection in the walking area (y < counter_y) closest to `prefer`;
    if neither is in the area, the one closest to `prefer`."""
    cands = circle_intersections(a, ra, b, rb)
    if not cands:
        return None
    pool = [c for c in cands if c[1] < counter_y] or cands
    return min(pool, key=lambda c: math.dist(c, prefer))


@dataclass
class Solution:
    position: Point
    residual_m: float
    used: list[str]
    blocked: list[str] = field(default_factory=list)


def solve(ranges: dict[str, float], anchors: dict[str, Point], prev: Point | None, *, counter_y: float,
          outlier_rms_m: float, iters: int = 5) -> Solution | None:
    """Position from horizontal ranges (anchor id -> h). `prev` is the filter's prediction (None on the first fix).

    3+ anchors: Gauss-Newton from `prev` (or the centroid), then leave-one-out. An anchor is dropped
    (reported in `blocked`) when the full solve's residual RMS exceeds `outlier_rms_m`, or, with a
    prediction, when the other anchors agree on a point closer to the prediction than the full solve and
    the dropped anchor misses that point by more than `outlier_rms_m`. The second rule is needed because
    least squares absorbs most of a single +0.4 m body-block error: with 3 anchors and 2 unknowns its RMS
    stays near 0.1-0.2 m, under the PRD's 0.25 m. Among the candidates, the pair solve with the lowest
    (residual + distance to the prediction) wins.
    2 anchors: circle intersection (see `solve_pair`). Fewer: None.
    """
    ids = sorted(k for k in ranges if k in anchors)
    if len(ids) < 2:
        return None
    ref = prev or (sum(anchors[i][0] for i in ids) / len(ids), sum(anchors[i][1] for i in ids) / len(ids))

    def fit(keep: list[str]) -> tuple[Point, float] | None:
        pts, hs = [anchors[i] for i in keep], [ranges[i] for i in keep]
        if len(keep) == 2:
            p = solve_pair(pts[0], hs[0], pts[1], hs[1], ref, counter_y)
        else:
            p = gauss_newton(pts, hs, ref, iters)
        return (p, rms_residual(p, pts, hs)) if p is not None else None

    full = fit(ids)
    if full is None:
        return None
    p, rms = full
    if len(ids) == 2:
        return Solution(p, rms, ids)
    if prev is None and rms <= outlier_rms_m:
        return Solution(p, rms, ids)

    cands = []  # (score, dropped anchor, point, residual)
    for drop in ids:
        keep = [i for i in ids if i != drop]
        sub = fit(keep)
        if sub is None:
            continue
        q, rq = sub
        miss = abs(ranges[drop] - math.dist(q, anchors[drop]))
        consistent = prev is None or math.dist(q, prev) < math.dist(p, prev)
        if miss > outlier_rms_m and consistent:
            cands.append((rq + math.dist(q, ref), drop, q, rq))
    if not cands and rms > outlier_rms_m:  # residual says something is off but no single anchor stands out
        for drop in ids:
            keep = [i for i in ids if i != drop]
            if (sub := fit(keep)) is not None:
                cands.append((sub[1] + math.dist(sub[0], ref), drop, sub[0], sub[1]))
    if not cands:
        return Solution(p, rms, ids)
    _, drop, q, rq = min(cands)
    return Solution(q, rq, [i for i in ids if i != drop], [drop])


def speed_ok(p: Point, last: Point, dt: float, max_speed_mps: float) -> bool:
    """Speed gate: False if moving from `last` to `p` in `dt` seconds implies more than `max_speed_mps`."""
    return math.dist(p, last) <= max_speed_mps * max(dt, 1e-6)


@dataclass
class AlphaBeta:
    """Alpha-beta filter on position + velocity."""

    pos: Point
    t: float
    vel: Point = (0.0, 0.0)

    def predict(self, t: float) -> Point:
        dt = max(0.0, t - self.t)
        return (self.pos[0] + self.vel[0] * dt, self.pos[1] + self.vel[1] * dt)

    def update(self, z: Point, t: float, alpha: float, beta: float) -> Point:
        dt = t - self.t
        if dt <= 0 or dt > 1.0:  # ponytail: after a >1 s gap the velocity is meaningless; restart from z
            self.pos, self.vel, self.t = z, (0.0, 0.0), t
            return self.pos
        px, py = self.predict(t)
        rx, ry = z[0] - px, z[1] - py
        self.pos = (px + alpha * rx, py + alpha * ry)
        self.vel = (self.vel[0] + beta / dt * rx, self.vel[1] + beta / dt * ry)
        self.t = t
        return self.pos


def facing_from_yaw(yaw_deg: float) -> Point:
    r = math.radians(yaw_deg)
    return (math.sin(r), math.cos(r))


def head_from_phone(phone: Point, facing: Point, head_offset_m: float) -> Point:
    """The head sits `head_offset_m` behind the handheld phone along the (unit) facing direction."""
    return (phone[0] - facing[0] * head_offset_m, phone[1] - facing[1] * head_offset_m)
