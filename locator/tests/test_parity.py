"""Parity checks must reject missing fixes and threshold/window regressions."""

import json
from dataclasses import asdict, replace

import numpy as np
import pytest
from tools.common.chirp import ChirpConfig, square_wave_samples
from tools.common.config import DEFAULT_BEACONS
from tools.compare_fixes import compare, parse_fix, read_fixes
from tools.pipeline import Fix, Pipeline, write_fixes
from tools.positioning import Detection, Parameters, marker_candidate


def records(count=20):
    return [
        Fix(
            i * 0.3 + 0.1,
            (i * 0.3 + 0.1) * 48000,
            (0, 0, 1.25),
            (0, 0, 1.6),
            "ok",
            ("B1", "B2", "B3"),
            tuple(Detection(f"B{j}", i * 0.3 + j * 0.05, 12) for j in range(1, 4)),
            0.1,
        )
        for i in range(count)
    ]


def test_identical_streams_and_exactly_95_percent_quality():
    reference = records()
    actual = [replace(reference[0], quality="degraded"), *reference[1:]]
    assert compare(reference, reference, 48000).quality_agreement == 1
    assert compare(reference, actual, 48000).quality_agreement == 0.95
    actual[1] = replace(actual[1], quality="degraded")
    with pytest.raises(ValueError, match="parity failed"):
        compare(reference, actual, 48000)


def test_empty_missing_shifted_and_centimetre_differences_fail():
    reference = records()
    for actual in ([], reference[1:]):
        with pytest.raises(ValueError, match="coverage"):
            compare(reference, actual, 48000)
    with pytest.raises(ValueError, match="sample_index"):
        compare(
            reference,
            [replace(r, sample_index=r.sample_index + 100) for r in reference],
            48000,
        )
    for field in ("mic_position", "ear_position"):
        actual = reference.copy()
        position = getattr(actual[0], field)
        actual[0] = replace(actual[0], **{field: (0.01, position[1], position[2])})
        with pytest.raises(ValueError, match="parity failed"):
            compare(reference, actual, 48000)


def test_different_subsets_correspond_without_mean_time_equality():
    reference = records()
    actual = []
    for fix in reference:
        arrival = fix.t + 0.1
        mean = (fix.t * 3 + arrival) / 4
        actual.append(
            replace(
                fix,
                t=mean,
                sample_index=mean * 48000,
                beacons_used=(*fix.beacons_used, "B4"),
                detections=(*fix.detections, Detection("B4", arrival, 8.05)),
            )
        )
    result = compare(reference, actual, 48000)
    assert result.max_sample_difference == pytest.approx(1200)
    assert result.max_mic_difference_m == 0
    assert result.quality_agreement == 1
    shifted = [
        replace(
            fix,
            t=fix.t + 0.3,
            sample_index=fix.sample_index + 14400,
            detections=tuple(
                replace(d, arrival=d.arrival + 0.3) for d in fix.detections
            ),
        )
        for fix in actual
    ]
    with pytest.raises(ValueError, match="unmatched cycles"):
        compare(reference, shifted, 48000)


def test_json_roundtrip_rejects_empty_duplicate_and_bad_schema(tmp_path):
    path = tmp_path / "fixes.jsonl"
    write_fixes(path, records())
    assert read_fixes(path) == records()
    path.write_text("")
    with pytest.raises(ValueError, match="empty"):
        read_fixes(path)
    write_fixes(path, records(1) * 2)
    with pytest.raises(ValueError, match="increase"):
        read_fixes(path)
    write_fixes(path, list(reversed(records())))
    with pytest.raises(ValueError, match="increase"):
        read_fixes(path)
    value = json.loads(json.dumps(asdict(records(1)[0])))
    for field, bad in (
        ("t", float("nan")),
        ("quality", "lost"),
        ("beacons_used", ["B1"]),
    ):
        with pytest.raises(ValueError):
            parse_fix({**value, field: bad})
    with pytest.raises(ValueError, match="schema"):
        parse_fix({**value, "extra": 1})


def test_first_marker_acquisition_threshold_uses_local_gate():
    fs, chirp = 48000, ChirpConfig()
    template = square_wave_samples(chirp, fs, "B1")
    signal = np.pad(template, (4800, 9600))
    found = marker_candidate(signal, 0, template, fs, chirp, Parameters())
    assert found is not None and 10 < found.snr < 100
    assert abs(found.arrival - 0.1) < 1 / fs
    assert (
        marker_candidate(signal, 0, template, fs, chirp, Parameters(gate_ms=1)) is None
    )
    assert (
        marker_candidate(signal, 0, template, fs, chirp, Parameters(snr_acquire=100))
        is None
    )


def test_initial_beacon_candidate_must_pass_local_gate_threshold():
    fs, chirp = 48000, ChirpConfig()
    signal = np.pad(square_wave_samples(chirp, fs, "B1"), (4800, 9600))
    for params, expected in (
        (Parameters(), True),
        (Parameters(gate_ms=1), False),
        (Parameters(snr_min=100), False),
    ):
        pipeline = Pipeline(params=params)
        pipeline.history = signal
        pipeline.next_sample = len(signal)
        found = pipeline._detect_beacon(DEFAULT_BEACONS[0], 0.1, np.array([0, 0, 1.25]))
        assert (found is not None) == expected
        if found is not None:
            assert 8 < found.snr < 100
