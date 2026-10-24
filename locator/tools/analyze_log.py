"""Field-log analyzer (LOCATOR_BRIEF.md section 7.5).

Parses a fixes.jsonl (the pipeline's per-cycle output, section 7.4) or a
fake_hub listener_pose recording, optionally joins truth.json from the
simulator (section 7.2), and produces per-beacon SNR over time, arrival
times, residuals, the estimated position versus truth, the fix rate, and
the quality states -- as CSVs always and as PNG plots when matplotlib is
installed. Prints the median, 95th-percentile and max position errors.

Parsed line schemas. Unknown fields are ignored; unknown LINES are skipped
and counted, so mixed iOS log.jsonl streams degrade gracefully.

Pipeline fix line (section 7.4 fields; aliases in parentheses):
    {"t": 12.05 (t_unix), "sample_index": 578400, "mic": [x,y,z]
     (mic_position, position), "ear": [x,y,z] (ear_position),
     "quality": "ok" (state), "beacons_used": ["B1","B2","B4","B5"]
     (or an int count), "beacons_heard": 4, "snr_db": {"B1": 23.1} (snr),
     "arrival_s": {"B1": 12.0053} (arrival, arrivals; arrival_ms also
     accepted in ms), "residual_rms_ms": 0.07 (residual_ms)}
listener_pose line (contracts/, e.g. a fake_hub recording): {"type":
    "listener_pose", "position": [x,y,z]  # EAR position
    "quality": "ok", "beacons_heard": 5, "source": "beacons", "t": ...}

Time base: fix ``t`` is compared against truth ``t`` after subtracting
--t0 (default 0). A fix carrying sample_index but no t uses
sample_index / truth fs when a truth file is given. listener_pose t is
Unix epoch per the contract; pass --t0 to map it onto a simulator truth.

Python 3.11+, numpy + stdlib; matplotlib optional.

Usage: python3 tools/analyze_log.py --fixes fixes.jsonl [--truth truth.json] [--out out/analysis]
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Sequence

import numpy as np

if __package__ in (None, ""):  # pragma: no cover - exercised via script runs
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

QUALITIES = ("ok", "degraded", "lost")
EPOCH_THRESHOLD_S = 1e9  # fix t above this is Unix epoch, not recording time
RATE_WINDOW_S = 1.0
RATE_STEP_S = 0.5
#: Default arrival-difference pair: the bring-up B5 timing test (section 10).
DEFAULT_DIFF_PAIR = ("B2", "B1")


class AnalyzeError(RuntimeError):
    """Raised when the log or truth file cannot be analyzed at all."""


@dataclass
class Fix:
    """One parsed fix (or lost emission) from a fixes/listener_pose log."""

    t: float | None
    sample_index: int | None
    mic: np.ndarray | None
    ear: np.ndarray | None
    quality: str
    beacons_used: list[str] | None
    beacons_heard: int | None
    snr_db: dict[str, float] = field(default_factory=dict)
    arrival_s: dict[str, float] = field(default_factory=dict)
    residual_rms_ms: float | None = None
    source: str | None = None
    line_no: int = 0


@dataclass
class ParseStats:
    lines: int = 0
    parsed: int = 0
    skipped: int = 0
    skip_reasons: list[str] = field(default_factory=list)

    def note_skip(self, reason: str) -> None:
        self.skipped += 1
        if len(self.skip_reasons) < 5:
            self.skip_reasons.append(reason)


def _as_position(raw: Any) -> np.ndarray | None:
    if isinstance(raw, (list, tuple)) and len(raw) == 3:
        try:
            return np.array([float(v) for v in raw], dtype=np.float64)
        except (TypeError, ValueError):
            return None
    return None


def _as_float(raw: Any) -> float | None:
    if isinstance(raw, bool) or raw is None:
        return None
    try:
        return float(raw)
    except (TypeError, ValueError):
        return None


def _as_beacon_dict(raw: Any, scale: float = 1.0) -> dict[str, float]:
    if not isinstance(raw, dict):
        return {}
    out: dict[str, float] = {}
    for key, value in raw.items():
        number = _as_float(value)
        if number is not None:
            out[str(key)] = number * scale
    return out


def parse_fix_line(line: dict[str, Any]) -> Fix | None:
    """One JSONL line -> Fix, or None when it is not a fix-shaped line."""
    if not isinstance(line, dict):
        return None
    if line.get("type") == "listener_pose":
        position = _as_position(line.get("position"))
        quality = line.get("quality")
        t = _as_float(line.get("t"))
        if position is None or quality not in QUALITIES or t is None:
            return None
        heard = line.get("beacons_heard")
        return Fix(
            t=t,
            sample_index=None,
            mic=None,
            ear=position,
            quality=str(quality),
            beacons_used=None,
            beacons_heard=heard if isinstance(heard, int) else None,
            source=line.get("source") if isinstance(line.get("source"), str) else None,
        )

    quality = line.get("quality", line.get("state"))
    mic = _as_position(
        line.get("mic") or line.get("mic_position") or line.get("position")
    )
    ear = _as_position(line.get("ear") or line.get("ear_position"))
    t = _as_float(line.get("t") if "t" in line else line.get("t_unix"))
    if quality not in QUALITIES or (mic is None and ear is None and t is None):
        return None

    beacons_used = line.get("beacons_used")
    if isinstance(beacons_used, list):
        beacons_used = [str(b) for b in beacons_used]
    elif isinstance(beacons_used, int) and not isinstance(beacons_used, bool):
        beacons_used = None
    else:
        beacons_used = None
    heard = line.get("beacons_heard")
    if (heard is None or not isinstance(heard, int)) and beacons_used is not None:
        heard = len(beacons_used)

    arrival_s = _as_beacon_dict(
        line.get("arrival_s") or line.get("arrival") or line.get("arrivals")
    )
    if not arrival_s:
        arrival_s = _as_beacon_dict(line.get("arrival_ms"), scale=1e-3)
    residual = _as_float(
        line.get("residual_rms_ms") or line.get("residual_ms") or line.get("residual_rms")
    )
    sample_index = line.get("sample_index")
    return Fix(
        t=t,
        sample_index=sample_index if isinstance(sample_index, int) else None,
        mic=mic,
        ear=ear,
        quality=str(quality),
        beacons_used=beacons_used,
        beacons_heard=heard if isinstance(heard, int) else None,
        snr_db=_as_beacon_dict(line.get("snr_db") or line.get("snr")),
        arrival_s=arrival_s,
        residual_rms_ms=residual,
    )


def parse_fixes(path: str | Path) -> tuple[list[Fix], ParseStats]:
    """Parse a fixes.jsonl / listener_pose recording; skips junk lines."""
    stats = ParseStats()
    fixes: list[Fix] = []
    with Path(path).open(encoding="utf-8") as handle:
        for line_no, raw in enumerate(handle, start=1):
            raw = raw.strip()
            if not raw:
                continue
            stats.lines += 1
            try:
                line = json.loads(raw)
            except json.JSONDecodeError as exc:
                stats.note_skip(f"line {line_no}: invalid JSON ({exc.msg})")
                continue
            fix = parse_fix_line(line)
            if fix is None:
                stats.note_skip(f"line {line_no}: not a fix or listener_pose line")
                continue
            fix.line_no = line_no
            fixes.append(fix)
            stats.parsed += 1
    if not fixes:
        raise AnalyzeError(
            f"{path}: no parseable fixes ({stats.lines} lines, "
            f"{stats.skipped} skipped: " + "; ".join(stats.skip_reasons[:3]) + ")"
        )
    fixes.sort(key=lambda f: (f.t if f.t is not None else 0.0, f.line_no))
    return fixes, stats


def load_truth(path: str | Path) -> dict[str, Any]:
    """Load truth.json (section 7.2): t[], position[[x,y,z]], plus metadata."""
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    trace = data.get("truth") or {}
    t = np.asarray(trace.get("t", []), dtype=np.float64)
    position = np.asarray(trace.get("position", []), dtype=np.float64)
    if t.size < 2 or position.shape != (t.size, 3):
        raise AnalyzeError(
            f"{path}: truth trace missing or malformed "
            "(expected truth.t and truth.position from sim_beacons.py)"
        )
    return data | {"_t": t, "_position": position}


def fix_time(fix: Fix, truth: dict[str, Any] | None, t0_s: float) -> float | None:
    """The fix's time on the truth/recording time base, or None."""
    if fix.t is not None:
        return fix.t - t0_s
    if fix.sample_index is not None and truth is not None:
        fs = truth.get("fs")
        if fs:
            return fix.sample_index / float(fs) - t0_s
    return None


