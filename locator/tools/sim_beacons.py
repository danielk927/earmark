"""Synthetic beacon mic recording (LOCATOR_BRIEF.md section 7.2).

Renders what the iPhone microphone would hear: the five beacons chirping on
their fixed schedule, propagated to a moving mic position, plus hall noise.
Outputs a mono 16-bit WAV plus truth.json (mic positions over time, beacon
positions, parameters).

Modeled effects (brief section 7.2):
- true time-varying propagation delay, including Doppler, implemented by
  resampling: each output sample reads the source at the retarded time
  t_src = (t - tau - d(t)/c) / (1 + clock_err), interpolated linearly.
- 1/r spreading (amplitude 1/max(d, 0.1 m)).
- buzzer frequency response: a resonant band-pass centered at 2.7 kHz with
  Q ~= 3 (RBJ biquad, constant 0 dB peak gain), togglable.
- floor reflection (coefficient 0.5) and one wall reflection (0.3), modeled
  as image sources.
- body shadowing: -10 dB for beacons behind the user's facing direction
  (the facing yaw comes from the path spec).
- unknown start offset tau (the phone-clock time when cycle 0 begins at the
  beacon).
- an ESP32 clock error of up to +/-50 ppm (the ESP32 schedule and chirp
  play out on a clock running at rate 1 + clock_err).
- hall-like noise: pink noise plus random speech-band bursts. The noise is
  scaled so a single beacon chirp at 1 m has the requested SNR against it.

Python 3.11+, numpy + stdlib only (no scipy).

Run with no arguments (what `make sim` does): renders stand_on_mat for
5 s at the default config into out/sim/.
"""

from __future__ import annotations

import argparse
import json
import math
import wave
from dataclasses import dataclass
from pathlib import Path
from typing import Any, NamedTuple, Sequence

import numpy as np

# Allow running both as a script (`make sim`) and as a package module
# (`from tools import sim_beacons` in the tests).
if __package__ in (None, ""):  # pragma: no cover - exercised via script runs
    import sys

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.common.chirp import ChirpConfig, square_wave_samples
from tools.common.config import Beacon, load_beacon_config, load_chirp_config
from tools.common.constants import DEFAULT_TEMPERATURE_C, speed_of_sound

LOCATOR_ROOT = Path(__file__).resolve().parents[1]

#: Hand mode: phone held at chest height (the height prior mean, brief 8.6).
HAND_MIC_HEIGHT_M = 1.25
#: Shirt-pocket mode mic height (brief 8.6 pocket prior mean).
POCKET_MIC_HEIGHT_M = 1.30
#: Body shadowing for beacons behind the facing direction (brief 7.2).
SHADOW_DB = -10.0
#: Floor reflection coefficient (brief 7.2).
FLOOR_COEFF = 0.5
#: One wall reflection coefficient (brief 7.2).
WALL_COEFF = 0.3
#: Default reflecting wall: behind the mat, on the pill-box side (room is
#: about 3.5 x 3.5 m centered on the mat, brief section 1).
WALL_Y_M = -2.25
#: ESP32 clock error is drawn from +/- this many ppm (brief 7.2).
CLOCK_ERROR_PPM_LIMIT = 50.0
#: The buzzer response ring-down tail kept after the chirp ends.
SOURCE_TAIL_S = 0.005
#: Default SNR of one beacon chirp at 1 m against the hall noise.
DEFAULT_NOISE_SNR_DB = 25.0
#: truth.json mic-position trace stride in seconds.
TRUTH_STRIDE_S = 0.001
#: Master peak level the mix is normalized to.
MASTER_PEAK = 0.9


class Waypoint(NamedTuple):
    """Path waypoint: time [s], position [m], facing yaw [deg, 0 = +x, 90 = +y]."""

    t_s: float
    x: float
    y: float
    z: float
    yaw_deg: float


@dataclass(frozen=True)
class PathPreset:
    name: str
    description: str
    duration_s: float
    mode: str  # "hand" or "pocket"
    waypoints: tuple[Waypoint, ...]


def _wp(t: float, x: float, y: float, z: float | None, yaw: float, mode: str) -> Waypoint:
    if z is None:
        z = POCKET_MIC_HEIGHT_M if mode == "pocket" else HAND_MIC_HEIGHT_M
    return Waypoint(t, x, y, z, yaw)


