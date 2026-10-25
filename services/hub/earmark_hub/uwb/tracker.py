"""Listener tracking: ranges -> solve -> smooth -> head offset -> modes (docs/UWB-PRD.md 8.2-8.5).

Modes:
- fixed: listener at the origin (UWB disabled, nothing ranged yet, or lost for too long). Today's behavior.
- tracked: live estimate while walking.
- frozen: the landing spot at the counter. Entered when inside `freeze_enter_m` of `counter_ref`, still for
  `still_for_s`, with >= 2 fresh anchors; also on `listener_command freeze` ("I'm here"). Left when moving
  and displaced more than `unfreeze_move_m`, or outside `freeze_exit_m` (not for a voice freeze).
  An NFC pickup/placement pulls the frozen point to within `reach_max_m` of that spot.
- lost: < 2 fresh anchors for `lost_after_s` while tracked; holds the last position for `lost_hold_s`, then fixed.

Time is passed in (`now`, hub clock seconds); nothing here reads a clock, so tests are deterministic.
Range freshness uses the hub's receive time, not the phone's `t`, so phone clock skew cannot age ranges.
"""
from __future__ import annotations

import collections
import logging
import math

from earmark_contracts import AnchorHealth, IngestAnchor, ListenerPose, UwbRange

from ..config import UwbCfg
from ..space import SpaceIndex
from .solver import AlphaBeta, Point, facing_from_yaw, head_from_phone, horizontal, solve, speed_ok

log = logging.getLogger("earmark.hub.uwb")

FORWARD: Point = (0.0, 1.0)  # facing the counter
MIN_TRAVEL_MPS = 0.3  # ponytail: below this the direction of travel is noise; keep the last facing


def wearer_geometry(cfg: UwbCfg, space: SpaceIndex) -> tuple[float, float]:
    """(phone_z, head_offset_m): space.json `tracking` overrides the hub.json defaults."""
    tr = space.space.tracking
    phone_z = tr.phone_z if tr and tr.phone_z is not None else cfg.phone_z
    head = tr.head_offset_m if tr and tr.head_offset_m is not None else cfg.head_offset_m
    return phone_z, head


