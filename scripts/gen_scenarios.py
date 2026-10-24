#!/usr/bin/env python3
"""Generate scenarios/*.jsonl from declarative physical timelines.

Each scenario line is a bus message (see contracts/schemas/bus_message.schema.json).
`t` is seconds relative to scenario start; the simulator rewrites it to wall time.

Spot readers are modeled as polling firmware: every spot reports every TICK seconds,
`seen` with the tag on it, or `removed` with tag "EMPTY" when nothing is there.
That is the raw signal the hub's debounce (2 matching reads to place, ~1.5 s of
continuous absence to remove) is designed for.

Usage: python3 scripts/gen_scenarios.py   (writes scenarios/*.jsonl)
"""
from __future__ import annotations

import json
from pathlib import Path

TICK = 0.5
SPOTS = (1, 2, 3, 4)
TAG = {
    "salt": "04A1B2C3D4E501",
    "sugar": "04A1B2C3D4E502",
    "pepper": "04A1B2C3D4E503",
    "bp_meds": "04A1B2C3D4E504",
    "unknown": "04A1B2C3D4E5FF",
}
HOME = {2: "salt", 3: "sugar", 4: "bp_meds"}
OUT = Path(__file__).resolve().parent.parent / "scenarios"


def spot_reads(duration, changes, initial=None, overrides=None):
    """Polled reads for every spot.

    changes: list of (t, spot, object_key_or_None) physical changes.
    overrides: {(t, spot): object_key_or_None} single reads that disagree with
    the physical state (flicker, misreads).
    """
    occupant = dict(initial if initial is not None else HOME)
    changes = sorted(changes)
    overrides = overrides or {}
    lines = []
    i = 0
    n_ticks = int(round(duration / TICK))
    for k in range(n_ticks + 1):
        t = round(k * TICK, 3)
        while i < len(changes) and changes[i][0] <= t:
            _, spot, obj = changes[i]
            occupant[spot] = obj
            i += 1
        for spot in SPOTS:
            obj = overrides.get((t, spot), occupant.get(spot))
            lines.append(read(t, spot, obj))
    return lines


def read(t, spot, obj):
    if obj is None:
        return {"type": "detection", "source": "simulator", "tag": "EMPTY", "kind": "removed",
                "where": {"spot": spot}, "precision": "exact", "rssi": None, "t": t}
    return {"type": "detection", "source": "simulator", "tag": TAG[obj], "kind": "seen",
            "where": {"spot": spot}, "precision": "exact", "rssi": None, "t": t}


def say(t, text):
    return {"type": "transcript", "text": text, "is_final": True, "source": "typed", "t": t}


def fob(t, distance_class, rssi):
    return {"type": "detection", "source": "simulator", "tag": "fob_keys", "kind": "seen",
            "where": {"near": "hub", "distance_class": distance_class}, "precision": "proximity",
            "rssi": rssi, "t": t}


def fob_lost(t):
    return {"type": "detection", "source": "simulator", "tag": "fob_keys", "kind": "lost",
            "where": None, "precision": "none", "rssi": None, "t": t}


def keys_far_to_near(start, end):
    """Fob walking from far to near at 1 Hz, RSSI rising from -92 to -48 dBm."""
    lines = []
    steps = int(end - start)
    for k in range(steps + 1):
        rssi = -92 + 44 * k / max(steps, 1)
        cls = "far" if rssi < -80 else "mid" if rssi < -65 else "near"
        lines.append(fob(round(start + k, 3), cls, round(rssi, 1)))
    return lines


def scenarios():
    s = {}
    s["normal_pickup"] = spot_reads(20, [(5.0, 3, None), (12.0, 3, "sugar")])

    s["wrong_jar"] = spot_reads(20, [(6.0, 2, None), (14.0, 2, "salt")]) + [
        say(2.0, "Where's the sugar?"),
    ]

    s["moved_item"] = spot_reads(25, [(5.0, 3, None), (10.0, 1, "sugar")]) + [
        say(15.0, "Where is the sugar?"),
    ]

    # Rapid EMPTY/TAG alternation on spot 3 and one stray misread of the salt
    # tag on spot 1. After debounce this must produce no events at all.
    flicker = {}
    for k in range(8, 16):
        t = round(k * TICK, 3)
        if k % 2 == 0:
            flicker[(t, 3)] = None
    flicker[(9.0, 1)] = "salt"
    s["flicker"] = spot_reads(15, [], overrides=flicker)

    # The medication on spot 4 is never lifted. Adherence is judged in Convex
    # against the schedule; the hub must simply emit no pickup for bp_meds.
    s["missed_dose"] = spot_reads(20, [])

    # The fob is first heard at t=2 (far), so the question at t=8 gets the proximity answer.
    s["roaming_keys"] = [fob_lost(0.0), say(8.0, "Where are my keys?")] + keys_far_to_near(2.0, 20.0)

    s["label_new_item"] = spot_reads(15, [(3.0, 1, "unknown")]) + [
        say(7.0, "This is honey."),
    ]

    # The live demo, in order:
    #  1. "Where's the sugar?"            -> guide to spot 3
    #  2. salt lifted (wrong jar)         -> correction naming salt, sugar one spot right
    #  3. salt back on spot 2
    #  4. sugar lifted                    -> "Got it, that's the sugar."
    #  5. sugar put down on spot 1 (moved)
    #  6. "Where's the sugar?"            -> guide to spot 1
    #  7. sugar lifted                    -> confirmation; sugar back home to spot 3
    #  8. "Where are my keys?"            -> proximity phrase + chirp; fob walks closer
    #  9. "Something for my eggs"          -> Moss: salt (and pepper), asks which one
    full = spot_reads(100, [
        (8.0, 2, None), (16.0, 2, "salt"),
        (22.0, 3, None), (30.0, 1, "sugar"),
        (40.0, 1, None), (46.0, 3, "sugar"),
    ])
    full += [
        say(3.0, "Where's the sugar?"),
        say(34.0, "Where's the sugar?"),
        say(55.0, "Where are my keys?"),
        say(85.0, "I need something for my eggs."),
    ]
    full += [fob_lost(0.0)] + keys_far_to_near(50.0, 75.0)
    s["full_demo"] = full
    return s


def main():
    OUT.mkdir(exist_ok=True)
    for name, lines in scenarios().items():
        lines.sort(key=lambda m: m["t"])
        path = OUT / f"{name}.jsonl"
        path.write_text("".join(json.dumps(m, separators=(",", ":")) + "\n" for m in lines))
        print(f"{path.relative_to(OUT.parent)}: {len(lines)} lines")


if __name__ == "__main__":
    main()
