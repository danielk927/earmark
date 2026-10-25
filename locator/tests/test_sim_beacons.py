"""Simulator smoke tests (LOCATOR_BRIEF.md sections 7.2 and 9.3).

Verifies the WAV and truth.json are well-formed, the expected slot energy
structure appears, presets run, and the seeded randomness is deterministic.
Renders are short (about 1 s) to keep the suite fast.
"""

import json
import wave
from pathlib import Path

import numpy as np
import pytest

from tools import sim_beacons
from tools.common.config import load_beacon_config, load_chirp_config

FS = 48000.0


def render(**overrides):
    """Clean, pinned render for deterministic assertions."""
    kwargs = {
        "fs": FS,
        "noise_snr_db": None,
        "tau_s": 0.2,
        "clock_error_ppm": 0.0,
        "seed": 7,
    }
    kwargs.update(overrides)
    return sim_beacons.run_sim(**kwargs)


def write_outputs(tmp_path: Path, result) -> tuple[Path, Path]:
    wav = sim_beacons.write_wav(tmp_path / "sim.wav", result.samples_int16, result.fs)
    truth = sim_beacons.write_truth(tmp_path / "truth.json", result.truth)
    return wav, truth


def test_wav_is_well_formed_mono_16bit(tmp_path: Path) -> None:
    result = render(duration_s=1.0)
    wav, _ = write_outputs(tmp_path, result)
    with wave.open(str(wav), "rb") as handle:
        assert handle.getnchannels() == 1
        assert handle.getsampwidth() == 2
        assert handle.getframerate() == 48000
        assert handle.getnframes() == int(round(1.0 * FS))
        frames = handle.readframes(handle.getnframes())
    assert len(frames) == handle.getnframes() * 2  # mono, 16-bit


def test_truth_json_is_complete(tmp_path: Path) -> None:
    result = render(duration_s=1.0, preset="walk_to_cupboard")
    _, truth_path = write_outputs(tmp_path, result)
    truth = json.loads(truth_path.read_text(encoding="utf-8"))

    for key in (
        "fs", "n_samples", "duration_s", "preset", "mode", "beacons", "chirp",
        "tau_s", "clock_error_ppm", "temperature_c", "speed_of_sound_mps",
        "noise_snr_at_1m_db", "buzzer_response_hz", "floor_reflection_coeff",
        "wall_reflection_coeff", "body_shadowing_db", "seed", "master_gain", "truth",
    ):
        assert key in truth, f"truth.json missing {key}"

    trace = truth["truth"]
    assert len(trace["t"]) == len(trace["position"]) == len(trace["facing_yaw_rad"])
    assert all(len(p) == 3 for p in trace["position"])
    assert truth["beacons"] == [b.to_dict() for b in load_beacon_config(None)]
    assert truth["chirp"] == load_chirp_config(None).to_dict()
    # Walking preset: positions actually move.
    positions = np.array(trace["position"])
    assert np.ptp(positions[:, 1]) > 0.5  # walks +y toward the cupboard


def test_tau_and_clock_error_recorded() -> None:
    result = render(duration_s=0.9, tau_s=0.123, clock_error_ppm=-37.5)
    assert result.truth["tau_s"] == pytest.approx(0.123)
    assert result.truth["clock_error_ppm"] == pytest.approx(-37.5)


def test_random_tau_within_expected_range() -> None:
    for seed in (1, 2, 3):
        result = render(duration_s=0.9, seed=seed)
        assert 0.05 <= result.truth["tau_s"] <= 0.5
        assert -50.0 <= result.truth["clock_error_ppm"] <= 50.0


def test_same_seed_is_deterministic() -> None:
    """Same seed, nothing pinned: identical tau, clock error and samples."""
    a = sim_beacons.run_sim(duration_s=0.9, seed=11, noise_snr_db=25.0, fs=FS)
    b = sim_beacons.run_sim(duration_s=0.9, seed=11, noise_snr_db=25.0, fs=FS)
    assert np.array_equal(a.samples_int16, b.samples_int16)
    assert a.truth["tau_s"] == b.truth["tau_s"]
    assert a.truth["clock_error_ppm"] == b.truth["clock_error_ppm"]


def test_different_seeds_differ() -> None:
    """The seed draws tau, clock error and noise; unpinning them, outputs differ."""
    a = sim_beacons.run_sim(duration_s=0.9, seed=1, noise_snr_db=25.0, fs=FS)
    b = sim_beacons.run_sim(duration_s=0.9, seed=2, noise_snr_db=25.0, fs=FS)
    assert not np.array_equal(a.samples_int16, b.samples_int16)
    assert a.truth["tau_s"] != b.truth["tau_s"]


def test_energy_appears_in_expected_slots() -> None:
    """Clean render: every chirp slot is loud, the silent slot is not (brief 7.7)."""
    result = render(duration_s=1.4)
    cfg = load_chirp_config(None)
    tau = result.truth["tau_s"]
    signal = np.abs(result.signal)
    silent_peaks: list[float] = []
    active_peaks: list[float] = []
    cycle = 0
    while tau + cycle * cfg.cycle_s + cfg.cycle_s <= 1.4:
        for slot in range(cfg.n_slots):
            lo = int(round((tau + cycle * cfg.cycle_s + slot * cfg.slot_s) * FS))
            hi = int(round((tau + cycle * cfg.cycle_s + (slot + 1) * cfg.slot_s) * FS))
            window = signal[lo:hi]
            assert window.size > 0
            if slot == cfg.n_slots - 1:
                silent_peaks.append(float(window.max()))
            else:
                active_peaks.append(float(window.max()))
        cycle += 1
    assert active_peaks, "expected at least one full cycle in the render"
    assert min(active_peaks) > 2.0 * max(silent_peaks), (
        f"chirp slots (min {min(active_peaks):.4f}) not clearly above "
        f"the silent slot (max {max(silent_peaks):.4f})"
    )


