"""Chirp edge tests (LOCATOR_BRIEF.md sections 4.3 and 9.3).

The implementation solves phi(t) = k*pi by a closed-form quadratic root; the
tests verify it against the phase formula itself (evaluated independently)
and against numerical bisection roots, for both sweep directions.
"""

import math

import numpy as np
import pytest

from tools.common.chirp import (
    ChirpConfig,
    chirp_edge_ticks,
    chirp_edge_times_s,
    square_wave_samples,
)
from tools.common.constants import TICK_S

DEFAULT_CFG = ChirpConfig()


def phase(t: np.ndarray, f_start: float, f_end: float, t_chirp_s: float) -> np.ndarray:
    """phi(t) = 2*pi*(f_start*t + (f_end - f_start)*t^2/(2T)), brief section 4.3."""
    return 2.0 * math.pi * (
        f_start * t + (f_end - f_start) * np.square(t) / (2.0 * t_chirp_s)
    )


def _bisect_root(f_start: float, f_end: float, t_chirp_s: float, k: int,
                 lo: float, hi: float) -> float:
    """Root of phi(t) - k*pi on [lo, hi] by bisection (phi is monotonic)."""
    f_lo = float(phase(np.array([lo]), f_start, f_end, t_chirp_s)[0]) - k * math.pi
    for _ in range(200):
        mid = 0.5 * (lo + hi)
        f_mid = float(phase(np.array([mid]), f_start, f_end, t_chirp_s)[0]) - k * math.pi
        if (f_lo < 0) == (f_mid < 0):
            lo, f_lo = mid, f_mid
        else:
            hi = mid
    return 0.5 * (lo + hi)


@pytest.mark.parametrize("beacon_id", ["B1", "B2", "B5"])
def test_quantized_edges_match_phase_formula(beacon_id: str) -> None:
    """Quantized edges land within one tick of the formula's k*pi crossings."""
    cfg = DEFAULT_CFG
    f_start, f_end = cfg.sweep_for(beacon_id)
    t_chirp_s = cfg.chirp_s
    ticks = chirp_edge_ticks(cfg, beacon_id=beacon_id)
    t_edges = ticks * TICK_S

    k = np.arange(1, ticks.size + 1, dtype=np.float64)
    residual = np.abs(phase(t_edges, f_start, f_end, t_chirp_s) - k * math.pi)
    # Worst-case phase shift from a 0.5-tick quantization at max frequency.
    tolerance = 2.0 * math.pi * max(f_start, f_end) * TICK_S * 0.6
    assert np.all(residual <= tolerance), (
        f"{beacon_id}: max edge phase residual {residual.max():.6f} rad > {tolerance:.6f}"
    )


