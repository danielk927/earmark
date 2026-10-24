"""The agent's tools: Convex read endpoints with argument handling, timing, logging, and LLM views.

`Toolbox` is shared by both answer paths. The typed methods (used by the keyword fallback) raise
`ConvexError`; `call_json` (used by the LLM loop) never raises and returns a compact, pre-formatted
view, or `{"ok": false, "error": ...}` the model can read.
"""

from __future__ import annotations

import json
import logging
import re
import time
from collections.abc import Awaitable
from dataclasses import dataclass, field
from datetime import date
from typing import Any, TypeVar

import earmark_contracts as ec

from .convex import ConvexError, ConvexReader
from .describe import SpaceLabels, cap, describe_location, dose_view, last_touched_phrase, where_phrase
from .household import HouseholdClock, resolve_date

log = logging.getLogger("earmark.memory.tools")
T = TypeVar("T")
HISTORY_VIEW_LIMIT = 30


class ToolArgError(ValueError):
    """The model (or router) passed an argument the tool can't use."""


@dataclass
class ToolCallRecord:
    name: str
    args: dict[str, Any]
    ok: bool
    ms: float
    error: str | None = None

    def short(self) -> str:
        args = ", ".join(f"{k}={v!r}" for k, v in self.args.items())
        return f"{self.name}({args}) {'ok' if self.ok else 'error'} {self.ms:.0f} ms"


