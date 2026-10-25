#!/usr/bin/env python3
"""Write config/space.json from tape-measure readings.

Room frame: meters in the file, centimeters here. The origin is a mark on the
FLOOR under the front-center edge of the table (or the mat). Measure every
point from that mark:

  forward  cm toward the table (the person walks in front of it, at forward < 0)
  side     cm to the right (left is negative)
  height   cm ABOVE THE FLOOR (never relative to your ears)

Spots are on the table (forward positive). UWB anchors ("UWB Reader/Emitter
1/2/3"): height is to the top of the phone, where the cameras and the UWB
antenna are. Wearer: ear height and held-phone height above the floor (the
file stores the phone relative to the ears), head offset, and table-top
height (stored as mark_z_m). Press Enter at any prompt to keep the current value.

The geometry check scores the walking area (horizontal DOP from the anchors,
and from each pair in case one anchor is body-blocked). Advice only.

Usage:
  python3 scripts/calibrate.py              interactive; previews before writing
  python3 scripts/calibrate.py --show       print the current layout as spoken directions
  python3 scripts/calibrate.py --area -1.5,1.5,-3,-0.5   walking area xmin,xmax,ymin,ymax in meters
                                            (default: anchors' bounding box shrunk 0.3 m)
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

Area = tuple[float, float, float, float]

# Placeholders (heights above the floor), used until measured.
DEFAULT_ANCHORS = [
    {"anchor": "uwb_1", "label": "UWB Reader/Emitter 1", "position": [-0.9, 0.75, 1.3]},
    {"anchor": "uwb_2", "label": "UWB Reader/Emitter 2", "position": [0.9, 0.75, 1.3]},
    {"anchor": "uwb_3", "label": "UWB Reader/Emitter 3", "position": [-1.4, -1.8, 1.3]},
]
DEFAULT_PHONE_Z = -0.35  # relative to the ears (schema rule)
DEFAULT_EAR_Z = 1.55
DEFAULT_MARK_Z = 0.9
DEFAULT_HEAD_OFFSET_M = 0.20
HDOP_TRIO_MAX = 2.0
HDOP_PAIR_MAX = 4.0
AREA_MARGIN = 0.3


def clock(x: float, y: float) -> str:
    azimuth = math.degrees(math.atan2(x, y))
    hour = round(azimuth / 30) % 12
    return f"{12 if hour == 0 else hour} o'clock"


def default_area(anchors: list[dict]) -> Area:
    """Anchors' horizontal bounding box shrunk by AREA_MARGIN on each side."""
    def shrink(vals: list[float]) -> tuple[float, float]:
        lo, hi = min(vals) + AREA_MARGIN, max(vals) - AREA_MARGIN
        if lo > hi:
            lo = hi = (lo + hi) / 2
        return lo, hi

    x0, x1 = shrink([a["position"][0] for a in anchors])
    y0, y1 = shrink([a["position"][1] for a in anchors])
    return (x0, x1, y0, y1)


def parse_area(text: str) -> Area:
    try:
        xmin, xmax, ymin, ymax = (float(v) for v in text.split(","))
    except ValueError:
        raise argparse.ArgumentTypeError("--area needs four numbers: xmin,xmax,ymin,ymax (meters)") from None
    if xmin > xmax or ymin > ymax:
        raise argparse.ArgumentTypeError("--area needs xmin <= xmax and ymin <= ymax")
    return (xmin, xmax, ymin, ymax)


def _dop(rows: list[tuple[float, float]]) -> float:
    """sqrt(trace((H^T H)^-1)) for a 2-column H; inf when singular."""
    sxx = sum(r[0] * r[0] for r in rows)
    syy = sum(r[1] * r[1] for r in rows)
    sxy = sum(r[0] * r[1] for r in rows)
    det = sxx * syy - sxy * sxy
    if det < 1e-9:
        return math.inf
    return math.sqrt((sxx + syy) / det)


def _grid(area: Area, step: float) -> list[tuple[float, float]]:
    xmin, xmax, ymin, ymax = area
    nx = int(math.floor((xmax - xmin) / step + 1e-9)) + 1
    ny = int(math.floor((ymax - ymin) / step + 1e-9)) + 1
    return [(xmin + i * step, ymin + j * step) for i in range(nx) for j in range(ny)]


