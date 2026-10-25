"""Pure numerical reference for LOCATOR_BRIEF sections 6.3–6.9.

Distances and solver residuals are in metres internally. Arrival timestamps
remain in the input sample clock; the unknown emission epoch is re-solved.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

import numpy as np
from numpy.typing import NDArray

from tools.common.chirp import ChirpConfig
from tools.common.config import Beacon
from tools.common.constants import speed_of_sound

FloatArray = NDArray[np.float64]
Quality = Literal["ok", "degraded"]


@dataclass(frozen=True)
class Parameters:
    gate_ms: float = 3.0
    lookback_ms: float = 2.0
    snr_min: float = 8.0
    snr_acquire: float = 10.0
    resid_max_ms: float = 0.30
    resid_ok_ms: float = 0.15
    height_mean_m: float = 1.25
    height_sigma_m: float = 0.25
    ear_offset_m: tuple[float, float, float] = (0.0, 0.0, 0.35)
    accel_sigma_mps2: float = 1.5
    meas_sigma_ok_m: float = 0.05
    meas_sigma_degraded_m: float = 0.15
    lost_timeout_s: float = 1.5
    air_temperature_c: float = 22.0

    def __post_init__(self) -> None:
        # Reject NaNs before they can poison FFTs or covariance matrices.
        for name, value in self.__dict__.items():
            if not np.all(np.isfinite(value)):
                raise ValueError(f"{name} must be finite")
        positive = (
            self.gate_ms,
            self.lookback_ms,
            self.snr_min,
            self.snr_acquire,
            self.resid_max_ms,
            self.resid_ok_ms,
            self.height_sigma_m,
            self.accel_sigma_mps2,
            self.meas_sigma_ok_m,
            self.meas_sigma_degraded_m,
            self.lost_timeout_s,
        )
        if min(positive) <= 0 or self.resid_ok_ms > self.resid_max_ms:
            raise ValueError(
                "thresholds and sigmas must be positive; resid_ok <= resid_max"
            )
        if len(self.ear_offset_m) != 3 or speed_of_sound(self.air_temperature_c) <= 0:
            raise ValueError(
                "ear offset must have three coordinates; sound speed must be positive"
            )


@dataclass(frozen=True)
class Detection:
    beacon: str
    arrival: float
    snr: float


@dataclass(frozen=True)
class Solution:
    position: FloatArray
    tau: float
    detections: tuple[Detection, ...]
    residual_rms_ms: float
    quality: Quality


def analytic_envelope(
    signal: FloatArray, template: FloatArray, fs: float, chirp: ChirpConfig
) -> FloatArray:
    """Linear FFT correlation, band mask, analytic magnitude at valid offsets.

    The mask is the zero-phase preprocessing filter. Combining it with the
    analytic correlation avoids an extra FFT and introduces no group delay.
    """
    if len(signal) < len(template) or not len(template):
        return np.empty(0)
    n = 1 << (len(signal) + len(template) - 2).bit_length()
    frequencies = np.fft.fftfreq(n, 1.0 / fs)
    spectrum = np.fft.fft(signal, n) * np.conj(np.fft.fft(template, n))
    mask = (frequencies >= chirp.f_lo - 300) & (frequencies <= chirp.f_hi + 300)
    analytic = np.fft.ifft(spectrum * mask * 2)
    return np.abs(analytic[: len(signal) - len(template) + 1])


def first_arrival(
    envelope: FloatArray, start: int, stop: int, fs: float, lookback_ms: float
) -> tuple[float, float] | None:
    """Earliest >= half-height local maximum within lookback of strongest peak."""
    start, stop = max(1, start), min(len(envelope) - 1, stop)
    if stop <= start:
        return None
    window = envelope[start:stop]
    peak = start + int(np.argmax(window))
    height = float(envelope[peak])
    if height <= np.finfo(float).eps:
        return None
    median = float(np.median(window))
    snr = height / max(median, np.finfo(float).eps)
    earliest = max(start, peak - round(lookback_ms * fs / 1000))
    indices = np.arange(earliest, peak + 1)
    local = indices[
        (envelope[indices] >= height * 0.5)
        & (envelope[indices] > envelope[indices - 1])
        & (envelope[indices] >= envelope[indices + 1])
    ]
    if not len(local):
        return None
    chosen = int(local[0])
    left, center, right = envelope[chosen - 1 : chosen + 2]
    denominator = left - 2 * center + right
    offset = (
        0.0
        if denominator == 0
        else float(np.clip(0.5 * (left - right) / denominator, -0.5, 0.5))
    )
    return chosen + offset, snr


def detect(
    samples: FloatArray,
    origin: int,
    template: FloatArray,
    fs: float,
    chirp: ChirpConfig,
    beacon: str,
    lo: float,
    hi: float,
    params: Parameters,
    threshold: float,
) -> Detection | None:
    """Search absolute sample-clock seconds, retaining 5ms FFT guard margins."""
    margin = round(0.005 * fs)
    first = max(origin, int(np.floor(lo * fs)) - margin)
    last = min(origin + len(samples), int(np.ceil(hi * fs)) + len(template) + margin)
    if last <= first or hi * fs + len(template) > origin + len(samples):
        return None
    envelope = analytic_envelope(
        samples[first - origin : last - origin], template, fs, chirp
    )
    found = first_arrival(
        envelope, int(lo * fs - first), int(hi * fs - first), fs, params.lookback_ms
    )
    if found is None or found[1] < threshold:
        return None
    return Detection(beacon, (first + found[0]) / fs, found[1])


def _fit(
    detections: tuple[Detection, ...],
    beacons: tuple[Beacon, ...],
    chirp: ChirpConfig,
    params: Parameters,
    initial: FloatArray,
) -> tuple[FloatArray, float, FloatArray] | None:
    by_id = {beacon.id: beacon for beacon in beacons}
    positions = np.array([by_id[d.beacon].position for d in detections])
    slots = np.array([by_id[d.beacon].slot for d in detections])
    c = speed_of_sound(params.air_temperature_c)
    epoch = detections[0].arrival
    observations = (
        np.array([d.arrival for d in detections]) - epoch - slots * chirp.slot_s
    ) * c
    p = initial.copy()
    bias = float(np.mean(observations - np.linalg.norm(p - positions, axis=1)))
    # Divide the metre-valued prior row by its relative standard deviation.
    # This makes the data sigma explicit rather than mixing seconds and metres.
    prior_weight = params.meas_sigma_ok_m / params.height_sigma_m
    for _ in range(10):
        differences = p - positions
        distances = np.linalg.norm(differences, axis=1)
        if np.any(distances < 1e-9):
            return None
        residuals = observations - distances - bias
        jacobian = np.column_stack(
            (differences / distances[:, None], np.ones(len(detections)))
        )
        jacobian = np.vstack((jacobian, [0, 0, prior_weight, 0]))
        residuals = np.append(residuals, (params.height_mean_m - p[2]) * prior_weight)
        delta, _, rank, _ = np.linalg.lstsq(jacobian, residuals, rcond=None)
        if rank < 4 or not np.all(np.isfinite(delta)):
            return None
        p += delta[:3]
        bias += float(delta[3])
        if np.linalg.norm(delta[:3]) < 0.001:
            break
    residuals_ms = (
        (observations - np.linalg.norm(p - positions, axis=1) - bias) / c * 1000
    )
    return p, epoch + bias / c, residuals_ms


def solve(
    detections: tuple[Detection, ...],
    beacons: tuple[Beacon, ...],
    chirp: ChirpConfig,
    params: Parameters,
    initial: FloatArray | None = None,
) -> Solution | None:
    """Gauss–Newton with a height prior, at most one worst-of-five rejection."""
    if len(detections) < 3:
        return None
    ids = [d.beacon for d in detections]
    if len(set(ids)) != len(ids) or not set(ids) <= {b.id for b in beacons}:
        raise ValueError("detections must identify distinct configured beacons")
    if not all(np.isfinite(d.arrival) and np.isfinite(d.snr) for d in detections):
        raise ValueError("detections must be finite")
    start = (
        np.array([0.0, 0.0, params.height_mean_m])
        if initial is None
        else np.asarray(initial, dtype=float)
    )
    fitted = _fit(detections, beacons, chirp, params, start)
    if fitted is None:
        return None
    if len(detections) == 5 and np.max(np.abs(fitted[2])) > params.resid_max_ms:
        worst = int(np.argmax(np.abs(fitted[2])))
        detections = tuple(d for i, d in enumerate(detections) if i != worst)
        fitted = _fit(detections, beacons, chirp, params, start)
        if fitted is None:
            return None
    position, tau, residuals = fitted
    rms = float(np.sqrt(np.mean(residuals**2)))
    if not np.isfinite(rms) or rms > params.resid_max_ms:
        return None
    quality: Quality = (
        "ok" if len(detections) >= 4 and rms <= params.resid_ok_ms else "degraded"
    )
    return Solution(position, tau, detections, rms, quality)


class Kalman:
    """Six-state constant-velocity filter, independent axes with shared model."""

    def __init__(self, params: Parameters) -> None:
        self.params = params
        self.state = np.zeros(6)
        self.covariance = np.eye(6)
        self.time: float | None = None

    def update(self, position: FloatArray, time: float, quality: Quality) -> FloatArray:
        if self.time is None:
            self.state[:3] = position
            self.time = time
            return position.copy()
        dt = time - self.time
        if dt <= 0:
            raise ValueError("Kalman measurement timestamps must increase")
        transition = np.eye(6)
        transition[:3, 3:] = np.eye(3) * dt
        drive = np.vstack((np.eye(3) * dt**2 / 2, np.eye(3) * dt))
        noise = drive @ drive.T * self.params.accel_sigma_mps2**2
        predicted = transition @ self.state
        covariance = transition @ self.covariance @ transition.T + noise
        sigma = (
            self.params.meas_sigma_ok_m
            if quality == "ok"
            else self.params.meas_sigma_degraded_m
        )
        measurement_noise = np.eye(3) * sigma**2
        gain = np.linalg.solve(
            covariance[:3, :3] + measurement_noise, covariance[:3, :]
        ).T
        self.state = predicted + gain @ (position - predicted[:3])
        correction = np.eye(6)
        correction[:, :3] -= gain
        self.covariance = (
            correction @ covariance @ correction.T + gain @ measurement_noise @ gain.T
        )
        self.time = time
        return self.state[:3].copy()

    def position_at(self, time: float) -> FloatArray:
        if self.time is None:
            return np.array([0.0, 0.0, self.params.height_mean_m])
        return self.state[:3] + self.state[3:] * (time - self.time)


class LossMonitor:
    """One lost transition per outage; never fabricates fixes or heartbeat poses."""

    def __init__(self, timeout: float = 1.5) -> None:
        self.timeout = timeout
        self.last_fix: float | None = None
        self.reported = False

    def fixed(self, time: float) -> None:
        self.last_fix = time
        self.reported = False

    def lost(self, time: float) -> bool:
        if (
            self.last_fix is None
            or self.reported
            or time - self.last_fix < self.timeout
        ):
            return False
        self.reported = True
        return True


class MarkerTracker:
    """Marker consistency and clock-rate estimation independent of SNR gates."""

    def __init__(self, cycle_s: float) -> None:
        self.cycle_s = cycle_s
        self.period = cycle_s
        self.last: float | None = None
        self.locked = False
        self.misses = 0

    @property
    def expected(self) -> float | None:
        return (
            None if self.last is None else self.last + self.period * (self.misses + 1)
        )

    def observe(self, marker: float | None) -> bool:
        if marker is None:
            self.misses += 1
            if self.misses >= 3:
                self.reset()
            return False
        expected = self.expected
        if expected is None:
            self.last = marker
            self.misses = 0
            return False
        if not self.locked and abs(marker - expected) > 0.001:
            return self.observe(None)
        if self.misses == 0:
            ratio = np.clip((marker - self.last) / self.cycle_s, 0.9999, 1.0001)
            self.period = 0.95 * self.period + 0.05 * ratio * self.cycle_s
        self.last = marker
        self.locked = True
        self.misses = 0
        return True

    def reset(self) -> None:
        self.last = None
        self.period = self.cycle_s
        self.locked = False
        self.misses = 0


def marker_candidate(
    samples: FloatArray,
    origin: int,
    template: FloatArray,
    fs: float,
    chirp: ChirpConfig,
    params: Parameters,
) -> Detection | None:
    """Search 400ms for a marker, then score only its configured ±gate window."""
    envelope = analytic_envelope(samples, template, fs, chirp)
    gate = round(params.gate_ms * fs / 1000)
    if len(envelope) < 2 * gate + 3:
        return None
    peak = gate + int(np.argmax(envelope[gate:-gate]))
    found = first_arrival(
        envelope, peak - gate, peak + gate + 1, fs, params.lookback_ms
    )
    if found is None or found[1] < params.snr_acquire:
        return None
    return Detection(chirp.marker_beacon, (origin + found[0]) / fs, found[1])
