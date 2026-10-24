"""WebSocket client for the hub bus with auto-reconnect (contracts/README.md "Bus rules")."""
from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable

from pydantic import BaseModel, ValidationError
from websockets.asyncio.client import ClientConnection, connect
from websockets.exceptions import ConnectionClosed

from earmark_contracts import Hello, dump, parse_bus

log = logging.getLogger(__name__)

SUBSCRIBE = [
    "snapshot", "registry_update", "state_update", "unknown_tag", "pickup", "mic_audio", "transcript",
    "trial_start", "trial_end", "guide_feedback", "playback", "status", "head_pose", "reset",
]


class BusClient:
    def __init__(self, url: str, on_message: Callable[[object], Awaitable[None]],
                 on_connect: Callable[[], Awaitable[None]] | None = None) -> None:
        self.url = url
        self.on_message = on_message
        self.on_connect = on_connect
        self._ws: ClientConnection | None = None

    @property
    def connected(self) -> bool:
        return self._ws is not None

    async def send(self, msg: BaseModel) -> bool:
        ws = self._ws
        if ws is None:
            log.debug("bus down, dropped %s", getattr(msg, "type", "?"))
            return False
        try:
            await ws.send(dump(msg))
            return True
        except ConnectionClosed:
            return False

    async def run_forever(self) -> None:
        delay = 0.5
        while True:
            try:
                async with connect(self.url, proxy=None, open_timeout=5, max_size=None) as ws:
                    await ws.send(dump(Hello(component="concierge", subscribe=SUBSCRIBE)))
                    self._ws = ws
                    delay = 0.5
                    log.info("bus connected %s", self.url)
                    if self.on_connect:
                        await self.on_connect()
                    async for raw in ws:
                        try:
                            msg = parse_bus(raw)
                        except ValidationError as e:
                            log.warning("dropped invalid bus message: %s", e.errors()[:1])
                            continue
                        try:
                            await self.on_message(msg)
                        except Exception:
                            log.exception("handler failed for %s", getattr(msg, "type", "?"))
            except (OSError, ConnectionClosed, asyncio.TimeoutError) as e:
                log.info("bus unavailable (%s); retrying in %.1f s", type(e).__name__, delay)
            finally:
                self._ws = None
            await asyncio.sleep(delay)
            delay = min(delay * 2, 5.0)
