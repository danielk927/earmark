"""Field kit for the UWB physical gates: a local bus recorder and offline gate analysis.

The hub never logs positions, so this tool writes them to a separate local file (under the gitignored var/).
Log format, one JSON object per line: {"rx": <time.time()>, "msg": {...}} or {"rx": ..., "marker": "<text>"}.
Analysis functions are pure (no I/O); the `main` subcommands print Markdown and exit 0 on PASS, 1 on FAIL.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import math
import signal
import statistics
import sys
import time
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import IO, Any

DEFAULT_TYPES = ("uwb_range", "listener_pose", "head_pose", "motion_state", "object_tap", "tap_position",
                 "place_item", "guide_start", "guide_stop", "status")
COMPONENT = "cli"  # hello component: must be in the contract's enum (a new value would be a contract change)

Entry = dict[str, Any]
Point = tuple[float, float]


# ---------------------------------------------------------------- recorder

class Recorder:
    """Writes log lines; callable without a bus (feed it dicts and marker text)."""

    def __init__(self, out: IO[str]) -> None:
        self.out = out
        self.counts: Counter[str] = Counter()

    def _write(self, entry: Entry) -> None:
        self.out.write(json.dumps(entry, separators=(",", ":")) + "\n")
        self.out.flush()

    def message(self, msg: dict, rx: float | None = None) -> None:
        self.counts[str(msg.get("type", "?"))] += 1
        self._write({"rx": time.time() if rx is None else rx, "msg": msg})

    def marker(self, text: str, rx: float | None = None) -> None:
        text = text.strip()
        if text:
            self.counts["marker"] += 1
            self._write({"rx": time.time() if rx is None else rx, "marker": text})

    def summary(self) -> str:
        """Counts per type only; never coordinates."""
        return " ".join(f"{k}={v}" for k, v in sorted(self.counts.items())) or "no messages yet"


def load_log(path: Path | str) -> list[Entry]:
    """Read a log file, skipping blank and malformed lines; sorted by rx."""
    entries: list[Entry] = []
    for line in Path(path).read_text().splitlines():
        try:
            e = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(e, dict) and isinstance(e.get("rx"), (int, float)):
            entries.append(e)
    entries.sort(key=lambda e: e["rx"])
    return entries


def messages(log: list[Entry], mtype: str) -> list[tuple[float, dict]]:
    return [(e["rx"], e["msg"]) for e in log if isinstance(e.get("msg"), dict) and e["msg"].get("type") == mtype]


def markers(log: list[Entry]) -> list[tuple[float, str]]:
    return [(e["rx"], e["marker"]) for e in log if isinstance(e.get("marker"), str)]


def _fmt(x: float | None, digits: int = 3) -> str:
    return "n/a" if x is None else f"{x:.{digits}f}"


def percentile(values: list[float], q: float) -> float:
    """Linear-interpolated percentile, q in [0, 100]."""
    s = sorted(values)
    if not s:
        raise ValueError("no values")
    k = (len(s) - 1) * q / 100
    lo, hi = math.floor(k), math.ceil(k)
    return s[lo] + (s[hi] - s[lo]) * (k - lo)


def _table(header: list[str], rows: list[list[str]]) -> str:
    lines = ["| " + " | ".join(header) + " |", "|" + "|".join("---" for _ in header) + "|"]
    lines += ["| " + " | ".join(r) + " |" for r in rows]
    return "\n".join(lines)


# ---------------------------------------------------------------- ranging

@dataclass
class RangingRow:
    truth: float
    n: int
    mean: float | None
    median: float | None
    std: float | None
    bias: float | None
    dropout: float | None
    passed: bool


@dataclass
class RangingResult:
    rows: list[RangingRow]
    offset: float | None
    consistent: bool | None
    passed: bool


def analyze_ranging(log: list[Entry], anchor: str, truth: list[float], window: float = 2.0,
                    tol: float = 0.10) -> RangingResult:
    """Per tape distance: stats of the anchor's ranges in `window` s after each marker naming that distance."""
    ranges = [(rx, float(m["distance_m"])) for rx, m in messages(log, "uwb_range") if m.get("anchor") == anchor]
    samples: dict[float, list[float]] = {d: [] for d in truth}
    arrivals: dict[float, list[float]] = {d: [] for d in truth}
    spans: dict[float, float] = {d: 0.0 for d in truth}
    for mrx, text in markers(log):
        try:
            val = float(text)
        except ValueError:
            continue
        d = next((t for t in truth if abs(t - val) < 1e-9), None)
        if d is None:
            continue
        spans[d] += window
        for rx, dist in ranges:
            if mrx <= rx < mrx + window:
                samples[d].append(dist)
                arrivals[d].append(rx)
    rows: list[RangingRow] = []
    for d in truth:
        xs = samples[d]
        if not xs:
            rows.append(RangingRow(d, 0, None, None, None, None, None, False))
            continue
        arr = sorted(arrivals[d])
        gaps = [b - a for a, b in zip(arr, arr[1:], strict=False) if b > a]
        dropout: float | None = None
        if gaps:
            expected = spans[d] / statistics.median(gaps)
            dropout = max(0.0, 1 - len(xs) / expected)
        mean = statistics.fmean(xs)
        rows.append(RangingRow(d, len(xs), mean, statistics.median(xs), statistics.pstdev(xs), mean - d, dropout,
                               abs(mean - d) <= tol))
    biases = [r.bias for r in rows if r.bias is not None]
    offset = statistics.fmean(biases) if biases else None
    consistent = (max(biases) - min(biases) <= 0.05) if biases else None
    return RangingResult(rows, offset, consistent, bool(rows) and all(r.passed for r in rows))


