#!/usr/bin/env python3
"""Summarize logs/latency.jsonl (written by the concierge) per stage and end to end.

End to end is final transcript -> first audible audio: the Mac app's `playback`
started event when present, otherwise the time the first speech message left the
concierge (marked "emitted", since nothing confirmed it was heard).
Budget (BUILD_BRIEF 5.D): 1.2 s target, 2.0 s maximum.

Usage: python3 scripts/latency_report.py [path/to/latency.jsonl]
Stdlib only, so any Python 3.9+ runs it.
"""
from __future__ import annotations

import json
import math
import statistics
import sys
from collections import Counter, defaultdict
from pathlib import Path

TARGET_MS = 1200.0
MAX_MS = 2000.0
DEFAULT = Path(__file__).resolve().parent.parent / "logs" / "latency.jsonl"


def p90(xs: list[float]) -> float:
    s = sorted(xs)
    return s[max(0, math.ceil(0.9 * len(s)) - 1)]


def row(name: str, xs: list[float], note: str = "") -> str:
    if not xs:
        return f"  {name:<34} {'-':>6} {'-':>9} {'-':>9} {'-':>9}  {note}"
    return (f"  {name:<34} {len(xs):>6} {statistics.median(xs):>9.1f} {p90(xs):>9.1f} {max(xs):>9.1f}  {note}")


def load(path: Path) -> list[dict]:
    recs = []
    for line in path.read_text().splitlines():
        line = line.strip()
        if line:
            try:
                recs.append(json.loads(line))
            except ValueError:
                continue
    return recs


def report(recs: list[dict]) -> str:
    by_event: dict[str, list[dict]] = defaultdict(list)
    for r in recs:
        by_event[r.get("event", "")].append(r)

    intents = by_event["intent"]
    llm_ms = [r["llm_ms"] for r in intents if r.get("llm_ms") is not None]
    llm_won = [r["llm_ms"] for r in intents if r.get("path") == "llm" and r.get("llm_ms") is not None]
    decide_ms = [r["ms"] for r in intents if r.get("ms") is not None]
    moss_ms = [r["moss_ms"] for r in by_event["resolve"] if r.get("moss_ms") is not None]
    tts_ms = [r["ms"] for r in by_event["tts_first_chunk"] if r.get("ms") is not None]

    first_out: dict[str, float] = {}
    for r in by_event["speech_out"]:
        t, v = r.get("turn"), r.get("since_final_ms")
        if t and v is not None:
            first_out[t] = min(v, first_out.get(t, math.inf))
    heard: dict[str, float] = {}
    for r in by_event["playback"]:
        t, v = r.get("turn"), r.get("since_final_ms")
        if t and v is not None:
            heard[t] = min(v, heard.get(t, math.inf))
    e2e_heard = list(heard.values())
    e2e_emitted = [v for t, v in first_out.items() if t not in heard]
    e2e = e2e_heard + e2e_emitted

    paths = Counter(r.get("path") for r in intents)
    statuses = Counter(r.get("llm_status") for r in intents)
    engines = Counter(r.get("engine") for r in by_event["resolve"])
    kinds = Counter(r.get("kind") for r in by_event["speech_out"])

    out = [f"Earmark latency report: {len(by_event['final_transcript'])} final transcripts", "",
           f"  {'stage (ms)':<34} {'n':>6} {'median':>9} {'p90':>9} {'max':>9}",
           row("intent decision (LLM race)", decide_ms),
           row("Bitdeer LLM call (all)", llm_ms, "vendor: bitdeer"),
           row("Bitdeer LLM call (used)", llm_won),
           row("Moss query", moss_ms, "vendor: moss"),
           row("Cartesia Sonic first chunk", tts_ms, "vendor: cartesia"),
           row("final -> first speech emitted", list(first_out.values())),
           row("final -> playback started", e2e_heard, "Mac app confirmed"),
           row("END TO END", e2e, f"{len(e2e_heard)} heard, {len(e2e_emitted)} emitted only"),
           "",
           f"  intent path: {dict(paths)}   llm status: {dict(statuses)}",
           f"  resolver: {dict(engines)}   speech: {dict(kinds)}",
           ""]
    if e2e:
        med, worst = statistics.median(e2e), max(e2e)
        over = sum(1 for v in e2e if v > MAX_MS)
        verdict = ("PASS" if med <= TARGET_MS and over == 0 else
                   "WARN" if med <= MAX_MS else "FAIL")
        out.append(f"  budget: median {med:.0f} ms vs {TARGET_MS:.0f} ms target, max {worst:.0f} ms vs "
                   f"{MAX_MS:.0f} ms maximum, {over} over maximum -> {verdict}")
    else:
        out.append("  budget: no completed turns yet")
    return "\n".join(out)


def main(argv: list[str]) -> int:
    path = Path(argv[1]) if len(argv) > 1 else DEFAULT
    if not path.exists():
        print(f"no latency log at {path}; run the concierge first", file=sys.stderr)
        return 1
    print(report(load(path)))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
