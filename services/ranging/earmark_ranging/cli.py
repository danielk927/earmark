"""earmark-ranging serve | sim | listen"""
from __future__ import annotations

import argparse
import asyncio
import logging
import os
import socket
import sys

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
    svc = RangingService(anchors, ChirpSpec(lo, hi, amplitude=args.volume), publisher=BusPublisher(bus))

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
                if args.save_audio:
                    svc.save_audio(args.save_audio)
                if args.verbose:
                    for (x, y), d in sorted(svc.pairs.items()):
                        print(f"   phones {x} and {y} are {d:.2f} m apart")
                    for slot in sorted(svc.phones):
                        d = svc.diag.get(slot)
                        who = "your phone" if slot == 0 else f"beacon {slot}"
                        mic = f"own chirp {d['own']:>4}, hears phones {d['heard']}" if d else "no recording yet"
                        print(f"   {who:<11} {mic}")

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
    phones = [VirtualPhone(s, world, spec, seed=args.seed, noise_rms=args.noise) for s in [0, *sorted(anchors)]]
    print(f"{len(anchors) + 1} virtual phones joining {url}; the user is really at {me}")
    await asyncio.gather(*(p.run(url, stop) for p in phones))


def _only(anchors: dict, only: list[str] | None) -> dict:
    if not only:
        return anchors
    want = {int("".join(ch for ch in o if ch.isdigit())) for o in only}
    missing = want - set(anchors)
    if missing:
        raise SystemExit(f"--only names beacons not in the config: {sorted(missing)} (have {sorted(anchors)})")
    return {k: v for k, v in anchors.items() if k in want}


def _listen_instructions(beacons: dict, known: dict, at, labels: dict) -> str:
    if at is not None:
        return (f"Hold the phone still at x {at[0]:.2f}  y {at[1]:.2f}  z {at[2]:.2f} m (bottom edge toward the beacons), "
                "then press Enter.")
    (k, d), = known.items()
    where = f"beacon B{k} ({labels[k]})" if labels.get(k) else f"beacon B{k}"
    return f"Hold the phone still at exactly {d:.2f} m from {where}, bottom edge toward it, then press Enter."


