"""In-test WebSocket servers: fake Cartesia Ink (turns), fake Sonic TTS, and a minimal hub bus."""
from __future__ import annotations

import asyncio
import base64
import json

from websockets.asyncio.server import serve
from websockets.exceptions import ConnectionClosed

from earmark_contracts import dump, parse_bus


class FakeServer:
    async def start(self):
        self.server = await serve(self.handler, "127.0.0.1", 0)
        self.port = self.server.sockets[0].getsockname()[1]
        return self

    async def stop(self):
        self.server.close()
        await self.server.wait_closed()

    @property
    def url(self) -> str:
        return f"ws://127.0.0.1:{self.port}"


class FakeInk(FakeServer):
    """mode: good (connected + turns), silent (never sends connected), mute (connected, no turns), error."""

    def __init__(self, mode="good", final="Where's the sugar?", end_after_bytes=6400):
        self.mode = mode
        self.final = final
        self.end_after_bytes = end_after_bytes
        self.connections = 0
        self.audio_bytes = 0
        self.got_close = 0
        self.paths: list[str] = []
        self.auth: list[str] = []

    async def handler(self, ws):
        self.connections += 1
        self.paths.append(ws.request.path)
        self.auth.append(ws.request.headers.get("Authorization", ""))
        mode = self.mode
        if mode != "silent":
            await ws.send(json.dumps({"type": "connected", "request_id": "r1"}))
        if mode == "error":
            await ws.send(json.dumps({"type": "error", "status_code": 429, "error_code": "concurrency_limited",
                                      "title": "Too many", "message": "x", "done": True}))
            return
        got, started, ended = 0, False, False
        try:
            async for msg in ws:
                if isinstance(msg, bytes):
                    got += len(msg)
                    self.audio_bytes += len(msg)
                    if mode == "good" and not started:
                        started = True
                        await ws.send(json.dumps({"type": "turn.start", "request_id": "r1"}))
                        await ws.send(json.dumps({"type": "turn.update", "transcript": "Where's", "request_id": "r1"}))
                    if mode == "good" and not ended and got >= self.end_after_bytes:
                        ended = True
                        await ws.send(json.dumps({"type": "turn.eager_end", "transcript": self.final}))
                        await ws.send(json.dumps({"type": "turn.end", "transcript": self.final}))
                elif json.loads(msg).get("type") == "close":
                    self.got_close += 1
                    return
        except Exception:
            return


class FakeSonic(FakeServer):
    """mode: good (3 chunks then done), error (error event), slow (no reply), drop (close at once)."""

    def __init__(self, mode="good"):
        self.mode = mode
        self.requests: list[dict] = []
        self.auth: list[str] = []
        self.open: set = set()

    async def handler(self, ws):
        self.auth.append(ws.request.headers.get("Authorization", ""))
        if self.mode == "drop":
            return
        self.open.add(ws)
        try:
            await self._serve(ws)
        except ConnectionClosed:
            pass
        finally:
            self.open.discard(ws)

    async def close_idle(self):
        """What Cartesia does to a TTS socket after 5 idle minutes."""
        for ws in list(self.open):
            await ws.close(1000, "idle")

    async def _serve(self, ws):
        async for msg in ws:
            req = json.loads(msg)
            if req.get("cancel"):
                continue
            self.requests.append(req)
            ctx = req["context_id"]
            if self.mode == "error":
                await ws.send(json.dumps({"type": "error", "done": True, "status_code": 400,
                                          "error_code": "voice_not_found", "context_id": ctx}))
            elif self.mode == "good":
                for i in range(3):
                    data = base64.b64encode(bytes([i]) * 8).decode()
                    await ws.send(json.dumps({"type": "chunk", "data": data, "done": False,
                                              "status_code": 206, "context_id": ctx}))
                await ws.send(json.dumps({"type": "done", "done": True, "status_code": 200, "context_id": ctx}))


class FakeBus(FakeServer):
    """Implements just hello -> snapshot and subscribe-filtered broadcast (contracts/README.md)."""

    def __init__(self, snapshot):
        self.snapshot = snapshot
        self.clients: dict = {}
        self.received: list[dict] = []

    async def handler(self, ws):
        sub = None
        try:
            async for raw in ws:
                msg = parse_bus(raw)
                if msg.type == "hello":
                    sub = msg.subscribe
                    self.clients[ws] = (msg.component, sub)
                    await ws.send(dump(self.snapshot))
                    continue
                self.received.append(json.loads(raw))
                for other, (_, osub) in list(self.clients.items()):
                    if other is ws:
                        continue
                    if osub is None and msg.type in ("mic_audio", "speak"):
                        continue
                    if osub is not None and "*" not in osub and msg.type not in osub:
                        continue
                    try:
                        await other.send(raw)
                    except Exception:
                        pass
        except ConnectionClosed:
            pass
        finally:
            self.clients.pop(ws, None)


async def wait_until(pred, timeout=5.0, step=0.02):
    loop = asyncio.get_running_loop()
    end = loop.time() + timeout
    while loop.time() < end:
        if pred():
            return True
        await asyncio.sleep(step)
    return pred()
