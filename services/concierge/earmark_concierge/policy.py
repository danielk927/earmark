"""Response policy (BUILD_BRIEF 5.D): what to do and say for each tool result.

Pure functions of the World and the clock. The core turns a Plan into bus
messages. Every sentence is computed here, never by an LLM.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from earmark_contracts import RegistryObject

from .phrasing import (
    Grammar, cap, clock_phrase, clock_time, direction_phrase, join_and, join_or, number_word,
    relative_spot_phrase, the, time_phrase,
)
from .world import Sighting, World

PHRASE_UNKNOWN_OBJECT = "unknown_object"
PHRASE_NOT_UNDERSTOOD = "not_understood"
PHRASE_STOPPING = "stopping"
PHRASE_NO_NEW_TAG = "no_new_tag"
PHRASE_CHIRPING = "chirping"
PHRASE_STT_FALLBACK = "stt_fallback"
PHRASE_READY = "ready"


@dataclass
class GuideTarget:
    object_id: str
    name: str
    position: list[float]
    precision: str


@dataclass
class LabelAction:
    tag: str
    name: str
    aliases: list[str]
    spot: int | None


@dataclass
class PlaceAction:
    object_id: str
    area: str | None = None
    position: list[float] | None = None


@dataclass
class Plan:
    text: str | None = None
    phrase_id: str | None = None
    guide: GuideTarget | None = None
    chirp: str | None = None
    label: LabelAction | None = None
    place: PlaceAction | None = None
    stop: bool = False
    clarify: list[str] = field(default_factory=list)
    clarify_tool: str | None = None
    object_id: str | None = None  # what this turn was about (for "it" follow-ups)


def where_phrase(world: World, s: Sighting) -> str | None:
    if s.spot is not None:
        spot = world.spot(s.spot)
        return f"on the {spot.label} spot" if spot else f"on spot {s.spot}"
    if s.area is not None:
        return f"near {world.area_label(s.area)}"
    if s.near is not None:
        return f"near {world.receiver_label(s.near)}"
    if s.position is not None:
        return "at the spot you saved"
    return None


def _chirp_suffix(obj: RegistryObject, g: Grammar) -> str:
    return f" I'll make {g.it} beep." if obj.fob_id else ""


def locate(world: World, obj: RegistryObject, now: float, stale_s: float) -> Plan:
    """Where is it? Policy by precision: exact -> guide; area/proximity -> chirp; none/stale -> last seen."""
    g = Grammar(obj.name)
    name = the(obj.name)
    st = world.states.get(obj.object_id)
    tz = world.timezone

    if st is not None and st.status == "held":
        pk = world.pickups.get(obj.object_id)
        sighting = world.sightings.get(obj.object_id)
        spot_n = pk.from_spot if pk else (sighting.spot if sighting else None)
        when = pk.t if pk else st.last_seen_t
        text = f"{cap(name)} {g.was} picked up"
        spot = world.spot(spot_n)
        if spot:
            text += f" from the {spot.label} spot"
        if when is not None:
            text += f" {time_phrase(when, now, tz)}"
        text += f", and I haven't seen {g.it} put down since."
        return Plan(text=text, object_id=obj.object_id)

    if st is not None and st.precision == "exact" and st.location.position:
        pos = list(st.location.position)
        return Plan(
            text=f"{cap(name)} {g.is_} {direction_phrase(world.relative(pos))}.",
            guide=GuideTarget(obj.object_id, obj.name, pos, "exact"),
            object_id=obj.object_id,
        )

    fresh = st is not None and (st.last_seen_t is None or now - st.last_seen_t <= stale_s)
    if st is not None and st.precision in ("area", "proximity") and fresh:
        loc = st.location
        if loc.area:
            where = f"near {world.area_label(loc.area)}"
        elif loc.near:
            label = world.receiver_label(loc.near)
            where = f"farther away from {label}" if loc.distance_class == "far" else f"near {label}"
        else:
            where = "nearby"
        noted = f" I noted that {time_phrase(st.last_seen_t, now, tz)}." if loc.area and st.last_seen_t else ""
        return Plan(
            text=f"{cap(name)} {g.is_} {where}.{noted}{_chirp_suffix(obj, g)}",
            chirp=obj.fob_id, object_id=obj.object_id,
        )

    sighting = world.sightings.get(obj.object_id)
    where = where_phrase(world, sighting) if sighting else None
    if sighting is not None and sighting.t is not None and where:
        text = f"I last saw {name} {where} {time_phrase(sighting.t, now, tz)}."
    elif sighting is not None and sighting.t is not None:
        text = f"I last saw {name} {time_phrase(sighting.t, now, tz)}."
    else:
        text = f"I haven't detected {name} yet."
        if obj.notes and not obj.fob_id:
            text += f" Its notes say: {obj.notes.strip()}"
    return Plan(text=text + _chirp_suffix(obj, g), chirp=obj.fob_id, object_id=obj.object_id)


def chirp(world: World, obj: RegistryObject, now: float, stale_s: float) -> Plan:
    if obj.fob_id:
        return Plan(phrase_id=PHRASE_CHIRPING, chirp=obj.fob_id, object_id=obj.object_id)
    g = Grammar(obj.name)
    p = locate(world, obj, now, stale_s)
    p.text = f"{cap(the(obj.name))} {g.does} have a beeper. {p.text}"
    p.chirp = None
    return p


def last_seen(world: World, obj: RegistryObject, now: float, started_t: float,
              medical_question: bool = False) -> Plan:
    """Report only what the events show. For medication, never advice."""
    g = Grammar(obj.name)
    name = the(obj.name)
    tz = world.timezone
    parts: list[str] = []
    if medical_question:
        parts.append("I can't give medical advice, but I can tell you what the sensors saw.")
    st = world.states.get(obj.object_id)
    pk = world.pickups.get(obj.object_id)
    now_where = None
    if st is not None and st.status == "on_spot" and st.location.spot is not None:
        spot = world.spot(st.location.spot)
        now_where = f"on the {spot.label} spot" if spot else f"on spot {st.location.spot}"
    if pk is not None:
        spot = world.spot(pk.from_spot)
        frm = f" from the {spot.label} spot" if spot else ""
        parts.append(f"{cap(name)} {g.was} last picked up{frm} {time_phrase(pk.t, now, tz)}.")
        if now_where:
            parts.append(f"{cap(g.its)} {now_where} now.")
        elif st is not None and st.status == "held":
            parts.append(f"I haven't seen {g.it} put down since.")
    elif now_where:
        parts.append(f"{cap(name)} {g.is_} {now_where}.")
        parts.append(f"I haven't seen {g.it} picked up since I started at {clock_time(started_t, tz)}.")
    else:
        sighting = world.sightings.get(obj.object_id)
        where = where_phrase(world, sighting) if sighting else None
        if sighting is not None and sighting.t is not None:
            parts.append(f"I last saw {name}{' ' + where if where else ''} {time_phrase(sighting.t, now, tz)}.")
        else:
            parts.append(f"I haven't detected {name} since I started at {clock_time(started_t, tz)}.")
    return Plan(text=" ".join(parts), object_id=obj.object_id)


def list_objects(world: World) -> Plan:
    objs = list(world.objects.values())
    if not objs:
        return Plan(text="I don't know any items yet.")
    n = len(objs)
    word = "item" if n == 1 else "items"
    return Plan(text=f"I know about {number_word(n)} {word}: {join_and([the(o.name) for o in objs])}.")


def clarify(world: World, object_ids: list[str], tool: str) -> Plan:
    names = [the(world.objects[i].name) for i in object_ids]
    return Plan(text=f"Do you mean {join_or(names)}?", clarify=list(object_ids), clarify_tool=tool)


def label(tag: str, name: str, aliases: list[str], spot: int | None) -> Plan:
    return Plan(
        text=f"Okay, I'll remember this as {name}.",
        label=LabelAction(tag=tag, name=name, aliases=aliases, spot=spot),
    )


def put_in_place(world: World, obj: RegistryObject, area: str) -> Plan:
    g = Grammar(obj.name)
    return Plan(text=f"Got it, {the(obj.name)} {g.is_} in {world.area_label(area)}.",
                place=PlaceAction(obj.object_id, area), object_id=obj.object_id)


# The phone is held at chest height, but the item is down where the hand put it.
HAND_HEIGHT_M = 1.0


def put_here(obj: RegistryObject, listener: list[float]) -> Plan:
    """'I'm leaving my keys here': keep the spot the locator says the user is standing at."""
    spot = [round(listener[0], 2), round(listener[1], 2), HAND_HEIGHT_M]
    return Plan(text=f"Got it, I'll remember where you left {the(obj.name)}.",
                place=PlaceAction(obj.object_id, position=spot), object_id=obj.object_id)


