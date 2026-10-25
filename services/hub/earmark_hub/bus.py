"""Local WebSocket bus server (ws://127.0.0.1:8765).

Every inbound frame is validated with parse_bus; invalid frames are dropped and reported
with a hub `status`. Each client has a bounded send queue drained by its own writer
task, so a slow client never blocks the others; when a queue is full the oldest audio
(mic_audio, speak) is dropped first, then the oldest message.
"""
from __future__ import annotations

import asyncio
import collections
import itertools
import logging
import time
from typing import Awaitable, Callable

from earmark_contracts import Hello, StatusMsg, dump, parse_bus
from pydantic import ValidationError
from websockets.asyncio.server import ServerConnection, serve
from websockets.exceptions import ConnectionClosed

log = logging.getLogger("earmark.hub.bus")

AUDIO_TYPES = frozenset({"mic_audio", "speak"})
MAX_FRAME = 4 * 2**20


class SendQueue:
    def __init__(self, maxsize: int) -> None:
        self.maxsize = maxsize
        self._items: collections.deque[tuple[str, str]] = collections.deque()
        self._ready = asyncio.Event()
        self.dropped = 0

    def __len__(self) -> int:
        return len(self._items)

    def put(self, msg_type: str, text: str) -> None:
        if len(self._items) >= self.maxsize:
            idx = next((i for i, (t, _) in enumerate(self._items) if t in AUDIO_TYPES), 0)
            del self._items[idx]
            self.dropped += 1
        self._items.append((msg_type, text))
        self._ready.set()

    async def get(self) -> str:
        while not self._items:
            self._ready.clear()
            await self._ready.wait()
        return self._items.popleft()[1]


class Client:
    _ids = itertools.count(1)

    def __init__(self, ws: ServerConnection | None, queue_max: int) -> None:
        self.id = next(self._ids)
        self.ws = ws
        self.component: str | None = None
        self.subscribe: frozenset[str] | None = None  # None = default (all but audio)
        self.hello = False
        self.queue = SendQueue(queue_max)
        self._last_error_status = 0.0

    @property
    def label(self) -> str:
        return f"{self.component or 'client'}#{self.id}"

    def wants(self, msg_type: str) -> bool:
        if self.subscribe is None:
            return msg_type not in AUDIO_TYPES
        return "*" in self.subscribe or msg_type in self.subscribe


OnMessage = Callable[[Client, object], Awaitable[None]]
OnHello = Callable[[Client], Awaitable[None]]


class BusServer:
    def __init__(self, host: str, port: int, *, on_message: OnMessage, on_hello: OnHello,
                 queue_max: int = 1000) -> None:
        self.host, self._port = host, port
        self.on_message, self.on_hello = on_message, on_hello
        self.queue_max = queue_max
        self.clients: set[Client] = set()
        self._server = None

    @property
    def port(self) -> int:
        if self._server is not None and self._server.sockets:
            return self._server.sockets[0].getsockname()[1]
        return self._port

    async def start(self) -> None:
        self._server = await serve(self._handle, self.host, self._port, max_size=MAX_FRAME)
        log.info("bus listening", extra={"url": f"ws://{self.host}:{self.port}"})

    async def stop(self) -> None:
        if self._server is not None:
            self._server.close()
            await self._server.wait_closed()

    # ------------------------------------------------------------ sending

    def broadcast(self, msg, exclude: Client | None = None) -> None:
        text = None
        for c in list(self.clients):
            if c is exclude or not c.wants(msg.type):
                continue
            text = text or dump(msg)
            c.queue.put(msg.type, text)

    def send_to(self, client: Client, msg) -> None:
        client.queue.put(msg.type, dump(msg))

    # ------------------------------------------------------------ connections

    async def _handle(self, ws: ServerConnection) -> None:
        client = Client(ws, self.queue_max)
        self.clients.add(client)
        writer = asyncio.create_task(self._writer(client))
        log.info("client connected", extra={"client": client.label, "remote": str(ws.remote_address)})
        try:
            async for raw in ws:
                await self._receive(client, raw)
        except ConnectionClosed:
            pass
        finally:
            self.clients.discard(client)
            writer.cancel()
            log.info("client disconnected", extra={"client": client.label, "dropped": client.queue.dropped})

    async def _writer(self, client: Client) -> None:
        try:
            while True:
                await client.ws.send(await client.queue.get())
        except (ConnectionClosed, asyncio.CancelledError):
            pass

    async def _receive(self, client: Client, raw: str | bytes) -> None:
        try:
            msg = parse_bus(raw)
        except (ValidationError, ValueError) as e:
            self._reject(client, e)
            return
        if isinstance(msg, Hello):
            client.component, client.hello = msg.component, True
            client.subscribe = frozenset(msg.subscribe) if msg.subscribe is not None else None
            log.info("hello", extra={"client": client.label,
                                     "subscribe": sorted(client.subscribe) if client.subscribe is not None else None})
            await self.on_hello(client)
            return
        if not client.hello:
            log.warning("message before hello; using default subscriptions", extra={"client": client.label,
                                                                                    "msg_type": msg.type})
            client.hello = True
        try:
            await self.on_message(client, msg)
        except Exception:
            log.exception("error handling bus message", extra={"client": client.label, "msg_type": msg.type})

    def _reject(self, client: Client, err: Exception) -> None:
        if isinstance(err, ValidationError):
            first = err.errors()[0] if err.errors() else {}
            detail = f"{'.'.join(str(p) for p in first.get('loc', ()))}: {first.get('msg', str(err))}"
        else:
            detail = str(err)
        detail = f"invalid message from {client.label} dropped: {detail}"[:300]
        log.warning("invalid bus message", extra={"client": client.label, "error": detail})
        now = time.time()
        if now - client._last_error_status >= 1.0:  # at most one status per client per second
            client._last_error_status = now
            self.broadcast(StatusMsg(component="hub", ok=False, detail=detail, t=now))