TOOL_SPECS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "find_object",
            "description": "Look up a household object by name or alias (for example 'keys', 'sugar', 'pills') and get where it is now, when it was last seen, and when it was last picked up or put down.",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "The object's name or alias, without words like 'my' or 'his'."}
                },
                "required": ["name"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_objects",
            "description": "List every object Earmark tracks with its current location and when it was last picked up or put down. Use for questions about many objects, such as what hasn't been touched recently.",
            "parameters": {"type": "object", "properties": {}, "additionalProperties": False},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "history",
            "description": "Recent events for one object (pickups, put-downs, fob chirps), newest first. Needs the object_id from find_object or list_objects.",
            "parameters": {
                "type": "object",
                "properties": {
                    "object_id": {"type": "string"},
                    "since": {
                        "type": "string",
                        "description": "How far back: 'today', 'yesterday', a date YYYY-MM-DD, or a duration like '2d' or '12h'. Default: 7 days.",
                    },
                },
                "required": ["object_id"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "adherence",
            "description": "Medication doses for one household-local date: each scheduled time and whether it was taken, late, missed, or pending, computed by Earmark from pickups of the medication bottle.",
            "parameters": {
                "type": "object",
                "properties": {"date": {"type": "string", "description": "'today' (default), 'yesterday', or YYYY-MM-DD."}},
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "daily_summary",
            "description": "A day's summary: doses, number of pickups, objects not touched in 7 days, missing objects, and a summary sentence written by Earmark's code.",
            "parameters": {
                "type": "object",
                "properties": {"date": {"type": "string", "description": "'today' (default), 'yesterday', or YYYY-MM-DD."}},
                "additionalProperties": False,
            },
        },
    },
]
TOOL_NAMES = {spec["function"]["name"] for spec in TOOL_SPECS}


@dataclass
class Toolbox:
    reader: ConvexReader
    clock: HouseholdClock
    labels: SpaceLabels = field(default_factory=SpaceLabels)
    records: list[ToolCallRecord] = field(default_factory=list)

    # ------------------------------------------------------------ argument handling

    def resolve_date_arg(self, value: str | None) -> str | None:
        """None/'today' -> None (Convex defaults to today); 'yesterday', weekdays, dates -> YYYY-MM-DD."""
        if value is None or not str(value).strip() or str(value).strip().lower() == "today":
            return None
        d = resolve_date(str(value), self.clock.today)
        if d is None:
            raise ToolArgError(f"date must be 'today', 'yesterday', or YYYY-MM-DD, got {value!r}")
        return d.isoformat()

    def resolve_since_arg(self, value: str | float | None) -> float | None:
        if value is None or (isinstance(value, str) and not value.strip()):
            return None
        if isinstance(value, (int, float)):
            return float(value)
        text = value.strip().lower()
        m = re.fullmatch(r"(\d+(?:\.\d+)?)\s*(d|h|days?|hours?)", text)
        if m:
            hours = float(m.group(1)) * (24 if m.group(2).startswith("d") else 1)
            return self.clock.now_t - hours * 3600
        d = resolve_date(text, self.clock.today)
        if d is None:
            raise ToolArgError(f"since must be 'today', 'yesterday', YYYY-MM-DD, or like '2d'/'12h', got {value!r}")
        return self.clock.day_start_t(d)

    # ------------------------------------------------------------ typed calls (raise ConvexError)

    async def _run(self, name: str, args: dict[str, Any], coro: Awaitable[T]) -> T:
        started = time.perf_counter()
        try:
            result = await coro
        except ConvexError as exc:
            rec = ToolCallRecord(name, args, False, (time.perf_counter() - started) * 1000, str(exc))
            self.records.append(rec)
            log.info("tool %s: %s", rec.short(), exc)
            raise
        rec = ToolCallRecord(name, args, True, (time.perf_counter() - started) * 1000)
        self.records.append(rec)
        log.info("tool %s (via %s)", rec.short(), self.reader.source)
        return result

    async def find_object(self, name: str) -> ec.ObjectLookupResponse:
        return await self._run("find_object", {"name": name}, self.reader.find_object(name))

    async def list_objects(self) -> ec.ObjectsResponse:
        return await self._run("list_objects", {}, self.reader.list_objects())

    async def history(self, object_id: str, since: str | float | None = None) -> ec.HistoryResponse:
        since_t = self.resolve_since_arg(since)
        args = {"object_id": object_id} | ({"since": since} if since is not None else {})
        return await self._run("history", args, self.reader.history(object_id, since_t))

    async def adherence(self, date: str | None = None) -> ec.AdherenceResponse:
        resolved = self.resolve_date_arg(date)
        return await self._run("adherence", {"date": resolved or "today"}, self.reader.adherence(resolved))

    async def daily_summary(self, date: str | None = None) -> ec.DailySummaryResponse:
        resolved = self.resolve_date_arg(date)
        return await self._run("daily_summary", {"date": resolved or "today"}, self.reader.daily_summary(resolved))

    # ------------------------------------------------------------ LLM calls (never raise)

    async def call_json(self, name: str, arguments: str | None) -> dict[str, Any]:
        try:
            args = json.loads(arguments or "{}")
            if not isinstance(args, dict):
                raise ToolArgError("arguments must be a JSON object")
            if name not in TOOL_NAMES:
                raise ToolArgError(f"unknown tool {name!r}; available: {sorted(TOOL_NAMES)}")
            if name == "find_object":
                obj_name = str(args.get("name", "")).strip()
                if not obj_name:
                    raise ToolArgError("name is required")
                return self.lookup_view(await self.find_object(obj_name))
            if name == "list_objects":
                return self.objects_view(await self.list_objects())
            if name == "history":
                object_id = str(args.get("object_id", "")).strip()
                if not object_id:
                    raise ToolArgError("object_id is required")
                return self.history_view(await self.history(object_id, args.get("since")))
            if name == "adherence":
                return self.adherence_view(await self.adherence(args.get("date")))
            return self.summary_view(await self.daily_summary(args.get("date")))
        except json.JSONDecodeError:
            return {"ok": False, "error": "arguments were not valid JSON"}
        except ToolArgError as exc:
            self.records.append(ToolCallRecord(name, {"raw": arguments}, False, 0.0, str(exc)))
            log.info("tool %s rejected arguments: %s", name, exc)
            return {"ok": False, "error": str(exc)}
        except ConvexError as exc:
            return {"ok": False, "error": str(exc), "kind": exc.kind}

    # ------------------------------------------------------------ views for the LLM

    def object_view(self, o: ec.ObjectSummary) -> dict[str, Any]:
        return {
            "object_id": o.object_id,
            "name": o.name,
            "aliases": o.aliases,
            "is_medication": o.is_medication,
            "tracked_by": "bluetooth fob (proximity only, no pickups)" if o.fob_id and o.home_spot is None else "NFC spot",
            "status": o.state.status if o.state else "never detected",
            "where_now": where_phrase(o, self.labels),
            "usual_place": self.labels.spot_place(o.home_spot, o.home_spot_label) if o.home_spot is not None else None,
            "last_touched": last_touched_phrase(o, self.clock),
            "last_touched_days_ago": None
            if o.last_touched_t is None
            else round((self.clock.now_t - o.last_touched_t) / 86400, 1),
            "answer_hint": describe_location(o, self.clock, self.labels),
            "notes": o.notes or None,
        }

    def lookup_view(self, r: ec.ObjectLookupResponse) -> dict[str, Any]:
        return {
            "ok": True,
            "query": r.query,
            "matches": [self.object_view(o) for o in r.matches[:3]],
            "note": None if r.matches else "No object with that name or alias.",
        }

    def objects_view(self, r: ec.ObjectsResponse) -> dict[str, Any]:
        return {"ok": True, "now": self.clock.now_phrase(), "objects": [self.object_view(o) for o in r.objects]}

    def history_view(self, r: ec.HistoryResponse) -> dict[str, Any]:
        events = [
            {"when": self.clock.when(self.clock.parse_local(e.at_local, e.t)), "kind": e.kind, "detail": e.detail}
            for e in r.events[:HISTORY_VIEW_LIMIT]
        ]
        return {
            "ok": True,
            "object_id": r.object_id,
            "name": r.name,
            "since": self.clock.when(self.clock.local(r.since_t)),
            "event_count": len(r.events),
            "events": events,
            "note": None if r.events else "No events recorded in this period.",
        }

    def _day(self, iso_date: str) -> str:
        return cap(self.clock.day_phrase(date.fromisoformat(iso_date)))

    def adherence_view(self, r: ec.AdherenceResponse) -> dict[str, Any]:
        return {
            "ok": True,
            "date": r.date,
            "day": self._day(r.date),
            "timezone": r.timezone,
            "now": self.clock.now_phrase(),
            "doses": [dose_view(d, self.clock) for d in r.doses],
            "note": None if r.doses else "No medication doses were scheduled on this date.",
        }

    def summary_view(self, r: ec.DailySummaryResponse) -> dict[str, Any]:
        return {
            "ok": True,
            "date": r.date,
            "day": self._day(r.date),
            "summary_text": r.text,
            "pickup_count": r.pickup_count,
            "untouched_7d": r.untouched_7d,
            "missing": r.missing,
            "doses": [dose_view(d, self.clock) for d in r.doses],
        }
