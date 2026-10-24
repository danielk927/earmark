"""Household time: the clock, date resolution ("yesterday", "on Thursday"), and time phrasing.

All date and time math lives here, in code. The LLM only ever sees pre-formatted strings.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from typing import Literal
from zoneinfo import ZoneInfo

PartOfDay = Literal["morning", "afternoon", "evening"]

_WEEKDAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
_MONTHS = {
    name: i + 1
    for i, names in enumerate(
        [("january", "jan"), ("february", "feb"), ("march", "mar"), ("april", "apr"), ("may",),
         ("june", "jun"), ("july", "jul"), ("august", "aug"), ("september", "sep", "sept"),
         ("october", "oct"), ("november", "nov"), ("december", "dec")]
    )
    for name in names
}
_MONTH_RE = "|".join(sorted(_MONTHS, key=len, reverse=True))


@dataclass(frozen=True)
class HouseholdClock:
    """The household's "now" and timezone, as reported by Convex (or the fixture)."""

    now_t: float
    timezone: str

    @property
    def tz(self) -> ZoneInfo:
        return ZoneInfo(self.timezone)

    @property
    def now(self) -> datetime:
        return datetime.fromtimestamp(self.now_t, self.tz)

    @property
    def today(self) -> date:
        return self.now.date()

    def local(self, t: float) -> datetime:
        return datetime.fromtimestamp(t, self.tz)

    def day_start_t(self, d: date) -> float:
        return datetime.combine(d, time(0, 0), self.tz).timestamp()

    def parse_local(self, iso: str | None, t: float | None = None) -> datetime | None:
        """A Convex `*_local` ISO string (already household time), else `t` converted."""
        if iso:
            try:
                return datetime.fromisoformat(iso)
            except ValueError:
                pass
        return self.local(t) if t is not None else None

    # ------------------------------------------------------------ phrasing

    def date_name(self, d: date) -> str:
        """'Thursday, October 23' (with the year only if it isn't the current year)."""
        text = f"{_WEEKDAYS[d.weekday()].capitalize()}, {d.strftime('%B')} {d.day}"
        return text if d.year == self.today.year else f"{text}, {d.year}"

    def relative_day(self, d: date) -> str | None:
        delta = (d - self.today).days
        return {0: "today", -1: "yesterday", 1: "tomorrow"}.get(delta)

    def day_phrase(self, d: date) -> str:
        """'today (Friday, October 24)', 'yesterday (Thursday, October 23)', or 'on Tuesday, October 21'."""
        rel = self.relative_day(d)
        return f"{rel} ({self.date_name(d)})" if rel else f"on {self.date_name(d)}"

    def when(self, dt: datetime) -> str:
        """'8:15 AM today', '8:05 AM yesterday', or '8:05 AM on Tuesday, October 21'."""
        dt = dt.astimezone(self.tz)
        rel = self.relative_day(dt.date())
        return f"{clock_time(dt)} {rel}" if rel else f"{clock_time(dt)} on {self.date_name(dt.date())}"

    def now_phrase(self) -> str:
        return f"{clock_time(self.now)} on {self.date_name(self.today)}"


def clock_time(dt: datetime | time) -> str:
    """'8:05 AM', '12:30 PM'."""
    hour12 = dt.hour % 12 or 12
    return f"{hour12}:{dt.minute:02d} {'AM' if dt.hour < 12 else 'PM'}"


def schedule_time(hhmm: str) -> str:
    """'20:00' -> '8:00 PM'."""
    h, m = (int(x) for x in hhmm.split(":"))
    return clock_time(time(h, m))


def part_of_day_for(hhmm: str) -> PartOfDay:
    hour = int(hhmm.split(":")[0])
    if hour < 12:
        return "morning"
    if hour < 17:
        return "afternoon"
    return "evening"


# ---------------------------------------------------------------- parsing questions

def _words(text: str) -> str:
    return " " + re.sub(r"[^a-z0-9:/\- ]+", " ", text.lower()) + " "


def part_of_day(text: str) -> PartOfDay | None:
    """Which part of the day a question is about: 'evening pills' -> evening (the 20:00 dose)."""
    w = _words(text)
    clock = re.search(r"\b(\d{1,2})(?::(\d{2}))?\s*(am|pm)\b", w) or re.search(r"\b([01]?\d|2[0-3]):([0-5]\d)\b", w)
    if clock:
        hour = int(clock.group(1)) % 12 if clock.lastindex == 3 else int(clock.group(1))
        if clock.lastindex == 3 and clock.group(3) == "pm":
            hour += 12
        return part_of_day_for(f"{hour:02d}:00")
    if re.search(r"\b(evening|tonight|night|bedtime|dinner|supper)\b", w):
        return "evening"
    if re.search(r"\b(morning|breakfast)\b", w):
        return "morning"
    if re.search(r"\b(afternoon|lunch|midday|noon)\b", w):
        return "afternoon"
    return None


def resolve_date(text: str, today: date) -> date | None:
    """The household date a question or tool argument refers to, or None if it names none.

    Understands: YYYY-MM-DD, today/tonight/this morning, yesterday/last night,
    the day before yesterday, N days ago, weekday names, 'October 23', '10/23'.
    """
    w = _words(text)
    m = re.search(r"\b(\d{4})-(\d{2})-(\d{2})\b", w)
    if m:
        try:
            return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except ValueError:
            return None
    if re.search(r"\bday before yesterday\b", w):
        return today - timedelta(days=2)
    if re.search(r"\b(yesterday|last night|last evening)\b", w):
        return today - timedelta(days=1)
    m = re.search(r"\b(\d{1,2}) days? ago\b", w)
    if m:
        return today - timedelta(days=int(m.group(1)))
    if re.search(r"\b(today|tonight|this (morning|afternoon|evening))\b", w):
        return today
    m = re.search(rf"\b({_MONTH_RE})\.? (\d{{1,2}})(st|nd|rd|th)?\b", w) or re.search(
        rf"\b(\d{{1,2}})(st|nd|rd|th)? (of )?({_MONTH_RE})\b", w
    )
    if m:
        if m.group(1).isdigit():
            day_num, month = int(m.group(1)), _MONTHS[m.group(4)]
        else:
            day_num, month = int(m.group(2)), _MONTHS[m.group(1)]
        return _past_date(today, month, day_num)
    m = re.search(r"\b(\d{1,2})/(\d{1,2})\b", w)
    if m:
        return _past_date(today, int(m.group(1)), int(m.group(2)))
    for i, name in enumerate(_WEEKDAYS):
        if re.search(rf"\b{name}\b", w):
            back = (today.weekday() - i) % 7
            if back == 0 and re.search(rf"\blast {name}\b", w):
                back = 7
            return today - timedelta(days=back)
    return None


def _past_date(today: date, month: int, day_num: int) -> date | None:
    """A month/day without a year: this year's, or last year's if that would be in the future."""
    try:
        d = date(today.year, month, day_num)
    except ValueError:
        return None
    if d > today:
        try:
            d = date(today.year - 1, month, day_num)
        except ValueError:
            return None
    return d
