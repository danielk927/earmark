"""Simulator: time rewriting, loop, step, and the interactive Wizard-of-Oz mode."""
from __future__ import annotations

import asyncio
import time

from earmark_contracts import DetectionEvent, Reset, Transcript

from conftest import ROOT, SALT, SUGAR, T0
from earmark_hub.adapters.simulator import Simulator, load_scenario
from earmark_hub.clock import ScaledClock, VirtualClock
from earmark_hub.state import StateEngine


def scenario(name):
    return load_scenario(ROOT / "scenarios" / f"{name}.jsonl")


async def collect(sim):
    got = []

    async def emit(msg):
        got.append(msg)

    await sim.run(emit)
    return got


async def test_rewrites_t_to_clock_time_preserving_gaps(space, objects):
    lines = scenario("wrong_jar")
    clock = VirtualClock(T0)
    got = await collect(Simulator(clock, objects=objects, spots=space.spot_numbers, scenario=lines))
    assert len(got) == len(lines)
    assert [round(m.t - T0, 6) for m in got] == [m.t for m in lines]
    assert clock.now() == T0 + lines[-1].t


async def test_loop_continues_time(space, objects):
    lines = scenario("roaming_keys")
    clock = VirtualClock(T0)
    got = []

    async def emit(msg):
        got.append(msg)
        if len(got) == 2 * len(lines):
            raise asyncio.CancelledError

    sim = Simulator(clock, objects=objects, spots=space.spot_numbers, scenario=lines, loop=True)
    try:
        await sim.run(emit)
    except asyncio.CancelledError:
        pass
    second = got[len(lines)]
    assert second.t == T0 + lines[-1].t + 0.5  # next loop starts one poll after the last line
    assert all(b.t >= a.t for a, b in zip(got, got[1:]))


async def test_speed_scales_wall_time_not_timestamps(space, objects):
    lines = [m for m in scenario("normal_pickup") if m.t <= 2.0]
    clock = ScaledClock(20.0)
    start = time.monotonic()
    got = await collect(Simulator(clock, objects=objects, spots=space.spot_numbers, scenario=lines))
    elapsed = time.monotonic() - start
    assert elapsed < 1.0  # 2 s of scenario at 20x
    gaps = [round(b.t - a.t, 3) for a, b in zip(got, got[1:]) if b.t != a.t]
    assert set(gaps) == {0.5}


async def test_step_pauses_only_before_changes(space, objects):
    lines = scenario("normal_pickup")
    prompts = []

    async def gate(prompt):
        prompts.append(prompt)

    clock = VirtualClock(T0)
    got = await collect(Simulator(clock, objects=objects, spots=space.spot_numbers, scenario=lines, step=True,
                                  gate=gate))
    assert len(got) == len(lines)
    # Initial reads, sugar lifted at 5.0, sugar back at 12.0; redundant polls play through.
    assert len(prompts) == 3
    assert prompts[1].startswith("next t=5s") and "spot 3: sugar -> EMPTY" in prompts[1]
    assert "spot 3: EMPTY -> sugar" in prompts[2]


async def test_step_pauses_before_transcripts_and_fob_class_changes(space, objects):
    prompts = []

    async def gate(prompt):
        prompts.append(prompt)

    sim = Simulator(VirtualClock(T0), objects=objects, spots=space.spot_numbers, scenario=scenario("roaming_keys"),
                    step=True, gate=gate)
    await collect(sim)
    assert len(prompts) == 5  # lost (t=0), far (t=2), mid (t=7), transcript (t=8), near
    assert "seen far" in prompts[1]
    assert "seen mid" in prompts[2]
    assert "transcript: Where are my keys?" in prompts[3]


