"""An offline stand-in for Earmark's Convex read endpoints.

Built from `config/objects.seed.json` and `config/space.json` plus two scripted days of history
(BUILD_BRIEF 5.C seed data): salt and sugar in identical jars on spots 2 and 3, blood-pressure
pills on spot 4 scheduled at 08:00 and 20:00, keys on a fob, pepper never detected, and one
missed evening dose (yesterday at 20:00).

"Now" is fixed (default: Friday 2025-10-24 17:00 America/Los_Angeles, the instant the contract
examples use), so answers are deterministic. Every response is built as a pydantic contract
model and round-tripped through JSON, exactly what the HTTP server sends.

Adherence follows contracts/README.md:
  taken   - a pickup with |pickup - S| <= W
  late    - no taken pickup, but one with W < pickup - S <= 2W
  missed  - neither, and now > S + 2W
  pending - neither, and now <= S + 2W
  each pickup is evidence for at most one dose (the nearest scheduled time).
"""

from __future__ import annotations

import json
import logging
import threading
import time
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from datetime import time as dtime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlsplit
from zoneinfo import ZoneInfo

import earmark_contracts as ec
from pydantic import BaseModel

from .config import CONFIG_DIR
from .convex import SECRET_HEADER, ConvexError
from .household import HouseholdClock

log = logging.getLogger("earmark.memory.fixture")

FIXTURE_NOW_T = 1761350400.0  # Friday 2025-10-24 17:00:00 -07:00
UNTOUCHED_DAYS = 7
HISTORY_DEFAULT_DAYS = 7
HISTORY_MAX_EVENTS = 200

# (day offset from "now"'s date, local HH:MM, object_id, kind, spot)
HISTORY_SCRIPT: list[tuple[int, str, str, str, int]] = [
    # Yesterday: morning dose taken at 08:05, evening dose missed (no pickup between 19:00 and 22:00).
    (-1, "07:32", "sugar", "pickup", 3),
    (-1, "07:34", "sugar", "placed", 3),
    (-1, "08:05", "bp_meds", "pickup", 4),
    (-1, "08:07", "bp_meds", "placed", 4),
    (-1, "08:20", "salt", "pickup", 2),
    (-1, "08:21", "salt", "placed", 2),
    (-1, "12:10", "salt", "pickup", 2),
    (-1, "12:12", "salt", "placed", 2),
    (-1, "15:30", "sugar", "pickup", 3),
    (-1, "15:31", "sugar", "placed", 3),
    (-1, "18:40", "salt", "pickup", 2),
    (-1, "18:43", "salt", "placed", 2),
    # Today: morning dose taken at 08:15; the 20:00 dose is still ahead at 17:00.
    (0, "07:50", "sugar", "pickup", 3),
    (0, "07:52", "sugar", "placed", 3),
    (0, "08:15", "bp_meds", "pickup", 4),
    (0, "08:16", "bp_meds", "placed", 4),
    (0, "12:30", "salt", "pickup", 2),
    (0, "12:33", "salt", "placed", 2),
    (0, "16:00", "sugar", "pickup", 3),
    (0, "16:02", "sugar", "placed", 3),
]
# Fob-tracked objects: (object_id, receiver, distance class, minutes before now last detected).
FOB_SIGHTINGS: list[tuple[str, str, str, int]] = [("keys", "hub", "near", 8)]


class FixtureError(Exception):
    def __init__(self, status: int, error: str):
        super().__init__(error)
        self.status = status
        self.error = error


@dataclass(frozen=True)
class FixtureEvent:
    event_id: str
    object_id: str
    kind: str  # "pickup" | "placed"
    t: float
    spot: int


def local_iso(t: float, tz: ZoneInfo) -> str:
    """ISO 8601 in household time, like the contract examples ('...T08:00:00-07:00', '...T17:00:00.120-07:00')."""
    dt = datetime.fromtimestamp(t, tz)
    return dt.isoformat(timespec="seconds" if float(t).is_integer() else "milliseconds")


def _validated(model: BaseModel) -> Any:
    """Round-trip through JSON and re-validate, so the fixture can only ever emit contract-valid bodies."""
    cls = type(model)
    return cls.model_validate_json(json.dumps(ec.to_dict(model)))