def render_ranging(res: RangingResult, anchor: str, tol: float) -> str:
    rows = [[f"{r.truth:g}", str(r.n), _fmt(r.mean), _fmt(r.median), _fmt(r.std), _fmt(r.bias),
             "n/a" if r.dropout is None else f"{r.dropout:.0%}", "PASS" if r.passed else "FAIL"] for r in res.rows]
    out = [f"## Ranging gate: {anchor} (tolerance +-{tol:g} m)", "",
           _table(["truth m", "n", "mean m", "median m", "std m", "bias m", "dropout", "result"], rows), ""]
    if res.offset is None:
        out.append("Suggested offset: n/a (no data)")
    else:
        cons = "consistent" if res.consistent else "NOT consistent"
        out.append(f"Suggested offset for {anchor}: {res.offset:+.3f} m (mean bias; subtract from readings), {cons} "
                   "(spread across distances <= 0.05 m)")
    out.append(f"**{'PASS' if res.passed else 'FAIL'}**")
    return "\n".join(out)


# ---------------------------------------------------------------- tracking

def parse_points(text: str) -> list[Point]:
    """'x1,y1;x2,y2' -> [(x1, y1), (x2, y2)]."""
    pts: list[Point] = []
    for part in text.split(";"):
        if part.strip():
            x, y = part.split(",")[:2]
            pts.append((float(x), float(y)))
    return pts


def dist_to_polyline(p: Point, path: list[Point]) -> float:
    """Horizontal distance from p to the polyline (or to the point, for a one-point path)."""
    if not path:
        raise ValueError("empty path")
    if len(path) == 1:
        return math.dist(p, path[0])
    best = math.inf
    for a, b in zip(path, path[1:], strict=False):
        dx, dy = b[0] - a[0], b[1] - a[1]
        seg = dx * dx + dy * dy
        u = 0.0 if seg == 0 else max(0.0, min(1.0, ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / seg))
        best = min(best, math.dist(p, (a[0] + u * dx, a[1] + u * dy)))
    return best


def marker_time(log: list[Entry], text: str | None, after: float | None = None) -> float | None:
    """rx of the first marker with this text (at or after `after`, if given); None when no text is given."""
    if text is None:
        return None
    for rx, t in markers(log):
        if t == text and (after is None or rx >= after):
            return rx
    raise ValueError(f"marker {text!r} not found in the log")


@dataclass
class TrackLimits:
    median_m: float = 0.15
    p95_m: float = 0.30
    jump_m: float = 0.30
    rate_hz: float = 10.0
    hold_m: float = 0.15
    lost_count: int = 1
    lost_s: float = 1.0


@dataclass
class TrackResult:
    n_poses: int
    n_ok: int
    median_err: float | None
    p95_err: float | None
    max_jump: float | None
    rate_hz: float | None
    lost_durations: list[float]
    fixed_count: int
    hold_displacement: float | None
    hold_fixed: int | None
    checks: dict[str, bool] = field(default_factory=dict)

    @property
    def passed(self) -> bool:
        return bool(self.checks) and all(self.checks.values())


