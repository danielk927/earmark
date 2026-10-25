#!/usr/bin/env python3
"""Write config/space.json from tape-measure readings.

Stand (or sit) in the listening position and face the counter. The origin is
the center of your head there; put a floor mark under it. Measure every point
from the origin, in centimeters:

  forward  cm straight ahead, toward the counter (behind is negative)
  side     cm to the right (left is negative)
  height   cm relative to ear level (below ear level is negative)

Spots must be in front of you (forward positive). The UWB anchors
("UWB Reader/Emitter 1/2/3") use the same convention as the Mac app's
Calibrate UWB anchors screen; anchor 3 is usually behind you (negative).
The wearer phone height and head offset go into `tracking`.
Press Enter at any prompt to keep the current value.

Usage:
  python3 scripts/calibrate.py              interactive; previews before writing
  python3 scripts/calibrate.py --show       print the current layout as spoken directions
  python3 scripts/calibrate.py --out PATH   write PATH instead of config/space.json

The old file is kept as config/space.json.bak (PATH.bak with --out). Then send
a reset (`make reset`) or restart the hub: it reads space.json at startup and
on reset, and pushes the anchors to Convex.
"""
from __future__ import annotations

import argparse
import json
import math
import shutil
from pathlib import Path

SPACE = Path(__file__).resolve().parent.parent / "config" / "space.json"

# PRD 9.1 placeholders (same as the Mac app's Calibration.defaultAnchors), used until measured.
DEFAULT_ANCHORS = [
    {"anchor": "uwb_1", "label": "UWB Reader/Emitter 1", "position": [-0.9, 0.75, -0.25]},
    {"anchor": "uwb_2", "label": "UWB Reader/Emitter 2", "position": [0.9, 0.75, -0.25]},
    {"anchor": "uwb_3", "label": "UWB Reader/Emitter 3", "position": [-1.4, -1.8, -0.25]},
]
# PRD section 5 defaults (also config/hub.json `uwb`).
DEFAULT_PHONE_Z = -0.35
DEFAULT_HEAD_OFFSET_M = 0.20


def clock(x: float, y: float) -> str:
    azimuth = math.degrees(math.atan2(x, y))
    hour = round(azimuth / 30) % 12
    return f"{12 if hour == 0 else hour} o'clock"


def describe(space: dict) -> str:
    lines = [f"Listener: {space['listener']['label']} ({space['listener']['origin_note']})"]
    for s in space["spots"]:
        x, y, z = s["position"]
        dist = math.sqrt(x * x + y * y + z * z)
        az = math.degrees(math.atan2(x, y))
        lines.append(
            f"  spot {s['spot']} {s['label']!r:16} x={x:+.2f} y={y:+.2f} z={z:+.2f} m"
            f"  azimuth {az:+5.1f} deg ({clock(x, y)}), {dist:.2f} m away"
        )
    anchors = space.get("anchors") or []
    if anchors:
        lines.append("UWB anchors:")
    for a in anchors:
        x, y, z = a["position"]
        lines.append(
            f"  {a['label']:22} x={x:+.2f} y={y:+.2f} z={z:+.2f} m"
            f"  ({clock(x, y)}), {math.hypot(x, y):.2f} m away on the floor"
        )
    tracking = space.get("tracking")
    if tracking:
        phone_z = tracking.get("phone_z", DEFAULT_PHONE_Z)
        head = tracking.get("head_offset_m", DEFAULT_HEAD_OFFSET_M)
        lines.append(f"Wearer: phone {phone_z * 100:+.0f} cm vs ear level, head {head * 100:.0f} cm behind the phone")
    lines += [f"  Warning: {w}" for w in anchor_warnings(anchors)]
    return "\n".join(lines)


def _dist_to_line(p: list[float], a: list[float], b: list[float]) -> float:
    """Floor distance from p to the line through a and b."""
    dx, dy = b[0] - a[0], b[1] - a[1]
    length = math.hypot(dx, dy)
    if length == 0:
        return math.hypot(p[0] - a[0], p[1] - a[1])
    return abs(dx * (p[1] - a[1]) - dy * (p[0] - a[0])) / length


def anchor_warnings(anchors: list[dict]) -> list[str]:
    """Booth layout rules from docs/project/UWB-PRD.md 4.2 (advice only; nothing is refused)."""
    pos = {a["anchor"]: a["position"] for a in anchors}
    if not {"uwb_1", "uwb_2", "uwb_3"} <= pos.keys():
        return [] if not anchors else ["the hub expects three anchors: uwb_1, uwb_2, uwb_3"]
    out = []
    a, b, c = pos["uwb_1"], pos["uwb_2"], pos["uwb_3"]
    if math.hypot(a[0] - b[0], a[1] - b[1]) < 1.2:
        out.append("UWB Reader/Emitter 1 and 2 are less than 1.2 m apart")
    if _dist_to_line(c, a, b) < 1.5:
        out.append("UWB Reader/Emitter 3 is less than 1.5 m from the line through 1 and 2 (nearly in line)")
    return out