def truth_at(truth: dict[str, Any], t_s: float) -> np.ndarray | None:
    t = truth["_t"]
    if t_s < t[0] or t_s > t[-1]:
        return None
    return np.array([np.interp(t_s, t, truth["_position"][:, i]) for i in range(3)])


def error_stats(fixes: list[Fix], truth: dict[str, Any] | None, t0_s: float,
                ear_offset_m: np.ndarray | None) -> tuple[list[float], list[float], list[float]]:
    """(3D, horizontal errors [m], fix times) over fixes comparable to truth.

    Uses the mic position when present, else the ear position (a
    listener_pose log; subtract --ear-offset to compare against mic truth).
    Fixes outside the truth trace's time span are skipped.
    """
    err3d: list[float] = []
    err_h: list[float] = []
    times: list[float] = []
    for fix in fixes:
        position = fix.mic if fix.mic is not None else fix.ear
        if position is None or truth is None:
            continue
        t_s = fix_time(fix, truth, t0_s)
        if t_s is None:
            continue
        reference = truth_at(truth, t_s)
        if reference is None:
            continue
        if position is fix.ear and fix.mic is None and ear_offset_m is not None:
            position = position - ear_offset_m
        delta = position - reference
        err3d.append(float(np.linalg.norm(delta)))
        err_h.append(float(np.linalg.norm(delta[:2])))
        times.append(t_s)
    return err3d, err_h, times