def _xy(msg: dict) -> Point:
    pos = msg["position"]
    return (float(pos[0]), float(pos[1]))


def analyze_track(log: list[Entry], path: list[Point], t0: float | None = None, t1: float | None = None,
                  hold: tuple[float, float] | None = None, limits: TrackLimits | None = None) -> TrackResult:
    """Gate numbers for `listener_pose` between t0 and t1 (rx times; default whole log)."""
    lim = limits or TrackLimits()
    lo = -math.inf if t0 is None else t0
    hi = math.inf if t1 is None else t1
    poses = [(rx, m) for rx, m in messages(log, "listener_pose") if lo <= rx <= hi]
    ok = [(rx, m) for rx, m in poses if m.get("quality") == "ok"]
    errs = [dist_to_polyline(_xy(m), path) for _, m in ok]
    median_err = statistics.median(errs) if errs else None
    p95_err = percentile(errs, 95) if errs else None

    moving = [(rx, m) for rx, m in poses if m.get("mode") != "fixed"]
    jumps = [math.dist(_xy(a[1]), _xy(b[1])) for a, b in zip(moving, moving[1:], strict=False)]
    max_jump = max(jumps) if jumps else None

    rate = None
    if len(poses) >= 2 and poses[-1][0] > poses[0][0]:
        rate = (len(poses) - 1) / (poses[-1][0] - poses[0][0])

    lost: list[float] = []
    start: float | None = None
    for i, (rx, m) in enumerate(poses):
        if m.get("mode") == "lost":
            if start is None:
                start = rx
        elif start is not None:
            lost.append(rx - start)
            start = None
        if start is not None and i == len(poses) - 1:
            lost.append(rx - start)
    fixed_count = sum(1 for _, m in poses if m.get("mode") == "fixed")

    disp = hold_fixed = None
    if hold is not None:
        seg = [(rx, m) for rx, m in messages(log, "listener_pose") if hold[0] <= rx <= hold[1]]
        hold_fixed = sum(1 for _, m in seg if m.get("mode") == "fixed")
        held = [_xy(m) for _, m in seg if m.get("mode") != "fixed"]
        disp = max((math.dist(held[0], p) for p in held), default=None)

    checks: dict[str, bool] = {
        "median error": median_err is not None and median_err <= lim.median_m,
        "p95 error": p95_err is not None and p95_err <= lim.p95_m,
        "max jump": max_jump is not None and max_jump <= lim.jump_m,
        "pose rate": rate is not None and rate >= lim.rate_hz,
        "lost episodes": len(lost) <= lim.lost_count and all(d < lim.lost_s for d in lost),
    }
    if hold is not None:
        checks["hold"] = disp is not None and disp <= lim.hold_m and hold_fixed == 0
    return TrackResult(len(poses), len(ok), median_err, p95_err, max_jump, rate, lost, fixed_count, disp, hold_fixed, checks)


def render_track(res: TrackResult, lim: TrackLimits) -> str:
    lost = ", ".join(f"{d:.2f} s" for d in res.lost_durations) or "none"
    rows = [
        ["median error", _fmt(res.median_err) + " m", f"<= {lim.median_m:g} m", "median error"],
        ["p95 error", _fmt(res.p95_err) + " m", f"<= {lim.p95_m:g} m", "p95 error"],
        ["max jump", _fmt(res.max_jump) + " m", f"<= {lim.jump_m:g} m", "max jump"],
        ["pose rate", _fmt(res.rate_hz, 1) + " Hz", f">= {lim.rate_hz:g} Hz", "pose rate"],
        ["lost episodes", f"{len(res.lost_durations)} ({lost})", f"<= {lim.lost_count}, each < {lim.lost_s:g} s",
         "lost episodes"],
    ]
    if "hold" in res.checks:
        rows.append(["hold", f"max displacement {_fmt(res.hold_displacement)} m, {res.hold_fixed} fixed",
                     f"<= {lim.hold_m:g} m, 0 fixed", "hold"])
    body = [[a, b, c, "PASS" if res.checks[k] else "FAIL"] for a, b, c, k in rows]
    out = ["## Tracking gate", "", f"poses: {res.n_poses} ({res.n_ok} ok), fixed poses: {res.fixed_count}", "",
           _table(["metric", "value", "limit", "result"], body), "", f"**{'PASS' if res.passed else 'FAIL'}**"]
    return "\n".join(out)