def _make_preset(name: str, description: str, duration_s: float, mode: str,
                 points: Sequence[tuple[float, float, float, float | None, float]]) -> PathPreset:
    return PathPreset(
        name=name,
        description=description,
        duration_s=duration_s,
        mode=mode,
        waypoints=tuple(_wp(t, x, y, z, yaw, mode) for t, x, y, z, yaw in points),
    )


#: Preset paths (brief section 7.2). Facing yaw: 0 deg = +x, 90 deg = +y.
PATH_PRESETS: dict[str, PathPreset] = {
    preset.name: preset
    for preset in (
        _make_preset(
            "stand_on_mat",
            "stand still on the mat at the origin, facing forward (+y)",
            5.0,
            "hand",
            [(0.0, 0.0, 0.0, None, 90.0), (5.0, 0.0, 0.0, None, 90.0)],
        ),
        _make_preset(
            "walk_to_cupboard",
            "walk from the mat forward to the cupboard at y=1.2, facing +y",
            3.0,
            "hand",
            [(0.0, 0.0, 0.0, None, 90.0), (2.0, 0.0, 1.2, None, 90.0), (3.0, 0.0, 1.2, None, 90.0)],
        ),
        _make_preset(
            "walk_past_target",
            "walk along +x past beacon B2's ground projection at (1.5, 1.5)",
            2.5,
            "hand",
            [(0.0, -1.0, 1.5, None, 0.0), (2.5, 2.0, 1.5, None, 0.0)],
        ),
        _make_preset(
            "turn_around_walk_back",
            "stand 1 s facing +y, turn 180 deg, walk back to y=-1.2 (the pill box)",
            4.7,
            "hand",
            [
                (0.0, 0.0, 0.0, None, 90.0),
                (1.0, 0.0, 0.0, None, 90.0),
                (2.0, 0.0, 0.0, None, -90.0),
                (3.7, 0.0, -1.2, None, -90.0),
                (4.7, 0.0, -1.2, None, -90.0),
            ],
        ),
        _make_preset(
            "pocket_mode",
            "same walk as walk_to_cupboard, phone in a shirt pocket (mic at 1.30 m)",
            3.0,
            "pocket",
            [(0.0, 0.0, 0.0, None, 90.0), (2.0, 0.0, 1.2, None, 90.0), (3.0, 0.0, 1.2, None, 90.0)],
        ),
    )
}


class Trajectory:
    """Mic position and facing over time, piecewise-linear between waypoints."""

    def __init__(self, waypoints: Sequence[Waypoint]) -> None:
        if not waypoints:
            raise ValueError("trajectory needs at least one waypoint")
        times = np.array([w.t_s for w in waypoints], dtype=np.float64)
        if np.any(np.diff(times) < 0):
            raise ValueError("waypoint times must be non-decreasing")
        self._t = times
        self._pos = np.array([[w.x, w.y, w.z] for w in waypoints], dtype=np.float64)
        self._yaw = np.array([math.radians(w.yaw_deg) for w in waypoints], dtype=np.float64)

    def position(self, t_s: np.ndarray) -> np.ndarray:
        """Positions (N, 3) at times ``t_s`` (seconds)."""
        t = np.atleast_1d(np.asarray(t_s, dtype=np.float64))
        return np.column_stack([np.interp(t, self._t, self._pos[:, i]) for i in range(3)])

    def yaw(self, t_s: np.ndarray) -> np.ndarray:
        """Facing yaw in radians at times ``t_s``."""
        t = np.atleast_1d(np.asarray(t_s, dtype=np.float64))
        return np.interp(t, self._t, self._yaw)


def _biquad_bandpass(source: np.ndarray, fs: float, f_center_hz: float, q: float) -> np.ndarray:
    """RBJ constant-0dB-peak-gain band-pass biquad, causal, pure Python.

    Applied once per beacon to the short chirp source (hundreds of samples),
    so a scalar loop is cheap and exact.
    """
    w0 = 2.0 * math.pi * f_center_hz / fs
    alpha = math.sin(w0) / (2.0 * q)
    b0 = alpha
    b1 = 0.0
    b2 = -alpha
    a0 = 1.0 + alpha
    a1 = -2.0 * math.cos(w0)
    a2 = 1.0 - alpha
    out = np.zeros_like(source)
    x1 = x2 = y1 = y2 = 0.0
    for i, x0 in enumerate(source.tolist()):
        y0 = (b0 * x0 + b1 * x1 + b2 * x2 - a1 * y1 - a2 * y2) / a0
        out[i] = y0
        x2, x1 = x1, x0
        y2, y1 = y1, y0
    return out


