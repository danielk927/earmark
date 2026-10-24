"""Minimal bus client used by the CLIs, scripts/trial.py, and tests."""
from __future__ import annotations

import asyncio

from earmark_contracts import Hello, Snapshot, dump, parse_bus
from websockets.asyncio.client import ClientConnection, connect

from .bus import MAX_FRAME
from .config import bus_url


class BusClient:
    def __init__(self, ws: ClientConnection, snapshot: Snapshot) -> None:
        self.ws = ws
        self.snapshot = snapshot

    @classmethod
    async def connect(cls, component: str, subscribe: list[str] | None = None, url: str | None = None,
                      timeout: float = 3.0) -> "BusClient":
        ws = await connect(url or bus_url(), open_timeout=timeout, max_size=MAX_FRAME)
        try:
            await ws.send(dump(Hello(component=component, **({"subscribe": subscribe} if subscribe is not None else {}))))
            async with asyncio.timeout(timeout):
                while True:
                    msg = parse_bus(await ws.recv())
                    if isinstance(msg, Snapshot):
                        return cls(ws, msg)
        except BaseException:
            await ws.close()
            raise

    async def send(self, msg) -> None:
        await self.ws.send(dump(msg))

    async def recv(self):
        """Next valid bus message (invalid frames are skipped)."""
        while True:
            raw = await self.ws.recv()
            try:
                return parse_bus(raw)
            except ValueError:
                continue

    def __aiter__(self):
        return self

    async def __anext__(self):
        from websockets.exceptions import ConnectionClosed

        try:
            return await self.recv()
        except ConnectionClosed:
            raise StopAsyncIteration from None

    async def close(self) -> None:
        await self.ws.close()