async def _listen(args) -> None:
    from .listen import known_distances, speed_of_sound
    from .service_listen import ListenService

    anchors = _only(load_anchors(args.beacons), args.only)
    labels = _labels(args.beacons)
    if not anchors:
        raise SystemExit("no beacons configured")
    at = tuple(args.calibrate_at) if args.calibrate_at else None
    if at is None and args.calibrate_distance is None:
        if len(anchors) == 1:
            args.calibrate_distance = 1.0
        else:
            raise SystemExit("with more than one beacon give --calibrate-at X Y Z "
                             "(or pick one with --only B1 and --calibrate-distance)")
    known = known_distances(anchors, args.calibrate_distance, at)
    c = speed_of_sound(args.temperature)
    spec = ChirpSpec(args.band[0], args.band[1])
    bus = None if args.no_bus else os.environ.get("EARMARK_BUS_URL", "ws://127.0.0.1:8765")
    recorder = None
    if args.record:
        from .record import SessionRecorder
        from .service import FS

        recorder = SessionRecorder(args.record, FS, meta={
            "band": list(args.band), "cycle_s": args.cycle, "slot_s": args.slot, "min_snr": args.min_snr,
            "temperature_c": args.temperature, "beacons": {f"B{k}": list(v) for k, v in sorted(anchors.items())},
            "calibrate_distance": args.calibrate_distance, "calibrate_at": list(at) if at else None,
            "calibration_seconds": args.calibration_seconds,
        })
    svc = ListenService(
        anchors, known, spec, c=c, calibration_s=args.calibration_seconds, cycle_s=args.cycle, slot_s=args.slot,
        publisher=BusPublisher(bus), log_path=args.log, min_snr=args.min_snr, recorder=recorder,
    )

    def clock(wall: float | None) -> str:
        from datetime import datetime

        return datetime.fromtimestamp(wall).strftime("%H:%M:%S.%f")[:-3] if wall is not None else "--:--:--.---"

    def on_heard(det, beacon, wall) -> None:
        if beacon is None:
            return  # a chirp shape no configured beacon makes, or noise
        what = "calibrating" if svc.state == "calibrating" else "not calibrated, press Enter when the phone is at the spot"
        print(f"{clock(wall)}  B{beacon}  heard   snr {det.snr:5.1f}   ({what})")

    def on_range(r, wall) -> None:
        print(f"{clock(wall)}  B{r.beacon}  d {r.distance_m:6.3f} m  snr {r.snr:5.1f}  cycle {r.cycle}")

    def on_fix(fix, pose) -> None:
        x, y, z = pose.position
        print(f"fix  x {x:6.2f}  y {y:6.2f}  z {z:5.2f}   {pose.quality:<8} {fix.used} beacons   fit {fix.rms_m * 100:4.1f} cm")

    def on_report(rep) -> None:
        print("\n".join(rep.lines()))
        if rep.ok:
            print("tracking. Walk around; one line per chirp. Press Enter to calibrate again.")
        elif svc.tracker is not None:
            print("keeping the previous calibration. Press Enter to try again.")
        else:
            print("fix the problem, put the phone back at the spot and press Enter to try again.")

    svc.on_heard, svc.on_range, svc.on_fix, svc.on_report = on_heard, on_range, on_fix, on_report
    stop = asyncio.Event()
    tasks = []
    async with serve(svc.handler, "0.0.0.0", args.port, max_size=2**22):
        print(f"listen service ready. The user's phone connects to:  ws://{lan_ip()}:{args.port}")
        print(f"chirp band {spec.f_lo:.0f} to {spec.f_hi:.0f} Hz, cycle {args.cycle} s, slot {args.slot} s, c {c:.1f} m/s")
        if recorder is not None:
            print(f"recording everything the phone hears to {args.record} (replay it with: earmark-ranging replay {args.record})")
        print(f"beacons: {', '.join(f'B{k} at {v}' for k, v in sorted(anchors.items()))} (self-timed, they do not connect)")
        print("Start the beacon phones in beacon mode. " + _listen_instructions(anchors, known, at, labels))
        auto = args.calibrate_after
        if args.sim:
            from .sim_listen import SelfTimedWorld, VirtualTargetPhone, calibration_spot, still_then_walk
            import time

            auto = 2.0 if auto is None else auto
            spot = calibration_spot(anchors, args.calibrate_distance, at)
            t0 = time.time()
            path = still_then_walk(spot, t0 + 1.0 + auto + args.calibration_seconds + 1.5)
            world = SelfTimedWorld(anchors, path, spec, t0, c=c, seed=args.seed, echo=args.sim_echo)
            phone = VirtualTargetPhone(world, t0 + 0.5, seed=args.seed, noise_rms=args.sim_noise, dropout=args.sim_dropout)
            here = tuple(round(v, 2) for v in spot)
            print(f"SIMULATION: a virtual phone stands at {here}, calibrates after {auto:.0f} s, then walks.")
            tasks.append(asyncio.create_task(phone.run(f"ws://127.0.0.1:{args.port}", stop)))
        if auto is not None:
            print(f"calibration starts by itself {auto:.0f} s after the first audio arrives (or press Enter sooner).")

        def on_enter() -> None:
            sys.stdin.readline()
            if svc.target is None:
                print("no phone connected yet")
                return
            print(f"calibrating for {args.calibration_seconds:.0f} s: keep the phone still...")
            svc.start_calibration()

        loop = asyncio.get_running_loop()
        try:
            loop.add_reader(sys.stdin.fileno(), on_enter)
        except (ValueError, OSError, NotImplementedError):
            print("(no console: calibration only starts with --calibrate-after)")
        tasks.append(asyncio.create_task(svc.run(auto)))

        async def beat() -> None:
            n = 0
            while True:
                await asyncio.sleep(1.0)
                n += 1
                if svc.state == "calibrating":
                    print(f"   calibrating... {svc.calibration_remaining():4.1f} s left, keep still")
                elif n % 2 == 0:
                    await svc.publisher.send(svc.status())
                    print(svc.status_line())
                    if args.save_audio:
                        svc.save_audio(args.save_audio)

        tasks.append(asyncio.create_task(beat()))
        try:
            await asyncio.gather(*tasks)
        finally:
            stop.set()
            if recorder is not None:
                recorder.close()
                print(f"recording saved: {args.record} ({recorder.n_bytes / 2 / 48000:.0f} s, {recorder.gaps} lost chunks)")


def _replay(args) -> None:
    from .replay import replay

    anchors = _only(load_anchors(args.beacons), args.only)
    at = tuple(args.calibrate_at) if args.calibrate_at else None
    res = replay(
        args.file, anchors, calibrate_from_s=args.calibrate_from, calibration_s=args.calibration_seconds,
        calibrate_distance=args.calibrate_distance, calibrate_at=at, band=tuple(args.band) if args.band else None,
        temperature_c=args.temperature, min_snr=args.min_snr, log_path=args.log, quiet=args.quiet,
    )
    print(f"--- {res.seconds:.0f} s of audio, {len(res.ranges)} distances, {len(res.fixes)} fixes")
    truth = {int(k[1:]): float(v) for k, v in (args.truth or [])}
    print("\n".join(res.summary(truth or None)))


def _labels(path) -> dict[int, str]:
    import json
    import re

    try:
        data = json.loads(open(path).read())
        return {int(re.search(r"(\d+)$", str(b["id"])).group(1)): str(b.get("label", "")) for b in data["beacons"]}
    except Exception:  # noqa: BLE001 - labels are decoration only
        return {}


