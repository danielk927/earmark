"""Simulator: replays scenarios/*.jsonl, or a Wizard-of-Oz keyboard mode for hardware-less demos.

Scenario lines are bus messages whose `t` is seconds from scenario start. Lines are
re-stamped `start + t` (gaps preserved, in the clock's time) and emitted when the
clock reaches that time; with --speed the clock itself runs faster (ScaledClock), so
debounce windows behave exactly as in real time.

The same `Simulator` drives the in-hub adapter and the standalone `earmark-sim` client;
only the `emit` callback differs.
"""
from __future__ import annotations

import asyncio
import itertools
import json
import logging
from pathlib import Path
from typing import AsyncIterator, Awaitable, Callable

from earmark_contracts import (
    DetectionEvent,
    RegistryObject,
    Reset,
    Transcript,
    WhereNear,
    WhereSpot,
    parse_bus,
)

from ..clock import Clock
from ..config import SimulatorCfg
from ..registry import normalize_tag
from .base import Adapter

log = logging.getLogger("earmark.hub.simulator")

Emit = Callable[[object], Awaitable[None]]
Gate = Callable[[str], Awaitable[None]]
FOB_STEPS = ("lost", "far", "mid", "near")

HELP = """\
interactive simulator keys:
  1-9   lift the object on that spot / put it back
  m<d>  move the held object to spot d
  k K   key fob nearer / farther
  t     type a transcript
  r     reset
  ?     help      q  quit the simulator"""


def load_scenario(path: Path) -> list:
    """Parse and validate every line; stable-sorted by t."""
    msgs = []
    for n, line in enumerate(path.read_text().splitlines(), 1):
        if not line.strip():
            continue
        try:
            msgs.append(parse_bus(line))
        except ValueError as e:
            raise ValueError(f"{path}:{n}: invalid bus message: {e}") from e
    return sorted(msgs, key=lambda m: m.t)


def _reading(msg) -> tuple[tuple, tuple] | None:
    """(key, value) of the raw reading a detection line reports, for --step."""
    if not isinstance(msg, DetectionEvent):
        return None
    tag = normalize_tag(msg.tag)
    if isinstance(msg.where, WhereSpot):
        present = msg.kind in ("seen", "placed") and tag != "EMPTY"
        return ("spot", msg.where.spot), (tag if present else "EMPTY",)
    if isinstance(msg.where, WhereNear):
        return ("tag", tag), (msg.kind, msg.where.distance_class)
    return ("tag", tag), (msg.kind, json.dumps(msg.where.model_dump() if msg.where else None))