@pytest.mark.parametrize("beacon_id", ["B1", "B2"])
def test_unquantized_edges_match_bisection_roots(beacon_id: str) -> None:
    cfg = DEFAULT_CFG
    f_start, f_end = cfg.sweep_for(beacon_id)
    t_chirp_s = cfg.chirp_s
    edges = chirp_edge_times_s(cfg, beacon_id=beacon_id)

    # Cross-check a deterministic sample of edges against numerical roots.
    sample_indices = sorted({0, edges.size // 3, edges.size // 2, 2 * edges.size // 3, edges.size - 1})
    for idx in sample_indices:
        k = idx + 1
        lo = 0.0 if idx == 0 else float(edges[idx - 1])
        hi = t_chirp_s if idx == edges.size - 1 else float(edges[idx + 1])
        root = _bisect_root(f_start, f_end, t_chirp_s, k, lo, hi)
        assert abs(edges[idx] - root) <= 1e-9, f"{beacon_id} edge k={k} off by {abs(edges[idx] - root)} s"


@pytest.mark.parametrize("beacon_id", ["B1", "B2"])
def test_edges_strictly_increasing_inside_chirp(beacon_id: str) -> None:
    edges = chirp_edge_times_s(DEFAULT_CFG, beacon_id=beacon_id)
    assert np.all(np.diff(edges) > 0)
    assert edges[0] > 0.0
    assert edges[-1] < DEFAULT_CFG.chirp_s


def test_falling_sweep_edges_are_widening() -> None:
    """B1 falls f_hi -> f_lo, so its half-cycles lengthen over the chirp."""
    rising = np.diff(chirp_edge_times_s(DEFAULT_CFG, beacon_id="B2"))
    falling = np.diff(chirp_edge_times_s(DEFAULT_CFG, beacon_id="B1"))
    assert rising[-1] < rising[0], "rising sweep half-cycles should shorten"
    assert falling[-1] > falling[0], "falling sweep half-cycles should lengthen"


def test_sweep_direction_mapping() -> None:
    assert DEFAULT_CFG.sweep_for("B1") == (4500.0, 2000.0)  # marker falls
    assert DEFAULT_CFG.sweep_for("B2") == (2000.0, 4500.0)  # others rise
    custom = ChirpConfig(marker_beacon="B3", marker_direction="up", others_direction="down")
    assert custom.sweep_for("B3") == (2000.0, 4500.0)
    assert custom.sweep_for("B1") == (4500.0, 2000.0)


def test_waveform_levels_and_length() -> None:
    fs = 48000.0
    wave_b2 = square_wave_samples(DEFAULT_CFG, fs, beacon_id="B2")
    assert wave_b2.size == int(round(DEFAULT_CFG.chirp_s * fs))
    assert np.all(np.isin(wave_b2, (1.0, -1.0)))
    assert wave_b2[0] == 1.0, "output is HIGH on even half-cycles starting at t = 0"
    # Level at sample-center times matches the half-cycle parity from the
    # unquantized formula edges (samples near an edge are skipped).
    edges = chirp_edge_times_s(DEFAULT_CFG, beacon_id="B2")
    t_center = (np.arange(wave_b2.size) + 0.5) / fs
    half_cycle = np.searchsorted(edges, t_center, side="right")
    neighbor_idx = np.clip(half_cycle, 0, edges.size - 1)
    gap = np.abs(t_center - edges[neighbor_idx])
    # Samples within 2 ticks of an edge may land on either side after
    # quantization; exclude them from the level comparison.
    far_from_edge = gap > 2.0 * TICK_S
    expected = np.where(half_cycle % 2 == 0, 1.0, -1.0)
    assert np.array_equal(wave_b2[far_from_edge], expected[far_from_edge])


def test_waveform_flips_align_with_quantized_edges() -> None:
    """Every quantized edge causes exactly one sign flip within one sample."""
    fs = 48000.0
    for beacon_id in ("B1", "B2"):
        wave = square_wave_samples(DEFAULT_CFG, fs, beacon_id=beacon_id)
        edges = chirp_edge_ticks(DEFAULT_CFG, beacon_id=beacon_id) * TICK_S
        flips = np.where(np.diff(wave) != 0)[0]
        assert flips.size == edges.size, (
            f"{beacon_id}: {flips.size} flips vs {edges.size} edges"
        )
        flip_time = (flips + 1.0) / fs  # flip occurs between samples; edge inside
        assert np.all(np.abs(flip_time - edges) <= 1.0 / fs + TICK_S)


@pytest.mark.parametrize(
    "kwargs",
    [
        {"f_lo": 999.0},
        {"f_hi": 20001.0},
        {"f_lo": 2000.0, "f_hi": 2999.0},  # spread < 1000 Hz
        {"length_ms": 4.9},
        {"length_ms": 40.1},
        {"slot_ms": 29.9},
        {"slot_ms": 100.1},
        {"n_slots": 4},
        {"marker_direction": "sideways"},
        {"version": 2},
    ],
)
def test_invalid_configs_rejected(kwargs: dict) -> None:
    with pytest.raises(ValueError):
        ChirpConfig(**kwargs)


@pytest.mark.parametrize(
    "kwargs",
    [
        {"f_lo": 1000.0, "f_hi": 2000.0},  # range floor, spread exactly 1000
        {"f_lo": 19000.0, "f_hi": 20000.0},  # range ceiling
        {"length_ms": 5.0},
        {"length_ms": 40.0},
        {"slot_ms": 30.0},
        {"slot_ms": 100.0},
    ],
)
def test_boundary_configs_accepted(kwargs: dict) -> None:
    ChirpConfig(**kwargs)  # must not raise