@dataclass(frozen=True)
class _ImageSource:
    """Mirror image of a beacon across a reflecting surface."""

    position: tuple[float, float, float]
    gain: float


def _images_for(beacon: Beacon, wall_y_m: float, floor_coeff: float = FLOOR_COEFF,
                wall_coeff: float = WALL_COEFF) -> tuple[_ImageSource, ...]:
    direct = _ImageSource(beacon.position, 1.0)
    floor = _ImageSource(
        (beacon.position[0], beacon.position[1], -beacon.position[2]), floor_coeff
    )
    wall = _ImageSource(
        (beacon.position[0], 2.0 * wall_y_m - beacon.position[1], beacon.position[2]),
        wall_coeff,
    )
    return (direct, floor, wall)


def _shadow_gains(shadow_enabled: bool, beacon_pos: tuple[float, float, float],
                  mic_xy: np.ndarray, yaw_rad: np.ndarray) -> np.ndarray:
    """1.0 in front, 10^(SHADOW_DB/20) for beacons behind the facing direction."""
    if not shadow_enabled:
        return np.ones(mic_xy.shape[0])
    dx = beacon_pos[0] - mic_xy[:, 0]
    dy = beacon_pos[1] - mic_xy[:, 1]
    ahead = dx * np.cos(yaw_rad) + dy * np.sin(yaw_rad)
    return np.where(ahead < 0.0, 10.0 ** (SHADOW_DB / 20.0), 1.0)


def _render_image(out: np.ndarray, source: np.ndarray, fs: float, cfg: ChirpConfig,
                  trajectory: Trajectory, beacon: Beacon, image: _ImageSource,
                  cycle_index: int, tau_s: float, clock_err: float, c_mps: float,
                  shadow_enabled: bool) -> None:
    """Render one beacon chirp via one image source into ``out`` (in place)."""
    n_total = out.size
    t_e0 = cycle_index * cfg.cycle_s + beacon.slot * cfg.slot_s  # ESP32 time [s]
    t_emit = tau_s + t_e0 * (1.0 + clock_err)  # phone-clock emit start [s]
    chirp_end_phone = t_emit + cfg.chirp_s * (1.0 + clock_err)
    if t_emit - 0.05 > n_total / fs:
        return

    # Two-pass arrival window: d(t) varies while the user walks.
    n_center = min(n_total - 1, max(0, int(round(t_emit * fs))))
    d0 = float(np.linalg.norm(trajectory.position(np.array([n_center / fs]))[0] - image.position))
    t_lo = t_emit + d0 / c_mps - 0.02
    t_hi = chirp_end_phone + d0 / c_mps + 0.02
    t_scan = np.arange(max(0.0, t_lo), min(n_total / fs, t_hi), 1e-3)
    if t_scan.size:
        d_scan = np.linalg.norm(trajectory.position(t_scan) - image.position, axis=1)
        d_min = float(d_scan.min())
        d_max = float(d_scan.max())
    else:
        d_min = d_max = d0
    margin = 0.005
    n_lo = max(0, int(math.floor((t_emit + d_min / c_mps - margin) * fs)) - 1)
    n_hi = min(n_total, int(math.ceil((chirp_end_phone + d_max / c_mps + margin) * fs)) + 2)
    if n_hi <= n_lo:
        return

    n = np.arange(n_lo, n_hi, dtype=np.int64)
    t = n / fs
    mic = trajectory.position(t)
    d = np.linalg.norm(mic - image.position, axis=1)

    shadow = _shadow_gains(shadow_enabled, beacon.position, mic, trajectory.yaw(t))
    amp = image.gain * shadow / np.maximum(d, 0.1)

    # Retarded source time in ESP32 seconds; (1+clock_err) folds the beacon's
    # clock error into both the schedule and the chirp length (Doppler comes
    # from the time-varying d(t)/c term).
    t_src = (t - tau_s - d / c_mps) / (1.0 + clock_err) - t_e0
    idx = t_src * fs
    i0 = np.floor(idx).astype(np.int64)
    n_src = source.size
    valid = (i0 >= 0) & (i0 < n_src - 1)
    i0c = np.clip(i0, 0, max(0, n_src - 2))
    frac = idx - i0c
    value = np.where(valid, source[i0c] * (1.0 - frac) + source[i0c + 1] * frac, 0.0)
    out[n_lo:n_hi] += amp * value


