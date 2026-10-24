"""The real concierge process against an in-test bus: hello -> snapshot, --text, guide_start + speech, reconnect."""
import asyncio
import json
import os
import socket
import sys

from websockets.asyncio.client import connect
from websockets.asyncio.server import serve

from conftest import SPOT_POS, snapshot
from earmark_contracts import Hello, StatusMsg, dump
from fakes import FakeBus, wait_until

BLANK = ["CARTESIA_API_KEY", "CARTESIA_VOICE_ID", "MOSS_PROJECT_ID", "MOSS_PROJECT_KEY", "BITDEER_API_KEY"]


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


async def mac_app(url: str, inbox: list[dict], stop: asyncio.Event) -> None:
    """A fake Mac app: subscribes to everything and announces itself every 100 ms."""
    async with connect(url, proxy=None) as ws:
        await ws.send(dump(Hello(component="mac_app", subscribe=["*"])))

        async def announce():
            while not stop.is_set():
                await ws.send(dump(StatusMsg(component="mac_app", ok=True, detail="fake")))
                await asyncio.sleep(0.1)

        task = asyncio.create_task(announce())
        try:
            async for raw in ws:
                inbox.append(json.loads(raw))
                if stop.is_set():
                    break
        finally:
            task.cancel()


async def test_concierge_process_over_the_bus(tmp_path):
    port = free_port()
    url = f"ws://127.0.0.1:{port}"
    env = {**os.environ, "EARMARK_BUS_URL": url, "CONCIERGE_SAY_CMD": "true",
           "CONCIERGE_LATENCY_LOG": str(tmp_path / "latency.jsonl"), "CONCIERGE_STATUS_INTERVAL_S": "0.5",
           **{k: "" for k in BLANK}}
    proc = await asyncio.create_subprocess_exec(
        sys.executable, "-m", "earmark_concierge", "--text", "Where's the sugar?", env=env,
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT)
    bus = FakeBus(snapshot())
    stop = asyncio.Event()
    inbox: list[dict] = []
    try:
        await asyncio.sleep(0.8)  # the concierge is already retrying: exercises reconnect
        server = await serve(bus.handler, "127.0.0.1", port)
        app = asyncio.create_task(mac_app(url, inbox, stop))
        def types():
            return [m["type"] for m in inbox]

        assert await wait_until(lambda: "guide_start" in types() and "speak_text" in types(), timeout=15), types()
        [g] = [m for m in inbox if m["type"] == "guide_start"]
        assert g["object_id"] == "sugar" and g["target_position"] == SPOT_POS[3]
        [sp] = [m for m in inbox if m["type"] == "speak_text"]
        assert sp["text"] == "The sugar is at your one o'clock, about an arm's length away."
        assert sp["utterance_id"] == g["utterance_id"]
        assert any(m["type"] == "transcript" and m["source"] == "typed" for m in inbox)
        assert any(m["type"] == "stt_mode" and m["engine"] == "apple" for m in inbox)
        statuses = [m for m in inbox if m["type"] == "status" and m["component"] == "concierge"]
        assert statuses and statuses[-1]["info"]["mac_app"] is True
        hello = [c for c, _ in bus.clients.values()]
        assert "concierge" in hello
        # the hub restarts: the concierge reconnects and says hello again
        stop.set()
        server.close()
        await server.wait_closed()
        bus.clients.clear()
        server = await serve(bus.handler, "127.0.0.1", port)
        assert await wait_until(lambda: "concierge" in [c for c, _ in bus.clients.values()], timeout=10)
        server.close()
        app.cancel()
    finally:
        proc.terminate()
        out, _ = await proc.communicate()
        log = out.decode()
    assert "Traceback" not in log, log
    assert "sk_" not in log
