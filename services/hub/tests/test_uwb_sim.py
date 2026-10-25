"""`uwb_sim` adapter (docs/project/UWB-PRD.md 8.6) feeding a Tracker on a virtual clock: tracked -> frozen, pose rate."""
from __future__ import annotations

import math

import pytest
from earmark_contracts import ListenerCommand, MotionState, UwbRange

from conftest import T0
from earmark_hub.clock import VirtualClock
from earmark_hub.config import UwbCfg, UwbSimCfg
from earmark_hub.uwb.sim import UwbSimAdapter, WalkPath
from earmark_hub.uwb.tracker import Tracker


class Done(Exception):
    pass


class Ctx:
    """HubContext stand-in: routes adapter messages to a Tracker as the hub does, ticking it at solve_hz."""

    def __init__(self, space, clock, uwb: UwbCfg, until_s: float) -> None:
        self.space, self.clock = space, clock
        self.tracker = Tracker(uwb, space, clock.now())
        self.period = 1.0 / uwb.solve_hz
        self.next_tick = clock.now() + self.period
        self.end = clock.now() + until_s
        self.poses, self.msgs, self.status = [], [], []

    def objects(self):
        return []

    def adapter_status(self, adapter, ok, detail):
        self.status.append((adapter, ok, detail))

    async def publish(self, msg, origin):
        now = self.clock.now()
        while self.next_tick <= now + 1e-9:
            self.poses += self.tracker.tick(self.next_tick)
            self.next_tick += self.period
        if now >= self.end:
            raise Done
        self.msgs.append((origin, msg))
        if isinstance(msg, UwbRange):
            self.tracker.on_range(msg, now, "sim")
        elif isinstance(msg, MotionState):
            self.tracker.on_motion(msg.state, now)
        elif isinstance(msg, ListenerCommand):
            self.poses += self.tracker.on_command(msg.action, now)


async def run_sim(space, seconds: float, seed: int = 7, **sim_cfg) -> Ctx:
    clock = VirtualClock(T0)
    uwb = UwbCfg()
    adapter = UwbSimAdapter(clock, UwbSimCfg(seed=seed, **sim_cfg), uwb)
    ctx = Ctx(space, clock, uwb, seconds)
    adapter.attach(ctx)
    with pytest.raises(Done):
        async for _ in adapter.events():
            pass
    return ctx


def segments(poses):
    """Consecutive runs of the same mode: [(mode, first t, last t), ...]."""
    out = []
    for p in poses:
        if out and out[-1][0] == p.mode:
            out[-1][2] = p.t
        else:
            out.append([p.mode, p.t, p.t])
    return [tuple(s) for s in out]


@pytest.mark.parametrize("seed", [1, 7, 42])
async def test_scripted_walk_tracks_then_freezes_at_the_counter(space, seed):
    """Default path: 4 s still at the start mark, walk to the counter at 0.6 m/s, stand still; noise 0.07 m,
    dropouts and a body block at 8 s. Tracked from the first tick, frozen within a second of stopping, close
    to the counter; walking back unfreezes."""
    ctx = await run_sim(space, 15.0, seed=seed)
    segs = segments(ctx.poses)
    assert [s[0] for s in segs] == ["tracked", "frozen", "tracked"], segs
    assert segs[0][1] - T0 <= 0.2
    stop_t = 4.0 + WalkPath(UwbSimCfg().path, 0.6, 4.0, True).length / 0.6  # ~9.05 s
    assert 0.6 <= segs[1][1] - T0 - stop_t <= 1.2
    frozen = next(p for p in ctx.poses if p.mode == "frozen")
    assert math.dist(frozen.position[:2], (0.0, 0.0)) < 0.2
    assert 13.05 < segs[2][1] - T0 < 14.5  # walking back after the 4 s dwell
    assert all(p.source == "sim" for p in ctx.poses)
    assert ctx.status == [("uwb_sim", True, "walking start -> counter")]


async def test_pose_rate_is_at_least_5_hz(space):
    ctx = await run_sim(space, 12.0)
    ts = [p.t for p in ctx.poses]
    assert len(ts) / (ts[-1] - ts[0]) >= 5.0
    assert max(b - a for a, b in zip(ts, ts[1:], strict=False)) <= 0.2 + 1e-6  # no gaps, even with dropouts


async def test_sim_publishes_ranges_and_motion_like_the_wearer(space):
    ctx = await run_sim(space, 6.0, dropout_prob=0.0)
    ranges = [m for _, m in ctx.msgs if isinstance(m, UwbRange)]
    motion = [m for _, m in ctx.msgs if isinstance(m, MotionState)]
    assert {r.anchor for r in ranges} == {"uwb_1", "uwb_2", "uwb_3"}
    assert len(ranges) == pytest.approx(3 * 15 * 6.0, abs=6)  # rate_hz per anchor
    assert {o for o, _ in ctx.msgs} == {"uwb_sim"}
    assert [m.state for m in motion][:4] == ["still"] * 4 and motion[-1].state == "moving"  # 1 s heartbeat


async def test_same_seed_same_ranges(space):
    a = await run_sim(space, 3.0, seed=5)
    b = await run_sim(space, 3.0, seed=5)
    c = await run_sim(space, 3.0, seed=6)
    da = [m.distance_m for _, m in a.msgs if isinstance(m, UwbRange)]
    assert da == [m.distance_m for _, m in b.msgs if isinstance(m, UwbRange)]
    assert da != [m.distance_m for _, m in c.msgs if isinstance(m, UwbRange)]


def test_walk_path_positions():
    path = WalkPath([[0.0, -3.0], [0.0, 0.0]], speed=1.0, dwell=2.0, loop=True)
    assert path.at(1.0) == ((0.0, -3.0), False, (0.0, 1.0))
    assert path.at(3.5)[0] == pytest.approx((0.0, -1.5)) and path.at(3.5)[1] is True
    assert path.at(6.0) == ((0.0, 0.0), False, (0.0, 1.0))
    p, moving, facing = path.at(8.5)  # walking back
    assert p == pytest.approx((0.0, -1.5)) and moving and facing == pytest.approx((0.0, -1.0))
    assert path.at(10.0 + 1.0)[0] == (0.0, -3.0)  # loop period 2 * (dwell + walk) = 10 s
    once = WalkPath([[0.0, -3.0], [0.0, 0.0]], speed=1.0, dwell=2.0, loop=False)
    assert once.at(100.0) == ((0.0, 0.0), False, (0.0, 1.0))


async def test_interactive_keys(space):
    clock = VirtualClock(T0)
    out = []
    adapter = UwbSimAdapter(clock, UwbSimCfg(), UwbCfg(), interactive=True, out=out.append)
    ctx = Ctx(space, clock, UwbCfg(), 100.0)
    adapter.attach(ctx)
    start = adapter.head
    assert await adapter.key("w") and adapter.head == (start[0], round(start[1] + 0.25, 3))
    head, moving, facing = adapter.wearer(clock.now())
    assert moving and facing == (0.0, 1.0)
    assert await adapter.key("x") and adapter.wearer(clock.now())[1] is False
    assert await adapter.key("f")
    assert [type(m) for _, m in ctx.msgs] == [ListenerCommand]
    assert await adapter.key("q") is False
    await adapter.on_reset()
    assert adapter.head == start