# ---------------------------------------------------------------- taps

@dataclass
class TapRow:
    index: int
    spot: int
    error: float
    passed: bool


@dataclass
class TapResult:
    rows: list[TapRow]
    not_ok: int
    passed: bool


def analyze_taps(log: list[Entry], spots: list[Point], tol: float = 0.10) -> TapResult:
    """Each ok tap against its nearest taped spot."""
    rows: list[TapRow] = []
    not_ok = 0
    for _, m in messages(log, "tap_position"):
        if not m.get("ok") or not m.get("position"):
            not_ok += 1
            continue
        errs = [math.dist(_xy(m), s) for s in spots]
        i = min(range(len(spots)), key=errs.__getitem__)
        rows.append(TapRow(len(rows) + 1, i + 1, errs[i], errs[i] <= tol))
    return TapResult(rows, not_ok, bool(rows) and all(r.passed for r in rows))


def render_taps(res: TapResult, tol: float) -> str:
    rows = [[str(r.index), str(r.spot), _fmt(r.error), "PASS" if r.passed else "FAIL"] for r in res.rows]
    return "\n".join([f"## Mark gate (tolerance {tol:g} m)", "", _table(["tap", "nearest spot", "error m", "result"], rows), "",
                      f"taps with ok=false: {res.not_ok}", f"**{'PASS' if res.passed else 'FAIL'}**"])


# ---------------------------------------------------------------- latency

@dataclass
class LatencyResult:
    n: int
    median_ms: float | None
    p95_ms: float | None
    max_ms: float | None


def analyze_latency(log: list[Entry]) -> LatencyResult:
    """For each listener_pose: rx minus rx of the latest earlier uwb_range."""
    last: float | None = None
    delays: list[float] = []
    for e in log:
        m = e.get("msg")
        if not isinstance(m, dict):
            continue
        if m.get("type") == "uwb_range":
            last = e["rx"]
        elif m.get("type") == "listener_pose" and last is not None:
            delays.append((e["rx"] - last) * 1000)
    if not delays:
        return LatencyResult(0, None, None, None)
    return LatencyResult(len(delays), statistics.median(delays), percentile(delays, 95), max(delays))


def render_latency(res: LatencyResult) -> str:
    return "\n".join(["## Latency: uwb_range to next listener_pose", "",
                      _table(["n", "median ms", "p95 ms", "max ms"],
                             [[str(res.n), _fmt(res.median_ms, 1), _fmt(res.p95_ms, 1), _fmt(res.max_ms, 1)]])])


# ---------------------------------------------------------------- live recording

async def record(out_path: Path, url: str | None, types: list[str], stdin: bool = True,
                 stop: asyncio.Event | None = None) -> int:
    """Record bus traffic and stdin markers until `stop` is set; reconnects when the hub goes away."""
    from earmark_contracts import to_dict

    from .client import BusClient
    from .config import bus_url

    out_path.parent.mkdir(parents=True, exist_ok=True)
    stop = stop or asyncio.Event()
    loop = asyncio.get_running_loop()
    with out_path.open("a") as f:
        rec = Recorder(f)

        def on_stdin() -> None:
            line = sys.stdin.readline()
            if line == "":
                loop.remove_reader(sys.stdin)
            else:
                rec.marker(line)

        if stdin:
            try:
                loop.add_reader(sys.stdin, on_stdin)
            except (NotImplementedError, ValueError, OSError):
                stdin = False

        async def report() -> None:
            while True:
                await asyncio.sleep(2.0)
                print(rec.summary(), file=sys.stderr, flush=True)

        async def pump() -> None:
            waiting = False
            while True:
                try:
                    client = await BusClient.connect(COMPONENT, subscribe=types, url=url)
                except (OSError, TimeoutError):
                    if not waiting:
                        print(f"waiting for the hub at {url or bus_url()} ...", file=sys.stderr)
                        waiting = True
                    await asyncio.sleep(1.0)
                    continue
                waiting = False
                print(f"recording to {out_path}", file=sys.stderr, flush=True)
                async for msg in client:
                    rec.message(to_dict(msg))
                print("hub disconnected", file=sys.stderr)

        tasks = [asyncio.create_task(report()), asyncio.create_task(pump())]
        try:
            await stop.wait()
        finally:
            for t in tasks:
                t.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            if stdin:
                loop.remove_reader(sys.stdin)
        print(f"stopped: {rec.summary()}", file=sys.stderr)
    return 0


