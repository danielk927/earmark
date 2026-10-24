"""Trial mode (brief 5.I): timing and wrong-pick counting, computed only from bus events.

`TrialSession` is pure: feed it bus messages and the current time; it returns the
`trial_end` once the trial is over. Nothing here invents or edits a measurement.
"""
from __future__ import annotations

import random
import re
import uuid
from dataclasses import dataclass, field

from earmark_contracts import Pickup, PickupResult, RegistryObject, TrialEnd, TrialStart

CONFIRM_WAIT_S = 1.0
PSEUDONYM_WORDS = {"tester", "test", "participant", "subject", "user", "pilot", "p", "t"}


def looks_like_real_name(text: str) -> bool:
    """True for anything that could be a real person's name (we only store pseudonyms)."""
    s = text.strip()
    if "@" in s:
        return True
    words = [w for w in re.split(r"[\s._,]+", s) if w]
    name_like = [w for w in words if re.fullmatch(r"[A-Za-z][A-Za-z'\-]+", w) and w.lower() not in PSEUDONYM_WORDS]
    return len(words) >= 2 and len(name_like) >= 2


def validate_pseudonym(text: str) -> str | None:
    """Error message, or None if `text` is an acceptable pseudonym."""
    s = text.strip()
    if not s:
        return "enter a pseudonym such as tester-A"
    if len(s) > 32:
        return "keep it under 32 characters (e.g. tester-A)"
    if looks_like_real_name(s):
        return "that looks like a real name; use a pseudonym such as tester-A"
    return None


def new_trial_id() -> str:
    return f"trial-{uuid.uuid4().hex[:12]}"


def suggest(history: list[TrialEnd], objects: list[RegistryObject], rng: random.Random | None = None) -> tuple[str, str | None]:
    """Suggested (mode, target): alternate modes; random target among spot objects, not the last one."""
    rng = rng or random.Random()
    mode = "baseline" if history and history[-1].mode == "earmark" else "earmark"
    candidates = [o.object_id for o in objects if o.tag and o.home_spot is not None]
    if history and len(candidates) > 1:
        candidates = [c for c in candidates if c != history[-1].target_object_id] or candidates
    return mode, (rng.choice(candidates) if candidates else None)


@dataclass
class TrialSession:
    start: TrialStart
    confirm_wait_s: float = CONFIRM_WAIT_S
    wrong_picks: int = 0
    _found_t: float | None = None
    _found_at: float | None = None  # local time the target pickup arrived
    _confirmed: bool = False
    picks: list[str] = field(default_factory=list)

    @property
    def confirmed(self) -> bool:
        return self._confirmed

    def on_message(self, msg, now: float) -> TrialEnd | None:
        if isinstance(msg, Pickup):
            if msg.t < self.start.t:
                return None
            self.picks.append(msg.object_id)
            if msg.object_id != self.start.target_object_id:
                self.wrong_picks += 1
                return None
            if self._found_t is None:
                self._found_t, self._found_at = msg.t, now
            if self.start.mode == "baseline" or self._confirmed:
                return self._end("found", now)
        elif isinstance(msg, PickupResult):
            if msg.correct and msg.actual == self.start.target_object_id and msg.t >= self.start.t:
                self._confirmed = True
                if self._found_t is not None:
                    return self._end("found", now)
        return None

    def poll(self, now: float) -> TrialEnd | None:
        """Earmark mode: without a confirming pickup_result, end on the pickup itself after the wait."""
        if self._found_at is not None and now - self._found_at >= self.confirm_wait_s:
            return self._end("found", now)
        return None

    def give_up(self, now: float) -> TrialEnd:
        return self._end("gave_up", now)

    def abort(self, now: float) -> TrialEnd:
        return self._end("aborted", now)

    def _end(self, outcome: str, now: float) -> TrialEnd:
        seconds = round(self._found_t - self.start.t, 3) if outcome == "found" and self._found_t is not None else None
        return TrialEnd(trial_id=self.start.trial_id, mode=self.start.mode,
                        target_object_id=self.start.target_object_id, tester=self.start.tester,
                        outcome=outcome, started_t=self.start.t, seconds_to_find=seconds,
                        wrong_picks=self.wrong_picks, t=now)
