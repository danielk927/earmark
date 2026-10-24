#!/usr/bin/env python3
"""Generate scenarios/*.jsonl (design v7: walking room, saved spots, no detection hardware).

Each scenario line is a bus message (see contracts/schemas/bus_message.schema.json).
`t` is seconds relative to scenario start; the simulator rewrites it to wall time.
Lines are listener poses (the user's ear position at 3 Hz, as the iPhone locator sends
them), typed transcripts (standing in for push-to-talk speech), and spot saves.
`arrived` is never scripted: the Mac app computes it from the pose and the target.

Usage: python3 scripts/gen_scenarios.py   (writes scenarios/*.jsonl)
"""
from __future__ import annotations

import json
import math
from pathlib import Path

OUT = Path(__file__).resolve().parent.parent / "scenarios"
EAR = 1.6           # standing ear height (m), matches space.json listener.fallback_position
POSE_HZ = 3.0
# Item spots (config/space.json): 1 cupboard (sugar), 2 drawer (keys), 3 bag (spice jar), 4 box (pills).
CUPBOARD_FRONT = (0.0, 1.08)   # 0.42 m from the sugar [-0.08, 1.5]: inside the 0.45 m arrival radius
BOX_FRONT = (0.0, -1.08)       # 0.42 m from the pills [0, -1.5]


def say(t, text):
    return {"type": "transcript", "text": text, "is_final": True, "source": "typed", "t": t}


def pose(t, x, y, quality="ok", beacons=5, z=EAR):
    return {"type": "listener_pose", "position": [round(x, 3), round(y, 3), z], "quality": quality,
            "beacons_heard": beacons, "source": "sim", "t": round(t, 3)}


def stand(t0, t1, x, y):
    """Listener standing still: poses at POSE_HZ in [t0, t1)."""
    n = int(round((t1 - t0) * POSE_HZ))
    return [pose(t0 + k / POSE_HZ, x, y) for k in range(n)]


def walk(t0, t1, start, end, sway=0.02):
    """Straight walk from start to end (x, y) at POSE_HZ, with a small left-right sway like real steps."""
    n = max(int(round((t1 - t0) * POSE_HZ)), 1)
    out = []
    for k in range(n + 1):
        f = k / n
        x = start[0] + (end[0] - start[0]) * f + sway * math.sin(k * math.pi / 2)
        y = start[1] + (end[1] - start[1]) * f
        out.append(pose(t0 + k / POSE_HZ, x, y))
    return out


def save(t, object_id, position, detail=None):
    m = {"type": "save_spot", "object_id": object_id, "position": position, "t": t}
    if detail:
        m["detail"] = detail
    return m


def scenarios():
    s = {}
    # No pose at all: consumers fall back to the mat and speak distances from it.
    s["ask_on_mat"] = [say(1.0, "Where's the sugar?"), say(6.0, "Stop."), say(8.0, "Where are my keys?")]

    # Setup: a teammate holds the phone at each item's spot and taps save (positions a little
    # off the placeholders, as a real hand would be).
    s["setup_spots"] = [
        save(1.0, "sugar", [-0.07, 1.52, 1.01], "Top shelf, front left."),
        save(3.0, "keys", [1.48, 0.03, 0.42]),
        save(5.0, "spice_jar", [-1.47, -0.02, 0.52]),
        save(7.0, "bp_meds", [0.02, -1.49, 0.79]),
    ]

    # Ask on the mat, walk to the cupboard, arrive.
    s["walk_to_cupboard"] = (
        [say(1.0, "Where's the sugar?")]
        + stand(0.0, 3.0, 0.0, 0.0) + walk(3.0, 9.0, (0.0, 0.0), CUPBOARD_FRONT) + stand(9.0 + 1 / POSE_HZ, 14.0, *CUPBOARD_FRONT)
    )

    # The drawer is at x=1.5, y=0; walking straight ahead at x=0.9 passes it on the right, so its
    # bearing goes front-right (27 deg) -> right (90) -> behind-right (153): the behind cue.
    s["walk_past_target"] = (
        [say(1.0, "Where are my keys?")]
        + stand(0.0, 3.0, 0.9, -1.2) + walk(3.0, 11.0, (0.9, -1.2), (0.9, 1.2)) + stand(11.0 + 1 / POSE_HZ, 14.0, 0.9, 1.2)
    )

    # Walking toward the cupboard, the locator degrades and then goes silent twice:
    # 2 s (hold the last position, "position lost") and 6 s (fall back to the mat), then recovers.
    drop = walk(3.0, 15.0, (0.0, 0.0), CUPBOARD_FRONT)
    drop = [p for p in drop if not (5.0 <= p["t"] < 7.0 or 8.5 <= p["t"] < 14.5)]
    for p in drop:
        if 4.3 <= p["t"] < 5.0 or 7.8 <= p["t"] < 8.5:
            p["quality"], p["beacons_heard"] = "degraded", 3
    last = [p for p in drop if p["t"] < 5.0][-1]
    drop.append(pose(5.0, *last["position"][:2], quality="lost", beacons=1))
    s["pose_dropout"] = (
        [say(1.0, "Where's the sugar?")]
        + stand(0.0, 3.0, 0.0, 0.0) + drop + stand(15.0 + 1 / POSE_HZ, 18.0, *CUPBOARD_FRONT)
    )

    # The live demo, in order (design v7):
    #  1. On the mat: "Where's the sugar?"          -> guide_start to the cupboard
    #  2. Walk to the cupboard                        -> louder, faster clicks; arrival -> "Top shelf, front left."
    #  3. "Where are my blood pressure pills?"        -> the box is behind: behind cue + "Turn right."
    #  4. Walk and turn to the box                    -> arrival -> "In the box, on top."
    #  5. "I need something for my eggs."             -> Moss: the spice jar, in the bag on the left
    full = [say(1.0, "Where's the sugar?"), say(16.0, "Where are my blood pressure pills?"),
            say(32.0, "I need something for my eggs.")]
    full += stand(0.0, 3.0, 0.0, 0.0) + walk(3.0, 9.0, (0.0, 0.0), CUPBOARD_FRONT)
    full += stand(9.0 + 1 / POSE_HZ, 19.0, *CUPBOARD_FRONT)
    full += walk(19.0, 28.0, CUPBOARD_FRONT, BOX_FRONT) + stand(28.0 + 1 / POSE_HZ, 36.0, *BOX_FRONT)
    s["full_demo"] = full
    return s


def main():
    OUT.mkdir(exist_ok=True)
    for old in OUT.glob("*.jsonl"):
        old.unlink()
    for name, lines in scenarios().items():
        lines.sort(key=lambda m: m["t"])
        path = OUT / f"{name}.jsonl"
        path.write_text("".join(json.dumps(m, separators=(",", ":")) + "\n" for m in lines))
        print(f"{path.relative_to(OUT.parent)}: {len(lines)} lines")


if __name__ == "__main__":
    main()
