"""Deterministic phrase building: directions, distances, relative spots, times.

Coordinates are Earmark's: meters, +x right, +y forward, origin at the
calibrated head position (contracts/README.md). Nothing here calls an LLM.
"""
from __future__ import annotations

import math
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

_NUMBERS = [
    "zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten",
    "eleven", "twelve", "thirteen", "fourteen", "fifteen", "sixteen", "seventeen", "eighteen",
    "nineteen", "twenty",
]
_ARTICLES = ("the ", "my ", "a ", "an ", "some ", "our ")

# Distance bands (meters, horizontal distance from the listener's head).
EASY_REACH_M = 0.45
ARM_LENGTH_M = 0.8
ONE_STEP_M = 1.5
STEP_M = 0.75


def number_word(n: int) -> str:
    return _NUMBERS[n] if 0 <= n < len(_NUMBERS) else str(n)


def _round_half_away(x: float) -> int:
    return int(math.floor(abs(x) + 0.5)) * (1 if x >= 0 else -1)


def azimuth_deg(x: float, y: float) -> float:
    """Degrees clockwise from the calibrated forward direction (+y); right is positive."""
    return math.degrees(math.atan2(x, y))


def clock_hour(x: float, y: float) -> int:
    """12 = straight ahead, 3 = right, 6 = behind, 9 = left."""
    h = _round_half_away(azimuth_deg(x, y) / 30.0) % 12
    return 12 if h == 0 else h


def clock_phrase(x: float, y: float) -> str:
    return f"at your {number_word(clock_hour(x, y))} o'clock"


def horizontal_distance(x: float, y: float) -> float:
    return math.hypot(x, y)


def distance_phrase(d: float) -> str:
    if d < EASY_REACH_M:
        return "within easy reach"
    if d < ARM_LENGTH_M:
        return "about an arm's length away"
    if d < ONE_STEP_M:
        return "about a step away"
    return f"about {number_word(max(2, round(d / STEP_M)))} steps away"


# Tracked guidance (UWB listener_pose, PRD 11.1): beyond this the listener is not "at the
# counter", so plain-word directions and meters beat the clock face.
TRACKED_MIN_M = 1.2
LOST_MESSAGE = "I've lost track of where you are. Walk to the counter and say 'I'm here'."
AT_COUNTER = "You're at the counter."


def relative_direction(dx: float, dy: float, yaw_deg: float = 0.0) -> str:
    """Plain-word direction of an offset for a listener facing `yaw_deg` (degrees clockwise from +y).

    yaw 0 is the room frame (facing the counter).
    """
    a = (azimuth_deg(dx, dy) - yaw_deg + 180.0) % 360.0 - 180.0
    side = "right" if a > 0 else "left"
    m = abs(a)
    if m <= 15:
        return "ahead of you"
    if m <= 60:
        return f"ahead of you, a little to the {side}"
    if m <= 120:
        return f"to your {side}"
    if m <= 150:
        return f"behind you, a little to the {side}"
    return "behind you"


def meters_phrase(d: float) -> str:
    """Nearest half meter: 'about 3 meters', 'about 2 and a half meters'."""
    halves = _round_half_away(d * 2)
    whole, half = divmod(halves, 2)
    if half:
        return f"about {whole} and a half meters" if whole else "about half a meter"
    return f"about {whole} meter{'' if whole == 1 else 's'}"


def direction_phrase(position: list[float], listener: list[float] | None = None,
                     mode: str = "fixed", yaw: float | None = None) -> str:
    """Where `position` (counter frame) is from the listener.

    tracked and > 1.2 m away: 'ahead of you, a little to the right, about 3 meters'.
    Otherwise (frozen, fixed, lost, or close) the clock face: 'at your one o'clock, about an
    arm's length away'. The lost *message* is not a direction; the core says it once per guidance.
    With no listener the origin is used, which is the pre-UWB behavior. `yaw` (fresh head yaw,
    degrees from calibrated forward, right positive) turns the tracked words to where the user
    is facing; None means the room frame. The clock face always uses calibrated forward.
    """
    lx, ly = (listener[0], listener[1]) if listener else (0.0, 0.0)
    x, y = position[0] - lx, position[1] - ly
    d = horizontal_distance(x, y)
    if mode == "tracked" and d > TRACKED_MIN_M:
        return f"{relative_direction(x, y, yaw or 0.0)}, {meters_phrase(d)}"
    return f"{clock_phrase(x, y)}, {distance_phrase(d)}"


def relative_spot_phrase(from_index: int, to_index: int) -> str | None:
    """Indices into the left-to-right spot order. None when they are the same spot."""
    d = to_index - from_index
    if d == 0:
        return None
    n = abs(d)
    side = "right" if d > 0 else "left"
    return f"{number_word(n)} spot{'s' if n > 1 else ''} to your {side}"


# ---------------------------------------------------------------- names

def bare_name(name: str) -> str:
    n = name.strip()
    low = n.lower()
    for a in _ARTICLES:
        if low.startswith(a):
            return n[len(a):].strip()
    return n


def is_plural(name: str) -> bool:
    last = bare_name(name).lower().split()[-1] if bare_name(name) else ""
    return len(last) > 2 and last.endswith("s") and not last.endswith(("ss", "us"))


def the(name: str) -> str:
    return "the " + bare_name(name)


def cap(s: str) -> str:
    return s[:1].upper() + s[1:]


class Grammar:
    """Pronoun and verb agreement for one object name."""

    def __init__(self, name: str) -> None:
        self.plural = is_plural(name)
        self.it = "them" if self.plural else "it"
        self.its = "they're" if self.plural else "it's"
        self.is_ = "are" if self.plural else "is"
        self.was = "were" if self.plural else "was"
        self.has = "have" if self.plural else "has"
        self.does = "don't" if self.plural else "doesn't"


def join_or(items: list[str]) -> str:
    if len(items) <= 1:
        return "".join(items)
    if len(items) == 2:
        return f"{items[0]} or {items[1]}"
    return ", ".join(items[:-1]) + f", or {items[-1]}"


def join_and(items: list[str]) -> str:
    if len(items) <= 1:
        return "".join(items)
    if len(items) == 2:
        return f"{items[0]} and {items[1]}"
    return ", ".join(items[:-1]) + f", and {items[-1]}"


# ---------------------------------------------------------------- times

def clock_time(t: float, tz: str) -> str:
    local = datetime.fromtimestamp(t, ZoneInfo(tz))
    hour = local.hour % 12 or 12
    return f"{hour}:{local.minute:02d} {'AM' if local.hour < 12 else 'PM'}"


def time_phrase(t: float, now: float, tz: str) -> str:
    """'at 8:12 PM' today; 'yesterday at ...'; weekday within a week; else month and day."""
    zone = ZoneInfo(tz)
    local = datetime.fromtimestamp(t, zone)
    today = datetime.fromtimestamp(now, zone).date()
    hm = clock_time(t, tz)
    if local.date() == today:
        return f"at {hm}"
    if local.date() == today - timedelta(days=1):
        return f"yesterday at {hm}"
    if today - timedelta(days=6) <= local.date() < today:
        return f"on {local.strftime('%A')} at {hm}"
    return f"on {local.strftime('%B')} {local.day} at {hm}"
