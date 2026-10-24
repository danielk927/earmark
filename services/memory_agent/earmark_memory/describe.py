"""Deterministic sentences built from contract models.

Used both by the keyword fallback (templated answers) and by the tool views handed to the LLM,
so every time and place the user hears was formatted in code from Convex's data.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

import earmark_contracts as ec

from .config import CONFIG_DIR
from .household import HouseholdClock, clock_time, schedule_time

log = logging.getLogger("earmark.memory")


@dataclass(frozen=True)
class SpaceLabels:
    """Human labels for receivers and areas (Convex returns their ids only), from config/space.json."""

    receivers: dict[str, str] = field(default_factory=dict)
    areas: dict[str, str] = field(default_factory=dict)

    @classmethod
    def load(cls, path: Path = CONFIG_DIR / "space.json") -> SpaceLabels:
        try:
            space = ec.Space.model_validate_json(path.read_text())
        except (OSError, ValueError) as exc:
            log.warning("could not read %s (%s); places will be named by id", path, type(exc).__name__)
            return cls()
        return cls(
            receivers={r.receiver: r.label for r in space.receivers},
            areas={a.area: a.label for a in space.areas if a.label},
        )

    def receiver(self, receiver_id: str) -> str:
        return self.receivers.get(receiver_id) or f"the {receiver_id.replace('_', ' ')} receiver"

    def area(self, area_id: str) -> str:
        return self.areas.get(area_id) or area_id.replace("_", " ")


def is_plural(name: str) -> bool:
    last = name.lower().split()[-1] if name.strip() else name
    return last.endswith("s") and not last.endswith("ss")


def the(name: str) -> str:
    return f"the {name}"


def cap(text: str) -> str:
    return text[:1].upper() + text[1:]


def _dt(clock: HouseholdClock, iso: str | None, t: float | None) -> datetime | None:
    return clock.parse_local(iso, t)


# ---------------------------------------------------------------- objects


def where_phrase(obj: ec.ObjectSummary, labels: SpaceLabels) -> str | None:
    """Where the object is now, as a short phrase ('on the center right spot'), or None if unknown."""
    s = obj.state
    if s is None:
        return None
    if s.status == "held":
        return "off its spot (picked up and not put back yet)"
    if s.status == "missing":
        return "missing"
    if s.spot is not None:
        return f"on the {s.spot_label or f'spot {s.spot}'} spot"
    if s.area:
        return f"in {labels.area(s.area)}"
    if s.near:
        reach = {"near": "close to", "mid": "a medium distance from", "far": "far from"}
        return f"{reach.get(s.distance_class or '', 'near')} {labels.receiver(s.near)}"
    return None


def last_touched_phrase(obj: ec.ObjectSummary, clock: HouseholdClock) -> str:
    dt = _dt(clock, obj.last_touched_local, obj.last_touched_t)
    return f"last picked up or put down at {clock.when(dt)}" if dt else "no pickup or placement on record"


def last_seen_phrase(obj: ec.ObjectSummary, clock: HouseholdClock) -> str | None:
    if obj.state is None:
        return None
    dt = _dt(clock, obj.state.last_seen_local, obj.state.last_seen_t)
    return clock.when(dt) if dt else None


def describe_location(obj: ec.ObjectSummary, clock: HouseholdClock, labels: SpaceLabels) -> str:
    """One or two sentences answering 'where is X?' strictly from the object's summary."""
    name, be = obj.name, "are" if is_plural(obj.name) else "is"
    s = obj.state
    seen = last_seen_phrase(obj, clock)
    home = f"the {obj.home_spot_label} spot" if obj.home_spot_label else None

    if s is None:
        text = f"Earmark has never detected {the(name)}, so I don't know where {'they are' if is_plural(name) else 'it is'}."
        if home:
            text += f" {cap(the(name))}'s home spot is {home}."
        if obj.notes:
            text += f' Notes on file: "{obj.notes}"'
        return text

    if s.status == "on_spot":
        where = f"the {s.spot_label or f'spot {s.spot}'} spot"
        if obj.home_spot is not None and s.spot == obj.home_spot:
            where += ", where it belongs" if not is_plural(name) else ", where they belong"
        elif home:
            where += f", not {'its' if not is_plural(name) else 'their'} usual spot ({home})"
        return f"{cap(the(name))} {be} on {where}." + (f" Last confirmed there at {seen}." if seen else "")

    if s.status == "held":
        picked = _dt(clock, obj.last_touched_local, obj.last_touched_t)
        when = f" at {clock.when(picked)}" if picked else ""
        return f"{cap(the(name))} {'were' if is_plural(name) else 'was'} picked up{when} and {'have' if is_plural(name) else 'has'} not been put back on a spot since."

    if s.status == "missing":
        return f"{cap(the(name))} {be} marked missing." + (
            f" Earmark last saw {'them' if is_plural(name) else 'it'} at {seen}." if seen else ""
        )

    # roaming: located by a fob's signal
    place = where_phrase(obj, labels)
    owner = f"{cap(the(name))}' fob" if is_plural(name) else f"{cap(the(name))}'s fob"
    if obj.fob_id is None:
        owner = cap(the(name))
    if place is None:
        return f"{owner} has no current location on record." + (f" It was last detected at {seen}." if seen else "")
    text = f"{owner} was last detected {place}" + (f" at {seen}" if seen else "") + "."
    if s.precision == "proximity":
        text += " That position is approximate: the fob only reports how close it is to a receiver."
    return text


