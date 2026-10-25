"""Where the fixed phones are. By default the UWB anchors in config/space.json: the same three phones are both
the UWB anchors and the sound beacons, so both systems share one layout (anchor uwb_N is beacon N)."""
from __future__ import annotations

import json
import re
from pathlib import Path

from .chirp import ChirpSpec

REPO = Path(__file__).resolve().parents[3]
DEFAULT_BEACONS = REPO / "config" / "space.json"  # the fixed phones; a bare beacons.json still works with --beacons
EAR_OFFSET_M = (0.0, 0.0, 0.35)  # the phone is held below the ear
HEIGHT_PRIOR = (1.25, 0.25)  # a held phone is about this high (mean, spread), meters
AUDIBLE_BAND = (2000.0, 4500.0)  # fallback if the phones cannot make or hear the quiet high pitch


def _entries(path: str | Path) -> list[tuple[int, tuple[float, float, float], str]]:
    """(slot, position, label) per fixed phone. A {"beacons": [{"id": "B3", ...}]} file, or space.json's UWB
    `anchors` ({"anchor": "uwb_3", ...}); the trailing number is the slot either way."""
    data = json.loads(Path(path).read_text())
    rows = data["beacons"] if "beacons" in data else [{**a, "id": a["anchor"]} for a in data["anchors"]]
    out = []
    for b in rows:
        m = re.search(r"(\d+)$", str(b["id"]))
        if not m or len(b["position"]) != 3:
            raise ValueError(f"bad beacon entry: {b}")
        out.append((int(m.group(1)), tuple(float(v) for v in b["position"]), str(b.get("label", ""))))
    return out  # type: ignore[return-value]


def load_anchors(path: str | Path = DEFAULT_BEACONS) -> dict[int, tuple[float, float, float]]:
    """Phone slot 1 to 5 -> position."""
    return {slot: pos for slot, pos, _ in _entries(path)}


def load_labels(path: str | Path = DEFAULT_BEACONS) -> dict[int, str]:
    """Phone slot -> label, for messages; empty if the file cannot be read (labels are decoration only)."""
    try:
        return {slot: label for slot, _, label in _entries(path)}
    except (OSError, ValueError, KeyError):
        return {}


def chirp_for_band(f_lo: float, f_hi: float, **kw) -> ChirpSpec:
    return ChirpSpec(f_lo=f_lo, f_hi=f_hi, **kw)
