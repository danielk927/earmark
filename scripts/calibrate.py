#!/usr/bin/env python3
"""Write config/space.json from tape-measure readings.

Sit in the demo chair (or stand at the counter) in the listening position and
face straight ahead. For each spot, measure from the center of your head:

  forward  cm straight ahead (always positive)
  side     cm to the right (left is negative)
  height   cm relative to ear level (below ear level is negative)

Usage:
  python3 scripts/calibrate.py            interactive; previews before writing
  python3 scripts/calibrate.py --show     print the current layout as spoken directions

The old file is kept as config/space.json.bak. Restart the hub afterwards
(it reads space.json at startup and on reset).
"""
from __future__ import annotations

import argparse
import json
import math
import shutil
from pathlib import Path

SPACE = Path(__file__).resolve().parent.parent / "config" / "space.json"


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
    return "\n".join(lines)


def ask_float(prompt: str, default: float | None, *, positive: bool = False) -> float:
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
        if abs(value) > 300:
            print("  That is more than 3 m; re-measure from the center of the head.")
            continue
        return value


def calibrate(space: dict) -> dict:
    label = input(f"Listening position label [{space['listener']['label']}]: ").strip()
    if label:
        space["listener"]["label"] = label
    note = input(f"Origin note [{space['listener']['origin_note']}]: ").strip()
    if note:
        space["listener"]["origin_note"] = note
    for s in space["spots"]:
        x, y, z = (round(v * 100, 1) for v in s["position"])
        print(f"\nSpot {s['spot']} ({s['label']}):")
        new_label = input(f"  spoken label [{s['label']}]: ").strip()
        if new_label:
            s["label"] = new_label
        fwd = ask_float("  forward cm", y if y > 0 else None, positive=True)
        side = ask_float("  side cm (right +, left -)", x)
        height = ask_float("  height cm vs ear level (below -)", z)
        s["position"] = [round(side / 100, 3), round(fwd / 100, 3), round(height / 100, 3)]
    return space


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--show", action="store_true", help="print the current layout and exit")
    args = parser.parse_args()

    space = json.loads(SPACE.read_text())
    if args.show:
        print(describe(space))
        return

    print(__doc__.split("Usage:")[0].strip(), "\n")
    print("Current layout:\n" + describe(space))
    updated = calibrate(json.loads(json.dumps(space)))
    print("\nNew layout:\n" + describe(updated))
    if input("\nWrite config/space.json? [y/N]: ").strip().lower() != "y":
        print("Nothing written.")
        return
    shutil.copyfile(SPACE, SPACE.with_suffix(".json.bak"))
    SPACE.write_text(json.dumps(updated, indent=2) + "\n")
    print(f"Wrote {SPACE} (backup at {SPACE.with_suffix('.json.bak').name}). Restart the hub or send a reset.")


if __name__ == "__main__":
    main()
