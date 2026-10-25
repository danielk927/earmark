#!/usr/bin/env python3
"""Generate scenarios/*.jsonl from declarative physical timelines.

Each scenario line is a bus message (see contracts/schemas/bus_message.schema.json).
`t` is seconds relative to scenario start; the simulator rewrites it to wall time.

Spot readers are modeled as polling firmware: every spot reports every TICK seconds,
`seen` with the tag on it, or `removed` with tag "EMPTY" when nothing is there.
That is the raw signal the hub's debounce (2 matching reads to place, ~1.5 s of
continuous absence to remove) is designed for.

`uwb_walk` adds the wearer iPhone (docs/project/UWB-PRD.md 8.6): `uwb_range` to every anchor
in config/space.json at UWB_HZ and `motion_state` (on change plus a 1 s heartbeat),
computed with the hub's slant geometry (earmark_hub/uwb/tracker.wearer_geometry).

Usage: python3 scripts/gen_scenarios.py   (writes scenarios/*.jsonl)
"""
from __future__ import annotations

import json
import math
import random
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
ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "scenarios"

# uwb_walk: the wearer's head walks this polyline (the hub's uwb_sim.path in config/hub.json:
# the start mark ~3 m behind the origin -> the listening position) at UWB_SPEED_MPS.
UWB_HZ = 10
UWB_PATH = ((0.4, -3.0), (0.1, -1.5), (0.0, 0.0))
UWB_SPEED_MPS = 0.6
UWB_NOISE_M = 0.03  # small Gaussian range noise; seeded, so the file is reproducible
UWB_SEED = 7
FORWARD = (0.0, 1.0)  # facing the counter


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


def wearer_setup():
    """(anchors {id: [x, y, z]}, phone_z, head_offset_m), resolved like the hub's
    tracker.wearer_geometry: space.json `tracking` overrides the hub.json `uwb` defaults."""
    space = json.loads((ROOT / "config" / "space.json").read_text())
    uwb = json.loads((ROOT / "config" / "hub.json").read_text())["uwb"]
    tracking = space.get("tracking") or {}
    phone_z = tracking.get("phone_z")
    head_offset = tracking.get("head_offset_m")
    anchors = {a["anchor"]: a["position"] for a in space["anchors"]}
    return (anchors, uwb["phone_z"] if phone_z is None else phone_z,
            uwb["head_offset_m"] if head_offset is None else head_offset)


def walk_at(t, start, points=UWB_PATH, speed=UWB_SPEED_MPS):
    """(head [x, y], facing unit vector, moving) at scenario time t for a wearer who stands on
    points[0] until `start`, walks the polyline at `speed`, then stands at the end facing the counter."""
    if t < start:
        return points[0], FORWARD, False
    s = (t - start) * speed
    for a, b in zip(points, points[1:]):
        seg = math.dist(a, b)
        if s < seg:
            k = s / seg
            return ((a[0] + (b[0] - a[0]) * k, a[1] + (b[1] - a[1]) * k),
                    ((b[0] - a[0]) / seg, (b[1] - a[1]) / seg), True)
        s -= seg
    return points[-1], FORWARD, False


def walk_time(points=UWB_PATH, speed=UWB_SPEED_MPS):
    return sum(math.dist(a, b) for a, b in zip(points, points[1:])) / speed


def uwb_stream(duration, walk_start):
    """The wearer phone's messages for 0..duration: `uwb_range` per anchor per tick (3D distance
    from the phone, held head_offset_m in front of the head at phone_z, plus seeded noise) and
    `motion_state` on change and as a 1 s heartbeat."""
    anchors, phone_z, head_offset = wearer_setup()
    rng = random.Random(UWB_SEED)
    lines = []
    motion, next_motion_t = None, -math.inf
    for k in range(int(round(duration * UWB_HZ)) + 1):
        t = round(k / UWB_HZ, 3)
        head, facing, moving = walk_at(t, walk_start)
        phone = (head[0] + facing[0] * head_offset, head[1] + facing[1] * head_offset, phone_z)
        for aid in sorted(anchors):
            d = math.dist(phone, anchors[aid]) + rng.gauss(0.0, UWB_NOISE_M)
            lines.append({"type": "uwb_range", "anchor": aid, "distance_m": round(max(d, 0.0), 3),
                          "seq": k, "t": t})
        state = "moving" if moving else "still"
        if state != motion or t >= next_motion_t - 1e-9:
            lines.append({"type": "motion_state", "state": state, "t": t})
            motion, next_motion_t = state, t + 1.0
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

    # The user says where the keys went, asks for them, moves them, then asks where they were before.
    s["put_in_place"] = [
        {"type": "ptt", "state": "stop", "t": 0.0},  # a harmless first line: the clock starts at the first message
        say(8.0, "I put my keys in the drawer."),
        say(11.0, "Where are my keys?"),
        say(17.0, "I put my keys in the bag."),
        say(23.0, "Where did I put my keys before?"),
    ]

    # The locator says where the user stands; "leaving it here" saves that spot, and the ping leads back to it.
    # Sound positioning drives the audio here (UWB is the hub's default), so the scenario selects it first.
    s["put_here"] = [{"type": "positioning_select", "active": "sound", "t": 0.5}] + [
        {"type": "listener_pose", "position": [0.8, -0.4, 1.5], "quality": "ok", "beacons_heard": 5,
         "source": "beacons", "t": float(k) / 3} for k in range(3, 27)  # the locator reports about 3 times a second
    ] + [say(8.0, "I'm leaving my keys here.")] + [
        {"type": "listener_pose", "position": [0.0, 0.0, 1.5], "quality": "ok", "beacons_heard": 5,
         "source": "beacons", "t": float(k) / 3} for k in range(30, 54)
    ] + [say(15.0, "Where are my keys?")]

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

    # UWB walking guidance (docs/project/UWB-PRD.md 8.6 and 12.1 e2e):
    #  1. standing on the start mark, ranging: "Where's the sugar?"  -> tracked: meters phrasing
    #  2. walks to the counter at 0.6 m/s and stops at the origin    -> frozen: "You're at the counter."
    #  3. stays still well past still_for_s + average_window_s, then the wrong-jar flow:
    #     salt lifted (NFC re-anchor check + correction), salt back, sugar lifted ("Got it"), sugar back.
    # Hub timing (still_for_s, freshness, speed gate) is wall-clock: replay at --speed 1.
    walk_start = 3.0
    lift = math.ceil(walk_start + walk_time()) + 3.0  # first jar lifted ~4 s after stopping
    end = lift + 17.0
    uwb = spot_reads(end, [
        (lift, 2, None), (lift + 5.0, 2, "salt"),
        (lift + 9.0, 3, None), (lift + 14.0, 3, "sugar"),
    ])
    uwb += [say(2.0, "Where's the sugar?")]
    uwb += uwb_stream(end, walk_start)
    s["uwb_walk"] = uwb
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
