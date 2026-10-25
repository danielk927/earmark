"""Reference DSP, solver, streaming lifecycle, and Swift record contract."""

import json
import wave
from dataclasses import replace
from pathlib import Path

import numpy as np
import pytest
from tools.common.chirp import ChirpConfig, square_wave_samples
from tools.common.config import DEFAULT_BEACONS
from tools.common.constants import speed_of_sound
from tools.pipeline import (
    Pipeline,
    load_parameters,
    main,
    read_wav,
    run_pipeline,
    write_fixes,
)
from tools.positioning import (
    Detection,
    Kalman,
    LossMonitor,
    MarkerTracker,
    Parameters,
    analytic_envelope,
    detect,
    first_arrival,
    solve,
)
from tools.sim_beacons import run_sim, write_wav

CHIRP = ChirpConfig()
PARAMS = Parameters()


def arrivals(position, noise=None):
    values = [
        0.1
        + b.slot * CHIRP.slot_s
        + np.linalg.norm(position - np.array(b.position)) / speed_of_sound()
        for b in DEFAULT_BEACONS
    ]
    if noise is not None:
        values = np.array(values) + noise
    return tuple(
        Detection(b.id, float(t), 30.0)
        for b, t in zip(DEFAULT_BEACONS, values, strict=True)
    )


def test_exact_arrivals_solve_exactly_at_prior_height():
    position = np.array([0.3, 0.6, 1.25])
    result = solve(arrivals(position), DEFAULT_BEACONS, CHIRP, PARAMS)
    assert result is not None
    np.testing.assert_allclose(result.position, position, atol=1e-6)
    assert result.tau == pytest.approx(0.1, abs=1e-8)
    assert result.quality == "ok"
    assert result.residual_rms_ms < 1e-6


def test_off_prior_height_remains_data_driven():
    position = np.array([0.3, 0.6, 1.40])
    result = solve(arrivals(position), DEFAULT_BEACONS, CHIRP, PARAMS)
    assert result is not None
    assert np.linalg.norm(result.position - position) < 0.02


def test_seeded_noisy_arrivals_have_bounded_error():
    rng = np.random.default_rng(22)
    errors = []
    for _ in range(50):
        position = np.array([rng.uniform(-1, 1), rng.uniform(-1, 1), 1.25])
        result = solve(
            arrivals(position, rng.normal(0, 0.00001, 5)),
            DEFAULT_BEACONS,
            CHIRP,
            PARAMS,
        )
        assert result is not None
        errors.append(np.linalg.norm(result.position - position))
    assert max(errors) < 0.03


def test_worst_of_five_outlier_is_dropped_and_resolved():
    position = np.array([0.3, 0.6, 1.25])
    noisy = arrivals(position, [0, 0, 0, 0, 0.002])
    result = solve(noisy, DEFAULT_BEACONS, CHIRP, PARAMS)
    assert result is not None
    assert [d.beacon for d in result.detections] == ["B1", "B2", "B3", "B4"]
    np.testing.assert_allclose(result.position, position, atol=1e-6)


def test_three_beacon_height_prior_and_insufficient_measurements():
    position = np.array([0.3, 0.6, 1.25])
    result = solve(arrivals(position)[:3], DEFAULT_BEACONS, CHIRP, PARAMS)
    assert result is not None
    assert result.quality == "degraded"
    np.testing.assert_allclose(result.position, position, atol=1e-6)
    assert solve(arrivals(position)[:2], DEFAULT_BEACONS, CHIRP, PARAMS) is None


def test_degenerate_geometry_is_rejected():
    beacons = tuple(replace(b, position=(0.0, 0.0, 0.0)) for b in DEFAULT_BEACONS)
    assert solve(arrivals(np.array([0, 0, 1.25])), beacons, CHIRP, PARAMS) is None


def test_solver_rejects_duplicate_or_nonfinite_measurements():
    measurements = arrivals(np.array([0, 0, 1.25]))
    with pytest.raises(ValueError, match="distinct"):
        solve((measurements[0],) * 3, DEFAULT_BEACONS, CHIRP, PARAMS)
    with pytest.raises(ValueError, match="finite"):
        solve(
            (replace(measurements[0], arrival=float("nan")), *measurements[1:]),
            DEFAULT_BEACONS,
            CHIRP,
            PARAMS,
        )


