"""Find chirps in a recording and say when each one started, to a fraction of a sample."""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy.signal import butter, correlate, hilbert, sosfiltfilt

from .chirp import ChirpSpec, synth


@dataclass(frozen=True)
class Event:
    t: float  # seconds from the start of the audio passed in, when the chirp started
    shape: str  # "up" or "down"
    score: float  # how strong the match is
    snr: float  # peak over the typical background, as a plain ratio


class Detector:
    def __init__(self, spec: ChirpSpec, fs: float, min_snr: float = 4.5) -> None:
        self.spec, self.fs, self.min_snr = spec, fs, min_snr
        self.templates = {d: synth(spec, fs, d, amplitude=1.0) for d in ("up", "down")}
        lo, hi = max(spec.f_lo - 600.0, 200.0), min(spec.f_hi + 600.0, fs / 2 - 200.0)
        self._sos = butter(4, [lo, hi], btype="bandpass", fs=fs, output="sos")
        self._min_gap = int(0.5 * spec.length_ms / 1000.0 * fs) + int(0.012 * fs)

    def _envelope(self, audio: np.ndarray, direction: str) -> np.ndarray:
        c = correlate(audio, self.templates[direction], mode="valid", method="fft")
        return np.abs(hilbert(c))

    def find(self, audio: np.ndarray) -> list[Event]:
        """Every chirp in `audio` (any slot), strongest first within each shape, in time order overall."""
        x = np.asarray(audio, dtype=np.float64)
        if len(x) < len(self.templates["up"]) * 2:
            return []
        x = sosfiltfilt(self._sos, x)
        env = {d: self._envelope(x, d) for d in ("up", "down")}
        events: list[Event] = []
        for d, e in env.items():
            floor = float(np.median(e)) + 1e-12
            threshold = self.min_snr * floor
            idx = np.flatnonzero((e[1:-1] > e[:-2]) & (e[1:-1] >= e[2:]) & (e[1:-1] > threshold)) + 1
            for i in idx:
                other = env["down" if d == "up" else "up"][i]
                if e[i] < 1.2 * other:  # the other template matches as well: this is not a clean chirp of this shape
                    continue
                y0, y1, y2 = e[i - 1], e[i], e[i + 1]
                denom = y0 - 2 * y1 + y2
                frac = 0.5 * (y0 - y2) / denom if denom != 0 else 0.0
                events.append(Event((i + frac) / self.fs, d, float(y1), float(y1 / floor)))
        events.sort(key=lambda ev: ev.t)
        # keep only the strongest event inside any short stretch (echoes and sidelobes)
        kept: list[Event] = []
        for ev in events:
            if kept and ev.t - kept[-1].t < self._min_gap / self.fs:
                if ev.score > kept[-1].score:
                    kept[-1] = ev
                continue
            kept.append(ev)
        return kept
