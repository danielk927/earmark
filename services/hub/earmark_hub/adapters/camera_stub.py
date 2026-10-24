"""Camera adapter: interface only.

A future vision adapter would run a detector (e.g. on a ceiling camera calibrated to the
listener's coordinate frame) and emit one DetectionEvent per tracked object, already
debounced by its own tracker:

    DetectionEvent(source="camera", tag="<object or marker id>", kind="placed",
                   where={"position": [x, y, z]},   # meters, +x right, +y forward, +z up
                   precision="exact", rssi=None, t=clock.now())

- `tag` must match a registry `tag` (e.g. an AprilTag id stored as the object's tag).
- Use `kind="seen"` for continuous position updates, `kind="lost"` with `where=None`
  when the track ends, and `precision="area"` with `where={"area": ...}` when only the
  zone is known.
- Map pixel coordinates to Earmark coordinates in the adapter; nothing downstream of
  the hub may know a camera was involved.
The state engine already turns position/area events into `roaming` state with the
resolved position, so a vision adapter needs no hub changes.
"""
from __future__ import annotations

import logging
from typing import AsyncIterator

from earmark_contracts import DetectionEvent

from .base import Adapter

log = logging.getLogger("earmark.hub.camera")


class CameraStubAdapter(Adapter):
    name = "camera_stub"

    async def events(self) -> AsyncIterator[DetectionEvent]:
        log.info("camera_stub enabled: it emits no events")
        self.ctx.adapter_status(self.name, True, "stub (no events)")
        return
        yield  # pragma: no cover