def ask_place(world: World, obj: RegistryObject) -> Plan:
    """'Here' can't be saved without a fresh position from the locator."""
    labels = [world.area_label(a) for a in world.area_ids()]
    hint = f" I know {join_and(labels)}." if labels else ""
    return Plan(text=f"I can't tell where you are, so tell me the place. For example, I put {the(obj.name)} in "
                     f"{labels[0] if labels else 'the drawer'}.{hint}", object_id=obj.object_id)


def unknown_place(world: World) -> Plan:
    labels = [world.area_label(a) for a in world.area_ids()]
    return Plan(text=f"I don't know that place. I know {join_and(labels)}." if labels
                else "I don't know any places yet.")


def place_history(world: World, obj: RegistryObject, now: float) -> Plan:
    """Earlier places, newest first, each with when it was noted."""
    g = Grammar(obj.name)
    name = the(obj.name)
    tz = world.timezone
    trail = [s for s in world.history.get(obj.object_id, []) if where_phrase(world, s) and s.t is not None]
    if not trail:
        return Plan(text=f"I haven't noted a place for {name} yet.", object_id=obj.object_id)
    cur = trail[-1]
    text = f"{cap(name)} {g.is_} {where_phrase(world, cur)}, noted {time_phrase(cur.t, now, tz)}."
    if len(trail) == 1:
        text += f" I don't know of an earlier place for {g.it}."
    else:
        prev = trail[-2]
        subject = "they" if g.plural else "it"
        text += (f" Before that, {subject} {g.was} {where_phrase(world, prev)}, "
                 f"noted {time_phrase(prev.t, now, tz)}.")
    return Plan(text=text, object_id=obj.object_id)


