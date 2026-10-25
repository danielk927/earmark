"""The chirp every phone plays: a short linear sweep, a rising one in even slots and a falling one in odd slots."""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

SPEED_OF_SOUND_M_S = 343.0  # at about 20 C


@dataclass(frozen=True)
class ChirpSpec:
    f_lo: float = 17000.0
    f_hi: float = 20000.0
    length_ms: float = 40.0
    amplitude: float = 1.0  # 0..1 of full scale

    def as_dict(self) -> dict:
        return {"f_lo": self.f_lo, "f_hi": self.f_hi, "length_ms": self.length_ms, "amplitude": self.amplitude}

    @classmethod
    def from_dict(cls, d: dict) -> "ChirpSpec":
        return cls(float(d["f_lo"]), float(d["f_hi"]), float(d["length_ms"]), float(d.get("amplitude", 0.8)))


def direction_for_slot(slot: int) -> str:
    """Even slots sweep up, odd slots sweep down, so neighbours in time look different to the detector."""
    return "up" if slot % 2 == 0 else "down"


def synth_at(spec: ChirpSpec, direction: str, t: np.ndarray, amplitude: float | None = None) -> np.ndarray:
    """The chirp evaluated at arbitrary times (seconds after it starts), so tests can place it between samples."""
    length = spec.length_ms / 1000.0
    f0, f1 = (spec.f_lo, spec.f_hi) if direction == "up" else (spec.f_hi, spec.f_lo)
    k = (f1 - f0) / length
    phase = 2 * np.pi * (f0 * t + 0.5 * k * t * t)
    x = np.clip(t / length, 0.0, 1.0)
    alpha = 0.4  # Tukey fade: cosine ramps over the first and last fifth
    ramp = np.where(x < alpha / 2, 0.5 * (1 + np.cos(2 * np.pi / alpha * (x - alpha / 2))),
                    np.where(x > 1 - alpha / 2, 0.5 * (1 + np.cos(2 * np.pi / alpha * (x - 1 + alpha / 2))), 1.0))
    a = spec.amplitude if amplitude is None else amplitude
    return np.where((t >= 0) & (t <= length), a * np.sin(phase) * ramp, 0.0)


def synth(spec: ChirpSpec, fs: float, direction: str = "up", amplitude: float | None = None) -> np.ndarray:
    """One chirp as float samples in -1..1, faded in and out so the speaker does not click."""
    n = int(round(spec.length_ms / 1000.0 * fs))
    return synth_at(spec, direction, np.arange(n) / fs, amplitude).astype(np.float32)
