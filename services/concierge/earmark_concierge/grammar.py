"""Keyword fallback grammar (BUILD_BRIEF 5.D) for when the LLM is slow, down, or off.

parse() maps an utterance to a ToolCall whose object is a free-text `query`
(resolved later by the resolver), or returns None.
"""
from __future__ import annotations

import re

from .tools import ToolCall, clean_name

_FILLER_TAIL = re.compile(
    r"(?:\s+(?:please|for me|right now|now|again|today|yet|this morning|this evening|tonight|"
    r"last night|at all|is|are|go))+$"
)
_DET = r"(?:(?:my|the|a|an|our|some|his|her|their)\s+)?"

_STOP = re.compile(r"\b(?:stop|cancel|never ?mind|nevermind|be quiet|quiet|that's enough|enough)\b")
_HERE = re.compile(r"^(?:(?:ok|okay|so|alright|hey earmark)\s+)*(?:i'm|im|i am)\s+here(?:\s+(?:now|please))?$")
_RECENTER = re.compile(r"\bre ?center\b")
_LABEL = re.compile(
    r"^(?:(?:ok|okay|so|and|now|hey earmark)\s+)*"
    r"(?:this(?: one| item| thing)? is(?: called| named)?|call this(?: one)?|label this(?: one)?(?: as)?|"
    r"name this(?: one)?|this is going to be)\s+" + _DET + r"(?P<x>.+)$"
)
_CHIRP = (
    re.compile(r"\bmake\s+" + _DET + r"(?P<x>.+?)\s+(?:beep|chirp|ring|buzz|make a sound|make noise|sound)\b"),
    re.compile(r"\b(?:beep|chirp|ring|buzz|ping)\s+" + _DET + r"(?P<x>.+)$"),
)
_LAST_SEEN = (
    re.compile(r"\b(?:when did i(?: last)?|did i(?: already)?|have i(?: already)?)\s+"
               r"(?:take|taken|use|used|have|had|touch|touched|pick up|picked up|move|moved)\s+"
               + _DET + r"(?P<x>.+)$"),
    re.compile(r"\bwhen (?:was|were)\s+" + _DET + r"(?P<x>.+?)\s+last\s+"
               r"(?:taken|used|picked up|touched|moved|seen)\b"),
    re.compile(r"\bwhen did you last see\s+" + _DET + r"(?P<x>.+)$"),
    # Advice-seeking ("should I take my pills") is answered with facts only (core.ADVICE).
    re.compile(r"\b(?:should|can|may|do) i (?:take|have|use)\s+" + _DET + r"(?P<x>.+)$"),
    re.compile(r"\b(?:last seen|last time i (?:took|used|had))\s+" + _DET + r"(?P<x>.+)$"),
)
_GUIDE = re.compile(r"\b(?:take|guide|lead|bring)\s+me\s+to\s+" + _DET + r"(?P<x>.+)$")
_WHERE = re.compile(
    r"\b(?:where(?:'s| is| are|'re| r| did i (?:put|leave)| have i (?:put|left)| did (?:you|someone) put)?|"
    r"find|locate|look for|looking for|search for|help me find|can you find|could you find|"
    r"i need|i want|get me|show me)\s+(?:me\s+)?" + _DET + r"(?P<x>.+)$"
)
_SOMETHING = re.compile(r"\b(?P<x>something\s+(?:for|to|that|i can|you use)\b.+)$")
_LIST = re.compile(
    r"\b(?:what do you know|what (?:items|things|objects) do you (?:know|track|have)|"
    r"list (?:everything|all|items|objects|things)|what can you find|what's on the counter|"
    r"what is on the counter)\b"
)


def normalize(text: str) -> str:
    s = text.replace("’", "'").replace("‘", "'").lower()
    s = re.sub(r"[^a-z0-9' ]+", " ", s)
    return " ".join(s.split())


def _clean_x(x: str) -> str:
    x = _FILLER_TAIL.sub("", x.strip())
    return clean_name(x)


def parse(text: str, known_terms: set[str] | None = None) -> ToolCall | None:
    s = normalize(text)
    if not s:
        return None
    if _HERE.match(s):
        return ToolCall("freeze_listener")
    if _RECENTER.search(s) and not re.search(r"\b(?:where|find)\b", s):
        return ToolCall("recenter_listener")
    if _STOP.search(s) and not re.search(r"\b(?:where|find)\b", s):
        return ToolCall("stop_guidance")
    m = _LABEL.search(s)
    if m and _clean_x(m["x"]):
        return ToolCall("label_object", {"tag": "", "name": _clean_x(m["x"]), "aliases": []})
    for rx in _CHIRP:
        m = rx.search(s)
        if m and _clean_x(m["x"]):
            return ToolCall("chirp_fob", {"query": _clean_x(m["x"])})
    for rx in _LAST_SEEN:
        m = rx.search(s)
        if m and _clean_x(m["x"]):
            return ToolCall("last_seen", {"query": _clean_x(m["x"])})
    if _LIST.search(s):
        return ToolCall("list_objects")
    m = _GUIDE.search(s)
    if m and _clean_x(m["x"]):
        return ToolCall("guide_to_object", {"query": _clean_x(m["x"])})
    m = _SOMETHING.search(s)
    if m:
        return ToolCall("locate_object", {"query": _clean_x(m["x"])})
    m = _WHERE.search(s)
    if m and _clean_x(m["x"]):
        return ToolCall("locate_object", {"query": _clean_x(m["x"])})
    bare = _clean_x(s)
    if known_terms and bare in known_terms:
        return ToolCall("locate_object", {"query": bare})
    return None