# ---------------------------------------------------------------- doses


def dose_clause(dose: ec.Dose, clock: HouseholdClock, *, with_name: bool) -> str:
    """'the 8:00 PM dose of blood pressure pills was missed (no pickup was recorded for it)'."""
    subject = f"the {schedule_time(dose.scheduled_local_time)} dose" + (f" of {dose.name}" if with_name else "")
    taken = _dt(clock, dose.taken_local, dose.taken_t)
    scheduled = _dt(clock, dose.scheduled_for_local, dose.scheduled_for_t)
    if taken is not None and scheduled is not None:
        at = clock_time(taken) if taken.date() == scheduled.date() else clock.when(taken)
    else:
        at = None
    if dose.status == "taken":
        return f"{subject} was marked taken (the bottle was picked up at {at})"
    if dose.status == "late":
        return f"{subject} was marked late (the bottle was picked up at {at}, after the on-time window)"
    if dose.status == "missed":
        return f"{subject} was missed (no pickup of the bottle was recorded for it)"
    if dose.scheduled_for_t > clock.now_t:
        return f"{subject} isn't due yet"
    return f"{subject} is due, and no pickup has been recorded yet"


def describe_day_doses(doses: Sequence[ec.Dose], clock: HouseholdClock) -> str:
    """'Yesterday (Thursday, October 23): the 8:00 AM dose of X was marked taken (...), and the 8:00 PM dose was missed (...).'"""
    if not doses:
        return ""
    day = _dt(clock, doses[0].scheduled_for_local, doses[0].scheduled_for_t).date()
    clauses, seen_names = [], set()
    for d in sorted(doses, key=lambda d: d.scheduled_for_t):
        clauses.append(dose_clause(d, clock, with_name=d.name not in seen_names))
        seen_names.add(d.name)
    body = clauses[0] if len(clauses) == 1 else ", ".join(clauses[:-1]) + ", and " + clauses[-1]
    return f"{cap(clock.day_phrase(day))}: {body}."


def dose_view(dose: ec.Dose, clock: HouseholdClock) -> dict:
    """A compact, pre-formatted dose for the LLM."""
    taken = _dt(clock, dose.taken_local, dose.taken_t)
    return {
        "medication": dose.name,
        "object_id": dose.object_id,
        "scheduled": schedule_time(dose.scheduled_local_time),
        "status": dose.status,
        "bottle_picked_up_at": clock.when(taken) if taken else None,
        "summary": cap(dose_clause(dose, clock, with_name=True)) + ".",
    }
