"""What the concierge knows about the room: space, registry, object states.

Fed only from bus messages (snapshot, registry_update, state_update, pickup,
unknown_tag). Also remembers the last place each object was seen and its last
pickup, so "none" states can still be answered with "I last saw it ...".
"""
from __future__ import annotations

import json
import logging
import math
import re
import time
from dataclasses import dataclass
from pathlib import Path

from earmark_contracts import (
    ObjectState, Pickup, RegistryObject, Snapshot, Space, Spot, UnknownTag,
)

log = logging.getLogger(__name__)
DEFAULT_TZ = "America/Los_Angeles"
MAX_HISTORY = 10
LISTENER_FRESH_S = 3.0  # a locator fix older than this is ignored
SAVE_SPOT_FIX_S = 10.0  # saving "I left it here" accepts an older fix: you stand still while you say it
HEAD_FRESH_S = 2.0


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
        self.listener: tuple[list[float], float] | None = None  # (position, received at)
        self.head_yaw: tuple[float, float] | None = None  # (degrees, received at)
        self.unknown_tag: UnknownTag | None = None
        self.registry_version: float | None = None
        self.last_object: str | None = None  # what the last turn was about (for "it")

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
        saved_spot = loc.position is not None and st.precision == "exact" and st.status == "roaming"
        if loc.spot is not None or loc.area is not None or loc.near is not None or saved_spot:
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

    def apply_listener(self, position: list[float], quality: str) -> None:
        if quality != "lost":
            self.listener = (list(position), time.time())

    def apply_head(self, yaw: float) -> None:
        self.head_yaw = (yaw, time.time())

    def listener_position(self, max_age_s: float = LISTENER_FRESH_S) -> list[float] | None:
        """Where the locator last put the user, or None when it is old or missing."""
        if self.listener is None or time.time() - self.listener[1] > max_age_s:
            return None
        return self.listener[0]

    def relative(self, pos: list[float]) -> list[float]:
        """A room position as seen by the user: from where they stand, turned to where they face.

        With no fresh locator fix the user is assumed to be at the origin facing forward.
        """
        here = self.listener_position() or [0.0, 0.0, 0.0]
        dx, dy = pos[0] - here[0], pos[1] - here[1]
        yaw = self.head_yaw[0] if self.head_yaw and time.time() - self.head_yaw[1] <= HEAD_FRESH_S else 0.0
        r = math.hypot(dx, dy)
        az = math.atan2(dx, dy) - math.radians(yaw)
        return [r * math.sin(az), r * math.cos(az), pos[2] - here[2] if len(pos) > 2 else 0.0]

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

    def fresh_unknown_tag(self, now: float, window_s: float) -> UnknownTag | None:
        tag = self.unknown_tag
        if tag is None or now - tag.t > window_s:
            return None
        if any(o.tag == tag.tag for o in self.objects.values()):
            return None  # already labeled
        return tag
