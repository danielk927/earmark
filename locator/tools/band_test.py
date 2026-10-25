"""Received-level band test on a sweep recording (LOCATOR_BRIEF.md section 7.3).

Input is a WAV recorded during the firmware's ``sweep <n>`` command
(section 4.5): 2 s of silence, then a linear sweep 1 -> 20 kHz over 10 s,
then silence. The tool detects the sweep onset automatically, computes the
received level versus frequency from 1 to 20 kHz, and recommends the
2.5 kHz-wide band that maximizes the minimum level across the band. It
prints the exact firmware serial command, e.g. ``band 2100 4600``, and the
matching chirp config JSON (section 4.6) to paste into the app.

The plot is saved with matplotlib when it is installed; otherwise the level
curve is written as CSV instead (same numbers, no picture).

Python 3.11+, numpy + stdlib only for the analysis; matplotlib optional.

Usage: python3 tools/band_test.py RECORDING.wav [--out DIR] [--chirp config/chirp.json]
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import sys
import wave
from pathlib import Path
from typing import Sequence

import numpy as np

# Allow running both as a script (`make bandtest FILE=...`) and as a package
# module (`from tools import band_test` in the tests).
if __package__ in (None, ""):  # pragma: no cover - exercised via script runs
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.common.chirp import ChirpConfig
from tools.common.config import ConfigError, load_chirp_config

LOCATOR_ROOT = Path(__file__).resolve().parents[1]

#: The firmware sweep (brief section 4.5): 1 -> 20 kHz, linear, over 10 s.
SWEEP_F_MIN_HZ = 1000.0
SWEEP_F_MAX_HZ = 20000.0
SWEEP_DURATION_S = 10.0
#: Recommended band width (brief section 7.3).
BAND_WIDTH_HZ = 2500.0
#: Resolution of the level curve and the band-search grid [Hz].
STEP_HZ = 50.0
#: STFT size for the level measurement.
NFFT = 4096
#: Onset detection: a frame counts as "sweep present" when its wideband level
#: exceeds this margin over the quiet floor, sustained for HOLD_FRAMES frames.
ONSET_MARGIN_DB = 8.0
ONSET_HOLD_FRAMES = 10
ONSET_FRAME_S = 0.02


class BandTestError(RuntimeError):
    """Raised when the recording has no detectable sweep."""


def read_wav_mono(path: str | Path) -> tuple[np.ndarray, float]:
    """Read a WAV as mono float64 samples in [-1, 1] plus its sample rate.

    Multi-channel files are averaged to mono; only 16-bit PCM is expected
    (the app records 16-bit, section 8.7).
    """
    with wave.open(str(path), "rb") as handle:
        n_channels = handle.getnchannels()
        samp_width = handle.getsampwidth()
        fs = float(handle.getframerate())
        frames = handle.readframes(handle.getnframes())
    if samp_width != 2:
        raise BandTestError(f"{path}: expected 16-bit PCM, got {samp_width * 8}-bit")
    interleaved = np.frombuffer(frames, dtype="<i2").astype(np.float64) / 32768.0
    if n_channels > 1:
        interleaved = interleaved.reshape(-1, n_channels).mean(axis=1)
    if interleaved.size == 0:
        raise BandTestError(f"{path}: empty recording")
    return interleaved, fs


def detect_sweep_onset(samples: np.ndarray, fs: float) -> float:
    """First-sweep time [s]: the sustained wideband rise above the quiet floor.

    The recording starts with at least 2 s of silence (the firmware's
    ``sweep`` command lead-in), so the 10th percentile of frame levels is a
    robust noise floor. The onset is the first frame that exceeds the floor
    by ONSET_MARGIN_DB and stays above half that margin for
    ONSET_HOLD_FRAMES consecutive frames (a noise blip cannot hold it).
    """
    samples = np.asarray(samples, dtype=np.float64)  # int16 WAV data would overflow when squared
    frame_len = max(1, int(round(ONSET_FRAME_S * fs)))
    n_frames = samples.size // frame_len
    if n_frames < ONSET_HOLD_FRAMES * 3:
        raise BandTestError(
            f"recording too short for onset detection ({samples.size / fs:.2f}s)"
        )
    frame_levels_db = 10.0 * np.log10(
        np.maximum(
            np.mean(samples[: n_frames * frame_len].reshape(n_frames, frame_len) ** 2, axis=1),
            1e-20,
        )
    )
    floor_db = float(np.percentile(frame_levels_db, 10))
    loud = frame_levels_db > floor_db + ONSET_MARGIN_DB
    holding = frame_levels_db > floor_db + ONSET_MARGIN_DB / 2.0
    # A run of ONSET_HOLD_FRAMES loud-and-holding frames marks the sweep.
    run = 0
    for i in range(n_frames):
        run = run + 1 if loud[i] and holding[i] else 0
        if run >= ONSET_HOLD_FRAMES:
            return (i - ONSET_HOLD_FRAMES + 1) * frame_len / fs
    raise BandTestError(
        "no sweep onset found: the recording never rises "
        f"{ONSET_MARGIN_DB:.0f} dB above its quiet floor — re-record closer "
        "(bring-up B3 'on fail' path)"
    )


def level_vs_frequency(
    samples: np.ndarray,
    fs: float,
    onset_s: float,
    sweep_duration_s: float = SWEEP_DURATION_S,
    f_min_hz: float = SWEEP_F_MIN_HZ,
    f_max_hz: float = SWEEP_F_MAX_HZ,
    step_hz: float = STEP_HZ,
    nfft: int = NFFT,
) -> tuple[np.ndarray, np.ndarray]:
    """Received level [dB] at each grid frequency, 1-20 kHz.

    The sweep passes frequency f at time onset + (f - 1000)/rate, so each
    STFT frame maps to the frequency it was swept at; the frame's in-band
    energy is the received level there. Frames are interpolated onto a
    ``step_hz`` grid. The firmware sweeps a *square* wave, so a frame also
    carries its odd harmonics; that energy is part of what a real chirp
    delivers and is included (documented behavior, not a bug).

    Returns (freqs_hz, levels_db), levels nan where the sweep never arrived
    (recording ended early).
    """
    if samples.size < nfft:
        raise BandTestError("recording shorter than one FFT window")
    hop = nfft // 2
    window = np.hanning(nfft)
    n_frames = 1 + (samples.size - nfft) // hop
    frame_start = np.arange(n_frames) * hop
    centered = samples[frame_start[:, None] + np.arange(nfft)[None, :]] * window[None, :]
    spectrum = np.fft.rfft(centered, axis=1)
    power = np.abs(spectrum) ** 2
    bin_hz = fs / nfft
    # In-band energy: bins from f_min - one bin width up to Nyquist, so the
    # level reflects everything the sweep actually delivered above f_min.
    bin_slice = power[:, max(0, int((f_min_hz - bin_hz) / bin_hz)) :]
    in_band = bin_slice.sum(axis=1)
    t_center = (frame_start + nfft / 2.0) / fs
    sweep_rate = (SWEEP_F_MAX_HZ - SWEEP_F_MIN_HZ) / sweep_duration_s
    f_center = SWEEP_F_MIN_HZ + (t_center - onset_s) * sweep_rate
    # Guard the FFT edges: the first/last half-window sees a partial sweep.
    valid = (
        (t_center >= onset_s + nfft / (2.0 * fs))
        & (t_center <= onset_s + sweep_duration_s - nfft / (2.0 * fs))
        & (f_center >= f_min_hz)
        & (f_center <= f_max_hz)
    )
    freqs = np.arange(f_min_hz, f_max_hz + step_hz / 2.0, step_hz)
    if int(valid.sum()) < 2:
        empty = np.full(freqs.size, np.nan)
        return freqs, empty
    levels_db = 10.0 * np.log10(np.maximum(in_band, 1e-20))
    curve = np.interp(freqs, f_center[valid], levels_db[valid])
    return freqs, curve


def recommend_band(
    freqs_hz: np.ndarray,
    levels_db: np.ndarray,
    width_hz: float = BAND_WIDTH_HZ,
    f_min_hz: float = SWEEP_F_MIN_HZ,
    f_max_hz: float = SWEEP_F_MAX_HZ,
    step_hz: float = STEP_HZ,
) -> tuple[int, int]:
    """The ``width_hz``-wide band maximizing the minimum level (brief 7.3).

    Scans candidate low edges on the ``step_hz`` grid within chirp-config
    limits (f_lo >= 1000, f_hi <= 20000, section 4.3). Ties on the minimum
    break on the band's mean level, then on the lowest edge (buzzers are
    loudest and the phone mic flattest at the low end). Unmeasured
    frequencies (NaN) are excluded from scoring.
    """
    measured = ~np.isnan(levels_db)
    if measured.sum() < 2:
        raise BandTestError("level curve is empty: no measurable sweep in the recording")
    freqs_m = freqs_hz[measured]
    levels_m = levels_db[measured]
    best: tuple[float, float, float] | None = None
    best_band = (int(f_min_hz), int(f_min_hz + width_hz))
    lo = f_min_hz
    while lo + width_hz <= f_max_hz + 1e-9:
        hi = lo + width_hz
        inside = (freqs_m > lo) & (freqs_m <= hi)
        if inside.sum() >= 2:
            min_level = float(levels_m[inside].min())
            mean_level = float(levels_m[inside].mean())
            score = (min_level, mean_level, -lo)  # lowest edge wins ties
            if best is None or score > best:
                best = score
                best_band = (int(round(lo)), int(round(hi)))
        lo += step_hz
    return best_band


def chirp_config_json(band_lo_hz: int, band_hi_hz: int, base: ChirpConfig) -> str:
    """The section 4.6 chirp config JSON with the recommended band, one line.

    f_lo/f_hi are integers, matching the brief 4.6 example and the firmware's
    ``config`` output the bring-up (B3 step 4) diffs this against.
    """
    cfg = ChirpConfig(
        f_lo=float(band_lo_hz),
        f_hi=float(band_hi_hz),
        length_ms=base.length_ms,
        slot_ms=base.slot_ms,
        n_slots=base.n_slots,
        marker_beacon=base.marker_beacon,
        marker_direction=base.marker_direction,
        others_direction=base.others_direction,
        version=base.version,
    )
    payload = cfg.to_dict()
    payload["f_lo"] = int(band_lo_hz)
    payload["f_hi"] = int(band_hi_hz)
    return json.dumps(payload, separators=(",", ":"))


def save_plot(
    path: Path, freqs_hz: np.ndarray, levels_db: np.ndarray, band: tuple[int, int]
) -> bool:
    """Plot the level curve and the recommended band; False without matplotlib."""
    try:
        import matplotlib  # noqa: F401 — optional, CI has no matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        return False
    fig, ax = plt.subplots(figsize=(10, 5))
    measured = ~np.isnan(levels_db)
    ax.plot(freqs_hz[measured] / 1000.0, levels_db[measured], lw=1.2, label="received level")
    lo, hi = band
    ax.axvspan(lo / 1000.0, hi / 1000.0, color="tab:green", alpha=0.2,
               label=f"recommended band {lo}-{hi} Hz")
    ax.set_xlabel("frequency [kHz]")
    ax.set_ylabel("received level [dB]")
    ax.set_title("band test: sweep recording level vs frequency (brief 7.3)")
    ax.grid(True, alpha=0.3)
    ax.legend()
    fig.tight_layout()
    fig.savefig(path, dpi=150)
    plt.close(fig)
    return True


def save_curve_csv(path: Path, freqs_hz: np.ndarray, levels_db: np.ndarray) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["freq_hz", "level_db"])
        for f, level in zip(freqs_hz, levels_db):
            writer.writerow([f"{f:.0f}", "" if math.isnan(level) else f"{level:.2f}"])


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Recommend the 2.5 kHz chirp band from a sweep recording (brief 7.3)."
    )
    parser.add_argument("wav", help="WAV recorded during the firmware `sweep <n>` command")
    parser.add_argument("--chirp", default=str(LOCATOR_ROOT / "config" / "chirp.json"),
                        help="chirp config JSON to re-band (default: config/chirp.json)")
    parser.add_argument("--out", default=str(LOCATOR_ROOT / "out" / "band_test"),
                        help="output directory for the plot/CSV (default: out/band_test)")
    parser.add_argument("--sweep-duration", type=float, default=SWEEP_DURATION_S,
                        help="firmware sweep length [s], default 10")
    parser.add_argument("--band-width", type=float, default=BAND_WIDTH_HZ,
                        help="recommended band width [Hz], default 2500")
    parser.add_argument("--no-plot", action="store_true", help="skip the plot entirely")
    args = parser.parse_args(argv)

    try:
        base_cfg = load_chirp_config(args.chirp)
    except ConfigError as exc:
        print(f"ERR {exc}")
        return 1

    try:
        samples, fs = read_wav_mono(args.wav)
        onset_s = detect_sweep_onset(samples, fs)
        freqs, levels = level_vs_frequency(
            samples, fs, onset_s, sweep_duration_s=args.sweep_duration
        )
        lo, hi = recommend_band(
            freqs, levels, width_hz=args.band_width
        )
    except BandTestError as exc:
        print(f"ERR {exc}")
        return 1

    unmeasured = float(np.isnan(levels).mean())
    if unmeasured > 0.2:
        print(
            f"WARNING: {unmeasured * 100:.0f}% of the 1-20 kHz grid was never swept "
            "in this recording; the recommendation covers only the measured part"
        )

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    plot_path = out_dir / "band_test.png"
    plotted = False
    if not args.no_plot:
        plotted = save_plot(plot_path, freqs, levels, (lo, hi))
    if not plotted:
        csv_path = out_dir / "band_test_curve.csv"
        save_curve_csv(csv_path, freqs, levels)
        print(f"matplotlib unavailable: level curve written to {csv_path} instead of a plot")
    else:
        print(f"wrote {plot_path}")

    print(f"onset: {onset_s:.3f} s  (fs {fs:.0f} Hz, {samples.size / fs:.2f} s total)")
    print(f"recommended band: {lo}-{hi} Hz (min level {float(np.nanmin(levels[(freqs > lo) & (freqs <= hi)])):.1f} dB)")
    print(f"band {lo} {hi}")
    print(chirp_config_json(lo, hi, base_cfg))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