class Simulator:
    def __init__(
        self,
        clock: Clock,
        *,
        objects: list[RegistryObject],
        spots: list[int],
        cfg: SimulatorCfg | None = None,
        scenario: list | None = None,
        loop: bool = False,
        step: bool = False,
        gate: Gate | None = None,
        interactive: bool = False,
        commands: AsyncIterator[str] | None = None,
        out: Callable[[str], None] | None = None,
        extra_keys: Callable[[str], Awaitable[bool]] | None = None,
    ) -> None:
        if interactive and scenario is not None:
            raise ValueError("--interactive and --scenario are mutually exclusive")
        self.clock = clock
        self.cfg = cfg or SimulatorCfg()
        self.scenario = scenario
        self.loop = loop
        self.step = step
        self.gate = gate
        self.interactive = interactive
        self.commands = commands
        self.out = out or (lambda s: print(s, end="", flush=True))
        self.extra_keys = extra_keys  # e.g. uwb_sim's wearer keys; tried first, True = handled
        self.spots = list(spots)
        self.set_objects(objects)
        self.reset_physical()

    # ------------------------------------------------------------ objects / physical state

    def set_objects(self, objects: list[RegistryObject]) -> None:
        self.objects = {o.object_id: o for o in objects}
        self._names = {normalize_tag(o.tag): o.name for o in objects if o.tag}
        self.fob_id = next((o.fob_id for o in objects if o.fob_id), None)

    def reset_physical(self) -> None:
        self.on_spot: dict[int, str | None] = {s: None for s in self.spots}
        for o in self.objects.values():
            if o.tag and o.home_spot in self.on_spot and self.on_spot[o.home_spot] is None:
                self.on_spot[o.home_spot] = o.object_id
        self.held: list[tuple[str, int]] = []
        self.fob = "lost"

    # ------------------------------------------------------------ run

    async def run(self, emit: Emit) -> None:
        if self.interactive:
            await self._interactive(emit)
        elif self.scenario:
            await self._replay(emit)

    async def _replay(self, emit: Emit) -> None:
        lines = self.scenario
        assert lines
        groups = [(t, list(g)) for t, g in itertools.groupby(lines, key=lambda m: m.t)]
        span = lines[-1].t - lines[0].t
        base = self.clock.now() - lines[0].t
        readings: dict[tuple, tuple] = {}
        while True:
            for t_rel, group in groups:
                if self.step and self._changes(group, readings):
                    await self._pause(t_rel, group, readings)
                    base = max(base, self.clock.now() - t_rel)
                else:
                    delay = base + t_rel - self.clock.now()
                    if delay > 0:
                        await self.clock.sleep(delay)
                for msg in group:
                    r = _reading(msg)
                    if r:
                        readings[r[0]] = r[1]
                    await emit(msg.model_copy(update={"t": base + t_rel}))
            if not self.loop:
                return
            base += span + self.cfg.poll_s

    def _changes(self, group: list, readings: dict) -> bool:
        for msg in group:
            r = _reading(msg)
            if r is None or readings.get(r[0]) != r[1]:
                return True
        return False

    async def _pause(self, t_rel: float, group: list, readings: dict) -> None:
        parts = []
        for msg in group:
            r = _reading(msg)
            if r is None:
                parts.append(f"{msg.type}: {getattr(msg, 'text', '') or msg.model_dump_json(exclude={'t'})}")
            elif readings.get(r[0]) != r[1]:
                key, val = r
                label = f"spot {key[1]}" if key[0] == "spot" else key[1]
                new = val[0] if key[0] == "spot" else " ".join(str(v) for v in val if v)
                old = readings.get(key)
                old_s = (old[0] if key[0] == "spot" else " ".join(str(v) for v in old if v)) if old else "?"
                parts.append(f"{label}: {self._name(old_s)} -> {self._name(new)}")
        prompt = f"next t={t_rel:g}s: " + "; ".join(parts)
        if self.gate is None:
            from ..console import make_step_gate

            self.gate = make_step_gate(self.out)
        await self.gate(prompt)

    def _name(self, tag: str) -> str:
        return self._names.get(tag, tag)

    # ------------------------------------------------------------ interactive

    async def _interactive(self, emit: Emit) -> None:
        if self.commands is None:
            from ..console import make_commands

            self.commands = make_commands(self.out)
        self.out(HELP + "\n")
        self._show()
        poll = asyncio.create_task(self._poll(emit))
        try:
            async for cmd in self.commands:
                if await self.command(cmd, emit):
                    break
        finally:
            poll.cancel()
            await asyncio.gather(poll, return_exceptions=True)

    async def _poll(self, emit: Emit) -> None:
        next_fob = self.clock.now()
        while True:
            t = self.clock.now()
            for spot in self.spots:
                await emit(self._spot_read(spot, t))
            if self.fob != "lost" and self.fob_id and t >= next_fob - 1e-9:
                await emit(self._fob_read(t))
                next_fob = t + self.cfg.fob_poll_s
            await self.clock.sleep(self.cfg.poll_s)

    def _spot_read(self, spot: int, t: float) -> DetectionEvent:
        oid = self.on_spot.get(spot)
        tag = self.objects[oid].tag if oid and oid in self.objects else None
        if tag:
            return DetectionEvent(source="simulator", tag=tag, kind="seen", where={"spot": spot},
                                  precision="exact", rssi=None, t=t)
        return DetectionEvent(source="simulator", tag="EMPTY", kind="removed", where={"spot": spot},
                              precision="exact", rssi=None, t=t)

    def _fob_read(self, t: float) -> DetectionEvent:
        if self.fob == "lost":
            return DetectionEvent(source="simulator", tag=self.fob_id, kind="lost", where=None,
                                  precision="none", rssi=None, t=t)
        return DetectionEvent(source="simulator", tag=self.fob_id, kind="seen",
                              where={"near": "hub", "distance_class": self.fob}, precision="proximity",
                              rssi=float(self.cfg.fob_rssi.get(self.fob, -80)), t=t)

    async def command(self, cmd: str, emit: Emit) -> bool:
        """Apply one keyboard command. Returns True to quit."""
        cmd = cmd.strip()
        if not cmd:
            return False
        if self.extra_keys is not None and await self.extra_keys(cmd):
            return False
        head, rest = cmd[0], cmd[1:].strip()
        if head.isdigit() and not rest:
            self._toggle(int(head))
        elif head == "m" and rest.isdigit():
            self._move(int(rest))
        elif head in ("k", "K") and not rest:
            await self._fob_step(1 if head == "k" else -1, emit)
        elif head == "t":
            if rest:
                await emit(Transcript(text=rest, is_final=True, source="typed", t=self.clock.now()))
                self.out(f"said: {rest}\n")
        elif head == "r":
            self.reset_physical()
            await emit(Reset(t=self.clock.now()))
            self.out("reset\n")
        elif head == "q":
            return True
        elif head in ("?", "h"):
            self.out(HELP + "\n")
            return False
        else:
            self.out(f"unknown command {cmd!r} (? for help)\n")
            return False
        self._show()
        return False

    def _toggle(self, spot: int) -> None:
        if spot not in self.on_spot:
            self.out(f"there is no spot {spot}\n")
        elif self.on_spot[spot]:
            self.held.append((self.on_spot[spot], spot))
            self.out(f"lifted {self._obj_name(self.on_spot[spot])} from spot {spot}\n")
            self.on_spot[spot] = None
        elif self.held:
            idx = next((i for i in range(len(self.held) - 1, -1, -1) if self.held[i][1] == spot), len(self.held) - 1)
            oid, _ = self.held.pop(idx)
            self.on_spot[spot] = oid
            self.out(f"put {self._obj_name(oid)} on spot {spot}\n")
        else:
            self.out(f"spot {spot} is empty and nothing is held\n")

    def _move(self, spot: int) -> None:
        if not self.held:
            self.out("nothing is held\n")
        elif spot not in self.on_spot:
            self.out(f"there is no spot {spot}\n")
        elif self.on_spot[spot]:
            self.out(f"spot {spot} is occupied\n")
        else:
            oid, _ = self.held.pop()
            self.on_spot[spot] = oid
            self.out(f"moved {self._obj_name(oid)} to spot {spot}\n")

    async def _fob_step(self, direction: int, emit: Emit) -> None:
        if not self.fob_id:
            self.out("no registered object has a fob\n")
            return
        i = max(0, min(len(FOB_STEPS) - 1, FOB_STEPS.index(self.fob) + direction))
        if FOB_STEPS[i] == self.fob:
            return
        self.fob = FOB_STEPS[i]
        await emit(self._fob_read(self.clock.now()))

    def _obj_name(self, oid: str) -> str:
        return self.objects[oid].name if oid in self.objects else oid

    def _show(self) -> None:
        spots = "  ".join(f"{s}[{self._obj_name(o) if o else ' '}]" for s, o in self.on_spot.items())
        held = ", ".join(self._obj_name(o) for o, _ in self.held) or "-"
        fob = f"  fob: {self.fob}" if self.fob_id else ""
        self.out(f"{spots}  held: {held}{fob}\n")