def compute_doses(
    *,
    medication: ec.Medication,
    name: str,
    pickups: list[tuple[str, float]],
    day: date,
    tz: ZoneInfo,
    now_t: float,
) -> list[ec.Dose]:
    """The contract's deterministic adherence rule for one medication on one household-local day."""
    window = medication.window_minutes * 60

    def instants(d: date) -> list[tuple[str, float]]:
        out = []
        for hhmm in medication.schedule_times:
            h, m = (int(x) for x in hhmm.split(":"))
            out.append((hhmm, datetime.combine(d, dtime(h, m), tz).timestamp()))
        return out

    neighborhood = sorted(
        (s for d in (day - timedelta(days=1), day, day + timedelta(days=1)) for s in instants(d)),
        key=lambda s: s[1],
    )
    # Each pickup (up to now) is evidence only for its nearest scheduled time; ties go to the earlier one.
    assigned: dict[float, list[tuple[str, float]]] = {s_t: [] for _, s_t in neighborhood}
    for event_id, p in pickups:
        if p > now_t:
            continue
        nearest = min(neighborhood, key=lambda s: (abs(p - s[1]), s[1]))
        assigned[nearest[1]].append((event_id, p))

    doses = []
    for hhmm, s_t in instants(day):
        evidence = assigned[s_t]
        on_time = [e for e in evidence if abs(e[1] - s_t) <= window]
        late = [e for e in evidence if window < e[1] - s_t <= 2 * window]
        chosen: tuple[str, float] | None = None
        if on_time:
            status, chosen = "taken", min(on_time, key=lambda e: abs(e[1] - s_t))
        elif late:
            status, chosen = "late", min(late, key=lambda e: e[1])
        elif now_t > s_t + 2 * window:
            status = "missed"
        else:
            status = "pending"
        doses.append(
            ec.Dose(
                object_id=medication.object_id,
                name=name,
                scheduled_local_time=hhmm,
                scheduled_for_t=s_t,
                scheduled_for_local=local_iso(s_t, tz),
                status=status,
                taken_t=chosen[1] if chosen else None,
                taken_local=local_iso(chosen[1], tz) if chosen else None,
                evidence_event_id=chosen[0] if chosen else None,
            )
        )
    return doses


