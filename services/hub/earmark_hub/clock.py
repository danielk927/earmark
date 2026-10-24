"""Injectable clocks. Everything that stamps or times detection events uses one of these."""
from __future__ import annotations

import asyncio
import time
from typing import Protocol


class Clock(Protocol):
    def now(self) -> float: ...

    async def sleep(self, seconds: float) -> None: ...


class SystemClock:
    """Wall-clock unix seconds."""

    def now(self) -> float:
        return time.time()

    async def sleep(self, seconds: float) -> None:
        await asyncio.sleep(max(0.0, seconds))


class ScaledClock:
    """Unix seconds that advance `speed` times faster than the wall clock (for --speed).

    Starts at the current wall time, so timestamps stay unix seconds, but they run
    ahead of the wall clock while speed > 1. Debounce windows are measured in this
    time, so a sped-up scenario behaves exactly like the real-time one.
    """

    def __init__(self, speed: float) -> None:
        if speed <= 0:
            raise ValueError("speed must be > 0")
        self.speed = speed
        self._t0 = time.time()
        self._m0 = time.monotonic()

    def now(self) -> float:
        return self._t0 + (time.monotonic() - self._m0) * self.speed

    async def sleep(self, seconds: float) -> None:
        await asyncio.sleep(max(0.0, seconds) / self.speed)


class VirtualClock:
    """Test clock: sleeping advances time instantly. Meant for a single sleeping task."""

    def __init__(self, start: float = 1_761_350_400.0) -> None:
        self._t = start

    def now(self) -> float:
        return self._t

    def advance(self, seconds: float) -> None:
        self._t += max(0.0, seconds)

    async def sleep(self, seconds: float) -> None:
        self.advance(seconds)
        await asyncio.sleep(0)