def fix_rate_series(times_s: list[float]) -> tuple[np.ndarray, np.ndarray]:
    """Sliding-window fix rate: (window centers, fixes/s)."""
    if not times_s:
        return np.array([]), np.array([])
    t = np.asarray(sorted(times_s))
    centers: list[float] = []
    rates: list[float] = []
    start = t[0]
    while start <= t[-1]:
        inside = t[(t >= start) & (t < start + RATE_WINDOW_S)]
        centers.append(start + RATE_WINDOW_S / 2.0)
        rates.append(float(inside.size) / RATE_WINDOW_S)
        start += RATE_STEP_S
    return np.array(centers), np.array(rates)


def lost_stretches(fixes: list[Fix], t0_s: float, timeout_s: float) -> list[tuple[float, float, float]]:
    """Contiguous lost periods (start, end, duration [s]) longer than timeout."""
    stretches: list[tuple[float, float, float]] = []
    start_t: float | None = None
    prev_t: float | None = None
    for fix in fixes:
        t_s = fix.t - t0_s if fix.t is not None else None
        if fix.quality == "lost" and t_s is not None:
            if start_t is None:
                start_t = t_s
            prev_t = t_s
        elif start_t is not None:
            end_t = prev_t if prev_t is not None else start_t
            duration = end_t - start_t
            if duration >= timeout_s:
                stretches.append((start_t, end_t, duration))
            start_t = prev_t = None
    if start_t is not None and prev_t is not None:
        duration = prev_t - start_t
        if duration >= timeout_s:
            stretches.append((start_t, prev_t, duration))
    return stretches


