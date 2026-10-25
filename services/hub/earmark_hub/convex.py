"""Convex sync over the HTTP actions in contracts/schemas/convex_http.schema.json.

- POST /ingest: batches of hub_events (durable, in order, idempotent by event_id) plus
  the latest ObjectState per object.
- POST /api/label: voice labels, in queue order with the events.
- GET /api/registry: polled; a new `version` replaces the local registry.
Every request carries X-Earmark-Secret and a timeout. Failures back off exponentially;
the queue lives on disk (var/hub/queue.jsonl) so nothing is lost while offline or across
restarts. The secret is never logged.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import uuid
from pathlib import Path
from typing import Awaitable, Callable

import httpx
from earmark_contracts import (
    HubEvent,
    IngestRequest,
    IngestResponse,
    LabelRequest,
    LabelResponse,
    ObjectState,
    Registry,
    to_dict,
)
from pydantic import ValidationError

from .config import ConvexCfg, ConvexEnv

log = logging.getLogger("earmark.hub.convex")

RETRYABLE = {401, 403, 404, 408, 409, 425, 429}


class ConvexHttpError(Exception):
    def __init__(self, status: int, body: str) -> None:
        super().__init__(f"HTTP {status}: {body[:200]}")
        self.status = status
        self.retryable = status >= 500 or status in RETRYABLE


class ConvexClient:
    def __init__(self, env: ConvexEnv, timeout_s: float = 3.0, transport: httpx.AsyncBaseTransport | None = None) -> None:
        self._http = httpx.AsyncClient(base_url=env.site_url, timeout=timeout_s, transport=transport,
                                       headers={"X-Earmark-Secret": env.secret})

    async def _request(self, method: str, path: str, body: dict | None = None) -> dict:
        r = await self._http.request(method, path, json=body)
        if r.status_code >= 400:
            raise ConvexHttpError(r.status_code, r.text)
        return r.json()

    async def ingest(self, req: IngestRequest) -> IngestResponse:
        return IngestResponse.model_validate(await self._request("POST", "/ingest", to_dict(req)))

    async def label(self, req: LabelRequest) -> LabelResponse:
        return LabelResponse.model_validate(await self._request("POST", "/api/label", to_dict(req)))

    async def registry(self) -> Registry:
        return Registry.model_validate(await self._request("GET", "/api/registry"))

    async def aclose(self) -> None:
        await self._http.aclose()


class DurableQueue:
    """Append-only JSON lines on disk; acknowledged items are removed by an atomic rewrite."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.items: list[dict] = []
        if path.is_file():
            for n, line in enumerate(path.read_text().splitlines(), 1):
                if not line.strip():
                    continue
                try:
                    self.items.append(json.loads(line))
                except json.JSONDecodeError:
                    log.error("skipping corrupt queue line", extra={"path": str(path), "line_no": n})
            if self.items:
                log.info("offline queue loaded", extra={"depth": len(self.items)})

    def __len__(self) -> int:
        return len(self.items)

    def append(self, item: dict) -> None:
        self.items.append(item)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a") as f:
            f.write(json.dumps(item, separators=(",", ":")) + "\n")
            f.flush()
            os.fsync(f.fileno())

    def drop_front(self, n: int) -> None:
        if n <= 0:
            return
        self.items = self.items[n:]
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text("".join(json.dumps(i, separators=(",", ":")) + "\n" for i in self.items))
        os.replace(tmp, self.path)


