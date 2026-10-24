"""earmark-ranging serve | sim"""
from __future__ import annotations

import argparse
import asyncio
import logging
import os
import socket

from websockets.asyncio.server import serve

from .chirp import ChirpSpec
from .config import AUDIBLE_BAND, DEFAULT_BEACONS, load_anchors
from .service import BusPublisher, RangingService


def lan_ip() -> str:
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("10.255.255.255", 1))
        return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        s.close()


async def _serve(args) -> None:
    anchors = load_anchors(args.beacons)
    lo, hi = AUDIBLE_BAND if args.audible else (args.band[0], args.band[1])
    bus = None if args.no_bus else os.environ.get("EARMARK_BUS_URL", "ws://127.0.0.1:8765")
    svc = RangingService(anchors, ChirpSpec(lo, hi), publisher=BusPublisher(bus))

    def show(fix, pose) -> None:
        x, y, z = pose.position
        print(f"fix  x {x:6.2f}  y {y:6.2f}  z {z:5.2f}   {pose.quality:<8} {fix.used} phones   fit {fix.rms_m * 100:4.1f} cm")

    svc.on_fix = show
    async with serve(svc.handler, "0.0.0.0", args.port, max_size=2**22):
        print(f"ranging service ready. Phones connect to:  ws://{lan_ip()}:{args.port}")
        print(f"chirp band {lo:.0f} to {hi:.0f} Hz; fixed phones at {sorted(anchors)}; user phone is slot 0")
        runner = asyncio.create_task(svc.run())

        async def beat() -> None:
            while True:
                await asyncio.sleep(2)
                await svc.publisher.send(svc.status())
                print(f"phones connected: {sorted(svc.phones)}   fixes so far: {svc.fixes}")

        await asyncio.gather(runner, beat())


async def _sim(args) -> None:
    from .sim import VirtualPhone, World

    anchors = load_anchors(args.beacons)
    lo, hi = AUDIBLE_BAND if args.audible else (args.band[0], args.band[1])
    spec = ChirpSpec(lo, hi)
    me = (args.x, args.y, args.z)
    world = World({0: me, **anchors})
    stop = asyncio.Event()
    url = f"ws://127.0.0.1:{args.port}"
    phones = [VirtualPhone(s, world, spec, seed=args.seed, noise_rms=args.noise) for s in range(6)]
    print(f"6 virtual phones joining {url}; the user is really at {me}")
    await asyncio.gather(*(p.run(url, stop) for p in phones))


def main() -> None:
    p = argparse.ArgumentParser(prog="earmark-ranging")
    sub = p.add_subparsers(dest="cmd", required=True)
    for name in ("serve", "sim"):
        s = sub.add_parser(name)
        s.add_argument("--port", type=int, default=8766)
        s.add_argument("--beacons", default=str(DEFAULT_BEACONS), help="where the fixed phones are (beacons.json or space.json)")
        s.add_argument("--band", type=float, nargs=2, default=(17000.0, 20000.0), metavar=("LO", "HI"))
        s.add_argument("--audible", action="store_true", help="use the 2000 to 4500 Hz band instead of the quiet high one")
    sv = sub.choices["serve"]
    sv.add_argument("--no-bus", action="store_true", help="do not publish to the Earmark bus")
    sm = sub.choices["sim"]
    sm.add_argument("--x", type=float, default=0.3)
    sm.add_argument("--y", type=float, default=0.5)
    sm.add_argument("--z", type=float, default=1.2)
    sm.add_argument("--noise", type=float, default=0.002)
    sm.add_argument("--seed", type=int, default=1)
    args = p.parse_args()
    logging.basicConfig(level=logging.WARNING)
    try:
        asyncio.run(_serve(args) if args.cmd == "serve" else _sim(args))
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
