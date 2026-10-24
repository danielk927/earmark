"""Tiny stand-in for the hub's bus, to exercise Earmark.app end to end without the real hub.

Run (from the repo root):
    uv run --with 'websockets>=13,<16' python mac/tools/fake_bus.py            # scripted check, exits 0/1
    uv run --with 'websockets>=13,<16' python mac/tools/fake_bus.py --hold     # stay up with guidance active

It serves ws://127.0.0.1:8765 (or --port), waits for the Mac app's hello, sends a snapshot, then a
scripted sequence (guide_start, speak_text, streamed speak, a behind target, speak_cached, guide_stop),
logs every message the app sends to logs/fake_bus.jsonl, and checks that the app answered with
hello (subscribing to speak), status, guide_feedback (behind), and playback started/finished.
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import json
import math
import struct
import sys
import time
from pathlib import Path

import websockets

REPO = Path(__file__).resolve().parents[2]
EXAMPLES = REPO / "contracts" / "examples" / "bus"


def now() -> float:
    return time.time()


def snapshot() -> dict:
    base = json.loads((EXAMPLES / "snapshot" / "01.json").read_text())
    spots = {s["spot"]: s["position"] for s in base["space"]["spots"]}

    def on_spot(obj: str, spot: int) -> dict:
        return {"type": "state_update", "object_id": obj, "location": {"spot": spot, "position": spots[spot]},
                "precision": "exact", "status": "on_spot", "home_spot": spot, "last_seen_t": now(),
                "source": "simulator", "t": now()}

    states = [on_spot("salt", 2), on_spot("sugar", 3), on_spot("bp_meds", 4)]
    states.append({"type": "state_update", "object_id": "keys",
                   "location": {"spot": None, "position": [0, 0.6, 0], "area": None, "near": "hub", "distance_class": "mid"},
                   "precision": "proximity", "status": "roaming", "home_spot": None, "last_seen_t": now(),
                   "source": "ble", "t": now()})
    for s in states:
        s.pop("type")
    return {"type": "snapshot", "space": base["space"], "objects": base["objects"], "states": states,
            "registry_version": 1, "t": now()}


def guide_start(obj: str, name: str, pos: list[float], uid: str) -> dict:
    return {"type": "guide_start", "object_id": obj, "name": name, "target_position": pos,
            "precision": "exact", "utterance_id": uid, "t": now()}


def speak_stream(uid: str, text: str, seconds: float = 0.6, rate: int = 48_000, chunks: int = 6) -> list[dict]:
    """A soft 330 Hz tone as pcm_f32le chunks, like Cartesia Sonic's raw WebSocket output."""
    n = int(seconds * rate)
    samples = [0.15 * math.sin(2 * math.pi * 330 * i / rate) * min(1, i / 480, (n - i) / 480) for i in range(n)]
    per = n // chunks
    msgs = []
    for k in range(chunks):
        part = samples[k * per:(k + 1) * per]
        b64 = base64.b64encode(struct.pack(f"<{len(part)}f", *part)).decode()
        m = {"type": "speak", "utterance_id": uid, "seq": k, "format": "pcm_f32le", "sample_rate": rate,
             "chunk_b64": b64, "final": False, "t": now()}
        if k == 0:
            m["text"] = text
        msgs.append(m)
    msgs.append({"type": "speak", "utterance_id": uid, "seq": chunks, "format": "pcm_f32le", "sample_rate": rate,
                 "chunk_b64": "", "final": True, "t": now()})
    return msgs