class ConvexSync:
    def __init__(self, client: ConvexClient, queue_path: Path, cfg: ConvexCfg) -> None:
        self.client, self.cfg = client, cfg
        self.queue = DurableQueue(queue_path)
        self._states: dict[str, ObjectState] = {}
        self._wake = asyncio.Event()
        self.reachable: bool | None = None
        self._last_poll_error = ""

    # ------------------------------------------------------------ producers

    def add_event(self, kind: str, object_id: str | None, t: float, data: dict) -> HubEvent:
        ev = HubEvent(event_id=str(uuid.uuid4()), kind=kind, object_id=object_id, t=t, data=data)
        self.queue.append({"kind": "event", "body": ev.model_dump(mode="json")})
        self._wake.set()
        return ev

    def add_state(self, state: ObjectState) -> None:
        self._states[state.object_id] = state
        self._wake.set()

    def add_label(self, req: LabelRequest) -> None:
        self.queue.append({"kind": "label", "body": to_dict(req)})
        self._wake.set()

    def pending_labels(self) -> list[LabelRequest]:
        return [LabelRequest.model_validate(i["body"]) for i in self.queue.items if i["kind"] == "label"]

    @property
    def depth(self) -> int:
        return len(self.queue)

    # ------------------------------------------------------------ flushing

    def _set_reachable(self, ok: bool, error: str = "") -> None:
        if ok != self.reachable:
            self.reachable = ok
            if ok:
                log.info("convex reachable", extra={"queue_depth": self.depth})
            else:
                log.warning("convex unreachable; queueing", extra={"error": error[:300], "queue_depth": self.depth})

    async def flush_once(self) -> bool:
        """Send the next unit (one label, or a batch of events plus latest states). False if idle."""
        items = self.queue.items
        if items and items[0]["kind"] == "label":
            req = LabelRequest.model_validate(items[0]["body"])
            try:
                resp = await self.client.label(req)
                log.info("label synced", extra={"object_id": resp.object_id, "created": resp.created})
            except ConvexHttpError as e:
                if e.retryable:
                    raise
                log.error("label rejected by convex; dropped", extra={"error": str(e), "label": items[0]["body"]})
            self.queue.drop_front(1)
            return True
        events = []
        for item in items:
            if item["kind"] != "event" or len(events) >= self.cfg.batch_max:
                break
            events.append(HubEvent.model_validate(item["body"]))
        states = list(self._states.values())
        if not events and not states:
            return False
        try:
            resp = await self.client.ingest(IngestRequest(events=events, states=states))
            log.debug("ingested", extra={"accepted_events": resp.accepted_events,
                                         "duplicate_events": resp.duplicate_events,
                                         "accepted_states": resp.accepted_states})
        except ConvexHttpError as e:
            if e.retryable:
                raise
            log.error("ingest batch rejected by convex; dropped", extra={
                "error": str(e), "events": [ev.model_dump(mode="json") for ev in events]})
        self.queue.drop_front(len(events))
        for s in states:
            if self._states.get(s.object_id) is s:
                del self._states[s.object_id]
        return True

    async def run(self) -> None:
        backoff = self.cfg.backoff_initial_s
        while True:
            try:
                await asyncio.wait_for(self._wake.wait(), timeout=self.cfg.flush_interval_s)
            except (asyncio.TimeoutError, TimeoutError):
                pass
            self._wake.clear()
            while True:
                try:
                    sent = await self.flush_once()
                except (httpx.HTTPError, ConvexHttpError, ValidationError, ValueError) as e:
                    self._set_reachable(False, f"{type(e).__name__}: {e}")
                    await asyncio.sleep(backoff)
                    backoff = min(backoff * 2, self.cfg.backoff_max_s)
                    continue
                if sent:
                    self._set_reachable(True)
                    backoff = self.cfg.backoff_initial_s
                else:
                    break

    async def poll_registry(self, on_registry: Callable[[Registry], Awaitable[None]]) -> None:
        while True:
            try:
                reg = await self.client.registry()
                self._set_reachable(True)
                self._last_poll_error = ""
                await on_registry(reg)
            except (httpx.HTTPError, ConvexHttpError) as e:
                self._set_reachable(False, f"{type(e).__name__}: {e}")
            except (ValidationError, ValueError) as e:  # ValueError: a 200 that is not JSON (wrong Convex URL)
                msg = str(e)[:300]
                if msg != self._last_poll_error:
                    log.error("GET /api/registry returned an invalid registry", extra={"error": msg})
                    self._last_poll_error = msg
            await asyncio.sleep(self.cfg.registry_poll_s)
