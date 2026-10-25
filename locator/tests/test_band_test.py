"""Band-test tool tests (LOCATOR_BRIEF.md sections 7.3 and 9.3).

The synthetic recording mirrors the firmware's `sweep <n>` output shape:
2 s of silence, then a linear 1 -> 20 kHz sweep over 10 s. The recording's
spectral envelope is designed so the best 2.5 kHz band is knowable by
construction: flat 0 dB up to 5 kHz, a -15 dB notch at 4.2-4.6 kHz, and a
-25 dB roll-off above 5.5 kHz -- so the recommendation must land in the
low flat region and avoid the notch.
"""

import json
import math
import wave
from pathlib import Path

import numpy as np
import pytest

from tools import band_test
from tools.common.config import chirp_from_dict

FS = 48000.0


def write_wav(path: Path, samples: np.ndarray, fs: float) -> Path:
    """Write mono 16-bit PCM. ``samples`` are already in int16 scale."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(int(fs))
        handle.writeframes(samples.astype("<i2").tobytes())
    return path


def _envelope_db(freq_hz: np.ndarray) -> np.ndarray:
    """Designed received level: flat low band, one notch, high roll-off."""
    envelope = np.zeros_like(freq_hz)
    roll = freq_hz >= 5000.0
    envelope[roll] = -25.0 * np.minimum((freq_hz[roll] - 5000.0) / 500.0, 1.0)
    notch_core = (freq_hz >= 4200.0) & (freq_hz <= 4600.0)
    envelope[notch_core] -= 15.0
    for edge_center, edge_lo, edge_hi in ((4200.0, 3900.0, 4200.0), (4600.0, 4600.0, 4900.0)):
        on_edge = (freq_hz >= edge_lo) & (freq_hz <= edge_hi)
        depth = 1.0 - np.abs(freq_hz[on_edge] - edge_center) / 300.0
        envelope[on_edge] -= 15.0 * np.clip(depth, 0.0, 1.0)
    return envelope


def make_sweep_wav(
    path: Path,
    fs: float = FS,
    lead_s: float = 2.0,
    sweep_s: float = 10.0,
    tail_s: float = 1.0,
    amplitude: float = 0.3,
    noise: float = 1e-4,
    seed: int = 0,
) -> Path:
    """Render the designed sweep recording (sine sweep, smooth envelope)."""
    rng = np.random.default_rng(seed)
    duration = lead_s + sweep_s + tail_s
    n = int(round(duration * fs))
    t = np.arange(n) / fs
    signal = np.zeros(n)
    rate = (band_test.SWEEP_F_MAX_HZ - band_test.SWEEP_F_MIN_HZ) / sweep_s
    in_sweep = (t >= lead_s) & (t <= lead_s + sweep_s)
    ts = t[in_sweep] - lead_s
    freq = band_test.SWEEP_F_MIN_HZ + rate * ts
    phase = 2 * math.pi * (band_test.SWEEP_F_MIN_HZ * ts + rate * ts * ts / 2.0)
    envelope = 10.0 ** (_envelope_db(freq) / 20.0)
    # Smooth the amplitude envelope only: convolving the modulated waveform
    # with a 20 ms kernel is a ~200 Hz low-pass and would kill the carrier.
    kernel = np.hanning(int(0.02 * fs) | 1)
    kernel /= kernel.sum()
    signal[in_sweep] = np.convolve(amplitude * envelope, kernel, mode="same") * np.sin(phase)
    smoothed = signal + noise * rng.standard_normal(n)
    return write_wav(path, np.clip(smoothed, -1.0, 1.0) * 32767.0, fs)


def test_onset_detected_at_sweep_start(tmp_path: Path) -> None:
    wav = make_sweep_wav(tmp_path / "sweep.wav")
    samples, fs = band_test.read_wav_mono(wav)
    onset_s = band_test.detect_sweep_onset(samples, fs)
    assert 1.9 <= onset_s <= 2.2


def test_silence_never_onsets(tmp_path: Path) -> None:
    samples = 1e-4 * np.random.default_rng(1).standard_normal(int(6 * FS))
    with pytest.raises(band_test.BandTestError, match="no sweep onset"):
        band_test.detect_sweep_onset(samples, FS)


def test_recommendation_lands_in_flat_region(tmp_path: Path) -> None:
    """Best 2.5 kHz band avoids the notch and the high roll-off by design."""
    wav = make_sweep_wav(tmp_path / "sweep.wav")
    samples, fs = band_test.read_wav_mono(wav)
    onset_s = band_test.detect_sweep_onset(samples, fs)
    freqs, levels = band_test.level_vs_frequency(samples, fs, onset_s)
    lo, hi = band_test.recommend_band(freqs, levels)
    assert hi - lo == int(band_test.BAND_WIDTH_HZ)
    assert 1000 <= lo
    assert hi <= 4200  # below the 4.2-4.6 kHz notch
    # And it beats the band that contains the notch on min level.
    notch_lo, notch_hi = lo + 2500, lo + 5000
    inside_rec = (freqs > lo) & (freqs <= hi)
    inside_notch = (freqs > notch_lo) & (freqs <= notch_hi)
    assert np.nanmin(levels[inside_rec]) >= np.nanmin(levels[inside_notch])


def test_recommend_band_tie_breaks_low_and_avoids_dips() -> None:
    """Pure-function behavior: flat curve with a dip -> lowest clean band."""
    freqs = np.arange(1000.0, 20001.0, 50.0)
    levels = np.zeros_like(freqs)
    dip = (freqs >= 12000.0) & (freqs <= 13000.0)
    levels[dip] = -10.0
    assert band_test.recommend_band(freqs, levels) == (1000, 3500)


def test_recommend_band_targets_an_isolated_bump() -> None:
    """A 2 kHz bump on a -30 dB floor: the band hugging the bump wins on mean."""
    freqs = np.arange(1000.0, 20001.0, 50.0)
    levels = np.full_like(freqs, -30.0)
    bump = (freqs >= 6000.0) & (freqs <= 8000.0)
    levels[bump] = 0.0
    assert band_test.recommend_band(freqs, levels) == (5500, 8000)


def test_chirp_config_json_is_contract_shaped() -> None:
    base = chirp_from_dict(json.loads(Path(__file__).resolve().parents[1].joinpath("config", "chirp.json").read_text()))
    payload = json.loads(band_test.chirp_config_json(2100, 4600, base))
    assert payload["f_lo"] == 2100 and payload["f_hi"] == 4600
    assert isinstance(payload["f_lo"], int) and isinstance(payload["f_hi"], int)
    assert set(payload) == {
        "f_lo", "f_hi", "length_ms", "slot_ms", "n_slots",
        "marker", "others_direction", "version",
    }
    # Round-trips through the shared config validation (band limits per 4.3).
    chirp_from_dict(payload)


def test_main_end_to_end_prints_command_and_config(tmp_path: Path, capsys) -> None:
    wav = make_sweep_wav(tmp_path / "sweep.wav")
    out_dir = tmp_path / "out"
    assert band_test.main([str(wav), "--out", str(out_dir), "--no-plot"]) == 0
    output = capsys.readouterr().out
    config_line = [ln for ln in output.splitlines() if ln.startswith('{"f_lo"')][0]
    payload = json.loads(config_line)
    assert payload["f_hi"] - payload["f_lo"] == 2500
    # The exact serial command and the JSON agree.
    command = [ln for ln in output.splitlines() if ln.startswith("band ")][0]
    _, lo, hi = command.split()
    assert (int(lo), int(hi)) == (payload["f_lo"], payload["f_hi"])


def test_main_returns_1_for_silence(tmp_path: Path, capsys) -> None:
    silent = write_wav(tmp_path / "silent.wav", np.zeros(int(6 * FS)), FS)
    assert band_test.main([str(silent), "--no-plot"]) == 1
    assert "ERR" in capsys.readouterr().out


def test_csv_fallback_without_matplotlib(tmp_path: Path, capsys, monkeypatch) -> None:
    wav = make_sweep_wav(tmp_path / "sweep.wav")
    monkeypatch.setitem(__import__("sys").modules, "matplotlib", None)
    monkeypatch.setitem(__import__("sys").modules, "matplotlib.pyplot", None)
    out_dir = tmp_path / "out"
    assert band_test.main([str(wav), "--out", str(out_dir)]) == 0
    output = capsys.readouterr().out
    assert "matplotlib unavailable" in output
    assert (out_dir / "band_test_curve.csv").exists()
    assert not (out_dir / "band_test.png").exists()


def test_plot_saved_when_matplotlib_present(tmp_path: Path) -> None:
    pytest.importorskip("matplotlib")
    wav = make_sweep_wav(tmp_path / "sweep.wav")
    out_dir = tmp_path / "out"
    assert band_test.main([str(wav), "--out", str(out_dir)]) == 0
    assert (out_dir / "band_test.png").exists()