async def _record_main(out: Path, url: str | None, types: list[str]) -> int:
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop.set)
    return await record(out, url, types, stop=stop)


# ---------------------------------------------------------------- CLI

def _floats(text: str) -> list[float]:
    return [float(x) for x in text.split(",") if x.strip()]


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="earmark-fieldkit", description="Record UWB field sessions and check the physical gates.")
    sub = p.add_subparsers(dest="cmd", required=True)

    r = sub.add_parser("record", help="record bus traffic and typed markers to a JSONL file")
    r.add_argument("out", type=Path)
    r.add_argument("--url", help="bus URL (default EARMARK_BUS_URL)")
    r.add_argument("--types", help="comma list of message types (default: the UWB set)")

    g = sub.add_parser("ranging", help="ranging gate")
    g.add_argument("log", type=Path)
    g.add_argument("--anchor", required=True)
    g.add_argument("--truth", required=True, help="tape distances in m, e.g. 0.5,1,2,3")
    g.add_argument("--window", type=float, default=2.0)
    g.add_argument("--tol", type=float, default=0.10)

    t = sub.add_parser("track", help="tracking gate")
    t.add_argument("log", type=Path)
    t.add_argument("--path", required=True, help='taped path "x1,y1;x2,y2;..."')
    t.add_argument("--from", dest="from_marker")
    t.add_argument("--to", dest="to_marker")
    t.add_argument("--hold-from")
    t.add_argument("--hold-to")
    d = TrackLimits()
    t.add_argument("--median", type=float, default=d.median_m)
    t.add_argument("--p95", type=float, default=d.p95_m)
    t.add_argument("--jump", type=float, default=d.jump_m)
    t.add_argument("--rate", type=float, default=d.rate_hz)
    t.add_argument("--hold-tol", type=float, default=d.hold_m)
    t.add_argument("--max-lost", type=int, default=d.lost_count)
    t.add_argument("--max-lost-s", type=float, default=d.lost_s)

    k = sub.add_parser("taps", help="mark gate")
    k.add_argument("log", type=Path)
    k.add_argument("--spots", required=True, help='taped spots "x1,y1;x2,y2;..."')
    k.add_argument("--tol", type=float, default=0.10)

    la = sub.add_parser("latency", help="uwb_range to listener_pose delay")
    la.add_argument("log", type=Path)

    args = p.parse_args(argv)
    if args.cmd == "record":
        from .config import load_dotenv_once

        load_dotenv_once()
        types = [x.strip() for x in args.types.split(",") if x.strip()] if args.types else list(DEFAULT_TYPES)
        try:
            return asyncio.run(_record_main(args.out, args.url, types)) or 0
        except KeyboardInterrupt:
            return 0

    try:
        log = load_log(args.log)
        if args.cmd == "ranging":
            rres = analyze_ranging(log, args.anchor, _floats(args.truth), args.window, args.tol)
            print(render_ranging(rres, args.anchor, args.tol))
            return 0 if rres.passed else 1
        if args.cmd == "track":
            t0 = marker_time(log, args.from_marker)
            t1 = marker_time(log, args.to_marker, after=t0)
            hold = None
            if args.hold_from or args.hold_to:
                if not (args.hold_from and args.hold_to):
                    p.error("--hold-from and --hold-to go together")
                h0 = marker_time(log, args.hold_from)
                hold = (h0, marker_time(log, args.hold_to, after=h0))
            lim = TrackLimits(args.median, args.p95, args.jump, args.rate, args.hold_tol, args.max_lost, args.max_lost_s)
            tres = analyze_track(log, parse_points(args.path), t0, t1, hold, lim)
            print(render_track(tres, lim))
            return 0 if tres.passed else 1
        if args.cmd == "taps":
            kres = analyze_taps(log, parse_points(args.spots), args.tol)
            print(render_taps(kres, args.tol))
            return 0 if kres.passed else 1
        print(render_latency(analyze_latency(log)))
        return 0
    except (OSError, ValueError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