async def test_step_rebases_time_after_a_pause(space, objects):
    clock = VirtualClock(T0)

    async def gate(prompt):
        clock.advance(100)  # the operator waits 100 s before pressing Enter

    lines = scenario("normal_pickup")
    got = await collect(Simulator(clock, objects=objects, spots=space.spot_numbers, scenario=lines, step=True,
                                  gate=gate))
    assert all(b.t >= a.t for a, b in zip(got, got[1:]))
    eng = StateEngine(space, objects)
    out = []
    for m in got:
        out.extend(eng.tick(m.t))
        out.extend(eng.handle(m))
    assert [(o.object_id, o.from_spot) for o in out if getattr(o, "type", "") == "pickup"] == [("sugar", 3)]


class Commands:
    """Feed interactive commands one at a time, letting the poll loop run in between."""

    def __init__(self, clock, cmds):
        self.clock, self.cmds = clock, list(cmds)

    def __aiter__(self):
        return self

    async def __anext__(self):
        if not self.cmds:
            raise StopAsyncIteration
        cmd = self.cmds.pop(0)
        if cmd.startswith("wait "):
            for _ in range(int(float(cmd[5:]) / 0.5)):
                await asyncio.sleep(0)  # let the poll loop emit
                await asyncio.sleep(0)
            return ""
        return cmd


async def run_interactive(space, objects, cmds):
    clock = VirtualClock(T0)
    eng = StateEngine(space, objects)
    out, msgs, text = [], [], []

    async def emit(msg):
        msgs.append(msg)
        out.extend(eng.tick(clock.now()))
        if isinstance(msg, DetectionEvent):
            out.extend(eng.handle(msg))

    sim = Simulator(clock, objects=objects, spots=space.spot_numbers, interactive=True,
                    commands=Commands(clock, cmds), out=text.append)
    await sim.run(emit)
    return sim, eng, out, msgs, "".join(text)


async def test_interactive_lift_and_put_back(space, objects):
    sim, eng, out, msgs, text = await run_interactive(space, objects, ["wait 2", "3", "wait 3", "3", "wait 2"])
    pickups = [(o.object_id, o.from_spot) for o in out if getattr(o, "type", "") == "pickup"]
    assert pickups == [("sugar", 3)]
    assert eng.state("sugar").status == "on_spot" and eng.state("sugar").location.spot == 3
    assert "lifted sugar from spot 3" in text and "put sugar on spot 3" in text


async def test_interactive_move_held_object(space, objects):
    sim, eng, out, msgs, text = await run_interactive(space, objects, ["wait 2", "3", "wait 3", "m1", "wait 2"])
    assert eng.state("sugar").location.spot == 1
    assert sim.on_spot[1] == "sugar" and sim.on_spot[3] is None


async def test_interactive_fob_transcript_reset(space, objects):
    sim, eng, out, msgs, text = await run_interactive(
        space, objects, ["k", "wait 1", "k", "k", "K", "t where's the sugar", "r", "q"])
    classes = [m.where.distance_class for m in msgs if isinstance(m, DetectionEvent) and m.tag == "fob_keys"]
    assert classes[0] == "far" and "near" in classes and classes[-1] == "mid"
    assert [m.text for m in msgs if isinstance(m, Transcript)] == ["where's the sugar"]
    assert any(isinstance(m, Reset) for m in msgs)
    assert sim.fob == "lost" and not sim.held


async def test_interactive_polls_reflect_physical_state(space, objects):
    sim, eng, out, msgs, text = await run_interactive(space, objects, ["wait 1"])
    reads = {m.where.spot: m.tag for m in msgs if isinstance(m, DetectionEvent) and m.where}
    assert reads == {1: "EMPTY", 2: SALT, 3: SUGAR, 4: "04A1B2C3D4E504"}


async def test_interactive_rejects_bad_commands(space, objects):
    sim, eng, out, msgs, text = await run_interactive(space, objects, ["1", "m2", "x", "7"])
    assert "spot 1 is empty and nothing is held" in text
    assert "nothing is held" in text and "unknown command 'x'" in text and "there is no spot 7" in text