class FixtureData:
    """Contract responses computed from the seed config and the scripted history."""

    def __init__(self, now_t: float = FIXTURE_NOW_T, config_dir: Path = CONFIG_DIR):
        self.now_t = now_t
        self.registry = ec.Registry.model_validate_json((config_dir / "objects.seed.json").read_text())
        self.space = ec.Space.model_validate_json((config_dir / "space.json").read_text())
        self.timezone = self.registry.household.timezone
        self.tz = ZoneInfo(self.timezone)
        self.objects = {o.object_id: o for o in self.registry.objects}
        self.spot_labels = {s.spot: s.label for s in self.space.spots}
        self.events = self._build_events()
        # Like convex/ medications.activeSinceT: no doses before monitoring began (the start of the history).
        first_day = datetime.fromtimestamp(now_t, self.tz).date() + timedelta(days=min(s[0] for s in HISTORY_SCRIPT))
        self.active_since_t = datetime.combine(first_day, dtime(0, 0), self.tz).timestamp()

    @property
    def clock(self) -> HouseholdClock:
        return HouseholdClock(now_t=self.now_t, timezone=self.timezone)

    def _build_events(self) -> list[FixtureEvent]:
        today = datetime.fromtimestamp(self.now_t, self.tz).date()
        events = []
        for i, (offset, hhmm, object_id, kind, spot) in enumerate(HISTORY_SCRIPT):
            h, m = (int(x) for x in hhmm.split(":"))
            t = datetime.combine(today + timedelta(days=offset), dtime(h, m), self.tz).timestamp()
            if t <= self.now_t:
                events.append(FixtureEvent(f"e-fx{i:04d}", object_id, kind, t, spot))
        return sorted(events, key=lambda e: e.t)

    # ------------------------------------------------------------ helpers

    def _parse_date(self, value: str | None) -> date:
        if value is None:
            return self.clock.today
        try:
            return date.fromisoformat(value)
        except ValueError as exc:
            raise FixtureError(400, "invalid date (expected YYYY-MM-DD)") from exc

    def _spot_label(self, spot: int | None) -> str | None:
        return self.spot_labels.get(spot) if spot is not None else None

    def _state(self, object_id: str) -> ec.SummaryState | None:
        for fob_object, receiver, distance, minutes in FOB_SIGHTINGS:
            if fob_object == object_id:
                seen = self.now_t - minutes * 60
                return ec.SummaryState(
                    status="roaming",
                    spot=None,
                    spot_label=None,
                    area=None,
                    near=receiver,
                    distance_class=distance,
                    precision="proximity",
                    last_seen_t=seen,
                    last_seen_local=local_iso(seen, self.tz),
                )
        mine = [e for e in self.events if e.object_id == object_id]
        if not mine:
            return None
        last = mine[-1]
        if last.kind == "pickup":
            return ec.SummaryState(
                status="held",
                spot=None,
                spot_label=None,
                area=None,
                near=None,
                distance_class=None,
                precision="none",
                last_seen_t=last.t,
                last_seen_local=local_iso(last.t, self.tz),
            )
        return ec.SummaryState(
            status="on_spot",
            spot=last.spot,
            spot_label=self._spot_label(last.spot),
            area=None,
            near=None,
            distance_class=None,
            precision="exact",
            last_seen_t=self.now_t,
            last_seen_local=local_iso(self.now_t, self.tz),
        )

    def _summary(self, obj: ec.RegistryObject) -> ec.ObjectSummary:
        touches = [e for e in self.events if e.object_id == obj.object_id]
        last_touched = touches[-1].t if touches else None
        return ec.ObjectSummary(
            object_id=obj.object_id,
            name=obj.name,
            aliases=obj.aliases,
            notes=obj.notes,
            description=obj.description,
            home_spot=obj.home_spot,
            home_spot_label=self._spot_label(obj.home_spot),
            is_medication=obj.is_medication,
            fob_id=obj.fob_id,
            state=self._state(obj.object_id),
            last_touched_t=last_touched,
            last_touched_local=local_iso(last_touched, self.tz) if last_touched is not None else None,
        )

    def _doses(self, day: date) -> list[ec.Dose]:
        doses = []
        for med in self.registry.medications:
            pickups = [(e.event_id, e.t) for e in self.events if e.object_id == med.object_id and e.kind == "pickup"]
            doses += compute_doses(
                medication=med,
                name=self.objects[med.object_id].name,
                pickups=pickups,
                day=day,
                tz=self.tz,
                now_t=self.now_t,
            )
        return sorted((d for d in doses if d.scheduled_for_t >= self.active_since_t), key=lambda d: d.scheduled_for_t)

    # ------------------------------------------------------------ endpoints

    def object_lookup(self, name: str) -> ec.ObjectLookupResponse:
        q = name.strip().lower()
        objs = list(self.registry.objects)
        by_name = [o for o in objs if o.name.lower() == q]
        by_alias = [o for o in objs if o not in by_name and q in (a.lower() for a in o.aliases)]
        by_substring = [
            o
            for o in objs
            if q and o not in by_name and o not in by_alias and (q in o.name.lower() or any(q in a.lower() for a in o.aliases))
        ]
        matches = [self._summary(o) for o in by_name + by_alias + by_substring]
        return _validated(
            ec.ObjectLookupResponse(query=name, matches=matches, now_t=self.now_t, now_local=local_iso(self.now_t, self.tz))
        )

    def objects_response(self) -> ec.ObjectsResponse:
        return _validated(
            ec.ObjectsResponse(
                objects=[self._summary(o) for o in self.registry.objects],
                now_t=self.now_t,
                now_local=local_iso(self.now_t, self.tz),
            )
        )

    def history(self, object_id: str, since_t: float | None = None) -> ec.HistoryResponse:
        obj = self.objects.get(object_id)
        if obj is None:
            raise FixtureError(404, "unknown objectId")
        since = since_t if since_t is not None else self.now_t - HISTORY_DEFAULT_DAYS * 86400
        mine = [e for e in self.events if e.object_id == object_id and e.t >= since]
        events = [
            ec.HistoryEvent(
                event_id=e.event_id,
                kind=e.kind,
                t=e.t,
                at_local=local_iso(e.t, self.tz),
                spot=e.spot,
                spot_label=self._spot_label(e.spot),
                detail=(
                    f"Picked up from the {self._spot_label(e.spot)} spot."
                    if e.kind == "pickup"
                    else f"Put down on the {self._spot_label(e.spot)} spot."
                ),
            )
            for e in sorted(mine, key=lambda e: e.t, reverse=True)[:HISTORY_MAX_EVENTS]
        ]
        return _validated(ec.HistoryResponse(object_id=object_id, name=obj.name, since_t=since, events=events))

    def adherence(self, date_str: str | None = None) -> ec.AdherenceResponse:
        day = self._parse_date(date_str)
        return _validated(
            ec.AdherenceResponse(date=day.isoformat(), timezone=self.timezone, doses=self._doses(day), now_t=self.now_t)
        )

    def daily_summary(self, date_str: str | None = None) -> ec.DailySummaryResponse:
        day = self._parse_date(date_str)
        doses = self._doses(day)
        day_start = datetime.combine(day, dtime(0, 0), self.tz).timestamp()
        day_end = datetime.combine(day + timedelta(days=1), dtime(0, 0), self.tz).timestamp()
        pickups = [e for e in self.events if e.kind == "pickup" and day_start <= e.t < day_end]
        window_start = day_end - UNTOUCHED_DAYS * 86400
        # Like convex/: only NFC-tagged objects; fob-only objects never produce pickups or placements.
        untouched = [
            o.object_id
            for o in self.registry.objects
            if o.tag is not None and not any(e.object_id == o.object_id and window_start <= e.t < day_end for e in self.events)
        ]
        missing = [
            o.object_id for o in self.registry.objects if (s := self._state(o.object_id)) is not None and s.status == "missing"
        ]
        return _validated(
            ec.DailySummaryResponse(
                date=day.isoformat(),
                timezone=self.timezone,
                generated_t=self.now_t,
                doses=doses,
                pickup_count=len(pickups),
                untouched_7d=untouched,
                missing=missing,
                text=self._summary_text(day, doses, len(pickups), untouched, missing),
            )
        )

    def _summary_text(self, day: date, doses: list[ec.Dose], pickups: int, untouched: list[str], missing: list[str]) -> str:
        parts = []
        windows = {m.object_id: m.window_minutes for m in self.registry.medications}
        for i, d in enumerate(doses):
            label = f"the {d.scheduled_local_time} {d.name} dose" if i == 0 else f"the {d.scheduled_local_time} dose"
            if d.status in ("taken", "late"):
                at = datetime.fromtimestamp(d.taken_t, self.tz).strftime("%H:%M")
                parts.append(f"{label} was {d.status}" + (f" at {at}" if d.status == "taken" else f" (picked up at {at})"))
            elif d.status == "missed":
                w = windows.get(d.object_id, 60) * 60
                start = datetime.fromtimestamp(d.scheduled_for_t - w, self.tz).strftime("%H:%M")
                end = datetime.fromtimestamp(d.scheduled_for_t + 2 * w, self.tz).strftime("%H:%M")
                parts.append(f"{label} was missed (no pickup between {start} and {end})")
            else:
                parts.append(f"{label} is pending")
        dose_text = ". ".join(p[0].upper() + p[1:] for p in parts)
        names = {o.object_id: o.name for o in self.registry.objects}
        text = f"On {day.strftime('%A')}, {day.strftime('%B')} {day.day}: " + (
            dose_text[0].lower() + dose_text[1:] + "." if dose_text else "no doses scheduled."
        )
        text += f" {pickups} pickup{'s' if pickups != 1 else ''} recorded."
        if untouched:
            text += " Not touched in 7 days: " + ", ".join(names[o] for o in untouched) + "."
        if missing:
            text += " Missing: " + ", ".join(names[o] for o in missing) + "."
        return text


