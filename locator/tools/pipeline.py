"""Reference streaming locator; run: python tools/pipeline.py input.wav --out fixes.jsonl.

Fix JSON is locked with EarmarkCore: t/sample_index, mic_position/ear_position,
quality, beacons_used, detections[{beacon,arrival,snr}], residual_rms_ms.
Only valid fixes are written; the lost transition belongs to the pose publisher.
"""

from __future__ import annotations

import argparse
import json
import wave
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass, fields
from pathlib import Path
from typing import Literal

import numpy as np

if __package__ in (None, ""):
    import sys

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.common.chirp import ChirpConfig, square_wave_samples
from tools.common.config import Beacon, load_beacon_config, load_chirp_config
from tools.common.constants import speed_of_sound
from tools.positioning import (
    Detection,
    FloatArray,
    Kalman,
    LossMonitor,
    MarkerTracker,
    Parameters,
    Quality,
    detect,
    marker_candidate,
    solve,
)


@dataclass(frozen=True)
class Fix:
    t: float
    sample_index: float
    mic_position: tuple[float, float, float]
    ear_position: tuple[float, float, float]
    quality: Quality
    beacons_used: tuple[str, ...]
    detections: tuple[Detection, ...]
    residual_rms_ms: float


def vector3(values: Sequence[float]) -> tuple[float, float, float]:
    if len(values) != 3:
        raise ValueError("position must contain exactly three coordinates")
    return float(values[0]), float(values[1]), float(values[2])


def _object(value: object, label: str) -> dict[str, object]:
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        raise ValueError(f"{label} must be a JSON object")
    return value


def _number(value: object, label: str) -> float:
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not np.isfinite(value)
    ):
        raise ValueError(f"{label} must be a finite number")
    return float(value)


def load_parameters(
    path: Path | None = None, mode: Literal["hand", "pocket"] = "hand"
) -> Parameters:
    """Read section 8.6 parameters; chirp/beacon loading remains in tools.common."""
    if mode not in ("hand", "pocket"):
        raise ValueError("mode must be hand or pocket")
    defaults = (
        Parameters()
        if mode == "hand"
        else Parameters(
            height_mean_m=1.30, height_sigma_m=0.20, ear_offset_m=(0, 0, 0.30)
        )
    )
    if path is None:
        return defaults
    data = _object(json.loads(path.read_text(encoding="utf-8")), "settings")
    scalars = {
        field.name: _number(data[field.name], field.name)
        for field in fields(Parameters)
        if field.name in data and field.name != "ear_offset_m"
    }
    values = {**asdict(defaults), **scalars}
    height = _object(
        _object(data.get("height_prior", {}), "height_prior").get(mode, {}),
        "height mode",
    )
    for source, destination in (
        ("mean_m", "height_mean_m"),
        ("sigma_m", "height_sigma_m"),
    ):
        if source in height:
            values[destination] = _number(height[source], source)
    kalman = _object(data.get("kalman", {}), "kalman")
    for name in ("accel_sigma_mps2", "meas_sigma_ok_m", "meas_sigma_degraded_m"):
        if name in kalman:
            values[name] = _number(kalman[name], name)
    offsets = _object(data.get("ear_offset_m", {}), "ear_offset_m")
    if mode in offsets:
        raw = offsets[mode]
        if not isinstance(raw, list) or len(raw) != 3:
            raise ValueError("ear offset must be a three-number array")
        values["ear_offset_m"] = vector3(
            [_number(value, "ear offset") for value in raw]
        )
    return Parameters(**values)