def geometry_report(anchors: list[dict], area: Area, phone_z_room: float, step: float = 0.1) -> dict | None:
    """Horizontal DOP over the walking area for the trio and for each anchor pair.

    Rows of H are horizontal unit vectors from the point to each anchor;
    HDOP = sqrt(trace((H^T H)^-1)). phone_z_room is the held phone's height
    above the floor; it gives each anchor's vertical offset `dz` (the slant
    the tracker removes before solving). Returns None unless uwb_1..3 exist.

    Keys: trio_max, trio_worst, trio_median, pairs {missing: {pair, max, worst}}, dz, area.
    """
    pos = {a["anchor"]: a["position"] for a in anchors}
    names = ["uwb_1", "uwb_2", "uwb_3"]
    if not set(names) <= pos.keys():
        return None
    pts = _grid(area, step)

    def unit(p: tuple[float, float], n: str) -> tuple[float, float]:
        dx, dy = pos[n][0] - p[0], pos[n][1] - p[1]
        d = math.hypot(dx, dy)
        return (dx / d, dy / d) if d > 1e-6 else (0.0, 0.0)

    def scan(use: list[str]) -> tuple[float, tuple[float, float], list[float]]:
        vals = [_dop([unit(p, n) for n in use]) for p in pts]
        i = max(range(len(pts)), key=lambda k: vals[k])
        return vals[i], pts[i], vals

    tmax, tworst, tvals = scan(names)
    ordered = sorted(tvals)
    mid = len(ordered) // 2
    median = ordered[mid] if len(ordered) % 2 else (ordered[mid - 1] + ordered[mid]) / 2
    pairs = {}
    for k in names:
        use = [n for n in names if n != k]
        mx, worst, _ = scan(use)
        pairs[k] = {"pair": use, "max": mx, "worst": worst}
    return {"trio_max": tmax, "trio_worst": tworst, "trio_median": median, "pairs": pairs,
            "dz": {n: pos[n][2] - phone_z_room for n in names}, "area": area}


def anchor_warnings(anchors: list[dict], area: Area | None = None,
                    phone_z_room: float = DEFAULT_EAR_Z + DEFAULT_PHONE_Z) -> list[str]:
    """Geometry advice (nothing is refused)."""
    have = {a["anchor"] for a in anchors}
    if not {"uwb_1", "uwb_2", "uwb_3"} <= have:
        return [] if not anchors else ["the hub expects three anchors: uwb_1, uwb_2, uwb_3"]
    rep = geometry_report(anchors, area or default_area(anchors), phone_z_room)
    out = []
    if rep["trio_max"] > HDOP_TRIO_MAX:
        x, y = rep["trio_worst"]
        out.append(f"poor geometry near ({x:+.2f}, {y:+.2f}): HDOP {rep['trio_max']:.1f} > {HDOP_TRIO_MAX:g}")
    for k, r in rep["pairs"].items():
        if r["max"] > HDOP_PAIR_MAX:
            i, j = r["pair"]
            x, y = r["worst"]
            out.append(f"if {k} is blocked, {i} and {j} are nearly in line near ({x:+.2f}, {y:+.2f})")
    return out


def describe(space: dict, area: Area | None = None) -> str:
    lines = [f"Listener: {space['listener']['label']} ({space['listener']['origin_note']})",
             "Heights are above the floor; the origin is a floor mark under the front-center edge of the table."]
    for s in space["spots"]:
        x, y, z = s["position"]
        dist = math.hypot(x, y)
        az = math.degrees(math.atan2(x, y))
        lines.append(
            f"  spot {s['spot']} {s['label']!r:16} x={x:+.2f} y={y:+.2f} z={z:.2f} m above the floor"
            f"  azimuth {az:+5.1f} deg ({clock(x, y)}), {dist:.2f} m from the origin"
        )
    anchors = space.get("anchors") or []
    if anchors:
        lines.append("UWB anchors:")
    for a in anchors:
        x, y, z = a["position"]
        lines.append(
            f"  {a['label']:22} x={x:+.2f} y={y:+.2f} z={z:.2f} m above the floor"
            f"  ({clock(x, y)}), {math.hypot(x, y):.2f} m from the origin on the floor"
        )
    tracking = space.get("tracking")
    phone_room = DEFAULT_EAR_Z + DEFAULT_PHONE_Z
    if tracking:
        ear = tracking.get("ear_z_m", DEFAULT_EAR_Z)
        phone_z = tracking.get("phone_z", DEFAULT_PHONE_Z)
        phone_room = ear + phone_z
        head = tracking.get("head_offset_m", DEFAULT_HEAD_OFFSET_M)
        mark = tracking.get("mark_z_m", DEFAULT_MARK_Z)
        lines.append(
            f"Wearer: ears {ear * 100:.0f} cm above the floor; phone {phone_room * 100:.0f} cm above the floor"
            f" ({phone_z * 100:+.0f} cm vs the ears); head {head * 100:.0f} cm behind the phone;"
            f" table top {mark * 100:.0f} cm above the floor"
        )
    if anchors:
        area = area or default_area(anchors)
        lines.append(f"Walking area: x {area[0]:+.2f}..{area[1]:+.2f}, y {area[2]:+.2f}..{area[3]:+.2f} m")
        rep = geometry_report(anchors, area, phone_room)
        if rep:
            tx, ty = rep["trio_worst"]
            lines.append(f"  HDOP, all three: max {rep['trio_max']:.2f} at ({tx:+.2f}, {ty:+.2f}),"
                         f" median {rep['trio_median']:.2f}")
            for k, r in rep["pairs"].items():
                px, py = r["worst"]
                lines.append(f"  HDOP, {k} blocked: max {r['max']:.2f} at ({px:+.2f}, {py:+.2f})")
    lines += [f"  Warning: {w}" for w in anchor_warnings(anchors, area, phone_room)]
    return "\n".join(lines)


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