def arrival_diff_stats(fixes: list[Fix], beacon_hi: str, beacon_lo: str) -> dict[str, float] | None:
    """Per-fix (a_hi - a_lo) differences in ms; the B5 slot-timing check."""
    diffs = [
        (fix.arrival_s[beacon_hi] - fix.arrival_s[beacon_lo]) * 1000.0
        for fix in fixes
        if beacon_hi in fix.arrival_s and beacon_lo in fix.arrival_s
    ]
    if not diffs:
        return None
    arr = np.asarray(diffs)
    return {
        "n": float(arr.size),
        "median_ms": float(np.median(arr)),
        "mean_ms": float(arr.mean()),
        "std_ms": float(arr.std(ddof=1)) if arr.size > 1 else 0.0,
        "min_ms": float(arr.min()),
        "max_ms": float(arr.max()),
    }


def _percentile(values: list[float], pct: float) -> float:
    return float(np.percentile(np.asarray(values), pct)) if values else float("nan")


def write_csvs(out_dir: Path, fixes: list[Fix], truth: dict[str, Any] | None,
               t0_s: float, ear_offset_m: np.ndarray | None) -> list[Path]:
    """CSV dumps of every series (always written, matplotlib or not)."""
    out_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    fixes_path = out_dir / "fixes.csv"
    with fixes_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(
            ["t_s", "sample_index", "quality", "source", "beacons_heard",
             "mic_x", "mic_y", "mic_z", "ear_x", "ear_y", "ear_z",
             "error_3d_m", "error_horiz_m", "residual_rms_ms"]
        )
        for fix in fixes:
            t_s = fix_time(fix, truth, t0_s)
            position = fix.mic if fix.mic is not None else fix.ear
            err3d = err_h = ""
            if position is not None and truth is not None and t_s is not None:
                reference = truth_at(truth, t_s)
                if reference is not None:
                    if position is fix.ear and fix.mic is None and ear_offset_m is not None:
                        position = position - ear_offset_m
                    delta = position - reference
                    err3d = f"{np.linalg.norm(delta):.4f}"
                    err_h = f"{np.linalg.norm(delta[:2]):.4f}"
            writer.writerow([
                "" if t_s is None else f"{t_s:.6f}",
                "" if fix.sample_index is None else fix.sample_index,
                fix.quality,
                fix.source or "",
                "" if fix.beacons_heard is None else fix.beacons_heard,
                *( [f"{v:.6f}" for v in fix.mic] if fix.mic is not None else ["", "", ""] ),
                *( [f"{v:.6f}" for v in fix.ear] if fix.ear is not None else ["", "", ""] ),
                err3d, err_h,
                "" if fix.residual_rms_ms is None else f"{fix.residual_rms_ms:.4f}",
            ])
    written.append(fixes_path)

    snr_rows = [(t, b, snr) for fix in fixes if (t := fix_time(fix, truth, t0_s)) is not None
                for b, snr in sorted(fix.snr_db.items())]
    if snr_rows:
        path = out_dir / "snr.csv"
        with path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.writer(handle)
            writer.writerow(["t_s", "beacon", "snr_db"])
            writer.writerows((f"{t:.6f}", b, f"{snr:.2f}") for t, b, snr in snr_rows)
        written.append(path)

    arrival_rows = [(t, b, a) for fix in fixes if (t := fix_time(fix, truth, t0_s)) is not None
                    for b, a in sorted(fix.arrival_s.items())]
    if arrival_rows:
        path = out_dir / "arrivals.csv"
        with path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.writer(handle)
            writer.writerow(["t_s", "beacon", "arrival_s"])
            writer.writerows((f"{t:.6f}", b, f"{a:.6f}") for t, b, a in arrival_rows)
        written.append(path)
    return written


