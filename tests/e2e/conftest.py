"""End-to-end harness: real hub + real concierge processes on an isolated bus port.

Each scenario is replayed over the bus by `earmark-sim`, exactly like a live
simulator client. A recorder joins as the Mac app (so the concierge sends speech
on the bus instead of running `say`) and records every message.

Vendor keys are blanked so the run is deterministic and offline: LLM off
(keyword grammar), Moss off (fallback resolver), system-voice speech.
Run with: make e2e-test
"""
from __future__ import annotations

import asyncio
import json
import os
import socket
import subprocess
import time
from pathlib import Path

import pytest
import websockets

ROOT = Path(__file__).resolve().parents[2]
BLANK = [
    "CARTESIA_API_KEY", "CARTESIA_VOICE_ID", "MOSS_PROJECT_ID", "MOSS_PROJECT_KEY", "BITDEER_API_KEY",
    "CONVEX_SITE_URL", "EARMARK_HUB_SECRET",
]
SPEECH = {"speak", "speak_cached", "speak_text"}


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class Stack:
    def __init__(self, tmp: Path, *, uwb: bool | None = None) -> None:
        """`uwb`: force `uwb.enabled` in the temp hub.json (True/False); None keeps config/hub.json's value."""
        self.port = free_port()
        self.url = f"ws://127.0.0.1:{self.port}"
        self.tmp = tmp
        cfg = json.loads((ROOT / "config" / "hub.json").read_text())
        cfg["adapters"] = ["camera_stub"]
        cfg["bus"]["port"] = self.port
        cfg.setdefault("paths", {})["cache"] = str(tmp / "objects.cache.json")
        if uwb is not None:
            cfg.setdefault("uwb", {})["enabled"] = uwb
        self.cfg = cfg
        (tmp / "hub.json").write_text(json.dumps(cfg))
        self.env = dict(os.environ, EARMARK_BUS_PORT=str(self.port), EARMARK_BUS_URL=self.url,
                        HUB_LOG_DIR=str(tmp), CONCIERGE_SAY_CMD="true",
                        CONCIERGE_LATENCY_LOG=str(tmp / "latency.jsonl"), **{k: "" for k in BLANK})
        self.env.pop("VIRTUAL_ENV", None)
        self.procs: list[subprocess.Popen] = []

    def spawn(self, name: str, *args: str) -> subprocess.Popen:
        p = subprocess.Popen(["uv", "run", "--quiet", *args], cwd=ROOT, env=self.env,
                             stdout=open(self.tmp / f"{name}.log", "w"), stderr=subprocess.STDOUT)
        self.procs.append(p)
        return p

    def start(self) -> None:
        self.spawn("hub", "--project", "services/hub", "earmark-hub", "--no-convex", "--config", str(self.tmp / "hub.json"))
        self.spawn("concierge", "--project", "services/concierge", "earmark-concierge", "--no-llm")

    def stop(self) -> None:
        for p in self.procs:
            p.terminate()
        for p in self.procs:
            try:
                p.wait(5)
            except subprocess.TimeoutExpired:
                p.kill()

    async def run_scenario(self, scenario: str, speed: float, settle_s: float = 3.0) -> list[dict]:
        """Join as the Mac app, wait for the concierge, replay the scenario, return every message."""
        ws = None
        for _ in range(100):
            try:
                ws = await websockets.connect(self.url, max_size=None)
                break
            except OSError:
                await asyncio.sleep(0.1)
        assert ws is not None, "hub did not start"
        await ws.send(json.dumps({"type": "hello", "component": "mac_app",
                                  "subscribe": ["*"], "t": time.time()}))
        msgs: list[dict] = []

        async def heartbeat():
            while True:
                await ws.send(json.dumps({"type": "status", "component": "mac_app", "ok": True,
                                          "detail": "e2e recorder", "t": time.time()}))
                await asyncio.sleep(2)

        async def recv_until(pred, timeout):
            end = time.time() + timeout
            while time.time() < end:
                try:
                    raw = await asyncio.wait_for(ws.recv(), timeout=0.2)
                except asyncio.TimeoutError:
                    continue
                m = json.loads(raw)
                msgs.append(m)
                if pred(m):
                    return True
            return False

        hb = asyncio.create_task(heartbeat())
        try:
            ready = await recv_until(lambda m: m["type"] == "status" and m["component"] == "concierge", 30)
            assert ready, "concierge never reported status"
            # The concierge only counts the Mac app as present once it has seen a status from it; a heartbeat
            # sent before it connected is lost, and without it answers go to local speech, not the bus.
            await ws.send(json.dumps({"type": "status", "component": "mac_app", "ok": True,
                                      "detail": "e2e recorder", "t": time.time()}))
            await recv_until(lambda m: False, 0.3)
            sim = self.spawn("sim", "--project", "services/hub", "earmark-sim", f"scenarios/{scenario}.jsonl",
                             "--speed", str(speed), "--url", self.url)
            while sim.poll() is None:
                await recv_until(lambda m: False, 0.5)
            await recv_until(lambda m: False, settle_s)
        finally:
            hb.cancel()
            await ws.close()
        return msgs


def _running(s: Stack):
    s.start()
    try:
        yield s
    finally:
        s.stop()


@pytest.fixture
def stack(tmp_path):
    yield from _running(Stack(tmp_path))


@pytest.fixture
def uwb_stack(tmp_path):
    """Hub with UWB tracking enabled (listener_pose from uwb_range + motion_state)."""
    yield from _running(Stack(tmp_path, uwb=True))


def of(msgs: list[dict], *types: str) -> list[dict]:
    return [m for m in msgs if m["type"] in types]


def spoken(msgs: list[dict]) -> list[str]:
    """Text of every utterance, whichever speech path carried it."""
    out = []
    for m in msgs:
        if m["type"] in ("speak_text", "speak_cached") or (m["type"] == "speak" and m.get("seq") == 0):
            out.append(m.get("text", ""))
    return out
