"""Adapter interface. An adapter turns one detection method into DetectionEvents."""
from __future__ import annotations

from typing import AsyncIterator, Protocol

from earmark_contracts import DetectionEvent, RegistryObject

from ..space import SpaceIndex


class HubContext(Protocol):
    """What the hub offers adapters."""

    space: SpaceIndex

    def objects(self) -> list[RegistryObject]: ...

    async def publish(self, msg, origin: str) -> None:
        """Publish a non-detection bus message as if a client of component `origin` sent it."""

    def adapter_status(self, adapter: str, ok: bool, detail: str) -> None:
        """Report an adapter health change (shown in the hub's `status`)."""


class Adapter:
    """Base class. Subclasses implement `events()`; the hooks are optional."""

    name: str = "adapter"

    def attach(self, ctx: HubContext) -> None:
        self.ctx = ctx

    async def events(self) -> AsyncIterator[DetectionEvent]:
        raise NotImplementedError
        yield  # pragma: no cover

    async def on_reset(self) -> None:
        """Called when the bus receives `reset`."""

    async def close(self) -> None:
        """Release hardware on shutdown."""