class Pipeline:
    """Bounded sample history; all DSP runs on caller-owned serial execution."""

    def __init__(
        self,
        fs: float = 48000,
        *,
        chirp: ChirpConfig | None = None,
        beacons: tuple[Beacon, ...] | None = None,
        params: Parameters | None = None,
        epoch: float = 0,
        templates: Mapping[str, FloatArray] | None = None,
    ) -> None:
        self.chirp = chirp or ChirpConfig()
        self.beacons = load_beacon_config() if beacons is None else beacons
        self.params = params or Parameters()
        if not np.isfinite(fs) or fs <= 2 * (self.chirp.f_hi + 300):
            raise ValueError(
                "WAV sample rate must exceed twice the band-pass upper frequency"
            )
        if not np.isfinite(epoch):
            raise ValueError("epoch must be finite")
        if len(self.beacons) < 3 or self.chirp.marker_beacon not in {
            b.id for b in self.beacons
        }:
            raise ValueError("at least three beacons including the marker are required")
        if any(
            b.slot < 0
            or b.slot >= self.chirp.n_slots
            or not np.all(np.isfinite(b.position))
            for b in self.beacons
        ):
            raise ValueError(
                "beacon geometry must be finite and slots within the cycle"
            )
        if len({b.id for b in self.beacons}) != len(self.beacons) or len(
            {b.slot for b in self.beacons}
        ) != len(self.beacons):
            raise ValueError("beacon IDs and slots must be unique")
        self.fs, self.epoch = fs, epoch
        self.templates = {
            b.id: square_wave_samples(self.chirp, fs, b.id) for b in self.beacons
        }
        for beacon, template in (templates or {}).items():
            if (
                beacon not in self.templates
                or template.ndim != 1
                or not len(template)
                or not np.all(np.isfinite(template))
            ):
                raise ValueError(
                    "captured templates must be finite mono arrays for configured beacons"
                )
            self.templates[beacon] = template.copy()
        self.history = np.empty(0)
        self.origin = 0
        self.next_sample = 0
        self.tracker = MarkerTracker(self.chirp.cycle_s)
        self.filter = Kalman(self.params)
        self.loss = LossMonitor(self.params.lost_timeout_s)
        self.pending: list[float] = []
        self.discontinuities = 0
        self.lost_transitions: list[float] = []

    def feed(self, samples: FloatArray, sample_index: int | None = None) -> list[Fix]:
        if samples.ndim != 1 or not np.all(np.isfinite(samples)):
            raise ValueError("input must be finite mono samples")
        start = self.next_sample if sample_index is None else sample_index
        if start < 0:
            raise ValueError("sample index must be nonnegative")
        if start != self.next_sample:
            self._reset_gap(start)
        # Process arbitrarily large caller buffers in bounded 50ms slices.
        fixes: list[Fix] = []
        block = max(1, round(0.05 * self.fs))
        for offset in range(0, len(samples), block):
            fixes.extend(self._append(samples[offset : offset + block]))
        return fixes

    def _reset_gap(self, start: int) -> None:
        self.discontinuities += 1
        self.history = np.empty(0)
        self.origin = start
        self.next_sample = start
        self.tracker.reset()
        self.pending.clear()
        self.filter = Kalman(self.params)

    def _append(self, samples: FloatArray) -> list[Fix]:
        self.history = np.concatenate((self.history, samples))
        self.next_sample += len(samples)
        now = self.next_sample / self.fs
        self._markers(now)
        fixes = self._completed_cycles(now)
        if self.loss.lost(now):
            self.lost_transitions.append(now)
        keep = round(max(1.0, self.chirp.cycle_s * 2) * self.fs)
        excess = max(0, len(self.history) - keep)
        self.history = self.history[excess:]
        self.origin += excess
        return fixes

    def _markers(self, now: float) -> None:
        expected = self.tracker.expected
        template = self.templates[self.chirp.marker_beacon]
        gate = self.params.gate_ms / 1000
        if expected is None:
            begin = max(self.origin, self.next_sample - round(0.4 * self.fs))
            candidate = marker_candidate(
                self.history[begin - self.origin :],
                begin,
                template,
                self.fs,
                self.chirp,
                self.params,
            )
            if candidate is not None:
                self.tracker.observe(candidate.arrival)
            return
        if now < expected + gate + len(template) / self.fs + 0.005:
            return
        marker = detect(
            self.history,
            self.origin,
            template,
            self.fs,
            self.chirp,
            self.chirp.marker_beacon,
            expected - gate,
            expected + gate,
            self.params,
            self.params.snr_acquire,
        )
        was_locked = self.tracker.locked
        confirmed = self.tracker.observe(None if marker is None else marker.arrival)
        if confirmed or was_locked:
            self.pending.append(expected if marker is None else marker.arrival)

    def _completed_cycles(self, now: float) -> list[Fix]:
        fixes = []
        while self.pending and now >= self.pending[0] + self._cycle_tail():
            marker = self.pending.pop(0)
            fix = self._solve_cycle(marker)
            if fix is not None:
                fixes.append(fix)
        return fixes

    def _cycle_tail(self) -> float:
        marker_slot = next(
            b.slot for b in self.beacons if b.id == self.chirp.marker_beacon
        )
        return (max(b.slot for b in self.beacons) - marker_slot + 1) * self.chirp.slot_s

    def _solve_cycle(self, marker: float) -> Fix | None:
        initial = (
            self.filter.state[:3].copy()
            if self.filter.time is not None
            else np.array([0.0, 0.0, self.params.height_mean_m])
        )
        c = speed_of_sound(self.params.air_temperature_c)
        marker_beacon = next(
            b for b in self.beacons if b.id == self.chirp.marker_beacon
        )
        tau = (
            marker
            - marker_beacon.slot * self.chirp.slot_s
            - np.linalg.norm(initial - marker_beacon.position) / c
        )
        detections = tuple(
            found
            for beacon in self.beacons
            if (found := self._detect_beacon(beacon, tau, initial)) is not None
        )
        solution = solve(detections, self.beacons, self.chirp, self.params, initial)
        if solution is None:
            return None
        time = float(np.mean([d.arrival for d in solution.detections]))
        position = self.filter.update(solution.position, time, solution.quality)
        self.loss.fixed(time)
        return Fix(
            self.epoch + time,
            time * self.fs,
            vector3(position),
            vector3(position + self.params.ear_offset_m),
            solution.quality,
            tuple(d.beacon for d in solution.detections),
            detections,
            solution.residual_rms_ms,
        )

    def _detect_beacon(
        self, beacon: Beacon, tau: float, position: FloatArray
    ) -> Detection | None:
        slot = tau + beacon.slot * self.chirp.slot_s
        arrival = slot + np.linalg.norm(position - beacon.position) / speed_of_sound(
            self.params.air_temperature_c
        )
        if self.filter.time is None:
            candidate = detect(
                self.history,
                self.origin,
                self.templates[beacon.id],
                self.fs,
                self.chirp,
                beacon.id,
                slot,
                slot + self.chirp.slot_s - 0.005,
                self.params,
                0,
            )
            if candidate is None:
                return None
            arrival = candidate.arrival
        lo, hi = (
            arrival - self.params.gate_ms / 1000,
            arrival + self.params.gate_ms / 1000,
        )
        return detect(
            self.history,
            self.origin,
            self.templates[beacon.id],
            self.fs,
            self.chirp,
            beacon.id,
            lo,
            hi,
            self.params,
            self.params.snr_min,
        )


