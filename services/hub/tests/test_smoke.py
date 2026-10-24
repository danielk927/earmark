"""End-to-end: real earmark-hub / earmark-sim / earmark-send / earmark-tail processes over a real WebSocket."""
from __future__ import annotations

import asyncio
import json
import os
import signal
import subprocess
import sys
from pathlib import Path

import pytest
from earmark_contracts import Pickup, Snapshot

from conftest import ROOT, free_port
from earmark_hub.cli import build_message, summarize
from earmark_hub.client import BusClient

BIN = Path(sys.executable).parent


def hub_env(tmp_path: Path, port: int) -> dict:
    cfg = json.loads((ROOT / "config" / "hub.json").read_text())
    cfg["paths"] = {"space": str(ROOT / "config" / "space.json"), "seed": str(ROOT / "config" / "objects.seed.json"),
                    "cache": str(tmp_path / "cache.json"), "queue": str(tmp_path / "queue.jsonl"),
                    "trials": str(tmp_path / "trials.jsonl"), "logs": str(tmp_path / "logs")}
    (tmp_path / "hub.json").write_text(json.dumps(cfg))
    env = {k: v for k, v in os.environ.items() if not k.startswith(("EARMARK_", "CONVEX_", "HUB_", "NFC_"))}
    env.update(EARMARK_BUS_PORT=str(port), EARMARK_BUS_URL=f"ws://127.0.0.1:{port}", HUB_CONFIG=str(tmp_path / "hub.json"))
    return env


async def connect_retry(url: str, **kw) -> BusClient:
    for _ in range(100):
        try:
            return await BusClient.connect(url=url, **kw)
        except (OSError, TimeoutError):
            await asyncio.sleep(0.05)
    raise RuntimeError("hub never came up")


def start(args: list[str], env: dict) -> subprocess.Popen:
    return subprocess.Popen([str(BIN / args[0]), *args[1:]], env=env, cwd=ROOT, stdin=subprocess.DEVNULL,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)


def stop(proc: subprocess.Popen) -> tuple[str, str]:
    if proc.poll() is None:
        proc.send_signal(signal.SIGINT)
    try:
        return proc.communicate(timeout=10)
    except subprocess.TimeoutExpired:
        proc.kill()
        return proc.communicate()


async def collect_pickups(client: BusClient, n: int, timeout: float) -> list[tuple[str, int]]:
    got = []
    async with asyncio.timeout(timeout):
        while len(got) < n:
            msg = await client.recv()
            if isinstance(msg, Pickup):
                got.append((msg.object_id, msg.from_spot))
    return got


async def test_hub_replays_full_demo_over_websocket(tmp_path):
    port = free_port()
    env = hub_env(tmp_path, port)
    proc = start(["earmark-hub", "--adapters", "simulator", "--scenario", "scenarios/full_demo.jsonl",
                  "--speed", "10", "--no-convex"], env)
    try:
        client = await connect_retry(f"ws://127.0.0.1:{port}", component="cli", subscribe=["pickup", "transcript"])
        assert isinstance(client.snapshot, Snapshot)
        pickups = await collect_pickups(client, 3, timeout=20)
        assert pickups == [("salt", 2), ("sugar", 3), ("sugar", 1)]
        await client.close()
    finally:
        out, err = stop(proc)
    assert proc.returncode == 0, err
    log_lines = (tmp_path / "logs" / "hub.jsonl").read_text().splitlines()
    assert all(json.loads(line)["msg"] for line in log_lines)
    assert any(json.loads(line)["msg"] == "pickup" for line in log_lines)


async def test_sim_send_and_tail_against_a_running_hub(tmp_path):
    port = free_port()
    env = hub_env(tmp_path, port)
    hub = start(["earmark-hub", "--adapters", "simulator", "--no-convex"], env)
    tail = None
    try:
        client = await connect_retry(f"ws://127.0.0.1:{port}", component="cli",
                                     subscribe=["pickup", "transcript", "reset", "snapshot"])
        tail = start(["earmark-tail", "--types", "pickup,transcript"], env)
        await asyncio.sleep(1.0)
        sim = start(["earmark-sim", "scenarios/normal_pickup.jsonl", "--speed", "10"], env)
        assert await collect_pickups(client, 1, timeout=15) == [("sugar", 3)]
        assert (await asyncio.to_thread(sim.wait, 15)) == 0

        sent = subprocess.run([str(BIN / "earmark-send"), "transcript", "--text", "where's the sugar"], env=env,
                              capture_output=True, text=True, timeout=10)
        assert sent.returncode == 0, sent.stderr
        async with asyncio.timeout(5):
            while (msg := await client.recv()).type != "transcript":
                pass
        assert msg.text == "where's the sugar" and msg.source == "typed" and msg.is_final

        reset = subprocess.run([str(BIN / "earmark-send"), "reset"], env=env, capture_output=True, text=True,
                               timeout=10)
        assert reset.returncode == 0, reset.stderr
        types = []
        async with asyncio.timeout(5):
            while "snapshot" not in types:
                types.append((await client.recv()).type)
        assert types[-2:] == ["reset", "snapshot"]
        await client.close()
    finally:
        tail_out, _ = stop(tail) if tail else ("", "")
        hub_out, hub_err = stop(hub)
    assert hub.returncode == 0, hub_err
    assert "pickup" in tail_out and "sugar from spot 3" in tail_out and "where's the sugar" in tail_out


def test_earmark_send_reports_unreachable_hub(tmp_path):
    env = hub_env(tmp_path, free_port())
    r = subprocess.run([str(BIN / "earmark-send"), "reset"], env=env, capture_output=True, text=True, timeout=10)
    assert r.returncode == 1 and "cannot reach the hub" in r.stderr


def test_build_message_fields():
    msg = build_message("transcript", ["--text", "where's the sugar"])
    assert (msg.type, msg.text, msg.is_final, msg.source) == ("transcript", "where's the sugar", True, "typed")
    msg = build_message("label", ["--tag", "04A1B2C3D4E5FF", "--name", "honey", "--spot", "1"])
    assert msg.spot == 1 and msg.aliases == []
    msg = build_message("chirp", ["--fob-id=fob_keys", "--action", "stop"])
    assert (msg.fob_id, msg.action) == ("fob_keys", "stop")
    msg = build_message("pickup", [], '{"object_id": "salt", "from_spot": 2}')
    assert summarize(msg).split()[1:] == ["pickup", "salt", "from", "spot", "2"]
    with pytest.raises(ValueError):
        build_message("pickup", ["--object_id", "salt"])
    with pytest.raises(ValueError):
        build_message("teleport", [])