def _pink_noise(n_samples: int, fs: float, rng: np.random.Generator) -> np.ndarray:
    """Unit-RMS pink noise (1/f power spectral density) via FFT shaping."""
    white = rng.standard_normal(n_samples)
    spectrum = np.fft.rfft(white)
    freqs_hz = np.fft.rfftfreq(n_samples, d=1.0 / fs)
    shape = 1.0 / np.sqrt(np.maximum(freqs_hz, 20.0))
    shaped = np.fft.irfft(spectrum * shape, n=n_samples)
    rms = float(np.sqrt(np.mean(shaped**2)))
    return shaped / rms if rms > 0 else shaped


def _speech_bursts(n_samples: int, fs: float, rng: np.random.Generator,
                   rate_per_s: float = 2.0, band_hz: tuple[float, float] = (100.0, 4000.0)) -> np.ndarray:
    """Sparse speech-band noise bursts, each ~unit RMS before the envelope."""
    out = np.zeros(n_samples)
    duration_s = n_samples / fs
    n_bursts = int(rng.poisson(rate_per_s * duration_s))
    for _ in range(n_bursts):
        burst_s = float(rng.uniform(0.08, 0.4))
        m = int(round(burst_s * fs))
        if m < 8 or m >= n_samples:
            continue
        start = int(rng.integers(0, n_samples - m))
        noise = rng.standard_normal(m)
        spec = np.fft.rfft(noise)
        freqs_hz = np.fft.rfftfreq(m, d=1.0 / fs)
        spec *= (freqs_hz >= band_hz[0]) & (freqs_hz <= band_hz[1])
        burst = np.fft.irfft(spec, n=m)
        rms = float(np.sqrt(np.mean(burst**2)))
        if rms > 0:
            burst = burst / rms
        out[start : start + m] += burst * np.hanning(m) * float(rng.uniform(0.5, 1.5))
    return out


def _chirp_rms_at_1m(cfg: ChirpConfig, fs: float, buzzer_response: bool,
                     f_center_hz: float, q: float) -> float:
    """RMS of one beacon chirp at 1 m with spreading gain 1 (the SNR reference)."""
    source = square_wave_samples(cfg, fs, beacon_id="B2")
    if buzzer_response:
        source = _biquad_bandpass(source, fs, f_center_hz, q)
    return float(np.sqrt(np.mean(source**2)))


@dataclass(frozen=True)
class SimResult:
    """Simulator output: quantized samples, float signal, and the truth dict."""

    fs: float
    samples_int16: np.ndarray
    signal: np.ndarray
    truth: dict[str, Any]