def arrived(world: World, obj: RegistryObject, pos: list[float]) -> str:
    """The user is within half a meter: say where to reach (height, then side), from where they stand."""
    g = Grammar(obj.name)
    rel = world.relative(pos)
    height = "up high" if pos[2] >= 1.3 else "down low" if pos[2] <= 0.5 else "at chest height"
    return f"You're here. {cap(the(obj.name))} {g.is_} {height}, {clock_phrase(rel[0], rel[1])}."


def stop() -> Plan:
    return Plan(phrase_id=PHRASE_STOPPING, stop=True)


def unknown_object() -> Plan:
    return Plan(phrase_id=PHRASE_UNKNOWN_OBJECT)


def not_understood() -> Plan:
    return Plan(phrase_id=PHRASE_NOT_UNDERSTOOD)


def no_new_tag() -> Plan:
    return Plan(phrase_id=PHRASE_NO_NEW_TAG)


# ---------------------------------------------------------------- pickups while guiding

def pickup_correct(target: RegistryObject) -> str:
    return f"Got it, that's {the(target.name)}."


def pickup_wrong(world: World, target: RegistryObject, actual: RegistryObject | None,
                 from_spot: int) -> str:
    first = f"That's {the(actual.name)}." if actual else f"That's not {the(target.name)}."
    g = Grammar(target.name)
    tname = cap(the(target.name))
    st = world.states.get(target.object_id)
    if st is not None and st.status == "on_spot" and st.location.spot is not None:
        order = [s.spot for s in world.spots_left_to_right()]
        if from_spot in order and st.location.spot in order:
            rel = relative_spot_phrase(order.index(from_spot), order.index(st.location.spot))
            if rel:
                return f"{first} {tname} {g.is_} {rel}."
    if st is not None and st.precision == "exact" and st.location.position:
        return f"{first} {tname} {g.is_} {direction_phrase(world.relative(list(st.location.position)))}."
    return f"{first} I'm not sure where {the(target.name)} {g.is_} right now."


def guide_timeout(target_name: str) -> str:
    return f"I've stopped the guide sound for {the(target_name)}."
