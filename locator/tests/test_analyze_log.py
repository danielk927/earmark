"""Log-analyzer tests (LOCATOR_BRIEF.md sections 7.5 and 9.3).

Synthetic data with errors known by construction: a straight walking trace
(y = 0.2 t, z = 1.25) with fixes offset by a constant [0.02, -0.01, 0],
so median/p95/max are identical and hand-computable (both 3D and horizontal
error are ~22.36 mm: the constant offset is purely horizontal). Pairs of
arrivals differ by exactly 50 ms -- the bring-up B5 slot-timing value.
"""

import csv
import json
from pathlib import Path

import numpy as np
import pytest

from tools import analyze_log

E3D = float(np.hypot(0.02, 0.01))  # constant 3D error of the synthetic mic fixes


def write_truth(path: Path, span_s: float = 5.0, step_s: float = 0.1,
                fs: float = 48000.0) -> Path:
    """truth.json in sim_beacons.py's format: straight walk, +y at 0.2 m/s."""
    t = np.arange(0.0, span_s + step_s / 2, step_s)
    pos = np.column_stack([np.zeros_like(t), 0.2 * t, np.full_like(t, 1.25)])
    payload = {
        "version": 1,
        "preset": "walk_to_cupboard",
        "fs": fs,
        "duration_s": span_s,
        "truth": {"t": t.tolist(), "position": pos.tolist()},
    }
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def mic_fix(t: float, t0: float = 0.0) -> dict:
    """A pipeline fix line 22.36 mm off truth; B2 arrives 50 ms after B1."""
    mic = [0.02, 0.2 * t - 0.01, 1.25]
    return {
        "t": t + t0,
        "mic": mic,
        "ear": [mic[0], mic[1], mic[2] + 0.35],
        "quality": "ok",
        "beacons_used": ["B1", "B2", "B4", "B5"],
        "beacons_heard": 4,
        "snr_db": {"B1": 23.0, "B2": 21.0, "B4": 19.0, "B5": 17.0},
        "arrival_s": {"B1": t + 0.005, "B2": t + 0.055},
        "residual_rms_ms": 0.07,
    }


def ear_pose(t: float, t0: float = 0.0) -> dict:
    """A listener_pose line (ear position, contract shape) on the truth + offset."""
    return {
        "type": "listener_pose",
        "position": [0.0, 0.2 * t, 1.25 + 0.35],
        "quality": "ok",
        "beacons_heard": 4,
        "source": "beacons",
        "t": t + t0,
    }


def write_lines(path: Path, lines: list) -> Path:
    path.write_text(
        "\n".join(
            ln if isinstance(ln, str) else json.dumps(ln) for ln in lines
        ) + "\n",
        encoding="utf-8",
    )
    return path


def test_error_stats_exact_on_constant_offset(tmp_path: Path) -> None:
    truth_path = write_truth(tmp_path / "truth.json")
    fixes, stats = analyze_log.parse_fixes(
        write_lines(tmp_path / "fixes.jsonl", [mic_fix(t) for t in np.arange(0.5, 5.01, 0.5)])
    )
    assert stats.skipped == 0
    truth = analyze_log.load_truth(truth_path)
    err3d, err_h, times = analyze_log.error_stats(fixes, truth, 0.0, None)
    assert len(err3d) == 10
    assert np.allclose(err3d, E3D, atol=1e-9)
    assert np.allclose(err_h, E3D, atol=1e-9)  # the offset is purely horizontal


def test_truth_interpolation_is_exact_on_linear_traces(tmp_path: Path) -> None:
    """A fix between truth samples on a linear trace keeps the same error."""
    truth = analyze_log.load_truth(write_truth(tmp_path / "truth.json"))
    fixes, _ = analyze_log.parse_fixes(
        write_lines(tmp_path / "fixes.jsonl", [mic_fix(1.35)])
    )
    err3d, _, _ = analyze_log.error_stats(fixes, truth, 0.0, None)
    assert np.allclose(err3d, [E3D], atol=1e-9)


