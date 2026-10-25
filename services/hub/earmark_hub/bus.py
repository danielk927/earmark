"""Local WebSocket bus server (ws://127.0.0.1:8765).

Every inbound frame is validated with parse_bus; invalid frames are dropped and reported
with a hub `status`. Each client has a bounded send queue drained by its own writer
task, so a slow client never blocks the others; when a queue is full the oldest audio
(mic_audio, speak) is dropped first, then the oldest message.

Auth: loopback clients are trusted. Any other client (the iPhones, once the bus binds
0.0.0.0) receives nothing and may send nothing until its `hello` carries
`secret == bus.secret` (EARMARK_BUS_SECRET); otherwise it gets `status ok:false` and is
closed. With no secret configured, every non-loopback client is refused. Secrets are
never logged.
"""
from __future__ import annotations

import asyncio
import collections
import hmac
import ipaddress
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


def is_loopback(host: str | None) -> bool:
    """True for 127.0.0.0/8, ::1 and IPv4-mapped loopback. None (no socket: in-process tests) counts as loopback."""
    if host is None:
        return True
    try:
        ip = ipaddress.ip_address(host.split("%")[0])
    except ValueError:
        return host == "localhost"
    if ip.version == 6 and ip.ipv4_mapped is not None:
        ip = ip.ipv4_mapped
    return ip.is_loopback


def auth_error(host: str | None, sent: str | None, secret: str | None) -> str | None:
    """Why a client at `host` whose hello carried `sent` must be refused, or None if it may stay."""
    if is_loopback(host):
        return None
    if not secret:
        return ("the hub has no bus secret (set EARMARK_BUS_SECRET), so only localhost clients are allowed; "
                f"refusing {host}")
    if not sent or not hmac.compare_digest(sent.encode(), secret.encode()):
        return "wrong or missing bus secret in hello"
    return None


class Client:
    _ids = itertools.count(1)

    def __init__(self, ws: ServerConnection | None, queue_max: int) -> None:
        self.id = next(self._ids)
        self.ws = ws
        remote = getattr(ws, "remote_address", None) if ws is not None else None
        self.remote_host: str | None = str(remote[0]) if remote else None
        self.authorized = is_loopback(self.remote_host)  # non-loopback clients only after a valid hello
        self.device_id: str | None = None  # from hello; addressed delivery (uwb_token)
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
                 on_change: Callable[[], None] | None = None, queue_max: int = 1000,
                 secret: str | None = None) -> None:
        self.host, self._port = host, port
        self.secret = secret
        self.on_message, self.on_hello = on_message, on_hello
        self.on_change = on_change or (lambda: None)
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
        if not is_loopback(self.host) and not self.secret:
            log.warning("bus is reachable from the network but EARMARK_BUS_SECRET is not set; "
                        "non-localhost clients (iPhones) will be refused", extra={"host": self.host})

    async def stop(self) -> None:
        if self._server is not None:
            self._server.close()
            await self._server.wait_closed()

    # ------------------------------------------------------------ sending

    def broadcast(self, msg, exclude: Client | None = None) -> None:
        text = None
        for c in list(self.clients):
            if c is exclude or not c.authorized or not c.wants(msg.type):
                continue
            text = text or dump(msg)
            c.queue.put(msg.type, text)

    def send_to(self, client: Client, msg) -> None:
        client.queue.put(msg.type, dump(msg))

    def send_to_device(self, device_id: str, msg) -> int:
        """Send to every authorized client whose hello.device_id is `device_id` (ignores subscriptions).
        Returns how many got it."""
        targets = [c for c in self.clients if c.authorized and c.device_id == device_id]
        for c in targets:
            self.send_to(c, msg)
        return len(targets)

    # ------------------------------------------------------------ connections

    async def _handle(self, ws: ServerConnection) -> None:
        client = Client(ws, self.queue_max)
        self.clients.add(client)
        writer = asyncio.create_task(self._writer(client))
        log.info("client connected", extra={"client": client.label, "remote": str(ws.remote_address)})
        self.on_change()
        try:
            async for raw in ws:
                await self._receive(client, raw)
        except ConnectionClosed:
            pass
        finally:
            self.clients.discard(client)
            writer.cancel()
            log.info("client disconnected", extra={"client": client.label, "dropped": client.queue.dropped})
            self.on_change()

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
            if not client.authorized:
                await self._refuse(client, "send a valid hello with the bus secret first")
                return
            self._reject(client, e)
            return
        if isinstance(msg, Hello):
            reason = auth_error(client.remote_host, msg.secret, self.secret)
            if reason:
                await self._refuse(client, reason)
                return
            client.component, client.hello, client.authorized = msg.component, True, True
            client.device_id = msg.device_id
            client.subscribe = frozenset(msg.subscribe) if msg.subscribe is not None else None
            log.info("hello", extra={"client": client.label, "device_id": msg.device_id, "role": msg.role,
                                     "subscribe": sorted(client.subscribe) if client.subscribe is not None else None})
            await self.on_hello(client)
            self.on_change()
            return
        if not client.authorized:
            await self._refuse(client, "send hello with the bus secret first")
            return
        if not client.hello:
            log.warning("message before hello; using default subscriptions", extra={"client": client.label,
                                                                                    "msg_type": msg.type})
            client.hello = True
        try:
            await self.on_message(client, msg)
        except Exception:
            log.exception("error handling bus message", extra={"client": client.label, "msg_type": msg.type})

    async def _refuse(self, client: Client, reason: str) -> None:
        """Tell the client why (status ok:false), then close it. Never logs the secret."""
        log.warning("client refused", extra={"client": client.label, "remote": client.remote_host, "reason": reason})
        client.authorized = False
        if client.ws is None:
            return
        try:
            await client.ws.send(dump(StatusMsg(component="hub", ok=False, detail=reason, t=time.time())))
            await client.ws.close(code=1008, reason="unauthorized")
        except ConnectionClosed:
            pass

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
