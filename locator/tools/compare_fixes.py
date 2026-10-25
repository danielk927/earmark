"""Compare complete Python/Swift JSONL streams; never truncate missing fixes.

Usage: python tools/compare_fixes.py python.jsonl swift.jsonl --sample-rate 48000
"""

from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from itertools import pairwise
from pathlib import Path

import numpy as np

if __package__ in (None, ""):
    import sys

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.pipeline import Fix, _number, _object, vector3
from tools.positioning import Detection

FIELDS = {
    "t",
    "sample_index",
    "mic_position",
    "ear_position",
    "quality",
    "beacons_used",
    "detections",
    "residual_rms_ms",
}


def _strings(value: object, label: str) -> tuple[str, ...]:
    if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
        raise ValueError(f"{label} must be a string array")
    if len(set(value)) != len(value):
        raise ValueError(f"{label} contains duplicates")
    return tuple(value)


def _position(value: object) -> tuple[float, float, float]:
    if not isinstance(value, list):
        raise TypeError("position must be an array")
    return vector3([_number(v, "position") for v in value])


def _detection(value: object) -> Detection:
    data = _object(value, "detection")
    if set(data) != {"beacon", "arrival", "snr"} or not isinstance(data["beacon"], str):
        raise ValueError("detection fields must be exactly beacon, arrival, snr")
    snr = _number(data["snr"], "snr")
    if snr < 0:
        raise ValueError("snr must be nonnegative")
    return Detection(data["beacon"], _number(data["arrival"], "arrival"), snr)


def parse_fix(value: object) -> Fix:
    data = _object(value, "fix")
    if set(data) != FIELDS:
        raise ValueError("fix fields do not match the agreed record schema")
    quality = data["quality"]
    if quality not in ("ok", "degraded"):
        raise ValueError("valid fix quality must be ok or degraded")
    raw = data["detections"]
    if not isinstance(raw, list):
        raise TypeError("detections must be an array")
    detections = tuple(_detection(v) for v in raw)
    used = _strings(data["beacons_used"], "beacons_used")
    heard = {d.beacon for d in detections}
    if len(heard) != len(detections) or len(used) < 3 or not set(used) <= heard:
        raise ValueError(
            "used beacons must be distinct detected beacons, at least three"
        )
    sample = _number(data["sample_index"], "sample_index")
    residual = _number(data["residual_rms_ms"], "residual_rms_ms")
    if sample < 0 or residual < 0:
        raise ValueError("sample index and residual must be nonnegative")
    return Fix(
        _number(data["t"], "t"),
        sample,
        _position(data["mic_position"]),
        _position(data["ear_position"]),
        quality,
        used,
        detections,
        residual,
    )


def read_fixes(path: Path) -> list[Fix]:
    fixes = [parse_fix(json.loads(line)) for line in path.read_text().splitlines()]
    if not fixes:
        raise ValueError(f"{path}: empty fix stream cannot pass parity")
    if any(b.sample_index <= a.sample_index or b.t <= a.t for a, b in pairwise(fixes)):
        raise ValueError(f"{path}: fix sample indices and times must increase")
    return fixes


@dataclass(frozen=True)
class Comparison:
    fixes: int
    max_mic_difference_m: float
    max_ear_difference_m: float
    quality_agreement: float
    max_sample_difference: float


def measurement_epoch(fix: Fix, fs: float) -> float:
    used = [d.arrival for d in fix.detections if d.beacon in fix.beacons_used]
    mean = float(np.mean(used))
    if abs(fix.sample_index - mean * fs) > 0.001:
        raise ValueError("sample_index must equal the mean used-beacon arrival")
    return fix.t - mean


def require_same_cycle(reference: Fix, actual: Fix, fs: float) -> None:
    reference_epoch = measurement_epoch(reference, fs)
    actual_epoch = measurement_epoch(actual, fs)
    if abs(reference_epoch - actual_epoch) > 0.000001:
        raise ValueError("measurement epochs differ")
    arrivals = {d.beacon: d.arrival for d in reference.detections}
    shared = [
        abs(d.arrival - arrivals[d.beacon])
        for d in actual.detections
        if d.beacon in arrivals
    ]
    # Different accepted subsets shift the mean measurement time. Shared
    # arrivals identify the cycle without requiring identical threshold decisions.
    if not shared or max(shared) > 0.001:
        raise ValueError("unmatched cycles: shared-beacon arrivals differ by >1 ms")


def compare(reference: Sequence[Fix], actual: Sequence[Fix], fs: float) -> Comparison:
    if not np.isfinite(fs) or fs <= 0:
        raise ValueError("sample rate must be finite and positive")
    if not reference or len(reference) != len(actual):
        raise ValueError(
            f"fix coverage differs or is empty: {len(reference)} vs {len(actual)}"
        )
    samples = max(
        abs(a.sample_index - b.sample_index)
        for a, b in zip(reference, actual, strict=True)
    )
    for expected, received in zip(reference, actual, strict=True):
        require_same_cycle(expected, received, fs)
    mic = max(
        float(np.linalg.norm(np.array(a.mic_position) - b.mic_position))
        for a, b in zip(reference, actual, strict=True)
    )
    ear = max(
        float(np.linalg.norm(np.array(a.ear_position) - b.ear_position))
        for a, b in zip(reference, actual, strict=True)
    )
    agreement = sum(
        a.quality == b.quality for a, b in zip(reference, actual, strict=True)
    ) / len(reference)
    if max(mic, ear) >= 0.01 or agreement < 0.95:
        raise ValueError(
            f"parity failed: mic={mic:.9f}m ear={ear:.9f}m quality={agreement:.3%}"
        )
    return Comparison(len(reference), mic, ear, agreement, samples)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("reference", type=Path)
    parser.add_argument("actual", type=Path)
    parser.add_argument("--sample-rate", type=float, required=True)
    args = parser.parse_args(argv)
    result = compare(
        read_fixes(args.reference), read_fixes(args.actual), args.sample_rate
    )
    print(json.dumps(asdict(result), allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
