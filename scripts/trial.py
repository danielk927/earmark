#!/usr/bin/env python3
"""Trial CLI for measurable usefulness (BUILD_BRIEF 5.I).

Run with the hub up:  uv run --project services/hub python scripts/trial.py

Per trial: pick a mode (alternate earmark/baseline), a target (randomize), and a tester
pseudonym (never a real name). Enter starts the timer and sends `trial_start`. The trial
ends on the target's `pickup` (earmark mode waits up to 1 s for the concierge's
confirming `pickup_result`); every other pickup is a wrong pick. Enter ends it as
gave_up, `a` + Enter aborts. `trial_end` carries metrics computed only from bus events;
nothing is typed in, edited, or extrapolated. Each trial_end is also appended to
var/trials/trials.jsonl, which is only used to suggest the next mode and target.
"""
from __future__ import annotations

import argparse
import asyncio
import sys
import time

from earmark_contracts import Pickup, PickupResult, RegistryUpdate, TrialEnd, TrialStart, dump, parse_bus
from earmark_hub.client import BusClient
from earmark_hub.config import bus_url, load_config, load_dotenv_once
from earmark_hub.console import StdinReader
from earmark_hub.trial import TrialSession, new_trial_id, suggest, validate_pseudonym


class Quit(Exception):
    pass


async def ask(reader: StdinReader, prompt: str, default: str | None = None) -> str:
    print(prompt, end="", flush=True)
    line = await reader.get()
    if line is None:
        raise Quit
    return line.strip() or (default or "")


def load_history(path) -> list[TrialEnd]:
    if not path.is_file():
        return []
    out = []
    for line in path.read_text().splitlines():
        try:
            msg = parse_bus(line)
        except ValueError:
            continue
        if isinstance(msg, TrialEnd):
            out.append(msg)
    return out


def resolve_target(text: str, objects) -> str | None:
    q = text.strip().lower()
    for o in objects:
        if q in (o.object_id.lower(), o.name.lower()) or q in (a.lower() for a in o.aliases):
            return o.object_id
    return None


async def run_trial(session: TrialSession, bus_q: asyncio.Queue, reader: StdinReader, names: dict) -> TrialEnd:
    print("Running. Enter = gave up, a + Enter = abort.", flush=True)
    line_task = asyncio.create_task(reader.get())
    bus_task = asyncio.create_task(bus_q.get())
    try:
        while True:
            done, _ = await asyncio.wait({line_task, bus_task}, timeout=0.1, return_when=asyncio.FIRST_COMPLETED)
            now = time.time()
            if bus_task in done:
                msg = bus_task.result()
                bus_task = asyncio.create_task(bus_q.get())
                before = session.wrong_picks
                end = session.on_message(msg, now)
                if isinstance(msg, Pickup) and msg.t >= session.start.t:
                    tag = " (wrong pick)" if session.wrong_picks > before else " (target)"
                    print(f"  pickup: {names.get(msg.object_id, msg.object_id)} from spot {msg.from_spot}{tag}")
                elif isinstance(msg, PickupResult) and msg.t >= session.start.t:
                    print(f"  pickup_result: expected {msg.expected}, actual {msg.actual}, correct={msg.correct}")
                if end:
                    return end
            if line_task in done:
                line = line_task.result()
                if line is None:
                    return session.abort(now)
                return session.abort(now) if line.strip().lower() == "a" else session.give_up(now)
            end = session.poll(now)
            if end:
                print("  (no confirming pickup_result within 1 s; ending on the pickup itself)")
                return end
    finally:
        line_task.cancel()
        bus_task.cancel()


async def main(url: str | None) -> int:
    cfg = load_config()
    history_path = cfg.path("trials")
    try:
        client = await BusClient.connect("trial_cli", subscribe=["pickup", "pickup_result", "registry_update"], url=url)
    except (OSError, TimeoutError) as e:
        print(f"cannot reach the hub at {url or bus_url()}: {e}", file=sys.stderr)
        return 1
    objects = list(client.snapshot.objects)
    bus_q: asyncio.Queue = asyncio.Queue()

    async def listen() -> None:
        nonlocal objects
        async for msg in client:
            if isinstance(msg, RegistryUpdate):
                objects = list(msg.objects)
            else:
                bus_q.put_nowait(msg)
        print("\nhub disconnected", file=sys.stderr)

    listener = asyncio.create_task(listen())
    reader = StdinReader(cbreak=False)
    history = load_history(history_path)
    print(f"Earmark trial mode. {len(history)} earlier trial(s) in {history_path}.")
    print("Rules: never fabricate or edit data. Report every trial, including gave_up and aborted ones.\n")
    try:
        while True:
            mode_s, target_s = suggest(history, objects)
            mode = ""
            while mode not in ("earmark", "baseline"):
                mode = (await ask(reader, f"Mode [earmark/baseline] (Enter = {mode_s}): ", mode_s)).lower()
            options = ", ".join(o.object_id for o in objects if o.tag)
            target = None
            while target is None:
                text = await ask(reader, f"Target ({options}) (Enter = random: {target_s}): ", target_s or "")
                target = resolve_target(text, objects)
                if target is None:
                    print("  unknown object")
            tester, error = "", "x"
            while error:
                tester = await ask(reader, "Tester pseudonym (e.g. tester-A): ")
                error = validate_pseudonym(tester)
                if error:
                    print(f"  {error}")
            await ask(reader, f"Press Enter when the tester starts searching for {target} ({mode} mode)... ")
            while not bus_q.empty():
                bus_q.get_nowait()
            start = TrialStart(trial_id=new_trial_id(), mode=mode, target_object_id=target, tester=tester,
                               t=time.time())
            await client.send(start)
            print(f"trial_start {start.trial_id}")
            names = {o.object_id: o.name for o in objects}
            end = await run_trial(TrialSession(start), bus_q, reader, names)
            await client.send(end)
            history.append(end)
            history_path.parent.mkdir(parents=True, exist_ok=True)
            with history_path.open("a") as f:
                f.write(dump(end) + "\n")
            secs = f"{end.seconds_to_find:.2f} s" if end.seconds_to_find is not None else "-"
            print(f"trial_end {end.trial_id}: outcome={end.outcome} seconds_to_find={secs} "
                  f"wrong_picks={end.wrong_picks}\n")
            again = await ask(reader, "Another trial? [Y/n] ", "y")
            if again.lower().startswith("n"):
                return 0
    except Quit:
        print()
        return 0
    finally:
        listener.cancel()
        await client.close()


if __name__ == "__main__":
    p = argparse.ArgumentParser(description="Earmark trial CLI (BUILD_BRIEF 5.I)")
    p.add_argument("--url", help="bus URL (default EARMARK_BUS_URL)")
    args = p.parse_args()
    load_dotenv_once()
    try:
        sys.exit(asyncio.run(main(args.url)))
    except KeyboardInterrupt:
        sys.exit(130)
