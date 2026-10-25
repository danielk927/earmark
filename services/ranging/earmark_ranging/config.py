"""Where the fixed phones are, read from the same file the beacon plan used."""
from __future__ import annotations

import json
import re
from pathlib import Path

from .chirp import ChirpSpec

REPO = Path(__file__).resolve().parents[3]
DEFAULT_BEACONS = REPO / "config" / "beacons.json"  # the beacon phones (the buzzer plan uses locator/config/beacons.json)
EAR_OFFSET_M = (0.0, 0.0, 0.35)  # the phone is held below the ear
HEIGHT_PRIOR = (1.25, 0.25)  # a held phone is about this high (mean, spread), meters
AUDIBLE_BAND = (2000.0, 4500.0)  # fallback if the phones cannot make or hear the quiet high pitch


def load_anchors(path: str | Path = DEFAULT_BEACONS) -> dict[int, tuple[float, float, float]]:
    """Phone slot 1 to 5 -> position. Accepts a bare {"beacons": [...]} file or a full space.json; B3 means slot 3."""
    data = json.loads(Path(path).read_text())
    out: dict[int, tuple[float, float, float]] = {}
    for b in data["beacons"]:
        m = re.search(r"(\d+)$", str(b["id"]))
        if not m or len(b["position"]) != 3:
            raise ValueError(f"bad beacon entry: {b}")
        out[int(m.group(1))] = tuple(float(v) for v in b["position"])  # type: ignore[assignment]
    return out


def chirp_for_band(f_lo: float, f_hi: float, **kw) -> ChirpSpec:
    return ChirpSpec(f_lo=f_lo, f_hi=f_hi, **kw)