def test_fix_time_uses_sample_index_with_truth_fs(tmp_path: Path) -> None:
    truth = analyze_log.load_truth(write_truth(tmp_path / "truth.json"))
    fixes, _ = analyze_log.parse_fixes(
        write_lines(tmp_path / "fixes.jsonl", [
            {"sample_index": 240000, "mic": [0.0, 1.0, 1.25], "quality": "ok"},
        ])
    )
    assert analyze_log.fix_time(fixes[0], truth, 0.0) == pytest.approx(5.0)


def test_lost_stretches_report_only_long_gaps(tmp_path: Path) -> None:
    fixes, _ = analyze_log.parse_fixes(
        write_lines(tmp_path / "fixes.jsonl", [
            mic_fix(1.0),
            {"t": 2.0, "quality": "lost", "ear": [0.0, 0.4, 1.6]},
            {"t": 2.6, "quality": "lost", "ear": [0.0, 0.4, 1.6]},
            {"t": 3.2, "quality": "lost", "ear": [0.0, 0.4, 1.6]},
            mic_fix(4.0),
        ])
    )
    long_default = analyze_log.lost_stretches(fixes, 0.0, 1.5)
    assert long_default == []  # 1.2 s of lost: under the 1.5 s publish timeout
    assert analyze_log.lost_stretches(fixes, 0.0, 1.0) == [(2.0, 3.2, pytest.approx(1.2))]


def test_arrival_diff_is_the_b5_slot_check(tmp_path: Path) -> None:
    fixes, _ = analyze_log.parse_fixes(
        write_lines(tmp_path / "fixes.jsonl", [mic_fix(t) for t in np.arange(0.5, 3.01, 0.5)])
    )
    stats = analyze_log.arrival_diff_stats(fixes, "B2", "B1")
    assert stats is not None
    assert stats["n"] == 6  # arange(0.5, 3.01, 0.5) is six fixes
    assert stats["median_ms"] == pytest.approx(50.0, abs=1e-9)
    assert stats["std_ms"] < 1e-6
    assert analyze_log.arrival_diff_stats(fixes, "B1", "B2")["median_ms"] == pytest.approx(-50.0)


def test_parser_skips_junk_and_counts_it(tmp_path: Path) -> None:
    path = write_lines(tmp_path / "mixed.jsonl", [
        mic_fix(1.0),
        "this is not json",
        {"type": "pose"},          # not a fix or listener_pose line
        [1, 2, 3],                 # JSON, but not an object
        mic_fix(2.0),
    ])
    fixes, stats = analyze_log.parse_fixes(path)
    assert stats.parsed == 2
    assert stats.skipped == 3
    assert len(stats.skip_reasons) == 3
    assert [f.t for f in fixes] == [1.0, 2.0]


def test_parser_raises_when_nothing_parses(tmp_path: Path) -> None:
    path = write_lines(tmp_path / "junk.jsonl", ["garbage", '{"type": "pose"}'])
    with pytest.raises(analyze_log.AnalyzeError, match="no parseable fixes"):
        analyze_log.parse_fixes(path)


def test_epoch_guard_then_t0_alignment(tmp_path: Path, capsys) -> None:
    """listener_pose logs carry epoch t; a small truth trace needs --t0."""
    truth_path = write_truth(tmp_path / "truth.json")
    epoch = 1_761_350_400.0
    fixes_path = write_lines(tmp_path / "poses.jsonl", [ear_pose(t, t0=epoch) for t in (0.5, 1.5, 2.5)])

    assert analyze_log.main(["--fixes", str(fixes_path), "--truth", str(truth_path), "--no-plot"]) == 1
    assert "--t0" in capsys.readouterr().out

    capsys.readouterr()
    assert analyze_log.main([
        "--fixes", str(fixes_path), "--truth", str(truth_path), "--no-plot", "--t0", str(epoch),
    ]) == 0
    output = capsys.readouterr().out
    assert "350.0 mm" in output  # ear position vs mic truth without an offset correction