def run_sim(
    *,
    beacons: str | Path | None = None,
    chirp: str | Path | None = None,
    fs: float = 48000.0,
    duration_s: float | None = None,
    preset: str = "stand_on_mat",
    waypoints: Sequence[Waypoint] | None = None,
    mode: str | None = None,
    noise_snr_db: float | None = DEFAULT_NOISE_SNR_DB,
    seed: int = 0,
    tau_s: float | None = None,
    clock_error_ppm: float | None = None,
    buzzer_response: bool = True,
    body_shadowing: bool = True,
    f_center_hz: float = 2700.0,
    q_buzzer: float = 3.0,
    floor_coeff: float = FLOOR_COEFF,
    wall_coeff: float = WALL_COEFF,
    wall_y_m: float = WALL_Y_M,
    temperature_c: float = DEFAULT_TEMPERATURE_C,
) -> SimResult:
    """Render a synthetic mic recording; pure compute, no file I/O.

    Paths and chirp config take a path or None for the in-code defaults
    (brief sections 2.2 and 4.6). ``tau_s``/``clock_error_ppm`` default to
    seeded random draws in [0.05, 0.5] s and +/-50 ppm.
    """
    beacon_list = list(load_beacon_config(beacons))
    cfg = load_chirp_config(chirp)

    spec = PATH_PRESETS.get(preset)
    if waypoints is None:
        if spec is None:
            raise ValueError(f"unknown preset {preset!r}; one of {sorted(PATH_PRESETS)}")
        traj_waypoints: tuple[Waypoint, ...] = spec.waypoints
        duration = spec.duration_s if duration_s is None else float(duration_s)
        resolved_mode = mode or spec.mode
        preset_name = spec.name
    else:
        traj_waypoints = tuple(waypoints)
        duration = float(duration_s) if duration_s is not None else traj_waypoints[-1].t_s
        resolved_mode = mode or "hand"
        preset_name = "custom"
    if resolved_mode not in ("hand", "pocket"):
        raise ValueError(f"mode must be 'hand' or 'pocket', got {resolved_mode!r}")

    rng = np.random.default_rng(seed)
    tau = float(rng.uniform(0.05, 0.5)) if tau_s is None else float(tau_s)
    clock_ppm = (
        float(rng.uniform(-CLOCK_ERROR_PPM_LIMIT, CLOCK_ERROR_PPM_LIMIT))
        if clock_error_ppm is None
        else float(clock_error_ppm)
    )
    clock_err = clock_ppm * 1e-6
    c_mps = speed_of_sound(temperature_c)

    n_total = int(round(duration * fs))
    trajectory = Trajectory(traj_waypoints)
    out = np.zeros(n_total, dtype=np.float64)

    for beacon in beacon_list:
        # Per-beacon source: the quantized square-wave chirp (brief 4.3),
        # optionally shaped by the buzzer's resonant response, with a tail
        # for the filter's ring-down.
        source = square_wave_samples(cfg, fs, beacon_id=beacon.id)
        if buzzer_response:
            source = _biquad_bandpass(source, fs, f_center_hz, q_buzzer)
        source = np.concatenate([source, np.zeros(int(round(SOURCE_TAIL_S * fs)))])

        for image in _images_for(beacon, wall_y_m, floor_coeff, wall_coeff):
            cycle = 0
            while True:
                t_e0 = cycle * cfg.cycle_s + beacon.slot * cfg.slot_s
                if tau + t_e0 * (1.0 + clock_err) - 0.05 > duration:
                    break
                _render_image(
                    out, source, fs, cfg, trajectory, beacon, image,
                    cycle, tau, clock_err, c_mps, body_shadowing,
                )
                cycle += 1

    if noise_snr_db is not None and math.isfinite(noise_snr_db):
        reference_rms = _chirp_rms_at_1m(cfg, fs, buzzer_response, f_center_hz, q_buzzer)
        target_noise_rms = reference_rms * 10.0 ** (-noise_snr_db / 20.0)
        noise = _pink_noise(n_total, fs, rng) + _speech_bursts(n_total, fs, rng)
        noise_rms = float(np.sqrt(np.mean(noise**2)))
        if noise_rms > 0:
            out = out + noise * (target_noise_rms / noise_rms)

    peak = float(np.max(np.abs(out))) if out.size else 0.0
    master_gain = MASTER_PEAK / peak if peak > 0 else 1.0
    signal = out * master_gain
    samples = np.clip(np.round(signal * 32767.0), -32768, 32767).astype(np.int16)

    truth = _build_truth(
        fs=fs, duration_s=duration, preset_name=preset_name, mode=resolved_mode,
        beacons=beacon_list, cfg=cfg, trajectory=trajectory, tau=tau,
        clock_ppm=clock_ppm, noise_snr_db=noise_snr_db, buzzer_response=buzzer_response,
        body_shadowing=body_shadowing,
        f_center_hz=f_center_hz, q_buzzer=q_buzzer, floor_coeff=floor_coeff,
        wall_coeff=wall_coeff, wall_y_m=wall_y_m, temperature_c=temperature_c,
        c_mps=c_mps, seed=seed, master_gain=master_gain,
    )
    return SimResult(fs=fs, samples_int16=samples, signal=signal, truth=truth)


def _build_truth(**params: Any) -> dict[str, Any]:
    fs: float = params["fs"]
    duration_s: float = params["duration_s"]
    trajectory: Trajectory = params["trajectory"]
    n_total = int(round(duration_s * fs))
    stride = max(1, int(round(TRUTH_STRIDE_S * fs)))
    trace_idx = np.arange(0, n_total + 1, stride)
    trace_t = np.minimum(trace_idx, n_total) / fs
    trace_pos = trajectory.position(trace_t)
    trace_yaw = trajectory.yaw(trace_t)

    noise_snr = params["noise_snr_db"]
    return {
        "version": 1,
        "fs": float(fs),
        "n_samples": n_total,
        "duration_s": float(duration_s),
        "preset": params["preset_name"],
        "mode": params["mode"],
        "beacons": [b.to_dict() for b in params["beacons"]],
        "chirp": params["cfg"].to_dict(),
        "tau_s": float(params["tau"]),
        "clock_error_ppm": float(params["clock_ppm"]),
        "temperature_c": float(params["temperature_c"]),
        "speed_of_sound_mps": float(params["c_mps"]),
        "noise_snr_at_1m_db": None if noise_snr is None else float(noise_snr),
        "buzzer_response_hz": params["f_center_hz"] if params["buzzer_response"] else None,
        "buzzer_response_q": params["q_buzzer"] if params["buzzer_response"] else None,
        "floor_reflection_coeff": float(params["floor_coeff"]),
        "wall_reflection_coeff": float(params["wall_coeff"]),
        "wall_y_m": float(params["wall_y_m"]),
        "body_shadowing_db": SHADOW_DB if params["body_shadowing"] else None,
        "seed": int(params["seed"]),
        "master_gain": float(params["master_gain"]),
        "truth": {
            "t": [round(float(t), 6) for t in trace_t],
            "position": [
                [round(float(x), 6), round(float(y), 6), round(float(z), 6)]
                for x, y, z in trace_pos
            ],
            "facing_yaw_rad": [round(float(y), 6) for y in trace_yaw],
        },
    }