class Tracker:
    def __init__(self, cfg: UwbCfg, space: SpaceIndex, now: float) -> None:
        self.cfg = cfg
        self.counter_ref: Point = (cfg.counter_ref[0], cfg.counter_ref[1])
        self.load_space(space)
        self.reset(now)

    # ------------------------------------------------------------ setup

    def load_space(self, space: SpaceIndex) -> None:
        """Anchors, wearer geometry and the counter line from space.json (called again on reset)."""
        self.space = space
        self.anchors = {a.anchor: a for a in space.space.anchors or []}
        self.phone_z, self.head_offset = wearer_geometry(self.cfg, space)
        spot_ys = [s.position[1] for s in space.space.spots]
        self.counter_y = min(spot_ys) if spot_ys else math.inf  # walking area: y < the nearest spot

    def reset(self, now: float) -> list[ListenerPose]:
        """Forget everything (ranges, motion, filter) and go back to fixed at the origin."""
        self.ranges: dict[str, tuple[float, float]] = {}  # anchor -> (distance_m, hub receive time)
        self.source = "sim"
        self.motion: str | None = None
        self.still_since: float | None = None
        self.yaw: tuple[float, float] | None = None  # (degrees, receive time)
        self._clear_track()
        self.ever_ranged = False
        self.mode = "fixed"
        self.position: Point = self.counter_ref
        self.pose = self._pose(now)
        return [self.pose]

    def _clear_track(self) -> None:
        self.filter: AlphaBeta | None = None
        self.last_fix: tuple[Point, float] | None = None  # last solution the speed gate accepted, and when
        self.estimate: Point | None = None  # listener (head) estimate from the smoothed phone position
        self.facing: Point = FORWARD
        self.history: collections.deque[tuple[float, Point]] = collections.deque()  # (t, accepted phone solution)
        self.residual: float | None = None
        self.used: list[str] = []
        self.blocked: list[str] = []
        self.last_fresh_t = -math.inf
        self.lost_since = 0.0
        self.freeze_phone: Point | None = None  # phone estimate when frozen (for the unfreeze displacement)
        self.override = False

    # ------------------------------------------------------------ inputs

    def on_range(self, msg: UwbRange, now: float, source: str) -> None:
        self.ranges[msg.anchor] = (msg.distance_m, now)
        self.source = source
        self.ever_ranged = True

    def on_motion(self, state: str, now: float) -> None:
        if state != self.motion:
            self.still_since = now if state == "still" else None
        self.motion = state

    def on_head_pose(self, yaw_deg: float, now: float) -> None:
        self.yaw = (yaw_deg, now)

    def on_command(self, action: str, now: float) -> list[ListenerPose]:
        """listener_command. `freeze` ("I'm here") freezes at once, even outside the radius; `recenter` is the
        Mac app's business."""
        if action != "freeze":
            return []
        if self.mode == "frozen":
            return [self._emit(now)]
        if self.mode == "tracked" and self.estimate is not None:
            point = self.counter_ref if self.cfg.freeze_mode == "snap" else self.estimate
        elif self.ever_ranged:  # lost, or fixed after lost: the user says they are at the counter
            point = self.counter_ref
        else:
            log.info("freeze ignored: no UWB ranges yet; listener stays fixed at the origin")
            return []
        stale = self.mode != "tracked"
        self._freeze(point, now, override=True)
        if stale:  # measure the unfreeze displacement from the first solve after this, not a stale estimate
            self.freeze_phone = None
        return [self._emit(now)]

    def on_contact(self, spot: int, now: float, kind: str) -> list[ListenerPose]:
        """NFC pickup/placed at `spot`: while frozen, pull the frozen point to within reach_max_m of the spot.
        Never while tracked: the user may have walked off with the jar."""
        pos = self.space.spot_position(spot)
        if self.mode != "frozen" or pos is None:
            return []
        d = math.dist(self.position, pos[:2])
        if d <= self.cfg.reach_max_m + 1e-9:  # a point already moved to exactly reach_max_m stays put
            return []
        k = self.cfg.reach_max_m / d
        old = self.position
        self.position = (pos[0] + (old[0] - pos[0]) * k, pos[1] + (old[1] - pos[1]) * k)
        log.info("nfc re-anchor", extra={"kind": kind, "spot": spot, "correction_m": round(d - self.cfg.reach_max_m, 3),
                                         "from": [round(v, 3) for v in old],
                                         "to": [round(v, 3) for v in self.position]})
        return [self._emit(now)]

    # ------------------------------------------------------------ solver tick

    def tick(self, now: float) -> list[ListenerPose]:
        """One solver step (call at solve_hz). Returns the pose(s) to publish: one per tick while tracked,
        frozen or lost; nothing while fixed unless the mode changed."""
        fresh = {a: horizontal(d, self.anchors[a].position[2] - self.phone_z)
                 for a, (d, t) in self.ranges.items() if a in self.anchors and now - t <= self.cfg.freshness_s}
        solved = False
        if len(fresh) >= 2:
            self.last_fresh_t = now
            solved = self._solve(fresh, now)
        before = self.mode

        if self.mode in ("fixed", "lost") and solved:
            self.mode, self.override = "tracked", False
        elif self.mode == "tracked":
            if len(fresh) < 2:
                if now - self.last_fresh_t > self.cfg.lost_after_s:
                    self.mode, self.lost_since = "lost", now
            elif solved and self._should_freeze(now):
                self._freeze(self._landing_point(now), now, override=False)
        elif self.mode == "frozen" and solved and self._should_unfreeze():
            self.mode, self.override = "tracked", False
        if self.mode == "lost" and now - self.lost_since >= self.cfg.lost_hold_s:
            self.mode = "fixed"
            self._clear_track()

        if self.mode == "tracked" and self.estimate is not None:
            self.position = self.estimate
        elif self.mode == "fixed":
            self.position = self.counter_ref
        if self.mode != before:
            log.info("listener mode", extra={"from": before, "to": self.mode,
                                             "position": [round(v, 3) for v in self.position]})
        elif self.mode == "fixed":
            return []
        return [self._emit(now)]

    def _solve(self, fresh: dict[str, float], now: float) -> bool:
        anchors = {a: (self.anchors[a].position[0], self.anchors[a].position[1]) for a in fresh}
        prev = self.filter.predict(now) if self.filter else None
        sol = solve(fresh, anchors, prev, counter_y=self.counter_y, outlier_rms_m=self.cfg.outlier_rms_m)
        if sol is None:
            return False
        # Gate against the last accepted solution, not the smoothed position: the filter lags a fast walker by
        # more than max_speed * dt, which would reject every good fix and stall the track.
        if self.last_fix and not speed_ok(sol.position, self.last_fix[0], now - self.last_fix[1],
                                          self.cfg.max_speed_mps):
            log.debug("uwb solution rejected by the speed gate", extra={"position": sol.position})
            return False
        self.last_fix = (sol.position, now)
        alpha = self.cfg.alpha_still if self.motion == "still" else self.cfg.alpha
        if self.filter is None:
            self.filter = AlphaBeta(sol.position, now)
        else:
            self.filter.update(sol.position, now, alpha, self.cfg.beta)
        phone = self.filter.pos
        self.history.append((now, sol.position))
        while self.history and self.history[0][0] < now - self.cfg.average_window_s:
            self.history.popleft()
        self.residual, self.used, self.blocked = sol.residual_m, sol.used, sol.blocked
        self.facing = self._facing(now, phone)
        self.estimate = head_from_phone(phone, self.facing, self.head_offset)
        if self.mode == "frozen" and self.freeze_phone is None:
            self.freeze_phone = phone
        return True

    def _facing(self, now: float, phone: Point) -> Point:
        """AirPods yaw if recent; else direction of travel; else facing the counter inside the counter zone."""
        if self.yaw is not None and now - self.yaw[1] <= self.cfg.head_pose_max_age_s:
            return facing_from_yaw(self.yaw[0])
        vx, vy = self.filter.vel if self.filter else (0.0, 0.0)
        speed = math.hypot(vx, vy)
        if speed >= MIN_TRAVEL_MPS:
            return (vx / speed, vy / speed)
        if math.dist(phone, self.counter_ref) <= self.cfg.freeze_enter_m:
            return FORWARD
        return self.facing

    # ------------------------------------------------------------ freeze

    def _should_freeze(self, now: float) -> bool:
        return (self.motion == "still" and self.still_since is not None
                and now - self.still_since >= self.cfg.still_for_s
                and math.dist(self.estimate, self.counter_ref) <= self.cfg.freeze_enter_m)

    def _landing_point(self, now: float) -> Point:
        """Snap: counter_ref. Average: mean phone position over the still part of the last average_window_s,
        moved back by the head offset facing the counter. It averages the accepted solutions, not the
        alpha-beta output: right after a stop the filter is still carrying the walking velocity and
        overshoots (by ~0.25 m from 1.8 m/s), and that overshoot would be frozen in. Averaging ~7 raw fixes
        already cuts sigma = 0.07 m noise to ~0.03 m."""
        if self.cfg.freeze_mode == "snap":
            return self.counter_ref
        start = max(now - self.cfg.average_window_s, self.still_since if self.still_since is not None else now)
        pts = [p for t, p in self.history if t >= start - 1e-9] or [self.filter.pos]
        mean = (sum(p[0] for p in pts) / len(pts), sum(p[1] for p in pts) / len(pts))
        return head_from_phone(mean, FORWARD, self.head_offset)

    def _freeze(self, point: Point, now: float, *, override: bool) -> None:
        self.mode, self.position, self.override = "frozen", point, override
        self.freeze_phone = self.filter.pos if self.filter else None

    def _should_unfreeze(self) -> bool:
        # Displacement is measured on the phone estimate since the freeze, so NFC re-anchoring (which only
        # moves the published point) and head turns (which move the head offset) never unfreeze by themselves.
        moved = self.freeze_phone is not None and math.dist(self.filter.pos, self.freeze_phone) > self.cfg.unfreeze_move_m
        if self.motion == "moving" and moved:
            return True
        return not self.override and math.dist(self.estimate, self.counter_ref) > self.cfg.freeze_exit_m

    # ------------------------------------------------------------ output

    def health(self, now: float) -> list[AnchorHealth]:
        out = []
        for a in self.anchors:
            d, t = self.ranges.get(a, (None, None))
            out.append(AnchorHealth(anchor=a, online=t is not None and now - t <= self.cfg.freshness_s,
                                    distance_m=None if d is None else round(d, 3)))
        return out

    def ingest_anchors(self, now: float) -> list[IngestAnchor]:
        """Anchor rows for Convex /ingest."""
        return [IngestAnchor(anchor=h.anchor, label=self.anchors[h.anchor].label,
                             position=list(self.anchors[h.anchor].position), online=h.online,
                             last_distance_m=h.distance_m, last_seen_t=self.ranges.get(h.anchor, (None, None))[1])
                for h in self.health(now)]

    def _pose(self, now: float) -> ListenerPose:
        live = self.mode in ("tracked", "frozen")
        return ListenerPose(
            position=[round(self.position[0], 3), round(self.position[1], 3), 0.0],
            mode=self.mode,
            source="none" if self.mode == "fixed" else self.source,
            residual_m=round(self.residual, 3) if live and self.residual is not None else None,
            anchors_used=len(self.used) if live else 0,
            blocked=list(self.blocked) if live else [],
            anchors=self.health(now) if self.anchors else None,
            t=now,
        )

    def _emit(self, now: float) -> ListenerPose:
        self.pose = self._pose(now)
        return self.pose
