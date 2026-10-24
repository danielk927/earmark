"""What the concierge knows about the room: space, registry, object states.

Fed only from bus messages (snapshot, registry_update, state_update, pickup,
unknown_tag). Also remembers the last place each object was seen and its last
pickup, so "none" states can still be answered with "I last saw it ...".
"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from pathlib import Path

from earmark_contracts import (
    ObjectState, Pickup, RegistryObject, Snapshot, Space, Spot, UnknownTag,
)

log = logging.getLogger(__name__)
DEFAULT_TZ = "America/Los_Angeles"
MAX_HISTORY = 10


@dataclass
class Sighting:
    """A resolvable place an object was last observed at."""
    spot: int | None
    area: str | None
    near: str | None
    position: list[float] | None
    t: float | None


@dataclass
class LastPickup:
    from_spot: int
    t: float


def household_timezone(paths: tuple[Path, ...]) -> str:
    """Timezone to use before the first snapshot arrives (the snapshot's household wins after that)."""
    for p in paths:
        try:
            return json.loads(p.read_text())["household"]["timezone"]
        except (OSError, KeyError, ValueError):
            continue
    return DEFAULT_TZ


class World:
    def __init__(self, timezone: str = DEFAULT_TZ, *, pinned: bool = False) -> None:
        self.timezone = timezone
        # pinned = set explicitly (CONCIERGE_TIMEZONE); otherwise follow the snapshot's household.
        self.timezone_pinned = pinned
        self.space: Space | None = None
        self.objects: dict[str, RegistryObject] = {}
        self.states: dict[str, ObjectState] = {}
        self.sightings: dict[str, Sighting] = {}
        self.history: dict[str, list[Sighting]] = {}  # every place an object was noted, oldest first
        self.pickups: dict[str, LastPickup] = {}
        self.unknown_tag: UnknownTag | None = None
        self.registry_version: float | None = None

    # ------------------------------------------------------------ updates

    def apply_snapshot(self, msg: Snapshot) -> None:
        if not self.timezone_pinned:
            self.timezone = msg.household.timezone
        self.space = msg.space
        self.set_objects(msg.objects)
        self.registry_version = msg.registry_version
        self.states = {}
        self.history = {}
        for st in msg.states:
            self.apply_state(st)

    def set_objects(self, objects: list[RegistryObject]) -> None:
        self.objects = {o.object_id: o for o in objects}

    def apply_state(self, st: ObjectState) -> None:
        self.states[st.object_id] = st
        loc = st.location
        if loc.spot is not None or loc.area is not None or loc.near is not None:
            sighting = Sighting(
                spot=loc.spot, area=loc.area, near=loc.near,
                position=list(loc.position) if loc.position else None,
                t=st.last_seen_t if st.last_seen_t is not None else st.t,
            )
            self.sightings[st.object_id] = sighting
            trail = self.history.setdefault(st.object_id, [])
            def place_of(s: Sighting) -> tuple:
                return (s.spot, s.area, s.near)

            if not trail or place_of(trail[-1]) != place_of(sighting):
                trail.append(sighting)
                del trail[:-MAX_HISTORY]

    def apply_pickup(self, msg: Pickup) -> None:
        self.pickups[msg.object_id] = LastPickup(from_spot=msg.from_spot, t=msg.t)
        prev = self.sightings.get(msg.object_id)
        self.sightings[msg.object_id] = Sighting(
            spot=msg.from_spot, area=None, near=None,
            position=self.spot_position(msg.from_spot) or (prev.position if prev else None),
            t=msg.t,
        )

    def apply_unknown_tag(self, msg: UnknownTag) -> None:
        self.unknown_tag = msg

    # ------------------------------------------------------------ lookups

    def spot(self, n: int | None) -> Spot | None:
        if n is None or self.space is None:
            return None
        return next((s for s in self.space.spots if s.spot == n), None)

    def spot_position(self, n: int | None) -> list[float] | None:
        s = self.spot(n)
        return list(s.position) if s else None

    def spots_left_to_right(self) -> list[Spot]:
        """Spots ordered by azimuth from the listener (leftmost first)."""
        from .phrasing import azimuth_deg
        if self.space is None:
            return []
        return sorted(self.space.spots, key=lambda s: azimuth_deg(s.position[0], s.position[1]))

    def area_label(self, area: str) -> str:
        if self.space:
            for a in self.space.areas:
                if a.area == area:
                    return a.label or "the " + a.area.replace("_", " ")
        return "the " + area.replace("_", " ")

    def area_ids(self) -> list[str]:
        return [a.area for a in self.space.areas] if self.space else []

    def resolve_area(self, text: str) -> str | None:
        """'the drawer' -> 'drawer'. Matches a saved place's id or label, ignoring 'the'/'my'."""
        def norm(s: str) -> str:
            return re.sub(r"^(?:the|my|a|an)\s+", "", " ".join(s.lower().replace("_", " ").split()))
        wanted = norm(text)
        if not wanted or self.space is None:
            return None
        for a in self.space.areas:
            if wanted in (norm(a.area), norm(a.label or "")):
                return a.area
        return None

    def receiver_label(self, receiver: str) -> str:
        if self.space:
            for r in self.space.receivers:
                if r.receiver == receiver:
                    return r.label
        return "the " + receiver.replace("_", " ") + " receiver"

    def object_on_spot(self, n: int) -> RegistryObject | None:
        for oid, st in self.states.items():
            if st.status == "on_spot" and st.location.spot == n and oid in self.objects:
                return self.objects[oid]
        return None

    def fresh_unknown_tag(self, now: float, window_s: float) -> UnknownTag | None:
        tag = self.unknown_tag
        if tag is None or now - tag.t > window_s:
            return None
        if any(o.tag == tag.tag for o in self.objects.values()):
            return None  # already labeled
        return tag