def test_ear_offset_flag_corrects_listener_pose_logs(tmp_path: Path, capsys) -> None:
    truth_path = write_truth(tmp_path / "truth.json")
    epoch = 1_761_350_400.0
    fixes_path = write_lines(tmp_path / "poses.jsonl", [ear_pose(t, t0=epoch) for t in (0.5, 1.5, 2.5)])
    assert analyze_log.main([
        "--fixes", str(fixes_path), "--truth", str(truth_path), "--no-plot",
        "--t0", str(epoch), "--ear-offset", "0,0,0.35",
    ]) == 0
    output = capsys.readouterr().out
    assert "median 0.0 mm" in output
    assert "max 0.0 mm" in output


def test_csvs_written_and_columns_aligned(tmp_path: Path) -> None:
    """Ear-only rows must keep their values in the ear_* columns (14 wide)."""
    truth = analyze_log.load_truth(write_truth(tmp_path / "truth.json"))
    fixes, _ = analyze_log.parse_fixes(
        write_lines(tmp_path / "mixed.jsonl", [mic_fix(1.0), ear_pose(2.0)])
    )
    out_dir = tmp_path / "out"
    written = analyze_log.write_csvs(out_dir, fixes, truth, 0.0, None)
    assert (out_dir / "fixes.csv") in written
    with (out_dir / "fixes.csv").open(newline="", encoding="utf-8") as handle:
        rows = list(csv.reader(handle))
    header = rows[0]
    assert len(header) == 14
    assert all(len(row) == 14 for row in rows[1:])
    mic_row, ear_row = rows[1], rows[2]
    assert float(mic_row[header.index("mic_x")]) == pytest.approx(0.02)
    assert mic_row[header.index("ear_x")] != ""
    assert ear_row[header.index("mic_x")] == ""  # no mic position in a listener_pose line
    assert float(ear_row[header.index("ear_x")]) == pytest.approx(0.0)
    assert float(ear_row[header.index("ear_z")]) == pytest.approx(1.60)
    # SNR and arrival CSVs follow when the fixes carry them.
    assert (out_dir / "snr.csv").exists()
    assert (out_dir / "arrivals.csv").exists()


def test_fix_rate_sliding_window(tmp_path: Path) -> None:
    # 0.3 s spacing -> 4 fixes fit in each [start, start+1.0) window.
    centers, rates = analyze_log.fix_rate_series([1.0 + 0.3 * i for i in range(10)])
    assert centers[0] == pytest.approx(1.5)
    assert rates[0] == pytest.approx(4.0)
    assert rates.max() == pytest.approx(4.0)


def test_plots_written_when_matplotlib_present(tmp_path: Path) -> None:
    pytest.importorskip("matplotlib")
    truth_path = write_truth(tmp_path / "truth.json")
    fixes_path = write_lines(tmp_path / "fixes.jsonl", [mic_fix(t) for t in np.arange(0.5, 5.01, 0.5)])
    out_dir = tmp_path / "out"
    assert analyze_log.main(["--fixes", str(fixes_path), "--truth", str(truth_path), "--out", str(out_dir)]) == 0
    for name in (
        "snr_over_time.png", "arrivals.png", "residuals.png",
        "position_vs_truth.png", "fix_rate.png", "quality_timeline.png",
    ):
        assert (out_dir / name).exists(), name


def test_csv_fallback_without_matplotlib(tmp_path: Path, capsys, monkeypatch) -> None:
    truth_path = write_truth(tmp_path / "truth.json")
    fixes_path = write_lines(tmp_path / "fixes.jsonl", [mic_fix(1.0), mic_fix(2.0)])
    monkeypatch.setitem(__import__("sys").modules, "matplotlib", None)
    monkeypatch.setitem(__import__("sys").modules, "matplotlib.pyplot", None)
    assert analyze_log.main(["--fixes", str(fixes_path), "--truth", str(truth_path)]) == 0
    output = capsys.readouterr().out
    assert "matplotlib unavailable" in output
    assert "error vs truth" in output