def main() -> None:
    p = argparse.ArgumentParser(prog="earmark-ranging")
    sub = p.add_subparsers(dest="cmd", required=True)
    for name in ("serve", "sim", "listen"):
        s = sub.add_parser(name)
        s.add_argument("--port", type=int, default=8766)
        s.add_argument("--beacons", default=str(DEFAULT_BEACONS), help="where the fixed phones are (beacons.json or space.json)")
        s.add_argument("--band", type=float, nargs=2, default=(12000.0, 16000.0) if name == "listen" else (17000.0, 20000.0),
                       metavar=("LO", "HI"))
        if name != "listen":
            s.add_argument("--audible", action="store_true", help="use the 2000 to 4500 Hz band instead of the quiet high one")
    sv = sub.choices["serve"]
    sv.add_argument("--volume", type=float, default=1.0, help="chirp loudness, 0 to 1 (use less when the phones are close)")
    sv.add_argument("--no-bus", action="store_true", help="do not publish to the Earmark bus")
    sv.add_argument("--save-audio", metavar="DIR", help="keep the last few seconds each phone heard as WAV files (for checking)")
    sv.add_argument("--verbose", action="store_true", help="every 2 s, show what each phone heard (for setting up)")
    sm = sub.choices["sim"]
    sm.add_argument("--x", type=float, default=0.3)
    sm.add_argument("--y", type=float, default=0.5)
    sm.add_argument("--z", type=float, default=1.2)
    sm.add_argument("--noise", type=float, default=0.002)
    sm.add_argument("--seed", type=int, default=1)
    li = sub.choices["listen"]
    li.add_argument("--cycle", type=float, default=0.5, help="seconds between a beacon's chirps")
    li.add_argument("--slot", type=float, default=0.125, help="seconds between beacon 1's chirp and beacon 2's")
    li.add_argument("--only", nargs="+", metavar="B1", help="use only these beacons from the config, e.g. --only B1")
    li.add_argument("--calibrate-distance", type=float, metavar="D",
                    help="meters from the phone to the (single) beacon while calibrating")
    li.add_argument("--calibrate-at", type=float, nargs=3, metavar=("X", "Y", "Z"), help="where the phone is while calibrating")
    li.add_argument("--calibration-seconds", type=float, default=10.0)
    li.add_argument("--calibrate-after", type=float, metavar="S",
                    help="start calibrating S seconds after the first audio arrives")
    li.add_argument("--temperature", type=float, default=20.0, help="room temperature in C, for the speed of sound")
    li.add_argument("--min-snr", type=float, default=4.5, help="how clearly a chirp must stand out to count")
    li.add_argument("--log", metavar="FILE", help="append every distance to this CSV file")
    li.add_argument("--no-bus", action="store_true", help="do not publish to the Earmark bus")
    li.add_argument("--save-audio", metavar="DIR", help="keep the last few seconds the phone heard as a WAV file (for checking)")
    li.add_argument("--record", metavar="FILE.wav", help="record everything the phone hears, for replay and study")
    li.add_argument("--sim", action="store_true", help="no phones: a virtual phone and virtual beacons run the whole path")
    li.add_argument("--sim-noise", type=float, default=0.1)
    li.add_argument("--sim-echo", action="store_true", help="the virtual room has echoes")
    li.add_argument("--sim-dropout", type=float, default=0.0, help="fraction of audio chunks the virtual phone loses")
    li.add_argument("--seed", type=int, default=1)
    rp = sub.add_parser("replay", help="run the listen pipeline over a recording made with listen --record")
    rp.add_argument("file", metavar="FILE.wav")
    rp.add_argument("--beacons", default=str(DEFAULT_BEACONS))
    rp.add_argument("--only", nargs="+", metavar="B1")
    rp.add_argument("--band", type=float, nargs=2, metavar=("LO", "HI"), help="default: what the recording used")
    rp.add_argument("--calibrate-from", type=float, metavar="S",
                    help="second of the file to start calibrating at (default: when the live run did)")
    rp.add_argument("--calibration-seconds", type=float, default=10.0)
    rp.add_argument("--calibrate-distance", type=float, metavar="D")
    rp.add_argument("--calibrate-at", type=float, nargs=3, metavar=("X", "Y", "Z"))
    rp.add_argument("--temperature", type=float, default=20.0)
    rp.add_argument("--min-snr", type=float, help="default: what the recording used")
    rp.add_argument("--log", metavar="FILE")
    rp.add_argument("--truth", nargs=2, action="append", metavar=("B1", "METERS"),
                    help="true distance to a beacon, for the error summary (repeatable)")
    rp.add_argument("--quiet", action="store_true", help="only the summary")
    args = p.parse_args()
    logging.basicConfig(level=logging.WARNING)
    if args.cmd == "replay":
        _replay(args)
        return
    runner = {"serve": _serve, "sim": _sim, "listen": _listen}[args.cmd]
    try:
        asyncio.run(runner(args))
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