def write_wav(path: Path, samples_int16: np.ndarray, fs: float) -> Path:
    """Write mono 16-bit PCM WAV (stdlib wave)."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(int(fs))
        handle.writeframes(samples_int16.tobytes())
    return path


def write_truth(path: Path, truth: dict[str, Any]) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(truth, handle, indent=2)
        handle.write("\n")
    return path


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Render a synthetic beacon mic recording (brief section 7.2)."
    )
    parser.add_argument("--beacons", help="beacon config JSON (bare or full space.json); default: config/beacons.json")
    parser.add_argument("--chirp", help="chirp config JSON (brief 4.6); default: config/chirp.json")
    parser.add_argument("--fs", type=float, default=48000.0, help="sample rate [Hz], default 48000")
    parser.add_argument("--duration", type=float, help="render length [s]; default: the preset's duration")
    parser.add_argument("--path", default="stand_on_mat", choices=sorted(PATH_PRESETS), help="path preset")
    parser.add_argument("--waypoints", help="custom path JSON: [{'t_s':..,'x':..,'y':..,'z':..,'yaw_deg':..}, ...]")
    parser.add_argument("--mode", choices=("hand", "pocket"), help="override the preset's hand/pocket mode")
    parser.add_argument("--noise-snr", type=float, default=DEFAULT_NOISE_SNR_DB,
                        help="SNR [dB] of one chirp at 1 m vs hall noise; pass 'inf' for clean")
    parser.add_argument("--clean", action="store_true", help="disable hall noise entirely")
    parser.add_argument("--seed", type=int, default=0, help="random seed (tau, clock error, noise)")
    parser.add_argument("--tau", type=float, help="pin the schedule start offset [s]")
    parser.add_argument("--clock-error-ppm", type=float, help="pin the ESP32 clock error [+/-50]")
    parser.add_argument("--no-buzzer-response", action="store_true", help="skip the 2.7 kHz buzzer resonance")
    parser.add_argument("--out", default=str(LOCATOR_ROOT / "out" / "sim"), help="output directory")
    args = parser.parse_args(argv)

    waypoints: list[Waypoint] | None = None
    if args.waypoints:
        raw = json.loads(Path(args.waypoints).read_text(encoding="utf-8"))
        waypoints = [
            Waypoint(float(w["t_s"]), float(w["x"]), float(w["y"]), float(w["z"]), float(w["yaw_deg"]))
            for w in raw
        ]

    result = run_sim(
        beacons=args.beacons,
        chirp=args.chirp,
        fs=args.fs,
        duration_s=args.duration,
        preset=args.path,
        waypoints=waypoints,
        mode=args.mode,
        noise_snr_db=None if (args.clean or args.noise_snr == float("inf")) else args.noise_snr,
        seed=args.seed,
        tau_s=args.tau,
        clock_error_ppm=args.clock_error_ppm,
        buzzer_response=not args.no_buzzer_response,
    )

    out_dir = Path(args.out)
    wav_path = write_wav(out_dir / "sim.wav", result.samples_int16, result.fs)
    truth_path = write_truth(out_dir / "truth.json", result.truth)
    cfg: ChirpConfig = load_chirp_config(args.chirp)
    n_cycles = math.floor((result.truth["duration_s"] - result.truth["tau_s"]) / cfg.cycle_s)
    print(f"wrote {wav_path}")
    print(f"wrote {truth_path}")
    print(
        f"preset={result.truth['preset']} fs={result.fs:.0f} duration={result.truth['duration_s']}s "
        f"tau={result.truth['tau_s']:.4f}s clock_err={result.truth['clock_error_ppm']:+.1f}ppm "
        f"noise_snr_at_1m={result.truth['noise_snr_at_1m_db']}dB full_cycles={max(n_cycles, 0)}"
    )
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