class FixtureConvexReader:
    """`ConvexReader` over `FixtureData`, in process (used by `--fixture` and the tests)."""

    source = "fixture"

    def __init__(self, data: FixtureData | None = None):
        self.data = data or FixtureData()

    def _call(self, fn, *args):
        try:
            return fn(*args)
        except FixtureError as exc:
            kind = "not_found" if exc.status == 404 else "bad_request"
            raise ConvexError(kind, exc.error) from exc

    async def clock(self) -> HouseholdClock:
        return self.data.clock

    async def find_object(self, name: str) -> ec.ObjectLookupResponse:
        return self._call(self.data.object_lookup, name)

    async def list_objects(self) -> ec.ObjectsResponse:
        return self._call(self.data.objects_response)

    async def history(self, object_id: str, since_t: float | None = None) -> ec.HistoryResponse:
        return self._call(self.data.history, object_id, since_t)

    async def adherence(self, date: str | None = None) -> ec.AdherenceResponse:
        return self._call(self.data.adherence, date)

    async def daily_summary(self, date: str | None = None) -> ec.DailySummaryResponse:
        return self._call(self.data.daily_summary, date)

    async def aclose(self) -> None:
        return None


# ---------------------------------------------------------------- HTTP server


class FixtureServer:
    """Serves `FixtureData` over HTTP with the real routes, auth header, and error bodies.

    For tests and for exercising the real HTTP client offline. `delay_s` slows every response
    (timeout tests); `overrides[path] = (status, body)` replaces a route's response.
    """

    def __init__(self, data: FixtureData, secret: str, *, host: str = "127.0.0.1", port: int = 0, delay_s: float = 0.0):
        self.data = data
        self.secret = secret
        self.delay_s = delay_s
        self.overrides: dict[str, tuple[int, Any]] = {}
        self.requests: list[dict[str, Any]] = []
        self._httpd = ThreadingHTTPServer((host, port), self._handler_class())
        self._httpd.daemon_threads = True
        self._thread: threading.Thread | None = None

    @property
    def url(self) -> str:
        host, port = self._httpd.server_address[:2]
        return f"http://{host}:{port}"

    def start(self) -> FixtureServer:
        self._thread = threading.Thread(target=self._httpd.serve_forever, name="fixture-convex", daemon=True)
        self._thread.start()
        return self

    def serve_forever(self) -> None:
        self._httpd.serve_forever()

    def stop(self) -> None:
        self._httpd.shutdown()
        self._httpd.server_close()

    def __enter__(self) -> FixtureServer:
        return self.start()

    def __exit__(self, *exc: object) -> None:
        self.stop()

    def route(self, path: str, query: dict[str, str]) -> Any:
        if path == "/api/object":
            if "name" not in query:
                raise FixtureError(400, "missing name")
            return self.data.object_lookup(query["name"])
        if path == "/api/objects":
            return self.data.objects_response()
        if path == "/api/history":
            if "objectId" not in query:
                raise FixtureError(400, "missing objectId")
            since = query.get("since")
            try:
                since_t = float(since) if since is not None else None
            except ValueError as exc:
                raise FixtureError(400, "invalid since (expected unix seconds)") from exc
            return self.data.history(query["objectId"], since_t)
        if path == "/api/adherence":
            return self.data.adherence(query.get("date"))
        if path == "/api/daily-summary":
            return self.data.daily_summary(query.get("date"))
        raise FixtureError(404, "no such route")

    def _handler_class(self) -> type[BaseHTTPRequestHandler]:
        server = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:  # noqa: N802 (http.server API)
                parts = urlsplit(self.path)
                query = {k: v[0] for k, v in parse_qs(parts.query).items()}
                server.requests.append({"path": parts.path, "query": query, "secret": self.headers.get(SECRET_HEADER)})
                if server.delay_s:
                    time.sleep(server.delay_s)
                if parts.path in server.overrides:
                    status, body = server.overrides[parts.path]
                    return self._send(status, body)
                if self.headers.get(SECRET_HEADER) != server.secret:
                    return self._send(401, {"ok": False, "error": "unauthorized"})
                try:
                    return self._send(200, ec.to_dict(server.route(parts.path, query)))
                except FixtureError as exc:
                    return self._send(exc.status, {"ok": False, "error": exc.error})

            def _send(self, status: int, body: Any) -> None:
                raw = body if isinstance(body, bytes) else (body.encode() if isinstance(body, str) else json.dumps(body).encode())
                try:
                    self.send_response(status)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Content-Length", str(len(raw)))
                    self.end_headers()
                    self.wfile.write(raw)
                except (BrokenPipeError, ConnectionResetError):
                    pass  # the client gave up (e.g. a timeout test)

            def log_message(self, fmt: str, *args: Any) -> None:
                log.info("fixture %s", fmt % args)  # request line and status only, never headers

        return Handler