def test_all_presets_render() -> None:
    for name in sorted(sim_beacons.PATH_PRESETS):
        result = render(duration_s=1.0, preset=name)
        assert result.signal.size == int(round(1.0 * FS))
        assert result.truth["preset"] == name


def test_pocket_mode_uses_pocket_height() -> None:
    result = render(duration_s=0.9, preset="pocket_mode")
    assert result.truth["mode"] == "pocket"
    positions = np.array(result.truth["truth"]["position"])
    assert np.allclose(positions[:, 2], 1.30, atol=1e-6)


def test_hand_mode_uses_hand_height() -> None:
    result = render(duration_s=0.9, preset="stand_on_mat")
    assert result.truth["mode"] == "hand"
    positions = np.array(result.truth["truth"]["position"])
    assert np.allclose(positions[:, 2], 1.25, atol=1e-6)


def test_body_shadowing_attenuates_beacons_behind() -> None:
    """Facing +y on the mat: B3 is behind (y=-1.5), B2 in front (y=+1.5).

    Shadowing on should cut B3's energy by about 10 dB relative to B2's
    compared with shadowing off; ratios are global-gain invariant.
    """
    def slot_energy_ratio(shadow_on: bool) -> float:
        result = render(duration_s=1.4, preset="stand_on_mat", body_shadowing=shadow_on)
        cfg = load_chirp_config(None)
        tau = result.truth["tau_s"]
        signal = result.signal**2
        energies: dict[str, float] = {}
        slots = {"B2": 1, "B3": 2}
        for beacon_id, slot in slots.items():
            total = 0.0
            cycle = 0
            while tau + cycle * cfg.cycle_s + cfg.cycle_s <= 1.4:
                lo = int(round((tau + cycle * cfg.cycle_s + slot * cfg.slot_s) * FS))
                hi = int(round((tau + cycle * cfg.cycle_s + (slot + 1) * cfg.slot_s) * FS))
                total += float(np.sum(signal[lo:hi]))
                cycle += 1
            energies[beacon_id] = total
        assert result.truth["body_shadowing_db"] == (sim_beacons.SHADOW_DB if shadow_on else None)
        return energies["B3"] / max(energies["B2"], 1e-12)

    ratio_on = slot_energy_ratio(True)
    ratio_off = slot_energy_ratio(False)
    assert ratio_on < 0.5 * ratio_off, (
        f"expected ~10 dB shadowing on B3: ratio on {ratio_on:.3f} vs off {ratio_off:.3f}"
    )


def test_noise_changes_the_signal_and_is_recorded() -> None:
    clean = render(duration_s=0.9)
    noisy = render(duration_s=0.9, noise_snr_db=0.0)
    assert not np.array_equal(clean.samples_int16, noisy.samples_int16)
    assert clean.truth["noise_snr_at_1m_db"] is None
    assert noisy.truth["noise_snr_at_1m_db"] == 0.0


def test_custom_waypoints_render(tmp_path: Path) -> None:
    waypoints = [
        sim_beacons.Waypoint(0.0, 0.0, 0.0, 1.25, 90.0),
        sim_beacons.Waypoint(1.0, 1.0, 0.0, 1.25, 90.0),
    ]
    result = render(duration_s=1.0, preset="unused-with-waypoints", waypoints=waypoints)
    assert result.truth["preset"] == "custom"
    positions = np.array(result.truth["truth"]["position"])
    assert np.ptp(positions[:, 0]) > 0.5


def test_cli_main_writes_outputs(tmp_path: Path) -> None:
    code = sim_beacons.main([
        "--out", str(tmp_path),
        "--clean",
        "--duration", "0.9",
        "--seed", "3",
    ])
    assert code == 0
    assert (tmp_path / "sim.wav").is_file()
    assert (tmp_path / "truth.json").is_file()
    truth = json.loads((tmp_path / "truth.json").read_text(encoding="utf-8"))
    assert truth["noise_snr_at_1m_db"] is None


def test_sim_accepts_space_json(tmp_path: Path) -> None:
    """The simulator reads beacons through the import rule (brief 2.2)."""
    space = tmp_path / "space.json"
    space.write_text(json.dumps({
        "spots": {"cupboard_salt": [-0.08, 1.5, 1.0]},
        "beacons": [
            {"id": "B1", "position": [-1.5, 1.5, 1.8], "slot": 0},
            {"id": "B2", "position": [1.5, 1.5, 0.3], "slot": 1},
            {"id": "B3", "position": [1.5, -1.5, 1.8], "slot": 2},
            {"id": "B4", "position": [-1.5, -1.5, 0.3], "slot": 3},
            {"id": "B5", "position": [-1.8, 0.0, 1.0], "slot": 4},
        ],
    }), encoding="utf-8")
    result = render(duration_s=0.9, beacons=space)
    assert [b["id"] for b in result.truth["beacons"]] == ["B1", "B2", "B3", "B4", "B5"]
