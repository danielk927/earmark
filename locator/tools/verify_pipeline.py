"""Run §7.7 acceptance and optionally save exact WAV/truth/fix parity inputs.

python tools/verify_pipeline.py --out /tmp/locator-parity
The standing rate includes acquisition and the incomplete final cycle (30s).
Walking accuracy uses the original 3s preset, never a padded stationary tail.
"""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass
from pathlib import Path

import numpy as np

if __package__ in (None, ""):
    import sys

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.pipeline import Fix, run_pipeline, write_fixes
from tools.sim_beacons import SimResult, run_sim, write_truth, write_wav


@dataclass(frozen=True)
class Metrics:
    preset: str
    clean: bool
    seed: int
    fixes: int
    duration_s: float
    median_m: float
    p95_m: float
    max_m: float
    fixes_per_second: float
    tracked_fixes_per_second: float

    @property
    def passed(self) -> bool:
        accuracy = (
            (self.median_m < 0.03 and self.max_m < 0.05)
            if self.clean
            else (self.median_m < 0.08 and self.p95_m < 0.15)
        )
        rate = self.preset != "stand_on_mat" or self.fixes_per_second >= 3.2
        return accuracy and rate


def measure(sim: SimResult, fixes: list[Fix], clean: bool) -> Metrics:
    if len(fixes) < 2:
        raise ValueError("acceptance requires at least two fixes")
    times = np.array([fix.t for fix in fixes])
    truth = sim.truth["truth"]
    positions = np.array(truth["position"])
    expected = np.column_stack(
        [np.interp(times, truth["t"], positions[:, i]) for i in range(3)]
    )
    error = np.linalg.norm(np.array([f.mic_position for f in fixes]) - expected, axis=1)
    return Metrics(
        sim.truth["preset"],
        clean,
        sim.truth["seed"],
        len(fixes),
        sim.truth["duration_s"],
        float(np.median(error)),
        float(np.quantile(error, 0.95)),
        float(np.max(error)),
        len(fixes) / sim.truth["duration_s"],
        (len(fixes) - 1) / (times[-1] - times[0]),
    )


def run_case(preset: str, clean: bool, seed: int, out: Path | None = None) -> Metrics:
    sim = run_sim(
        preset=preset,
        seed=seed,
        duration_s=30 if preset == "stand_on_mat" else None,
        noise_snr_db=None if clean else 25,
        buzzer_response=not clean,
        body_shadowing=not clean,
        floor_coeff=0 if clean else 0.5,
        wall_coeff=0 if clean else 0.3,
    )
    fixes = run_pipeline(sim.samples_int16.astype(float) / 32768, sim.fs)
    result = measure(sim, fixes, clean)
    if out is not None:
        case = out / f"{preset}-{'clean' if clean else 'effects'}-{seed}"
        write_wav(case / "input.wav", sim.samples_int16, sim.fs)
        write_truth(case / "truth.json", sim.truth)
        write_fixes(case / "fixes.jsonl", fixes)
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()
    results = [
        run_case(preset, clean, seed, args.out)
        for preset in ("stand_on_mat", "walk_to_cupboard")
        for clean in (True, False)
        for seed in (0, 1, 2)
    ]
    payload = [dict(asdict(result), passed=result.passed) for result in results]
    print(json.dumps(payload, indent=2))
    if args.out is not None:
        (args.out / "metrics.json").write_text(
            json.dumps(payload, indent=2) + "\n", encoding="utf-8"
        )
    return 0 if all(result.passed for result in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
