"""Sanity check: count detectable chirp cycles in a rendered sim (brief 7.2).

Renders stand_on_mat for 5 s at the default config, then detects chirp
cycles by simple energy gating (no matched filtering): a cycle counts as
detected when at least 4 of its 5 chirp slots are louder than the silent
slot. Prints the detected count and the implied cycle rate, and exits
non-zero if the rate is below the 3.2/s the brief's acceptance uses
(brief section 7.7).

Usage: python3 tools/verify_sim_cycles.py [--out DIR]
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np

if __package__ in (None, ""):  # pragma: no cover - exercised via script runs
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools import sim_beacons
from tools.common.config import load_chirp_config

MIN_CYCLE_RATE_PER_S = 3.2
#: A chirp slot counts as active when its mean-square level exceeds this
#: multiple of the same cycle's silent-slot level. Energy, not peak: hall
#: noise is spiky, so a noise peak can rival a weak chirp's peak while its
#: energy stays well below the chirp's.
ACTIVE_RATIO = 1.5
#: Slots (of 5 chirp slots) that must be active for a detected cycle.
MIN_ACTIVE_SLOTS = 4


def _slot_levels(signal: np.ndarray, fs: float, cycle_start_s: float,
                 cfg_cycle_s: float, cfg_slot_s: float, n_slots: int) -> list[float]:
    """Mean-square level of each slot window in one cycle."""
    levels = []
    for slot in range(n_slots):
        lo = int(round((cycle_start_s + slot * cfg_slot_s) * fs))
        hi = int(round((cycle_start_s + (slot + 1) * cfg_slot_s) * fs))
        lo = max(lo, 0)
        hi = min(hi, signal.size)
        window = signal[lo:hi] if hi > lo else np.zeros(1)
        levels.append(float(np.mean(np.square(window))))
    return levels


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", help="optional output directory for the WAV/truth files")
    parser.add_argument("--duration", type=float, default=5.0, help="render length [s], default 5")
    args = parser.parse_args(argv)

    result = sim_beacons.run_sim(preset="stand_on_mat", duration_s=args.duration)
    cfg = load_chirp_config(None)
    fs = result.fs
    tau = result.truth["tau_s"]
    signal = result.signal.astype(np.float64)

    silent_levels: list[float] = []
    cycle_starts: list[float] = []
    detected: list[int] = []
    cycle = 0
    while tau + cycle * cfg.cycle_s + cfg.cycle_s <= result.truth["duration_s"]:
        start_s = tau + cycle * cfg.cycle_s
        levels = _slot_levels(signal, fs, start_s, cfg.cycle_s, cfg.slot_s, cfg.n_slots)
        silent_level = levels[cfg.n_slots - 1]
        silent_levels.append(silent_level)
        reference = max(silent_level, 1e-12)
        active = sum(1 for level in levels[:5] if level > ACTIVE_RATIO * reference)
        if active >= MIN_ACTIVE_SLOTS:
            detected.append(cycle)
            cycle_starts.append(start_s)
        cycle += 1

    if len(cycle_starts) >= 2:
        gaps = np.diff(cycle_starts)
        rate = 1.0 / float(np.median(gaps))
    else:
        rate = 0.0

    total_slots = len(detected) * 5
    print(f"rendered stand_on_mat {result.truth['duration_s']}s at {fs:.0f} Hz "
          f"(seed {result.truth['seed']}, tau {tau:.4f}s)")
    print(f"cycles fully inside the render: {cycle}, detected by energy gating: {len(detected)}")
    print(f"chirp slots detected: {total_slots}, median inter-cycle gap -> rate {rate:.2f} cycles/s")
    print(f"silent-slot mean-square: min {min(silent_levels):.6f}, max {max(silent_levels):.6f}")
    ok = rate >= MIN_CYCLE_RATE_PER_S and len(detected) >= 3
    print(f"{'PASS' if ok else 'FAIL'}: rate {rate:.2f} vs required {MIN_CYCLE_RATE_PER_S} cycles/s")
    if args.out:
        out_dir = Path(args.out)
        sim_beacons.write_wav(out_dir / "sim.wav", result.samples_int16, fs)
        sim_beacons.write_truth(out_dir / "truth.json", result.truth)
        print(f"wrote {out_dir / 'sim.wav'} and {out_dir / 'truth.json'}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
