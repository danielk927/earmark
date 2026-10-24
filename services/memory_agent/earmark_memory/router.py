"""Deterministic keyword router and templated answers.

This is the fallback when the LLM is unavailable, and the only path for medical-advice-style
questions. Every sentence is built in code from Convex's data.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import timedelta
from typing import Literal

import earmark_contracts as ec

from .convex import ConvexError
from .describe import cap, describe_day_doses, describe_location, is_plural, last_seen_phrase, the, where_phrase
from .household import PartOfDay, part_of_day, part_of_day_for, resolve_date
from .tools import Toolbox

Intent = Literal["medication", "untouched", "where", "history", "summary", "help"]

HELP_TEXT = (
    "I answer questions from this household's Earmark records: where something is "
    "(\"Where did Dad leave his keys?\"), medication pickups (\"Did Mom take her evening pills?\"), "
    "what hasn't been touched lately (\"What hasn't been touched in a week?\"), when something was last used "
    "(\"When was the salt last used?\"), and daily summaries (\"Give me today's summary\"). "
    "I can't give medical advice."
)

_MED = r"\b(pills?|medications?|medicines?|meds|doses?|dosage|tablets?|prescriptions?|blood pressure)\b"
_TAKE = r"\b(take|took|taken|taking)\b"
_ADVICE = [
    r"\bshould\b", r"\bsafe\b", r"\b(ok|okay|alright) to\b", r"\bis (it|that) (ok|okay|bad|safe|fine|dangerous|a problem)\b",
    r"\bdouble\b", r"\bextra\b", r"\bskip\b", r"\bmake up\b", r"\bcatch up\b", r"\bhow (much|many)\b(?!.*\btimes\b)",
    r"\bmg\b", r"\bside effects?\b", r"\boverdose\b", r"\binteract", r"\bwhat (do|should|can) (i|we)\b",
    r"\bdo (i|we|they) need\b", r"\bcan (she|he|they|mom|dad|mum|i|we) (take|have|skip|stop)\b",
]
_HEALTH = [
    r"\bunder control\b", r"\bhealthy\b", r"\bhealth\b", r"\bsick\b", r"\bsymptoms?\b", r"\bdizzy\b",
    r"\bworr(y|ied)\b", r"\bblood pressure (is|was|looks?|seems?|high|low|normal|reading|okay|ok)\b",
    r"\bis (she|he|mom|mum|dad|they) (ok|okay|alright|fine|doing|well)\b",
]
_UNTOUCHED = [
    r"\b(hasn ?t|haven ?t|has not|have not|not been|never been|wasn ?t|weren ?t|nobody|no one)\b.*\b(touched|used|moved|picked up|handled|opened)\b",
    r"\buntouched\b", r"\bunused\b", r"\bnot (touched|used)\b",
]
_WHERE = r"\b(where|find|leave|left|put|locate|location|lost|misplaced)\b"
_HISTORY = r"\b(when|last time|last used|how many times|how often|history)\b"
_SUMMARY = r"\b(summary|summarize|summarise|recap|overview|how was|what happened|anything (unusual|new)|today|yesterday|this week)\b"

_STOPWORDS = set(
    """where whereabouts did does do is are was were the a an my his her their our your its mom mum mother dad father
    grandma grandpa grandmother grandfather he she they them him i we you me leave left put place placed find found
    can could cant can t see seen last any idea earmark please tell know what about of keep kept go gone went
    when time times used use using touched picked up pick moved how many often history lately recently today
    yesterday s it there here now currently at in on to for from with be been has have had lost misplaced locate
    location hello hi hey thanks thank good morning afternoon evening help""".split()
)


@dataclass(frozen=True)
class Analysis:
    intent: Intent
    medical: bool  # dosing or health-interpretation question: answered with facts only, never by the LLM
    asks_what_to_do: bool
    part: PartOfDay | None
    untouched_days: int
    pronoun: str  # "her" | "his" | "their"

    @property
    def needs_data(self) -> bool:
        return self.intent != "help"


def _norm(text: str) -> str:
    return " " + re.sub(r"[^a-z0-9: ]+", " ", text.lower().replace("'", " ").replace("’", " ")) + " "


def _any(patterns: list[str], text: str) -> bool:
    return any(re.search(p, text) for p in patterns)


def _untouched_days(q: str) -> int:
    m = re.search(r"\b(\d{1,3}) days?\b", q)
    if m:
        return max(1, int(m.group(1)))
    m = re.search(r"\b(\d|two|three|four) weeks?\b", q)
    if m:
        n = {"two": 2, "three": 3, "four": 4}.get(m.group(1)) or int(m.group(1))
        return 7 * n
    if re.search(r"\bmonth\b", q):
        return 30
    return 7


def analyze(question: str) -> Analysis:
    q = _norm(question)
    med_topic = bool(re.search(_MED, q))
    advice = _any(_ADVICE, q) and (med_topic or _any(_HEALTH, q) or bool(re.search(_TAKE, q)))
    medical = advice or _any(_HEALTH, q)

    asks_where = bool(re.search(_WHERE, q)) and not re.search(_TAKE, q)
    if asks_where and not medical:
        intent: Intent = "where"
    elif med_topic or re.search(_TAKE, q):
        intent = "medication"
    elif _any(_UNTOUCHED, q):
        intent = "untouched"
    elif re.search(_WHERE, q):
        intent = "where"
    elif re.search(_HISTORY, q):
        intent = "history"
    elif re.search(_SUMMARY, q):
        intent = "summary"
    else:
        intent = "help"

    if re.search(r"\b(mom|mum|mother|she|her|grandma|grandmother|wife|aunt)\b", q):
        pronoun = "her"
    elif re.search(r"\b(dad|father|he|his|him|grandpa|grandfather|husband|uncle)\b", q):
        pronoun = "his"
    else:
        pronoun = "their"
    return Analysis(intent, medical, advice, part_of_day(question), _untouched_days(q), pronoun)


def object_phrase(question: str) -> str:
    """The object words of a question: 'Where did Dad leave his keys?' -> 'keys'."""
    words = [w for w in _norm(question).split() if w not in _STOPWORDS and not w.isdigit()]
    return " ".join(words)


def match_object_in_text(question: str, objects: list[ec.ObjectSummary]) -> ec.ObjectSummary | None:
    """The object whose name or alias appears in the question (longest match wins)."""
    q = _norm(question)
    best: tuple[int, ec.ObjectSummary] | None = None
    for o in objects:
        for label in [o.name, *o.aliases]:
            label_n = _norm(label).strip()
            stem = label_n[:-1] if label_n.endswith("s") else label_n
            if label_n and re.search(rf"\b{re.escape(stem)}s?\b", q) and (best is None or len(label_n) > best[0]):
                best = (len(label_n), o)
    return best[1] if best else None


# ---------------------------------------------------------------- answers

async def answer(question: str, tb: Toolbox, a: Analysis | None = None) -> str:
    a = a or analyze(question)
    try:
        if a.medical:
            return await _medical(question, a, tb)
        if a.intent == "medication":
            return await _medication(question, a, tb)
        if a.intent == "untouched":
            return await _untouched(a, tb)
        if a.intent == "where":
            return await _where(question, tb)
        if a.intent == "history":
            return await _history(question, tb)
        if a.intent == "summary":
            return await _summary(question, tb)
        return await _help_or_object(question, tb)
    except ConvexError as exc:
        return unreachable_text(exc)


def unreachable_text(exc: ConvexError) -> str:
    if exc.kind == "not_found":
        return f"Earmark's records have no match for that ({exc})."
    return f"I can't reach Earmark's records right now ({exc}). Please try again in a minute."


def _filter(doses: list[ec.Dose], part: PartOfDay | None) -> list[ec.Dose]:
    return [d for d in doses if part is None or part_of_day_for(d.scheduled_local_time) == part]


async def _dose_facts(question: str, a: Analysis, tb: Toolbox) -> tuple[str, str]:
    """(lead, facts) for the medication doses a question is about."""
    clock = tb.clock
    explicit = resolve_date(question, clock.today)
    day = explicit or clock.today
    resp = await tb.adherence(day.isoformat() if day != clock.today else None)
    if not resp.doses:
        return "", f"Earmark has no medication doses on record for {clock.relative_day(day) or clock.date_name(day)}."
    doses = _filter(resp.doses, a.part)
    if not doses:
        times = " and ".join(sorted({d.scheduled_local_time for d in resp.doses}))
        return "", f"There's no {a.part} dose on the schedule {clock.day_phrase(day)} (scheduled times: {times})."

    sentences = [describe_day_doses(doses, clock)]
    lead = ""
    if explicit is None and all(d.status == "pending" for d in doses):
        # Nothing has settled today yet, so also report the most recent settled day.
        y = clock.today - timedelta(days=1)
        ydoses = _filter((await tb.adherence(y.isoformat())).doses, a.part)
        if ydoses:
            sentences.append(describe_day_doses(ydoses, clock))
        lead = "Not yet tonight." if a.part == "evening" else "Not yet today."
    elif len(doses) == 1:
        lead = {
            "taken": "Yes.",
            "late": "Yes, but late.",
            "missed": "Not according to Earmark's records.",
            "pending": "Not yet.",
        }[doses[0].status]
    return lead, " ".join(sentences)


async def _medication(question: str, a: Analysis, tb: Toolbox) -> str:
    lead, facts = await _dose_facts(question, a, tb)
    return f"{lead} {facts}".strip()


async def _medical(question: str, a: Analysis, tb: Toolbox) -> str:
    _, facts = await _dose_facts(question, a, tb)
    text = "I can't give medical advice or interpret health. Earmark only records when the pill bottle is picked up. "
    text += f"Here's what the records show: {facts}"
    if a.asks_what_to_do:
        text += f" For what to do, please check with {a.pronoun} clinician or pharmacist."
    return text


async def _resolve_object(question: str, tb: Toolbox) -> tuple[ec.ObjectSummary | None, list[ec.ObjectSummary], str]:
    phrase = object_phrase(question)
    others: list[ec.ObjectSummary] = []
    if phrase:
        found = await tb.find_object(phrase)
        if found.matches:
            return found.matches[0], found.matches[1:], phrase
    everything = (await tb.list_objects()).objects
    obj = match_object_in_text(question, everything)
    if obj is None:
        others = everything
    return obj, [] if obj else others, phrase


def _not_found(phrase: str, known: list[ec.ObjectSummary]) -> str:
    what = f"\"{phrase}\"" if phrase else "that"
    names = ", ".join(o.name for o in known)
    return f"I couldn't find {what} in Earmark's records." + (f" Earmark tracks: {names}." if names else "")


async def _where(question: str, tb: Toolbox) -> str:
    obj, others, phrase = await _resolve_object(question, tb)
    if obj is None:
        return _not_found(phrase, others)
    text = describe_location(obj, tb.clock, tb.labels)
    if others:
        text += " I also found " + ", ".join(the(o.name) for o in others[:2]) + "; ask about one by name."
    return text


async def _history(question: str, tb: Toolbox) -> str:
    obj, others, phrase = await _resolve_object(question, tb)
    if obj is None:
        return _not_found(phrase, others)
    clock, name = tb.clock, obj.name
    h = await tb.history(obj.object_id)
    touches = [e for e in h.events if e.kind in ("pickup", "placed")]
    if not touches:
        text = f"Earmark recorded no pickups or put-downs of {the(name)} in the last 7 days."
        if obj.state is not None:
            seen = last_seen_phrase(obj, clock)
            place = where_phrase(obj, tb.labels)
            if seen and place:
                text += f" {cap(the(name))} {'were' if is_plural(name) else 'was'} last detected {place} at {seen}."
        return text
    pickups = [e for e in touches if e.kind == "pickup"]
    latest = pickups[0] if pickups else touches[0]
    verb = "picked up" if latest.kind == "pickup" else "put down"
    spot = f" {'from' if latest.kind == 'pickup' else 'on'} the {latest.spot_label} spot" if latest.spot_label else ""
    text = f"{cap(the(name))} {'were' if is_plural(name) else 'was'} last {verb} at {clock.when(clock.parse_local(latest.at_local, latest.t))}{spot}."
    after = [e for e in touches if e.t > latest.t and e.kind == "placed"]
    if latest.kind == "pickup" and after:
        back = after[-1]
        text += f" {'They were' if is_plural(name) else 'It was'} put back" + (
            f" on the {back.spot_label} spot" if back.spot_label else "") + f" at {clock.when(clock.parse_local(back.at_local, back.t))}."
    n = len(pickups)
    text += f" In the last 7 days, Earmark recorded {n} pickup{'s' if n != 1 else ''}."
    return text


async def _untouched(a: Analysis, tb: Toolbox) -> str:
    clock = tb.clock
    objects = (await tb.list_objects()).objects
    cutoff = clock.now_t - a.untouched_days * 86400
    window = "the last week" if a.untouched_days == 7 else f"the last {a.untouched_days} days"

    def fob_only(o: ec.ObjectSummary) -> bool:
        return o.fob_id is not None and o.home_spot is None and o.last_touched_t is None

    stale = [o for o in objects if not fob_only(o) and (o.last_touched_t is None or o.last_touched_t < cutoff)]
    if stale:
        items = []
        for o in stale:
            dt = clock.parse_local(o.last_touched_local, o.last_touched_t)
            items.append(f"{the(o.name)} ({'last picked up or put down at ' + clock.when(dt) if dt else 'no pickup or put-down on record'})")
        text = f"Not picked up or put down in {window}: " + "; ".join(items) + "."
    else:
        text = f"Everything on a spot reader was picked up or put down in {window}."
    for o in (o for o in objects if fob_only(o)):
        seen, place = last_seen_phrase(o, clock), where_phrase(o, tb.labels)
        text += f" {cap(the(o.name))} {'are' if is_plural(o.name) else 'is'} tracked by a Bluetooth fob, which doesn't record pickups"
        text += f"; the fob was last detected {place} at {seen}." if seen and place else "."
    return text


async def _summary(question: str, tb: Toolbox) -> str:
    day = resolve_date(question, tb.clock.today)
    s = await tb.daily_summary(day.isoformat() if day and day != tb.clock.today else None)
    return s.text


async def _help_or_object(question: str, tb: Toolbox) -> str:
    """No keyword matched: if the question names a tracked object, say where it is; otherwise explain."""
    if object_phrase(question):
        everything = (await tb.list_objects()).objects
        obj = match_object_in_text(question, everything)
        if obj is not None:
            return describe_location(obj, tb.clock, tb.labels)
    return HELP_TEXT