def calibrate(space: dict, area: Area | None = None) -> dict:
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
        fwd = ask_float("  forward cm (toward the table)", y if y > 0 else None, positive=True)
        side = ask_float("  side cm (right +, left -)", x)
        height = ask_float("  height cm above the floor", z, minimum=0)
        s["position"] = [round(side / 100, 3), round(fwd / 100, 3), round(height / 100, 3)]
    calibrate_uwb(space)
    return space


def calibrate_uwb(space: dict) -> None:
    """UWB anchors and wearer geometry. Enter at the first question skips it all."""
    if input("\nUpdate the UWB anchors and wearer phone (walking guidance)? [y/N]: ").strip().lower() != "y":
        return
    anchors = space.get("anchors") or json.loads(json.dumps(DEFAULT_ANCHORS))
    print("Measure each anchor's phone from the floor mark (forward: behind the mark, away from the table, is negative).")
    for a in anchors:
        x, y, z = (cm(v) for v in a["position"])
        print(f"\n{a['label']} ({a['anchor']}):")
        fwd = ask_float("  forward cm (behind -)", y, limit_cm=600)
        side = ask_float("  side cm (right +, left -)", x, limit_cm=600)
        height = ask_float("  height cm above the floor, to the top of the phone", z, minimum=0)
        a["position"] = [round(side / 100, 3), round(fwd / 100, 3), round(height / 100, 3)]
    space["anchors"] = anchors

    tracking = space.get("tracking") or {}
    ear_now = tracking.get("ear_z_m", DEFAULT_EAR_Z)
    print("\nWearer (standing, phone held out in front, screen up):")
    ear = ask_float("  ear height cm above the floor", cm(ear_now), minimum=50)
    phone_now = cm(ear_now + tracking.get("phone_z", DEFAULT_PHONE_Z))
    phone = ask_float("  held-phone height cm above the floor", phone_now, minimum=0)
    head = ask_float("  head offset cm (how far the head is behind the phone)",
                     cm(tracking.get("head_offset_m", DEFAULT_HEAD_OFFSET_M)), limit_cm=100, minimum=0)
    mark = ask_float("  table-top height cm above the floor",
                     cm(tracking.get("mark_z_m", DEFAULT_MARK_Z)), minimum=0)
    tracking["ear_z_m"] = round(ear / 100, 3)
    tracking["phone_z"] = round((phone - ear) / 100, 3)  # relative to the ears
    tracking["head_offset_m"] = round(head / 100, 3)
    tracking["mark_z_m"] = round(mark / 100, 3)
    space["tracking"] = tracking


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--show", action="store_true", help="print the current layout and exit")
    parser.add_argument("--area", type=parse_area, default=None, metavar="XMIN,XMAX,YMIN,YMAX",
                        help="walking area in meters for the geometry check "
                             "(default: anchors' bounding box shrunk 0.3 m)")
    parser.add_argument("--out", type=Path, default=SPACE,
                        help="where to write (default config/space.json); the old file there is kept as .bak")
    args = parser.parse_args()
    out: Path = args.out

    space = json.loads(SPACE.read_text())
    if args.show:
        print(describe(space, args.area))
        return

    print(__doc__.split("Usage:")[0].strip(), "\n")
    print("Current layout:\n" + describe(space, args.area))
    updated = calibrate(json.loads(json.dumps(space)))
    print("\nNew layout:\n" + describe(updated, args.area))
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