def test_first_arrival_prefers_direct_path_to_stronger_echo():
    fs = 48000
    template = square_wave_samples(CHIRP, fs, "B1")
    signal = np.zeros(3000)
    direct, echo = 600, 672  # 1.5ms echo, below the 2ms lookback.
    signal[direct : direct + len(template)] += template
    signal[echo : echo + len(template)] += 1.4 * template
    found = detect(signal, 0, template, fs, CHIRP, "B1", 0.008, 0.018, PARAMS, 0)
    assert found is not None
    assert abs(found.arrival * fs - direct) < 3


def test_first_arrival_excludes_early_weak_and_remote_peaks():
    envelope = np.zeros(300)
    envelope[50], envelope[190], envelope[200], envelope[220] = 0.9, 0.4, 0.6, 1
    found = first_arrival(envelope, 1, 299, 48000, 2)
    assert found is not None
    assert found[0] == 200
    assert first_arrival(np.zeros(300), 1, 299, 48000, 2) is None


def test_snr_uses_configured_gate_not_marker_spacing_tolerance():
    fs = 48000
    template = square_wave_samples(CHIRP, fs, "B1")
    signal = np.pad(template, (480, 1000))
    configured = detect(signal, 0, template, fs, CHIRP, "B1", 0.007, 0.013, PARAMS, 10)
    wrong_window = detect(signal, 0, template, fs, CHIRP, "B1", 0.009, 0.011, PARAMS, 0)
    assert configured is not None and configured.snr > 10
    assert wrong_window is not None and wrong_window.snr < 10
    tracker = MarkerTracker(0.3)
    assert not tracker.observe(0.01)
    assert not tracker.observe(0.312)  # Strong signal alone cannot confirm spacing.
    tracker.reset()
    assert not tracker.observe(0.01)
    assert tracker.observe(0.3105)


def test_fft_masks_out_of_band_interference_and_zero_pads():
    fs = 48000
    template = square_wave_samples(CHIRP, fs, "B1")
    signal = np.pad(template, (480, 1000))
    envelope = analytic_envelope(signal, template, fs, CHIRP)
    noisy = signal + 10 * np.sin(2 * np.pi * 600 / fs * np.arange(len(signal)))
    other = analytic_envelope(noisy, template, fs, CHIRP)
    assert abs(np.argmax(other) - 480) <= 1
    assert np.argmax(envelope) == 480
    assert len(envelope) == len(signal) - len(template) + 1
    assert len(analytic_envelope(np.zeros(5), template, fs, CHIRP)) == 0


def test_tracker_acquires_misses_three_then_reacquires_and_bounds_drift():
    tracker = MarkerTracker(0.3)
    assert not tracker.observe(0.1)
    assert tracker.observe(0.4)
    for i in range(1, 20):
        assert tracker.observe(0.4 + i * 0.300015)
    assert 0.3 < tracker.period <= 0.30003
    assert not tracker.observe(None)
    assert not tracker.observe(None)
    assert tracker.locked
    assert not tracker.observe(None)
    assert not tracker.locked and tracker.expected is None
    assert not tracker.observe(8)
    assert tracker.observe(8.3)


def test_kalman_constant_velocity_and_covariance_stability():
    kalman = Kalman(PARAMS)
    for i in range(100):
        t = i * 0.3
        truth = np.array([0.1 * t, -0.2 * t, 1.25])
        result = kalman.update(truth, t, "ok")
        assert np.min(np.linalg.eigvalsh(kalman.covariance)) > 0
    np.testing.assert_allclose(result, truth, atol=1e-7)
    np.testing.assert_allclose(
        kalman.position_at(t + 0.1), truth + [0.01, -0.02, 0], atol=1e-7
    )
    with pytest.raises(ValueError, match="increase"):
        kalman.update(truth, t, "ok")


def test_loss_is_once_per_outage_with_recovery():
    monitor = LossMonitor()
    assert not monitor.lost(100)
    monitor.fixed(10)
    assert not monitor.lost(11.49)
    assert monitor.lost(11.5)
    assert not monitor.lost(20)
    monitor.fixed(21)
    assert monitor.lost(22.5)


@pytest.fixture(scope="module")
def clean_sim():
    return run_sim(
        duration_s=6,
        tau_s=0.05,
        clock_error_ppm=50,
        noise_snr_db=None,
        floor_coeff=0,
        wall_coeff=0,
        buzzer_response=False,
        body_shadowing=False,
    )


def test_streaming_silence_loss_and_reacquisition(clean_sim):
    signal = clean_sim.samples_int16.astype(float) / 32768
    signal[2 * 48000 : 4 * 48000] = 0
    pipeline = Pipeline()
    fixes = pipeline.feed(signal)
    assert any(f.t < 2 for f in fixes)
    assert not any(2.2 < f.t < 4 for f in fixes)
    assert any(f.t > 4.5 for f in fixes)
    assert len(pipeline.lost_transitions) == 1
    assert len(pipeline.history) <= 48000