def save_plots(out_dir: Path, fixes: list[Fix], truth: dict[str, Any] | None,
               t0_s: float, ear_offset_m: np.ndarray | None) -> list[Path]:
    """PNG plots (brief 7.5); empty list without matplotlib (CSVs carry the data)."""
    try:
        import matplotlib  # noqa: F401 — optional, CI has no matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        return []
    out_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    series_t = [t for fix in fixes if (t := fix_time(fix, truth, t0_s)) is not None]

    # Per-beacon SNR over time.
    if any(fix.snr_db for fix in fixes):
        fig, ax = plt.subplots(figsize=(10, 4))
        for beacon in sorted({b for fix in fixes for b in fix.snr_db}):
            pts = [(t, fix.snr_db[beacon]) for fix in fixes
                   if (t := fix_time(fix, truth, t0_s)) is not None and beacon in fix.snr_db]
            ax.plot(*zip(*pts), marker=".", ms=3, lw=0.8, label=beacon)
        ax.set_xlabel("time [s]"); ax.set_ylabel("SNR [dB]")
        ax.set_title("per-beacon SNR (brief 7.5)")
        ax.grid(alpha=0.3); ax.legend(ncol=5, fontsize=8)
        fig.tight_layout(); fig.savefig(out_dir / "snr_over_time.png", dpi=150); plt.close(fig)
        written.append(out_dir / "snr_over_time.png")

    # Arrival times per beacon.
    if any(fix.arrival_s for fix in fixes):
        fig, ax = plt.subplots(figsize=(10, 4))
        for beacon in sorted({b for fix in fixes for b in fix.arrival_s}):
            pts = [(t, fix.arrival_s[beacon]) for fix in fixes
                   if (t := fix_time(fix, truth, t0_s)) is not None and beacon in fix.arrival_s]
            ax.plot(*zip(*pts), marker=".", ms=3, lw=0.8, label=beacon)
        ax.set_xlabel("time [s]"); ax.set_ylabel("arrival [s]")
        ax.set_title("per-beacon arrival times (brief 7.5)")
        ax.grid(alpha=0.3); ax.legend(ncol=5, fontsize=8)
        fig.tight_layout(); fig.savefig(out_dir / "arrivals.png", dpi=150); plt.close(fig)
        written.append(out_dir / "arrivals.png")

    # Residual RMS over time.
    res_pts = [(t, fix.residual_rms_ms) for fix in fixes
               if (t := fix_time(fix, truth, t0_s)) is not None
               and fix.residual_rms_ms is not None]
    if res_pts:
        fig, ax = plt.subplots(figsize=(10, 4))
        ax.plot(*zip(*res_pts), marker=".", ms=3, lw=0.8)
        ax.set_xlabel("time [s]"); ax.set_ylabel("residual RMS [ms]")
        ax.set_title("solve residual RMS (brief 7.5)")
        ax.grid(alpha=0.3)
        fig.tight_layout(); fig.savefig(out_dir / "residuals.png", dpi=150); plt.close(fig)
        written.append(out_dir / "residuals.png")

    # Estimated position vs truth: XY top view plus Z over time.
    if truth is not None:
        est: list[tuple[float, np.ndarray]] = []
        for fix in fixes:
            position = fix.mic if fix.mic is not None else fix.ear
            t_s = fix_time(fix, truth, t0_s)
            if position is None or t_s is None:
                continue
            if position is fix.ear and fix.mic is None and ear_offset_m is not None:
                position = position - ear_offset_m
            est.append((t_s, position))
        if est:
            fig, (ax_xy, ax_z) = plt.subplots(1, 2, figsize=(11, 5))
            tt = truth["_t"]
            pos = truth["_position"]
            ax_xy.plot(pos[:, 0], pos[:, 1], "k--", lw=1.0, label="truth")
            ax_xy.plot([p[0] for _, p in est], [p[1] for _, p in est], ".", ms=4,
                       label="estimate")
            ax_xy.set_xlabel("x [m]"); ax_xy.set_ylabel("y [m]")
            ax_xy.set_title("position vs truth, top view")
            ax_xy.axis("equal"); ax_xy.grid(alpha=0.3); ax_xy.legend(fontsize=8)
            ax_z.plot(tt, pos[:, 2], "k--", lw=1.0, label="truth")
            ax_z.plot([t for t, _ in est], [p[2] for _, p in est], ".", ms=4, label="estimate")
            ax_z.set_xlabel("time [s]"); ax_z.set_ylabel("z [m]")
            ax_z.set_title("height vs truth")
            ax_z.grid(alpha=0.3); ax_z.legend(fontsize=8)
            fig.tight_layout(); fig.savefig(out_dir / "position_vs_truth.png", dpi=150)
            plt.close(fig)
            written.append(out_dir / "position_vs_truth.png")

    # Fix rate over time.
    if series_t:
        centers, rates = fix_rate_series(series_t)
        fig, ax = plt.subplots(figsize=(10, 3.5))
        ax.step(centers, rates, where="mid", lw=1.2)
        ax.set_xlabel("time [s]"); ax.set_ylabel("fixes / s")
        ax.set_title("fix rate (brief 7.5)")
        ax.grid(alpha=0.3)
        fig.tight_layout(); fig.savefig(out_dir / "fix_rate.png", dpi=150); plt.close(fig)
        written.append(out_dir / "fix_rate.png")

    # Quality state timeline (ok=2, degraded=1, lost=0).
    qual_pts = [(t, QUALITIES.index(fix.quality)) for fix in fixes
                if (t := fix_time(fix, truth, t0_s)) is not None]
    if qual_pts:
        fig, ax = plt.subplots(figsize=(10, 3))
        ax.step(*zip(*qual_pts), where="post", lw=1.4)
        ax.set_yticks([0, 1, 2], labels=["lost", "degraded", "ok"])
        ax.set_xlabel("time [s]")
        ax.set_title("quality states (brief 7.5)")
        ax.grid(alpha=0.3)
        ax.set_ylim(-0.2, 2.2)
        fig.tight_layout(); fig.savefig(out_dir / "quality_timeline.png", dpi=150); plt.close(fig)
        written.append(out_dir / "quality_timeline.png")
    return written


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Analyze a fixes.jsonl / listener_pose log against truth (brief 7.5)."
    )
    parser.add_argument("--fixes", required=True, help="fixes.jsonl or a fake_hub listener_pose JSONL")
    parser.add_argument("--truth", help="truth.json from sim_beacons.py (optional)")
    parser.add_argument("--out", default=str(Path(__file__).resolve().parents[1] / "out" / "analysis"),
                        help="output directory for CSVs and plots (default: out/analysis)")
    parser.add_argument("--t0", type=float, default=0.0,
                        help="recording start in fix-time units: sim_t = fix_t - t0")
    parser.add_argument("--ear-offset", default=None, metavar="DX,DY,DZ",
                        help="subtract this ear offset from ear-only logs before "
                             "comparing to mic-position truth, e.g. 0,0,0.35")
    parser.add_argument("--arrival-diff", default=" ".join(DEFAULT_DIFF_PAIR),
                        metavar="HI LO",
                        help="beacon pair for the arrival-difference timing check "
                             "(default 'B2 B1' for bring-up B5); pass 'none' to disable")
    parser.add_argument("--lost-timeout", type=float, default=1.5,
                        help="lost stretches longer than this are listed [s], default 1.5")
    parser.add_argument("--no-plot", action="store_true", help="skip PNG plots entirely")
    args = parser.parse_args(argv)

    ear_offset = None
    if args.ear_offset:
        try:
            parts = [float(v) for v in args.ear_offset.split(",")]
            if len(parts) != 3:
                raise ValueError
            ear_offset = np.array(parts)
        except ValueError:
            print("ERR --ear-offset wants three comma-separated numbers, e.g. 0,0,0.35")
            return 1

    try:
        fixes, stats = parse_fixes(args.fixes)
        truth = load_truth(args.truth) if args.truth else None
    except (AnalyzeError, OSError, json.JSONDecodeError) as exc:
        print(f"ERR {exc}")
        return 1

    if truth is not None:
        fix_epoch = any(fix.t is not None and abs(fix.t) > EPOCH_THRESHOLD_S for fix in fixes)
        truth_small = float(np.max(truth["_t"])) < EPOCH_THRESHOLD_S
        if fix_epoch and truth_small and args.t0 == 0.0:
            print(
                "ERR fixes carry Unix epoch t but the truth trace starts near 0; "
                "pass --t0 <recording start in fix time> to align them"
            )
            return 1

    err3d, err_h, times = error_stats(fixes, truth, args.t0, ear_offset)
    qualities = {q: sum(1 for fix in fixes if fix.quality == q) for q in QUALITIES}
    n_lost_free = sum(1 for fix in fixes if fix.quality != "lost")
    span_s = (max(times) - min(times)) if len(times) >= 2 else 0.0
    overall_rate = n_lost_free / span_s if span_s > 0 else float("nan")
    stretches = lost_stretches(fixes, args.t0, args.lost_timeout)

    print(f"parsed {stats.parsed}/{stats.lines} lines"
          + (f" ({stats.skipped} skipped: {stats.skip_reasons[0]})" if stats.skipped else ""))
    print(f"quality: ok {qualities['ok']}, degraded {qualities['degraded']}, "
          f"lost {qualities['lost']}; {n_lost_free} fixes over {span_s:.2f} s "
          f"-> {overall_rate:.2f} fixes/s")
    if stretches:
        print(f"lost stretches >= {args.lost_timeout:g}s: {len(stretches)}")
        for start, end, duration in stretches:
            print(f"  lost {start:.2f}s to {end:.2f}s ({duration:.2f}s)")
    else:
        print(f"no lost stretches >= {args.lost_timeout:g}s")

    diff_pair = tuple(args.arrival_diff.split()) if args.arrival_diff.lower() != "none" else None
    if diff_pair and len(diff_pair) == 2:
        diff = arrival_diff_stats(fixes, diff_pair[0], diff_pair[1])
        if diff:
            print(
                f"arrival diff {diff_pair[0]}-{diff_pair[1]}: median {diff['median_ms']:.4f} ms, "
                f"mean {diff['mean_ms']:.4f} +/- {diff['std_ms']:.4f} ms std "
                f"(min {diff['min_ms']:.4f}, max {diff['max_ms']:.4f}, n={int(diff['n'])})"
            )

    if truth is not None and err3d:
        print(f"error vs truth, 3D (n={len(err3d)}): median {1000 * _percentile(err3d, 50):.1f} mm, "
              f"95th {1000 * _percentile(err3d, 95):.1f} mm, max {1000 * max(err3d):.1f} mm")
        print(f"error vs truth, horizontal: median {1000 * _percentile(err_h, 50):.1f} mm, "
              f"95th {1000 * _percentile(err_h, 95):.1f} mm, max {1000 * max(err_h):.1f} mm")
    elif truth is None:
        print("no truth file given: error stats and the track overlay are skipped")
    else:
        print("no fix overlapped the truth time span: error stats are empty")

    out_dir = Path(args.out)
    written = write_csvs(out_dir, fixes, truth, args.t0, ear_offset)
    plots: list[Path] = []
    if not args.no_plot:
        plots = save_plots(out_dir, fixes, truth, args.t0, ear_offset)
        if not plots:
            print("matplotlib unavailable: CSVs in " + str(out_dir) + " carry the same series")
    for path in written + plots:
        print(f"wrote {path}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