def run_pipeline(
    samples: FloatArray,
    fs: float = 48000,
    *,
    chirp: ChirpConfig | None = None,
    beacons: tuple[Beacon, ...] | None = None,
    params: Parameters | None = None,
    epoch: float = 0,
    templates: Mapping[str, FloatArray] | None = None,
) -> list[Fix]:
    return Pipeline(
        fs,
        chirp=chirp,
        beacons=beacons,
        params=params,
        epoch=epoch,
        templates=templates,
    ).feed(samples)


def write_fixes(path: Path, fixes: Sequence[Fix]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for fix in fixes:
            handle.write(
                json.dumps(asdict(fix), allow_nan=False, separators=(",", ":")) + "\n"
            )


def read_wav(path: Path) -> tuple[FloatArray, int]:
    with wave.open(str(path), "rb") as wav:
        if (
            wav.getnchannels() != 1
            or wav.getsampwidth() != 2
            or wav.getcomptype() != "NONE"
        ):
            raise ValueError("input WAV must be mono uncompressed 16-bit PCM")
        rate = wav.getframerate()
        count = wav.getnframes()
        data = wav.readframes(count)
        if len(data) != count * 2:
            raise ValueError("input WAV is truncated")
    return np.frombuffer(data, dtype="<i2").astype(float) / 32768, rate


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path)
    parser.add_argument("--out", type=Path, default=Path("fixes.jsonl"))
    parser.add_argument(
        "--beacons", type=Path, help="bare beacons config or full space.json"
    )
    parser.add_argument("--chirp", type=Path)
    parser.add_argument("--settings", type=Path)
    parser.add_argument("--mode", choices=("hand", "pocket"), default="hand")
    parser.add_argument(
        "--epoch",
        type=float,
        default=0,
        help="Unix seconds corresponding to WAV sample zero",
    )
    args = parser.parse_args(argv)
    samples, fs = read_wav(args.input)
    fixes = run_pipeline(
        samples,
        fs,
        beacons=load_beacon_config(args.beacons),
        chirp=load_chirp_config(args.chirp or args.settings),
        params=load_parameters(args.settings, args.mode),
        epoch=args.epoch,
    )
    write_fixes(args.out, fixes)
    print(f"{len(fixes)} valid fixes written to {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
