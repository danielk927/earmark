"""`uwb_sim` adapter: a simulated wearer iPhone (docs/UWB-PRD.md 8.6).

Publishes `uwb_range` to every anchor in config/space.json at `rate_hz`, plus `motion_state` (on change
and as a 1 s heartbeat), exactly as the wearer app would. The ranges are 3D distances from the phone
(held `head_offset_m` in front of the head at `phone_z`) with Gaussian noise, random dropouts and
periodic body-block bursts (+`jump_m` on one anchor for `block_s`).

- Scripted (default): stand at the start of `path`, walk it at `speed_mps` to the counter, stand still
  `dwell_s`, and (with `loop`) walk back and forth.
- Interactive (`earmark-hub --adapters simulator,uwb_sim --interactive`): the keyboard simulator forwards
  the keys it does not use to `key()`: WASD or the arrow keys move the wearer `step_m`, `x` stops (still),
  `f` says "I'm here" (`listener_command freeze`).

Enable with EARMARK_ADAPTERS=simulator,uwb_sim. Do not combine with `--scenario scenarios/uwb_walk.jsonl`,
which already contains ranges.
"""
from __future__ import annotations

import asyncio
import logging
import math
import random
from typing import AsyncIterator, Callable

from earmark_contracts import DetectionEvent, ListenerCommand, MotionState, UwbRange

from ..adapters.base import Adapter
from ..clock import Clock
from ..config import UwbCfg, UwbSimCfg
from .solver import Point
from .tracker import FORWARD, wearer_geometry

log = logging.getLogger("earmark.hub.uwb_sim")

MOVE_HOLD_S = 0.6  # interactive: "moving" this long after the last move key
MOVES = {"w": (0, 1), "up": (0, 1), "s": (0, -1), "down": (0, -1),
         "a": (-1, 0), "left": (-1, 0), "d": (1, 0), "right": (1, 0)}
HELP = """\
uwb_sim keys:
  w a s d / arrows   move the wearer (forward = toward the counter)
  x                  stop (motion still)
  f                  "I'm here" (freeze)"""


class WalkPath:
    """Head position along a polyline at constant speed, standing still `dwell_s` at each end."""

    def __init__(self, points: list[list[float]], speed: float, dwell: float, loop: bool) -> None:
        self.points = [(p[0], p[1]) for p in points]
        self.lengths = [math.dist(a, b) for a, b in zip(self.points, self.points[1:])]
        self.length = sum(self.lengths)
        self.speed, self.dwell, self.loop = speed, dwell, loop

    def _at(self, s: float) -> tuple[Point, Point]:
        """Point and unit direction at arc length s."""
        segs = list(zip(self.points, self.points[1:], self.lengths))
        for i, (a, b, seg) in enumerate(segs):
            if seg == 0:
                continue
            if s <= seg or i == len(segs) - 1:
                k = min(max(s / seg, 0.0), 1.0)
                return (a[0] + (b[0] - a[0]) * k, a[1] + (b[1] - a[1]) * k), ((b[0] - a[0]) / seg, (b[1] - a[1]) / seg)
            s -= seg
        return self.points[-1], FORWARD

    def at(self, t: float) -> tuple[Point, bool, Point]:
        """(head position, moving, facing) at `t` seconds since the walk started."""
        walk = self.length / self.speed
        if self.loop:
            t %= 2 * (self.dwell + walk)
        if t < self.dwell:
            return self.points[0], False, self._at(0.0)[1]
        t -= self.dwell
        if t < walk:
            p, d = self._at(t * self.speed)
            return p, True, d
        t -= walk
        if not self.loop or t < self.dwell:
            return self.points[-1], False, FORWARD
        p, d = self._at(self.length - (t - self.dwell) * self.speed)
        return p, True, (-d[0], -d[1])


