"""Console scripts: earmark-hub, earmark-send, earmark-sim, earmark-tail."""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import signal
import sys
import time
from pathlib import Path

from earmark_contracts import DetectionEvent, Reset, dump, parse_bus, to_dict
from pydantic import ValidationError

from .config import bus_url, convex_env, load_config, load_dotenv_once, parse_adapters

log = logging.getLogger("earmark.cli")


def _run(coro) -> int:
    try:
        return asyncio.run(coro) or 0
    except KeyboardInterrupt:
        return 130


# ---------------------------------------------------------------- earmark-hub

def main_hub(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="earmark-hub", description="Run the Earmark hub (bus, adapters, state, Convex sync).")
    p.add_argument("--adapters", help="comma list (simulator,nfc_serial,ble_fobs,camera_stub); overrides EARMARK_ADAPTERS")
    p.add_argument("--scenario", type=Path, help="scenario JSONL for the simulator")
    p.add_argument("--speed", type=float, default=1.0, help="playback speed; the hub clock runs this much faster")
    p.add_argument("--loop", action="store_true", help="loop the scenario")
    p.add_argument("--step", action="store_true", help="pause (Enter) before each line that changes a reading")
    p.add_argument("--interactive", action="store_true", help="Wizard-of-Oz keyboard simulator")
    p.add_argument("--no-convex", action="store_true", help="never talk to Convex")
    p.add_argument("--config", type=Path, help="hub config (default HUB_CONFIG or config/hub.json)")
    p.add_argument("-v", "--verbose", action="store_true", help="debug logging on the console")
    args = p.parse_args(argv)
    if args.scenario and args.interactive:
        p.error("--scenario and --interactive are mutually exclusive")

    load_dotenv_once()
    from .adapters import build_adapters
    from .clock import ScaledClock, SystemClock
    from .hub import Hub
    from .logs import setup_logging

    cfg = load_config(args.config)
    if args.adapters:
        cfg.adapters = parse_adapters(args.adapters)
    if (args.scenario or args.interactive) and "simulator" not in cfg.adapters:
        cfg.adapters.append("simulator")
    console = logging.DEBUG if args.verbose else logging.WARNING if (args.interactive or args.step) else logging.INFO
    setup_logging(cfg.path("logs"), "hub", console)
    if args.speed != 1.0:
        log.warning("speed != 1: hub timestamps run ahead of the wall clock; use only for scenario playback",
                    extra={"speed": args.speed})
    clock = ScaledClock(args.speed) if args.speed != 1.0 else SystemClock()
    scenario = args.scenario.resolve() if args.scenario else None
    adapters = build_adapters(cfg.adapters, cfg, clock, scenario=scenario, loop=args.loop, step=args.step,
                              interactive=args.interactive)
    env, reason = (None, "--no-convex") if args.no_convex else convex_env()
    hub = Hub(cfg, clock=clock, adapters=adapters, convex_env=env, offline_reason=reason)
    return _run(_serve(hub))


async def _serve(hub) -> int:
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, stop.set)
        except NotImplementedError:  # Windows: Ctrl+C still raises KeyboardInterrupt; terminate() kills
            pass
    try:
        await hub.start()
    except OSError as e:
        log.error("cannot start the bus", extra={"error": str(e)})
        return 1
    await stop.wait()
    log.info("shutting down")
    await hub.stop()
    return 0


# ---------------------------------------------------------------- earmark-send

SEND_DEFAULTS = {
    "transcript": {"is_final": True, "source": "typed"},
    "label": {"aliases": []},
    "chirp": {"action": "start"},
}


def _field_value(raw: str):
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return raw


def build_message(msg_type: str, fields: list[str], json_body: str | None = None):
    """Build and validate one bus message from `--key value` pairs (values parsed as JSON when possible)."""
    data: dict = {"type": msg_type, **SEND_DEFAULTS.get(msg_type, {})}
    if json_body:
        data.update(json.loads(json_body))
    it = iter(fields)
    for key in it:
        if not key.startswith("--"):
            raise ValueError(f"expected --field, got {key!r}")
        name = key[2:].replace("-", "_")
        if "=" in name:
            name, value = name.split("=", 1)
        else:
            value = next(it, None)
            if value is None:
                raise ValueError(f"missing value for {key}")
        data[name] = _field_value(value)
    return parse_bus(data)


def main_send(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="earmark-send", description="Publish one bus message.",
                                epilog='examples: earmark-send reset | earmark-send transcript --text "where\'s the sugar" '
                                       "| earmark-send chirp --fob_id fob_keys --action stop")
    p.add_argument("type", help="bus message type")
    p.add_argument("--json", dest="json_body", help="JSON object with fields")
    p.add_argument("--url", help="bus URL (default EARMARK_BUS_URL)")
    args, fields = p.parse_known_args(argv)
    load_dotenv_once()
    try:
        msg = build_message(args.type, fields, args.json_body)
    except (ValidationError, ValueError) as e:
        print(f"invalid {args.type} message: {e}", file=sys.stderr)
        return 2
    return _run(_send(msg, args.url))