def test_sample_gap_resets_tracking_and_keeps_absolute_clock(clean_sim):
    signal = clean_sim.samples_int16.astype(float) / 32768
    pipeline = Pipeline(epoch=1000)
    pipeline.feed(signal[:48000])
    fixes = pipeline.feed(signal[96000:], sample_index=96000)
    assert pipeline.discontinuities == 1
    assert fixes and fixes[0].t > 1002
    assert all(f.t == pytest.approx(1000 + f.sample_index / 48000) for f in fixes)


def test_missing_marker_still_solves_remaining_beacons(clean_sim):
    signal = clean_sim.samples_int16.astype(float) / 32768
    signal[round(1.25 * 48000) : round(1.29 * 48000)] = 0
    fixes = run_pipeline(signal)
    fixes_without_b1 = [f for f in fixes if "B1" not in f.beacons_used]
    assert len(fixes_without_b1) == 1
    assert len(fixes_without_b1[0].beacons_used) == 4


def test_jsonl_exact_swift_contract_and_wav_cli(tmp_path, clean_sim):
    wav_path, out = tmp_path / "test.wav", tmp_path / "fixes.jsonl"
    write_wav(wav_path, clean_sim.samples_int16, clean_sim.fs)
    assert main([str(wav_path), "--out", str(out), "--epoch", "1000"]) == 0
    records = [json.loads(line) for line in out.read_text().splitlines()]
    assert records
    assert set(records[0]) == {
        "t",
        "sample_index",
        "mic_position",
        "ear_position",
        "quality",
        "beacons_used",
        "detections",
        "residual_rms_ms",
    }
    for record in records:
        assert record["quality"] in ("ok", "degraded")
        assert record["t"] == pytest.approx(1000 + record["sample_index"] / 48000)
        assert all(set(d) == {"beacon", "arrival", "snr"} for d in record["detections"])
        np.testing.assert_allclose(
            np.subtract(record["ear_position"], record["mic_position"]), [0, 0, 0.35]
        )
    write_fixes(out, [])
    assert out.read_text() == ""


def test_shared_settings_load_and_validation(tmp_path):
    path = Path(__file__).parents[1] / "config" / "locator_params.json"
    assert load_parameters(path) == PARAMS
    pocket = load_parameters(path, "pocket")
    assert pocket.height_mean_m == 1.30 and pocket.height_sigma_m == 0.20
    assert pocket.ear_offset_m == (0, 0, 0.30)
    bad = tmp_path / "bad.json"
    bad.write_text('{"gate_ms": -1}')
    with pytest.raises(ValueError, match="positive"):
        load_parameters(bad)
    bad.write_text('{"snr_min": true}')
    with pytest.raises(ValueError, match="finite number"):
        load_parameters(bad)
    with pytest.raises(ValueError, match="finite"):
        Parameters(gate_ms=float("nan"))
    with pytest.raises(ValueError, match="sample rate"):
        Pipeline(fs=8000)


def test_initial_fix_scores_only_the_local_detection_gate(clean_sim):
    fixes = run_pipeline(clean_sim.samples_int16.astype(float) / 32768)
    assert fixes
    # A slot-wide median in this noiseless case would inflate SNR by orders of magnitude.
    assert all(8 <= d.snr < 100 for d in fixes[0].detections)


def test_pipeline_rejects_empty_duplicate_and_invalid_templates():
    with pytest.raises(ValueError, match="three beacons"):
        Pipeline(beacons=())
    with pytest.raises(ValueError, match="unique"):
        Pipeline(beacons=(*DEFAULT_BEACONS, DEFAULT_BEACONS[0]))
    with pytest.raises(ValueError, match="captured templates"):
        Pipeline(templates={"B1": np.array([float("nan")])})
    with pytest.raises(ValueError, match="finite mono"):
        Pipeline().feed(np.array([float("nan")]))


def test_wav_rejects_stereo_and_truncation(tmp_path):
    path = tmp_path / "bad.wav"
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(2)
        handle.setsampwidth(2)
        handle.setframerate(48000)
        handle.writeframes(b"\0" * 100)
    with pytest.raises(ValueError, match="mono"):
        read_wav(path)
    write_wav(path, np.zeros(100, dtype=np.int16), 48000)
    path.write_bytes(path.read_bytes()[:-10])
    with pytest.raises(ValueError, match="truncated"):
        read_wav(path)
