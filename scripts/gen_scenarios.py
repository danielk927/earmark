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
SPOTS = (1, 2, 3, 4, 5, 6)
TAG = {
    "salt": "04A1B2C3D4E501",
    "sugar": "04A1B2C3D4E502",
    "pepper": "04A1B2C3D4E503",
    "bp_meds": "04A1B2C3D4E504",
    "keys": "04A1B2C3D4E505",
    "wallet": "04A1B2C3D4E506",
    "unknown": "04A1B2C3D4E5FF",
}
# Amendment 01 room: 1 drawer, 2-3 cupboard top shelf, 4 box behind, 5 bag, 6 setup spot (empty).
HOME = {1: "keys", 2: "salt", 3: "sugar", 4: "bp_meds", 5: "wallet"}
EAR = 1.6           # standing ear height (m), matches space.json listener.fallback_position
POSE_HZ = 3.0
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


def pose(t, x, y, quality="ok", beacons=5, z=EAR):
    return {"type": "listener_pose", "position": [round(x, 3), round(y, 3), z], "quality": quality,
            "beacons_heard": beacons, "source": "sim", "t": round(t, 3)}


def stand(t0, t1, x, y):
    """Listener standing still: poses at POSE_HZ in [t0, t1)."""
    n = int(round((t1 - t0) * POSE_HZ))
    return [pose(t0 + k / POSE_HZ, x, y) for k in range(n)]


def walk(t0, t1, start, end, sway=0.02):
    """Straight walk from start to end (x, y) at POSE_HZ, with a small left-right sway like real steps."""
    import math
    n = max(int(round((t1 - t0) * POSE_HZ)), 1)
    out = []
    for k in range(n + 1):
        f = k / n
        x = start[0] + (end[0] - start[0]) * f + sway * math.sin(k * math.pi / 2)
        y = start[1] + (end[1] - start[1]) * f
        out.append(pose(t0 + k / POSE_HZ, x, y))
    return out


CUPBOARD_FRONT = (0.0, 1.08)   # 0.42 m from both cupboard spots horizontally: inside the 0.45 m arrival radius
BOX_FRONT = (0.0, -1.08)       # 0.42 m from the pill box


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
    # Stationary scenarios (no listener_pose: consumers use space.listener.fallback_position, the mat).
    s["normal_pickup"] = spot_reads(20, [(5.0, 3, None), (12.0, 3, "sugar")])

    s["wrong_jar"] = spot_reads(20, [(6.0, 2, None), (14.0, 2, "salt")]) + [
        say(2.0, "Where's the sugar?"),
    ]

    s["moved_item"] = spot_reads(25, [(5.0, 3, None), (10.0, 6, "sugar")]) + [
        say(15.0, "Where is the sugar?"),
    ]

    # Rapid EMPTY/TAG alternation on spot 3 and one stray misread of the salt
    # tag on the empty setup spot. After debounce this must produce no events at all.
    flicker = {}
    for k in range(8, 16):
        t = round(k * TICK, 3)
        if k % 2 == 0:
            flicker[(t, 3)] = None
    flicker[(9.0, 6)] = "salt"
    s["flicker"] = spot_reads(15, [], overrides=flicker)

    # The medication in the box is never lifted. Adherence is judged in Convex
    # against the schedule; the hub must simply emit no pickup for bp_meds.
    s["missed_dose"] = spot_reads(20, [])

    # STRETCH (Amendment 01: no BLE fobs on hand). The keys are not on their drawer
    # spot here; a fob walks from far to near. The fob is first heard at t=2 (far),
    # so the question at t=8 gets the proximity answer.
    s["roaming_keys"] = [fob_lost(0.0), say(8.0, "Where are my keys?")] + keys_far_to_near(2.0, 20.0)

    s["label_new_item"] = spot_reads(15, [(3.0, 6, "unknown")]) + [
        say(7.0, "This is honey."),
    ]

    # Walking scenarios (Amendment 01). Poses are the user's ear position at 3 Hz.
    #  walk_to_cupboard: ask on the mat, walk to the cupboard (arrival), lift the sugar.
    s["walk_to_cupboard"] = (
        spot_reads(16, [(11.0, 3, None)])
        + [say(1.0, "Where's the sugar?")]
        + stand(0.0, 3.0, 0.0, 0.0) + walk(3.0, 9.0, (0.0, 0.0), CUPBOARD_FRONT) + stand(9.0 + 1 / POSE_HZ, 16.0, *CUPBOARD_FRONT)
    )
    #  walk_past_target: the drawer is at x=1.5, y=0; walking straight ahead at x=0.9 passes it on
    #  the right, so its bearing goes front-right (27 deg) -> right (90) -> behind-right (153).
    s["walk_past_target"] = (
        spot_reads(14, [])
        + [say(1.0, "Where are my keys?")]
        + stand(0.0, 3.0, 0.9, -1.2) + walk(3.0, 11.0, (0.9, -1.2), (0.9, 1.2)) + stand(11.0 + 1 / POSE_HZ, 14.0, 0.9, 1.2)
    )
    #  pose_dropout: walking toward the cupboard, the locator degrades and then goes silent twice:
    #  2 s (hold the last position, "position lost") and 6 s (fall back to the mat), then recovers.
    drop = walk(3.0, 15.0, (0.0, 0.0), CUPBOARD_FRONT)
    drop = [p for p in drop if not (5.0 <= p["t"] < 7.0 or 8.5 <= p["t"] < 14.5)]
    for p in drop:
        if 4.3 <= p["t"] < 5.0 or 7.8 <= p["t"] < 8.5:
            p["quality"], p["beacons_heard"] = "degraded", 3
    drop += [pose(5.0, drop[-1]["position"][0], 0.3, quality="lost", beacons=1)]
    s["pose_dropout"] = (
        spot_reads(18, [])
        + [say(1.0, "Where's the sugar?")]
        + stand(0.0, 3.0, 0.0, 0.0) + drop + stand(15.0 + 1 / POSE_HZ, 18.0, *CUPBOARD_FRONT)
    )

    # The live demo, in order (Amendment 01):
    #  1. On the mat: "Where's the sugar?"            -> guide_start to the cupboard, top shelf right
    #  2. Walk to the cupboard                          -> louder, faster pings; arrival -> "Top shelf, front right."
    #  3. Salt lifted (wrong jar)                       -> correction naming the salt; the sugar is just to its right
    #  4. Salt back; sugar lifted                       -> "Got it, that's the sugar."; sugar back
    #  5. "Where are my blood pressure pills?"          -> the box is behind: behind cue + "It's behind you. Turn ..."
    #  6. Walk and turn to the box                      -> arrival -> "In the box, on top."; pills lifted -> confirmation
    #  7. "I need something for my eggs."               -> Moss: salt and pepper, asks which one
    full = spot_reads(58, [
        (10.0, 2, None), (16.0, 2, "salt"),
        (19.0, 3, None), (25.0, 3, "sugar"),
        (43.0, 4, None), (48.0, 4, "bp_meds"),
    ])
    full += [
        say(1.0, "Where's the sugar?"),
        say(28.0, "Where are my blood pressure pills?"),
        say(53.0, "I need something for my eggs."),
    ]
    full += stand(0.0, 3.0, 0.0, 0.0) + walk(3.0, 9.0, (0.0, 0.0), CUPBOARD_FRONT)
    full += stand(9.0 + 1 / POSE_HZ, 31.0, *CUPBOARD_FRONT)
    full += walk(31.0, 40.0, CUPBOARD_FRONT, BOX_FRONT) + stand(40.0 + 1 / POSE_HZ, 58.0, *BOX_FRONT)
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
