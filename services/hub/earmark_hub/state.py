"""State engine: raw detections in, debounced object state out.

Pure and deterministic. Time comes only from event timestamps and `tick(now)`, and the
engine's notion of "now" never moves backwards, so tests replay scenarios instantly on
a virtual clock.

Spot readers poll: every read is either the tag on the spot (`seen`) or empty
(`removed`, or the literal tag "EMPTY"). Debounce rules:
- placement: `placement_reads` consecutive reads of the same tag on a spot
  (`kind: placed` from a self-debouncing adapter confirms immediately);
- removal: the confirmed tag is continuously absent for `removal_s`, counted from the
  first read that did not show it. Checked on every event and on every tick, so a
  reader that reports one EMPTY and then goes quiet still produces the removal.
  Silence alone (no absent read at all) is never treated as a removal.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Union

from earmark_contracts import (
    DetectionEvent,
    Location,
    ObjectState,
    Pickup,
    RegistryObject,
    UnknownTag,
    WhereArea,
    WhereNear,
    WherePosition,
    WhereSpot,
)

from .registry import normalize_tag
from .space import SpaceIndex

EMPTY = "EMPTY"
_EPS = 1e-6


@dataclass(frozen=True)
class Placed:
    """A debounced placement on a spot (Convex hub_event `placed`; not a bus message)."""

    object_id: str | None
    spot: int
    tag: str
    source: str
    t: float


@dataclass(frozen=True)
class Removed:
    """A debounced removal from a spot (Convex hub_event `removed`; not a bus message)."""

    object_id: str | None
    spot: int
    tag: str
    source: str
    t: float


@dataclass(frozen=True)
class Stored:
    """The user said where they put an item (Convex hub_event `stored`; not a bus message)."""

    object_id: str
    area: str | None
    t: float
    position: list[float] | None = None


Output = Union[ObjectState, Pickup, UnknownTag, Placed, Removed, Stored]


@dataclass
class _SpotTrack:
    confirmed: str | None = None
    confirmed_source: str = "none"
    absent_since: float | None = None
    candidate: str | None = None
    candidate_count: int = 0


@dataclass
class _Belief:
    status: str = "missing"
    spot: int | None = None
    position: list[float] | None = None
    area: str | None = None
    near: str | None = None
    distance_class: str | None = None
    precision: str = "none"
    last_seen_t: float | None = None
    source: str = "none"
    placed_t: float | None = None  # when the user said where it is; cleared once a reader hears it again

    def clear_location(self) -> None:
        self.spot = self.position = self.area = self.near = self.distance_class = None


@dataclass
class StateEngine:
    space: SpaceIndex
    objects: list[RegistryObject]
    placement_reads: int = 2
    removal_s: float = 1.5
    _now: float = 0.0
    _spots: dict[int, _SpotTrack] = field(default_factory=dict)
    _beliefs: dict[str, _Belief] = field(default_factory=dict)
    _emitted: dict[str, tuple] = field(default_factory=dict)
    _by_tag: dict[str, str] = field(default_factory=dict)
    _registry: dict[str, RegistryObject] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self._index(self.objects)
        for oid in self._registry:
            self._beliefs[oid] = _Belief()
            self._emitted[oid] = self._key(oid)

    # ------------------------------------------------------------ public API

    @property
    def now(self) -> float:
        return self._now

    def handle(self, ev: DetectionEvent) -> list[Output]:
        self._now = max(self._now, ev.t)
        out: list[Output] = []
        self._expire(out)
        where = ev.where
        if isinstance(where, WhereSpot):
            self._spot_read(where.spot, ev, out)
        elif ev.kind in ("lost", "removed") or where is None:
            self._lost(ev, out)
        else:
            self._free(ev, where, out)
        self._sync(out)
        return out

    def place_in_area(self, object_id: str, area: str, t: float) -> list[Output]:
        """The user's word that an item is at a named place; overrides what the readers last saw."""
        pos = self.space.area_position(area)
        if object_id not in self._registry or pos is None:
            return []
        self._now = max(self._now, t)
        b = self._beliefs[object_id]
        b.clear_location()
        b.status, b.area, b.position, b.precision = "roaming", area, pos, "area"
        b.last_seen_t, b.source = self._now, "none"
        b.placed_t = self._now
        out: list[Output] = [Stored(object_id, area, self._now)]
        self._sync(out)
        return out

    def place_at_position(self, object_id: str, position: list[float], t: float) -> list[Output]:
        """The user left the item where they stand (position from the locator)."""
        if object_id not in self._registry:
            return []
        self._now = max(self._now, t)
        b = self._beliefs[object_id]
        b.clear_location()
        b.status, b.position, b.precision = "roaming", list(position), "exact"
        b.last_seen_t, b.source = self._now, "none"
        b.placed_t = self._now
        out: list[Output] = [Stored(object_id, None, self._now, list(position))]
        self._sync(out)
        return out

    def tick(self, now: float) -> list[Output]:
        self._now = max(self._now, now)
        out: list[Output] = []
        self._expire(out)
        self._sync(out)
        return out

    def set_objects(self, objects: list[RegistryObject]) -> list[Output]:
        """Apply a registry change; re-resolve tags already confirmed on spots."""
        self.objects = list(objects)
        self._index(self.objects)
        for oid in list(self._beliefs):
            if oid not in self._registry:
                del self._beliefs[oid]
                self._emitted.pop(oid, None)
        for oid in self._registry:
            if oid not in self._beliefs:
                self._beliefs[oid] = _Belief()
                self._emitted[oid] = self._key(oid)
        for spot, track in self._spots.items():
            oid = self._by_tag.get(track.confirmed) if track.confirmed else None
            if oid is None:
                continue
            b = self._beliefs[oid]
            if not (b.status == "on_spot" and b.spot == spot):
                self._put_on_spot(oid, spot, track.confirmed_source)
        out: list[Output] = []
        self._sync(out)
        return out

    def reset(self, objects: list[RegistryObject] | None = None, now: float | None = None) -> list[Output]:
        """Back to the startup state: nothing confirmed anywhere, every object missing."""
        if now is not None:
            self._now = max(self._now, now)
        if objects is not None:
            self.objects = list(objects)
            self._index(self.objects)
        self._spots.clear()
        self._beliefs = {oid: _Belief() for oid in self._registry}
        self._emitted = {oid: v for oid, v in self._emitted.items() if oid in self._registry}
        out: list[Output] = []
        self._sync(out)
        return out

    def states(self) -> list[ObjectState]:
        return [self._state(oid) for oid in self._registry]

    def state(self, object_id: str) -> ObjectState:
        return self._state(object_id)

    def object_for_tag(self, tag: str) -> str | None:
        return self._by_tag.get(normalize_tag(tag))

    # ------------------------------------------------------------ spot reads

    def _spot_read(self, spot: int, ev: DetectionEvent, out: list[Output]) -> None:
        track = self._spots.setdefault(spot, _SpotTrack())
        tag = normalize_tag(ev.tag)
        present = ev.kind in ("seen", "placed") and tag != EMPTY
        now = self._now

        if present and tag == track.confirmed:
            track.absent_since = None
            track.candidate, track.candidate_count = None, 0
            oid = self._by_tag.get(tag)
            b = self._beliefs[oid] if oid else None
            if b is not None and b.placed_t is not None and ev.t > b.placed_t:
                self._put_on_spot(oid, spot, track.confirmed_source)  # read after the spoken place: still here
            elif b is not None and b.status == "on_spot" and b.spot == spot:
                b.last_seen_t = now
            return

        if track.confirmed is not None and track.absent_since is None:
            track.absent_since = now
        self._check_removal(spot, track, out)

        if not present:
            track.candidate, track.candidate_count = None, 0
            return
        if track.candidate == tag:
            track.candidate_count += 1
        else:
            track.candidate, track.candidate_count = tag, 1
        if ev.kind == "placed" or track.candidate_count >= self.placement_reads:
            self._confirm(spot, tag, ev.source, out)

    def _expire(self, out: list[Output]) -> None:
        for spot, track in self._spots.items():
            self._check_removal(spot, track, out)

    def _check_removal(self, spot: int, track: _SpotTrack, out: list[Output]) -> None:
        if track.confirmed is None or track.absent_since is None:
            return
        if self._now - track.absent_since >= self.removal_s - _EPS:
            self._remove(spot, track, out)

    def _remove(self, spot: int, track: _SpotTrack, out: list[Output]) -> None:
        tag = track.confirmed
        assert tag is not None
        lift_t = track.absent_since if track.absent_since is not None else self._now
        oid = self._by_tag.get(tag)
        out.append(Removed(object_id=oid, spot=spot, tag=tag, source=track.confirmed_source, t=self._now))
        track.confirmed, track.confirmed_source, track.absent_since = None, "none", None
        if oid is None:
            return
        b = self._beliefs[oid]
        b.status, b.precision, b.last_seen_t, b.placed_t = "held", "none", lift_t, None
        b.clear_location()
        out.append(Pickup(object_id=oid, from_spot=spot, t=self._now))

    def _confirm(self, spot: int, tag: str, source: str, out: list[Output]) -> None:
        track = self._spots[spot]
        if track.confirmed is not None:
            # A different tag is still recorded here: it must have left first.
            self._remove(spot, track, out)
        for other, ot in self._spots.items():
            if other != spot and ot.confirmed == tag:
                # Confirmed on a new spot while still recorded on an old one.
                self._remove(other, ot, out)
        track.confirmed, track.confirmed_source, track.absent_since = tag, source, None
        track.candidate, track.candidate_count = None, 0
        oid = self._by_tag.get(tag)
        out.append(Placed(object_id=oid, spot=spot, tag=tag, source=source, t=self._now))
        if oid is None:
            out.append(UnknownTag(tag=tag, spot=spot, t=self._now))
        else:
            self._put_on_spot(oid, spot, source)

    def _put_on_spot(self, oid: str, spot: int, source: str) -> None:
        b = self._beliefs[oid]
        b.clear_location()
        b.status, b.spot, b.position = "on_spot", spot, self.space.spot_position(spot)
        b.precision, b.last_seen_t, b.source, b.placed_t = "exact", self._now, source, None

    # ------------------------------------------------------------ proximity / free position

    def _free(self, ev: DetectionEvent, where, out: list[Output]) -> None:
        oid = self._by_tag.get(normalize_tag(ev.tag))
        if oid is None:
            return
        b = self._beliefs[oid]
        if b.status == "on_spot":
            return  # a spot reader is more precise than proximity; it decides when it leaves
        if b.placed_t is not None and ev.t <= b.placed_t:
            return  # heard before the user said where it is
        b.clear_location()
        b.placed_t = None
        if isinstance(where, WhereNear):
            b.near, b.distance_class = where.near, where.distance_class
            b.position = self.space.receiver_position(where.near)
            b.precision = "proximity"
        elif isinstance(where, WhereArea):
            b.area, b.position, b.precision = where.area, self.space.area_position(where.area), ev.precision
        elif isinstance(where, WherePosition):
            b.position, b.precision = list(where.position), ev.precision
        b.status, b.last_seen_t, b.source = "roaming", self._now, ev.source

    def _lost(self, ev: DetectionEvent, out: list[Output]) -> None:
        oid = self._by_tag.get(normalize_tag(ev.tag))
        if oid is None:
            return
        b = self._beliefs[oid]
        if b.status == "on_spot" or b.placed_t is not None:
            return  # a spoken place stands until the fob is heard again
        b.status, b.precision = "missing", "none"  # location keeps the last known values

    # ------------------------------------------------------------ registry / output

    def _index(self, objects: list[RegistryObject]) -> None:
        self._registry = {o.object_id: o for o in objects}
        self._by_tag = {}
        for o in objects:
            for ident in (o.tag, o.fob_id):
                if ident:
                    self._by_tag.setdefault(normalize_tag(ident), o.object_id)

    def _state(self, oid: str) -> ObjectState:
        b = self._beliefs[oid]
        return ObjectState(
            object_id=oid,
            location=Location(spot=b.spot, position=b.position, area=b.area, near=b.near,
                              distance_class=b.distance_class),
            precision=b.precision,
            status=b.status,
            home_spot=self._registry[oid].home_spot,
            last_seen_t=b.last_seen_t,
            source=b.source,
            t=self._now,
        )

    def _key(self, oid: str) -> tuple:
        b = self._beliefs[oid]
        return (b.status, b.spot, tuple(b.position) if b.position else None, b.area, b.near,
                b.distance_class, b.precision, b.source, self._registry[oid].home_spot)

    def _sync(self, out: list[Output]) -> None:
        """Append a state_update for every object whose state changed (ignoring t and last_seen_t)."""
        for oid in self._registry:
            key = self._key(oid)
            if self._emitted.get(oid) != key:
                self._emitted[oid] = key
                out.append(self._state(oid))