def ask_float(prompt: str, default: float | None, *, positive: bool = False,
              limit_cm: float = 300, minimum: float | None = None) -> float:
    while True:
        hint = f" [{default:g}]" if default is not None else ""
        raw = input(f"{prompt}{hint}: ").strip()
        if not raw and default is not None:
            return default
        try:
            value = float(raw)
        except ValueError:
            print("  Please enter a number in centimeters.")
            continue
        if positive and value <= 0:
            print("  Forward distance must be positive (the spot is in front of you).")
            continue
        if minimum is not None and value < minimum:
            print(f"  Must be at least {minimum:g} cm.")
            continue
        if abs(value) > limit_cm:
            print(f"  That is more than {limit_cm / 100:g} m; re-measure from the origin.")
            continue
        return value


def cm(m: float) -> float:
    return round(m * 100, 1)


def calibrate(space: dict) -> dict:
    label = input(f"Listening position label [{space['listener']['label']}]: ").strip()
    if label:
        space["listener"]["label"] = label
    note = input(f"Origin note [{space['listener']['origin_note']}]: ").strip()
    if note:
        space["listener"]["origin_note"] = note
    for s in space["spots"]:
        x, y, z = (cm(v) for v in s["position"])
        print(f"\nSpot {s['spot']} ({s['label']}):")
        new_label = input(f"  spoken label [{s['label']}]: ").strip()
        if new_label:
            s["label"] = new_label
        fwd = ask_float("  forward cm", y if y > 0 else None, positive=True)
        side = ask_float("  side cm (right +, left -)", x)
        height = ask_float("  height cm vs ear level (below -)", z)
        s["position"] = [round(side / 100, 3), round(fwd / 100, 3), round(height / 100, 3)]
    calibrate_uwb(space)
    return space


def calibrate_uwb(space: dict) -> None:
    """UWB anchors and wearer geometry (docs/project/UWB-PRD.md 10.6). Enter at the first question skips it all."""
    if input("\nUpdate the UWB anchors and wearer phone (walking guidance)? [y/N]: ").strip().lower() != "y":
        return
    anchors = space.get("anchors") or json.loads(json.dumps(DEFAULT_ANCHORS))
    print("Measure each anchor's phone from the origin floor mark (forward: behind the origin is negative).")
    for a in anchors:
        x, y, z = (cm(v) for v in a["position"])
        print(f"\n{a['label']} ({a['anchor']}):")
        fwd = ask_float("  forward cm (behind -)", y, limit_cm=600)
        side = ask_float("  side cm (right +, left -)", x, limit_cm=600)
        height = ask_float("  height cm vs ear level (below -)", z)
        a["position"] = [round(side / 100, 3), round(fwd / 100, 3), round(height / 100, 3)]
    space["anchors"] = anchors

    tracking = space.get("tracking") or {}
    print("\nWearer phone (held in hand, close to the chest):")
    phone = ask_float("  phone height cm vs ear level (below -)", cm(tracking.get("phone_z", DEFAULT_PHONE_Z)),
                      limit_cm=150)
    head = ask_float("  head offset cm (how far the head is behind the phone)",
                     cm(tracking.get("head_offset_m", DEFAULT_HEAD_OFFSET_M)), limit_cm=100, minimum=0)
    tracking["phone_z"] = round(phone / 100, 3)
    tracking["head_offset_m"] = round(head / 100, 3)
    space["tracking"] = tracking


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--show", action="store_true", help="print the current layout and exit")
    parser.add_argument("--out", type=Path, default=SPACE,
                        help="where to write (default config/space.json); the old file there is kept as .bak")
    args = parser.parse_args()
    out: Path = args.out

    space = json.loads(SPACE.read_text())
    if args.show:
        print(describe(space))
        return

    print(__doc__.split("Usage:")[0].strip(), "\n")
    print("Current layout:\n" + describe(space))
    updated = calibrate(json.loads(json.dumps(space)))
    print("\nNew layout:\n" + describe(updated))
    if input(f"\nWrite {out}? [y/N]: ").strip().lower() != "y":
        print("Nothing written.")
        return
    bak = out.with_name(out.name + ".bak")
    backed_up = out.exists()
    if backed_up:
        shutil.copyfile(out, bak)
    out.write_text(json.dumps(updated, indent=2) + "\n")
    kept = f" (backup at {bak.name})" if backed_up else ""
    print(f"Wrote {out}{kept}. Send a reset (make reset) or restart the hub.")


if __name__ == "__main__":
    main()