async def _send(msg, url: str | None) -> int:
    from .client import BusClient

    try:
        client = await BusClient.connect("cli", subscribe=[], url=url)
    except (OSError, TimeoutError) as e:
        print(f"cannot reach the hub at {url or bus_url()}: {e}", file=sys.stderr)
        return 1
    await client.send(msg)
    await client.close()
    print(dump(msg))
    return 0


# ---------------------------------------------------------------- earmark-sim

def main_sim(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="earmark-sim", description="Play a scenario (or the keyboard simulator) "
                                                               "against a running hub.")
    p.add_argument("scenario", nargs="?", type=Path)
    p.add_argument("--speed", type=float, default=1.0)
    p.add_argument("--loop", action="store_true")
    p.add_argument("--step", action="store_true")
    p.add_argument("--interactive", action="store_true")
    p.add_argument("--url", help="bus URL (default EARMARK_BUS_URL)")
    args = p.parse_args(argv)
    if bool(args.scenario) == bool(args.interactive):
        p.error("give a scenario file or --interactive (not both)")
    load_dotenv_once()
    from .logs import setup_logging

    setup_logging(None, "sim", logging.WARNING)
    return _run(_sim(args))


async def _sim(args) -> int:
    from .adapters.simulator import Simulator, load_scenario
    from .client import BusClient
    from .clock import ScaledClock, SystemClock

    lines = load_scenario(args.scenario) if args.scenario else None
    try:
        client = await BusClient.connect("simulator", subscribe=["reset", "registry_update"], url=args.url)
    except (OSError, TimeoutError) as e:
        print(f"cannot reach the hub at {args.url or bus_url()}: {e}", file=sys.stderr)
        return 1
    cfg = load_config().simulator
    clock = ScaledClock(args.speed) if args.speed != 1.0 else SystemClock()
    snap = client.snapshot
    sim = Simulator(clock, objects=snap.objects, spots=[s.spot for s in snap.space.spots], cfg=cfg,
                    scenario=lines, loop=args.loop, step=args.step, interactive=args.interactive)

    async def listen() -> None:
        async for msg in client:
            if isinstance(msg, Reset) and sim.interactive:
                sim.reset_physical()
            elif msg.type == "registry_update":
                sim.set_objects(msg.objects)

    listener = asyncio.create_task(listen())
    try:
        await sim.run(client.send)
    finally:
        listener.cancel()
        await client.close()
    return 0


# ---------------------------------------------------------------- earmark-tail

def summarize(msg) -> str:
    t = msg.t
    stamp = time.strftime("%H:%M:%S", time.localtime(t)) + f".{int((t % 1) * 1000):03d}"
    body = to_dict(msg)
    body.pop("type", None)
    body.pop("t", None)
    if isinstance(msg, DetectionEvent):
        where = json.dumps(body.get("where"), separators=(",", ":"))
        text = f"{msg.source} {msg.kind} {msg.tag} {where}" + (f" rssi={msg.rssi}" if msg.rssi is not None else "")
    elif msg.type == "state_update":
        loc = {k: v for k, v in body["location"].items() if v is not None}
        text = f"{msg.object_id} {msg.status} {json.dumps(loc, separators=(',', ':'))} ({msg.precision})"
    elif msg.type == "pickup":
        text = f"{msg.object_id} from spot {msg.from_spot}"
    elif msg.type == "snapshot":
        text = f"{len(msg.objects)} objects, {len(msg.states)} states, registry_version={msg.registry_version}"
    elif msg.type in ("mic_audio", "speak"):
        body["chunk_b64"] = f"<{len(body.get('chunk_b64', ''))} b64 chars>"
        text = json.dumps(body, separators=(",", ":"))
    else:
        text = json.dumps(body, separators=(",", ":"))
    return f"{stamp} {msg.type:<15} {text}"


def main_tail(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="earmark-tail", description="Print bus traffic.")
    g = p.add_mutually_exclusive_group()
    g.add_argument("--types", help="comma list of message types to receive")
    g.add_argument("--all", action="store_true", help="everything, including mic_audio and speak")
    p.add_argument("--raw", action="store_true", help="print raw JSON lines")
    p.add_argument("--url", help="bus URL (default EARMARK_BUS_URL)")
    args = p.parse_args(argv)
    load_dotenv_once()
    subscribe = ["*"] if args.all else [t.strip() for t in args.types.split(",")] if args.types else None
    return _run(_tail(subscribe, args.raw, args.url))


async def _tail(subscribe, raw: bool, url: str | None) -> int:
    from .client import BusClient

    waiting = False
    while True:
        try:
            client = await BusClient.connect("cli", subscribe=subscribe, url=url)
        except (OSError, TimeoutError):
            if not waiting:
                print(f"waiting for the hub at {url or bus_url()} ...", file=sys.stderr)
                waiting = True
            await asyncio.sleep(1.0)
            continue
        waiting = False
        print(summarize(client.snapshot) if not raw else dump(client.snapshot), flush=True)
        async for msg in client:
            print(dump(msg) if raw else summarize(msg), flush=True)
        print("hub disconnected", file=sys.stderr)
