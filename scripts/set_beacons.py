#!/usr/bin/env python3
"""Type in where each beacon phone sits (measured with a tape) and save it to config/beacons.json.

Measure from the floor under the middle of the mat: how far right, how far forward (negative = left, behind).
Press Enter on any question to keep the number shown in brackets.
"""
from __future__ import annotations

import re
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "services" / "ranging"))
from earmark_ranging.config import save_beacons  # noqa: E402

BEACONS = ROOT / "config" / "beacons.json"
DEFAULT_HEIGHT = 0.75


def parse_meters(text: str, default: float) -> float:
    """A number in meters; empty means keep `default`. Raises ValueError for anything else."""
    text = text.strip().lower().removesuffix("m").strip()
    return default if not text else float(text)


def ask(prompt: str, default: float, read=input) -> float:
    while True:
        try:
            return parse_meters(read(f"  {prompt} [{default:g}]: "), default)
        except ValueError:
            print("  Please type a number, like 1.2 or -0.5.")


def ask_all(current: dict[int, tuple[float, float, float]], read=input) -> dict[int, tuple[float, float, float]]:
    print("From the floor under the middle of the mat, in meters. Left and behind are negative.")
    out = {}
    for k, (x, y, z) in sorted(current.items()):
        print(f"B{k}")
        right = ask("how far right", x, read)
        forward = ask("how far forward", y, read)
        out[k] = (right, forward, ask("height (table or chair)", z or DEFAULT_HEIGHT, read))
    return out


def main() -> None:
    import json

    data = json.loads(BEACONS.read_text())
    current = {int(re.search(r"(\d+)$", b["id"]).group(1)): tuple(b["position"]) for b in data["beacons"]}
    positions = ask_all(current)
    save_beacons(BEACONS, positions, datetime.now().isoformat(timespec="seconds"))
    print(f"Saved to {BEACONS.relative_to(ROOT)}. Next: make session")


if __name__ == "__main__":
    main()