class Session:
    def __init__(self, log_path: Path, hold: bool):
        self.log_path = log_path
        self.hold = hold
        self.received: list[dict] = []
        self.done = asyncio.Event()
        self.ok = False

    def log(self, direction: str, msg: dict) -> None:
        summary = msg.get("type", "?")
        for key in ("object_id", "utterance_id", "event", "turn", "detail", "engine"):
            if key in msg and msg[key] is not None:
                summary += f" {key}={msg[key]}"
        print(f"{time.strftime('%H:%M:%S')} {direction} {summary}", flush=True)
        with self.log_path.open("a") as f:
            f.write(json.dumps({"dir": direction, "msg": msg}) + "\n")

    async def send(self, ws, msg: dict) -> None:
        self.log("->", msg)
        await ws.send(json.dumps(msg))

    async def reader(self, ws) -> None:
        async for raw in ws:
            msg = json.loads(raw)
            self.received.append(msg)
            if msg.get("type") not in ("head_pose", "mic_audio"):
                self.log("<-", msg)

    def wait_for(self, pred, timeout: float):
        async def poll():
            end = time.monotonic() + timeout
            while time.monotonic() < end:
                if any(pred(m) for m in self.received):
                    return True
                await asyncio.sleep(0.05)
            return False
        return poll()

    async def script(self, ws) -> None:
        if not await self.wait_for(lambda m: m.get("type") == "hello", 10):
            print("FAIL: no hello from the app", flush=True)
            self.done.set()
            return
        hello = next(m for m in self.received if m.get("type") == "hello")
        await self.send(ws, snapshot())
        await asyncio.sleep(1.0)
        await self.send(ws, guide_start("sugar", "sugar", [0.16, 0.58, 0.0], "u-1"))
        await asyncio.sleep(0.5)
        await self.send(ws, {"type": "speak_text", "utterance_id": "u-1",
                             "text": "The sugar is at your one o'clock, about an arm's length away.", "t": now()})
        if self.hold:
            await asyncio.sleep(1e9)
        await self.wait_for(lambda m: m.get("type") == "playback" and m.get("utterance_id") == "u-1" and m.get("event") == "finished", 12)
        for m in speak_stream("u-2", "Streaming audio check."):
            await self.send(ws, m)
            await asyncio.sleep(0.05)
        await self.wait_for(lambda m: m.get("type") == "playback" and m.get("utterance_id") == "u-2" and m.get("event") == "finished", 6)
        await self.send(ws, guide_start("keys", "keys", [0.2, -0.8, -0.2], "u-3"))
        await self.wait_for(lambda m: m.get("type") == "guide_feedback" and m.get("event") == "behind", 3)
        await self.send(ws, {"type": "speak_cached", "phrase_id": "behind_turn_right", "utterance_id": "u-4",
                             "text": "It's behind you. Turn right.", "t": now()})
        await self.wait_for(lambda m: m.get("type") == "playback" and m.get("utterance_id") == "u-4" and m.get("event") == "finished", 10)
        await self.send(ws, {"type": "guide_stop", "reason": "found", "object_id": "keys", "t": now()})
        await asyncio.sleep(1.5)

        checks = {
            "hello as mac_app subscribing to speak": hello.get("component") == "mac_app" and "speak" in (hello.get("subscribe") or []),
            "status from mac_app with renderer/head_tracking/guidance_mode/stt_engine":
                any(m.get("type") == "status" and m.get("component") == "mac_app"
                    and all(k in (m.get("info") or {}) for k in ("renderer", "head_tracking", "guidance_mode", "input_device",
                                                                  "output_device", "output_sample_rate", "stt_engine"))
                    for m in self.received),
            "playback started+finished for speak_text u-1": all(any(m.get("type") == "playback" and m.get("utterance_id") == "u-1" and m.get("event") == e for m in self.received) for e in ("started", "finished")),
            "playback started+finished for streamed speak u-2": all(any(m.get("type") == "playback" and m.get("utterance_id") == "u-2" and m.get("event") == e for m in self.received) for e in ("started", "finished")),
            "playback finished for speak_cached u-4": any(m.get("type") == "playback" and m.get("utterance_id") == "u-4" and m.get("event") == "finished" for m in self.received),
            "exactly one guide_feedback behind (turn right) for the keys": [ (m.get("event"), m.get("turn")) for m in self.received if m.get("type") == "guide_feedback" and m.get("object_id") == "keys"][:1] == [("behind", "right")],
            "head_pose at <= 10 Hz": self.head_pose_rate() <= 11,
        }
        print("\n== checks", flush=True)
        for name, passed in checks.items():
            print(f"{'PASS' if passed else 'FAIL'}  {name}", flush=True)
        counts: dict[str, int] = {}
        for m in self.received:
            counts[m.get("type", "?")] = counts.get(m.get("type", "?"), 0) + 1
        print(f"received: {json.dumps(counts, sort_keys=True)}", flush=True)
        self.ok = all(checks.values())
        self.done.set()

    def head_pose_rate(self) -> float:
        ts = [m["t"] for m in self.received if m.get("type") == "head_pose"]
        if len(ts) < 2:
            return 0.0
        return (len(ts) - 1) / max(ts[-1] - ts[0], 1e-6)


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--hold", action="store_true", help="keep guidance active and stay up (for screenshots)")
    ap.add_argument("--log", default=str(REPO / "logs" / "fake_bus.jsonl"))
    args = ap.parse_args()
    log_path = Path(args.log)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_path.write_text("")
    session = Session(log_path, args.hold)

    async def handler(ws):
        reader = asyncio.create_task(session.reader(ws))
        try:
            await session.script(ws)
        finally:
            reader.cancel()

    async with websockets.serve(handler, "127.0.0.1", args.port, max_size=16 << 20):
        print(f"fake bus on ws://127.0.0.1:{args.port}, waiting for the Mac app", flush=True)
        await session.done.wait()
    return 0 if session.ok else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
