"""Chirp waveform definition shared by firmware, app, and tools.

Implements brief section 4.3 exactly:

- A square-wave linear frequency sweep of duration ``T = length_ms``,
  from ``f_start`` to ``f_end``.
- Rising sweep (B2-B5): f_start = f_lo, f_end = f_hi.
- Falling sweep (B1, the cycle marker): f_start = f_hi, f_end = f_lo.
- Instantaneous phase phi(t) = 2*pi*(f_start*t + (f_end - f_start)*t^2/(2T)),
  for 0 <= t <= T.
- Edges happen where phi crosses k*pi, for k = 1, 2, ...
- Output HIGH (active) on even half-cycles starting at t = 0, and toggle at
  each edge.
- Edge times are quantized to a 0.1 us tick (10 MHz), matching what the
  ESP32 RMT hardware would be programmed with.

The audio-rate synthesis evaluates the level from the *quantized* edge
schedule, so the Python reference waveform is identical to the firmware's
output sampled at the same rate.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

from .constants import TICK_S

#: Allowed frequency range for f_lo/f_hi in Hz (brief section 4.3).
F_MIN_HZ = 1000.0
F_MAX_HZ = 20000.0
#: Minimum sweep width f_hi - f_lo in Hz.
MIN_SWEEP_HZ = 1000.0
#: Allowed chirp length range in ms.
LENGTH_MS_RANGE = (5.0, 40.0)
#: Allowed slot length range in ms (brief section 4.4).
SLOT_MS_RANGE = (30.0, 100.0)

_RISING = "up"
_FALLING = "down"


@dataclass(frozen=True)
class ChirpConfig:
    """The single source of truth for the chirp definition (brief 4.6).

    Defaults are the brief section 4.6 placeholder values, valid until the
    band test (brief section 7.3) picks the final band.
    """

    f_lo: float = 2000.0
    f_hi: float = 4500.0
    length_ms: float = 12.0
    slot_ms: float = 50.0
    n_slots: int = 6
    marker_beacon: str = "B1"
    marker_direction: str = "down"
    others_direction: str = "up"
    version: int = 1

    def __post_init__(self) -> None:
        self._validate()

    def _validate(self) -> None:
        for name in ("f_lo", "f_hi", "length_ms", "slot_ms"):
            value = float(getattr(self, name))
            if not math.isfinite(value):
                raise ValueError(f"chirp config {name} must be finite, got {value!r}")
        f_lo = float(self.f_lo)
        f_hi = float(self.f_hi)
        if not (F_MIN_HZ <= f_lo <= F_MAX_HZ):
            raise ValueError(
                f"f_lo {f_lo} Hz outside allowed range [{F_MIN_HZ}, {F_MAX_HZ}] Hz"
            )
        if not (F_MIN_HZ <= f_hi <= F_MAX_HZ):
            raise ValueError(
                f"f_hi {f_hi} Hz outside allowed range [{F_MIN_HZ}, {F_MAX_HZ}] Hz"
            )
        if f_hi - f_lo < MIN_SWEEP_HZ:
            raise ValueError(
                f"f_hi - f_lo = {f_hi - f_lo} Hz below minimum {MIN_SWEEP_HZ} Hz"
            )
        if not (LENGTH_MS_RANGE[0] <= float(self.length_ms) <= LENGTH_MS_RANGE[1]):
            raise ValueError(
                f"length_ms {self.length_ms} outside allowed range "
                f"{list(LENGTH_MS_RANGE)}"
            )
        if not (SLOT_MS_RANGE[0] <= float(self.slot_ms) <= SLOT_MS_RANGE[1]):
            raise ValueError(
                f"slot_ms {self.slot_ms} outside allowed range {list(SLOT_MS_RANGE)}"
            )
        if int(self.n_slots) < 5:
            # Five beacons occupy slots 0-4; the brief reserves a 6th silent slot.
            raise ValueError(f"n_slots {self.n_slots} must leave slots 0-4 for beacons")
        if self.marker_direction not in (_RISING, _FALLING):
            raise ValueError(f"marker_direction {self.marker_direction!r} not up|down")
        if self.others_direction not in (_RISING, _FALLING):
            raise ValueError(f"others_direction {self.others_direction!r} not up|down")
        if int(self.version) != 1:
            raise ValueError(f"unsupported chirp config version {self.version}")

    @property
    def chirp_s(self) -> float:
        """Chirp duration in seconds."""
        return float(self.length_ms) / 1000.0

    @property
    def slot_s(self) -> float:
        """Slot duration in seconds."""
        return float(self.slot_ms) / 1000.0

    @property
    def cycle_s(self) -> float:
        """Cycle duration (n_slots slots) in seconds."""
        return int(self.n_slots) * self.slot_s

    def to_dict(self) -> dict:
        """JSON-safe dict in the brief section 4.6 layout."""
        return {
            "f_lo": float(self.f_lo),
            "f_hi": float(self.f_hi),
            "length_ms": float(self.length_ms),
            "slot_ms": float(self.slot_ms),
            "n_slots": int(self.n_slots),
            "marker": {
                "beacon": self.marker_beacon,
                "direction": self.marker_direction,
            },
            "others_direction": self.others_direction,
            "version": int(self.version),
        }

    def sweep_for(self, beacon_id: str) -> tuple[float, float]:
        """(f_start, f_end) in Hz for ``beacon_id``.

        The marker beacon sweeps in ``marker_direction`` (down by default);
        every other beacon sweeps in ``others_direction`` (up by default).
        """
        if beacon_id == self.marker_beacon:
            direction = self.marker_direction
        else:
            direction = self.others_direction
        if direction == _RISING:
            return (float(self.f_lo), float(self.f_hi))
        return (float(self.f_hi), float(self.f_lo))


def _max_half_cycles(f_start: float, f_end: float, t_chirp_s: float) -> int:
    """Number of pi crossings phi(t) makes for t in (0, t_chirp_s).

    phi(T) = 2*pi*T*(f_start + f_end)/2, so k_max = floor(T*(f_start+f_end)).
    """
    return int(math.floor(t_chirp_s * (f_start + f_end) + 1e-9))


def chirp_edge_times_s(
    cfg: ChirpConfig,
    beacon_id: str | None = None,
    f_start: float | None = None,
    f_end: float | None = None,
) -> np.ndarray:
    """Unquantized edge times t_k (seconds) where phi(t_k) = k*pi, k = 1, 2, ...

    Solves a*f_start*t^2/... via the quadratic
        a*t^2 + f_start*t - k/2 = 0,  a = (f_end - f_start)/(2T),
    using the cancellation-free root  t_k = k / (f_start + sqrt(f_start^2 + 2*a*k))
    which is exact for both rising (a > 0) and falling (a < 0) sweeps and
    reduces to k/(2*f_start) for a == 0.
    """
    t_chirp_s = cfg.chirp_s
    if f_start is None or f_end is None:
        assert beacon_id is not None, "provide beacon_id or an explicit sweep"
        f_start, f_end = cfg.sweep_for(beacon_id)
    f_start = float(f_start)
    f_end = float(f_end)
    a = (f_end - f_start) / (2.0 * t_chirp_s)
    k = np.arange(1, _max_half_cycles(f_start, f_end, t_chirp_s) + 1, dtype=np.float64)
    discriminant = f_start**2 + 2.0 * a * k
    # Guard the (non-occurring for valid configs) sqrt domain; the final edge
    # satisfies discriminant >= f_end^2 > 0.
    t_k = k / (f_start + np.sqrt(np.maximum(discriminant, 1e-12)))
    return t_k[t_k < t_chirp_s - 1e-12]


def chirp_edge_ticks(
    cfg: ChirpConfig,
    beacon_id: str | None = None,
    f_start: float | None = None,
    f_end: float | None = None,
) -> np.ndarray:
    """Edge times quantized to 0.1 us ticks, as integer tick counts from chirp start.

    Round-half-up (floor(x + 0.5)) matches the C round() the firmware uses.
    """
    t_k = chirp_edge_times_s(cfg, beacon_id, f_start, f_end)
    ticks = np.floor(t_k / TICK_S + 0.5).astype(np.int64)
    if ticks.size > 1 and not np.all(np.diff(ticks) > 0):
        raise AssertionError("quantized chirp edges are not strictly increasing")
    return ticks


def square_wave_samples(
    cfg: ChirpConfig,
    fs: float,
    beacon_id: str | None = None,
    f_start: float | None = None,
    f_end: float | None = None,
    quantized: bool = True,
) -> np.ndarray:
    """Sample the +/-1 square-wave chirp at ``fs`` over its duration [0, T).

    Level is +1 (HIGH) during even half-cycles starting at t = 0 and -1
    during odd half-cycles. Sample values are evaluated at sample-center
    times (n + 0.5)/fs so a sample never straddles an edge exactly.
    Returns ``round(T * fs)`` float64 samples.
    """
    n_samples = int(round(cfg.chirp_s * fs))
    t_center = (np.arange(n_samples, dtype=np.float64) + 0.5) / fs
    if quantized:
        edges = chirp_edge_ticks(cfg, beacon_id, f_start, f_end) * TICK_S
    else:
        edges = chirp_edge_times_s(cfg, beacon_id, f_start, f_end)
    edges_leq = np.searchsorted(edges, t_center, side="right")
    return np.where(edges_leq % 2 == 0, 1.0, -1.0)
