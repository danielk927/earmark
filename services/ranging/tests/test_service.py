"""The whole thing with no hardware: the service, six virtual phones with their own clocks, and a fake bus."""
import asyncio
import contextlib
import math
import time

import numpy as np
import pytest
from earmark_contracts import ListenerPose, parse_bus
from websockets.asyncio.server import serve

from earmark_ranging.chirp import ChirpSpec
from earmark_ranging.config import load_anchors
from earmark_ranging.service import BusPublisher, RangingService
from earmark_ranging.sim import VirtualPhone, World


@contextlib.asynccontextmanager
async def running(listener, seconds_ignored=None, spec=None, noise=0.002, bus_url=None, **phone_kw):
    spec = spec or ChirpSpec()
    anchors = load_anchors()
    svc = RangingService(anchors, spec, publisher=BusPublisher(bus_url))
    fixes = []
    svc.on_fix = lambda fix, pose: fixes.append((time.monotonic(), fix, pose))
    world = World({0: listener, **anchors})
    stop = asyncio.Event()
    async with serve(svc.handler, "127.0.0.1", 0, max_size=2**22) as server:
        port = server.sockets[0].getsockname()[1]
        tasks = [asyncio.create_task(svc.run())]
        slots = [0, *sorted(anchors)]
        url = f"ws://127.0.0.1:{port}"
        for s in slots:
            phone = VirtualPhone(s, world, spec, seed=3, noise_rms=noise, **phone_kw)
            tasks.append(asyncio.create_task(phone.run(url, stop)))
        try:
            yield svc, fixes, world
        finally:
            stop.set()
            for t in tasks:
                t.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)


def ear(p):
    return (p[0], p[1], p[2] + 0.35)  # the service reports the ear, which sits above the phone


async def test_standing_still_is_found_to_a_few_centimeters():
    me = (0.3, 0.5, 1.2)
    async with running(me) as (svc, fixes, _):
        await asyncio.sleep(6.0)
    assert len(fixes) >= 5, f"only {len(fixes)} fixes"
    errs = [math.dist(f.position, me) for _, f, _ in fixes[2:]]
    assert np.median(errs) < 0.05, errs
    assert all(p.quality in ("ok", "degraded") and p.beacons_heard >= 3 for _, _, p in fixes)
    assert fixes[-1][2].position == pytest.approx(ear(fixes[-1][1].position), abs=0.002)


async def test_every_phone_has_its_own_clock_and_it_does_not_matter():
    me = (-0.4, 0.2, 1.1)
    async with running(me, drift_ppm=45.0) as (svc, fixes, _):
        await asyncio.sleep(5.0)
    assert fixes and np.median([math.dist(f.position, me) for _, f, _ in fixes[1:]]) < 0.06


async def test_walking_across_the_room_is_followed():
    start, end, secs = (0.0, -0.8, 1.2), (0.0, 1.0, 1.2), 5.0
    t0 = time.monotonic() + 1.0

    def path(t):
        f = min(max((t - t0) / secs, 0.0), 1.0)
        return tuple(start[i] + f * (end[i] - start[i]) for i in range(3))

    async with running(path) as (svc, fixes, world):
        await asyncio.sleep(1.0 + secs + 1.0)
    assert len(fixes) >= 8
    errs = []
    for t, f, _ in fixes:
        errs.append(math.dist(f.position, path(t - 0.7)))  # a fix describes where the user was about 0.7 s ago
    assert np.median(errs) < 0.25, np.round(errs, 2)
    ys = [f.position[1] for _, f, _ in fixes]
    assert ys[-1] - ys[0] > 1.3  # it saw the user walk forward


async def test_a_lost_chunk_or_two_does_not_break_it():
    me = (0.3, 0.5, 1.2)
    async with running(me, dropout=0.04) as (svc, fixes, _):
        await asyncio.sleep(6.0)
    assert len(fixes) >= 3 and np.median([math.dist(f.position, me) for _, f, _ in fixes]) < 0.08


async def test_the_position_reaches_the_earmark_bus():
    got = []

    async def bus(ws):
        async for raw in ws:
            got.append(parse_bus(raw))

    async with serve(bus, "127.0.0.1", 0) as bus_server:
        url = f"ws://127.0.0.1:{bus_server.sockets[0].getsockname()[1]}"
        async with running((0.3, 0.5, 1.2), bus_url=url) as (svc, fixes, _):
            await asyncio.sleep(4.5)
    poses = [m for m in got if isinstance(m, ListenerPose)]
    assert got[0].type == "hello" and got[0].component == "locator"
    assert poses and poses[-1].source == "beacons" and poses[-1].quality in ("ok", "degraded")
    assert poses[-1].position == pytest.approx((0.3, 0.5, 1.55), abs=0.1)