class UwbSimAdapter(Adapter):
    name = "uwb_sim"

    def __init__(self, clock: Clock, cfg: UwbSimCfg, uwb: UwbCfg, *, interactive: bool = False,
                 out: Callable[[str], None] | None = None) -> None:
        self.clock, self.cfg, self.uwb = clock, cfg, uwb
        self.interactive = interactive
        self.out = out or (lambda s: print(s, end="", flush=True))
        self.path = WalkPath(cfg.path, cfg.speed_mps, cfg.dwell_s, cfg.loop)
        self.rng = random.Random(cfg.seed)
        self._t0: float | None = None
        self._home()

    def _home(self) -> None:
        self.head: Point = self.path.points[0]
        self.facing: Point = FORWARD
        self.moving_until = -math.inf

    async def events(self) -> AsyncIterator[DetectionEvent]:
        anchors = {a.anchor: a.position for a in self.ctx.space.space.anchors or []}
        if not anchors:
            self.ctx.adapter_status(self.name, False, "no anchors in config/space.json")
            await asyncio.Event().wait()
        self.ctx.adapter_status(self.name, True, "interactive" if self.interactive else "walking start -> counter")
        if self.interactive:
            self.out(HELP + "\n")
        period = 1.0 / self.cfg.rate_hz
        seq, motion, next_motion_t = 0, None, -math.inf
        block_anchor, block_until, next_block_t = None, -math.inf, None
        while True:
            now = self.clock.now()
            if self._t0 is None:
                self._t0 = now
            if next_block_t is None:
                next_block_t = now + self.cfg.block_every_s
            if now >= next_block_t:
                block_anchor, block_until = self.rng.choice(sorted(anchors)), now + self.cfg.block_s
                next_block_t = now + self.cfg.block_every_s
            phone_z, head_offset = wearer_geometry(self.uwb, self.ctx.space)
            head, moving, facing = self.wearer(now)
            phone = (head[0] + facing[0] * head_offset, head[1] + facing[1] * head_offset, phone_z)
            for aid, pos in anchors.items():
                if self.rng.random() < self.cfg.dropout_prob:
                    continue
                d = math.dist(phone, pos) + self.rng.gauss(0.0, self.cfg.noise_sigma_m)
                if aid == block_anchor and now < block_until:
                    d += self.cfg.jump_m
                await self.ctx.publish(UwbRange(anchor=aid, distance_m=round(max(d, 0.0), 3), seq=seq, t=now),
                                       self.name)
            seq += 1
            state = "moving" if moving else "still"
            if state != motion or now >= next_motion_t:
                await self.ctx.publish(MotionState(state=state, t=now), self.name)
                motion, next_motion_t = state, now + 1.0
            await self.clock.sleep(period)
        yield  # pragma: no cover  (never reached; makes this an async generator like the other adapters)

    def wearer(self, now: float) -> tuple[Point, bool, Point]:
        """(head position, moving, facing) now."""
        if self.interactive:
            return self.head, now < self.moving_until, self.facing
        return self.path.at(now - (self._t0 if self._t0 is not None else now))

    async def key(self, cmd: str) -> bool:
        """Interactive key from the keyboard simulator. Returns False for keys this adapter does not use."""
        now = self.clock.now()
        if cmd in MOVES:
            dx, dy = MOVES[cmd]
            self.head = (round(self.head[0] + dx * self.cfg.step_m, 3), round(self.head[1] + dy * self.cfg.step_m, 3))
            self.facing, self.moving_until = (float(dx), float(dy)), now + MOVE_HOLD_S
            self.out(f"wearer at x={self.head[0]:+.2f} y={self.head[1]:+.2f} m\n")
        elif cmd == "x":
            self.moving_until = -math.inf
            self.out("wearer standing still\n")
        elif cmd == "f":
            await self.ctx.publish(ListenerCommand(action="freeze", t=now), self.name)
            self.out("said: I'm here (freeze)\n")
        else:
            return False
        return True

    async def on_reset(self) -> None:
        self._t0 = None
        self._home()