_END = object()


class SimulatorAdapter(Adapter):
    """In-hub simulator. Detections go to the state engine; other lines are published
    on the bus as if sent by component `simulator`."""

    name = "simulator"

    def __init__(self, clock: Clock, cfg: SimulatorCfg, *, scenario: Path | None = None, loop: bool = False,
                 step: bool = False, interactive: bool = False, gate: Gate | None = None,
                 commands: AsyncIterator[str] | None = None, out: Callable[[str], None] | None = None,
                 extra_keys: Callable[[str], Awaitable[bool]] | None = None) -> None:
        self.clock, self.cfg = clock, cfg
        self.lines = load_scenario(scenario) if scenario else None
        self.scenario_path = scenario
        self.opts = dict(loop=loop, step=step, interactive=interactive, gate=gate, commands=commands, out=out,
                         extra_keys=extra_keys)
        self.sim: Simulator | None = None

    async def events(self) -> AsyncIterator[DetectionEvent]:
        if not self.lines and not self.opts["interactive"]:
            self.ctx.adapter_status(self.name, True, "idle (no scenario)")
            await asyncio.Event().wait()
        if self.cfg.start_delay_s:
            await asyncio.sleep(self.cfg.start_delay_s)
        self.sim = Simulator(self.clock, objects=self.ctx.objects(), spots=self.ctx.space.spot_numbers,
                             cfg=self.cfg, scenario=self.lines, **self.opts)
        what = f"replaying {self.scenario_path.name}" if self.lines else "interactive"
        self.ctx.adapter_status(self.name, True, what)
        log.info("simulator started", extra={"mode": what})
        queue: asyncio.Queue = asyncio.Queue()

        async def runner() -> None:
            try:
                await self.sim.run(queue.put)
            finally:
                queue.put_nowait(_END)

        task = asyncio.create_task(runner())
        try:
            while (msg := await queue.get()) is not _END:
                if isinstance(msg, DetectionEvent):
                    yield msg
                else:
                    await self.ctx.publish(msg, "simulator")
            await task
        finally:
            task.cancel()
        self.ctx.adapter_status(self.name, True, "finished")

    async def on_reset(self) -> None:
        if self.sim and self.sim.interactive:
            self.sim.reset_physical()
