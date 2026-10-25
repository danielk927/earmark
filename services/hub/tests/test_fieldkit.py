"""Field kit: recorder writer and gate analysis on synthetic logs (no bus, no ports)."""
from __future__ import annotations

import asyncio
import io
import json

import pytest
from earmark_contracts import UwbRange

from earmark_hub import fieldkit as fk


def rng(rx: float, dist: float, anchor: str = "uwb_1") -> dict:
    return {"rx": rx, "msg": {"type": "uwb_range", "anchor": anchor, "distance_m": dist, "seq": 0, "t": rx}}


def pose(rx: float, x: float, y: float = 0.0, mode: str = "tracked", quality: str = "ok") -> dict:
    return {"rx": rx, "msg": {"type": "listener_pose", "position": [x, y, 1.0], "quality": quality, "mode": mode,
                              "source": "uwb", "t": rx}}


def mark(rx: float, text: str) -> dict:
    return {"rx": rx, "marker": text}


def tap(rx: float, x: float | None, y: float = 0.0, ok: bool = True) -> dict:
    msg: dict = {"type": "tap_position", "ok": ok, "source": "uwb", "t": rx}
    if x is not None:
        msg["position"] = [x, y, 0.8]
    return {"rx": rx, "msg": msg}


def walk(t0: float, t1: float, speed: float = 0.8, hz: float = 10.0, noise: float = 0.0) -> list[dict]:
    out = []
    n = int((t1 - t0) * hz)
    for i in range(n + 1):
        t = t0 + i / hz
        out.append(pose(t, (t - t0) * speed, noise * (1 if i % 2 else -1)))
    return out


# ---------------------------------------------------------------- recorder

def test_recorder_writes_messages_and_markers() -> None:
    buf = io.StringIO()
    rec = fk.Recorder(buf)
    rec.message({"type": "uwb_range", "anchor": "uwb_1", "distance_m": 1.0, "seq": 1, "t": 5.0}, rx=10.0)
    rec.message(pose(11.0, 0.0)["msg"], rx=11.0)
    rec.marker("  turn \n", rx=12.0)
    rec.marker("   ", rx=13.0)  # blank: ignored
    lines = [json.loads(line) for line in buf.getvalue().splitlines()]
    assert lines[0] == {"rx": 10.0, "msg": {"type": "uwb_range", "anchor": "uwb_1", "distance_m": 1.0, "seq": 1, "t": 5.0}}
    assert lines[2] == {"rx": 12.0, "marker": "turn"}
    assert len(lines) == 3
    assert rec.counts == {"uwb_range": 1, "listener_pose": 1, "marker": 1}
    assert "listener_pose=1" in rec.summary()
    assert "1.0" not in rec.summary()  # counts only, never coordinates


def test_recorder_flushes_every_line(tmp_path) -> None:
    path = tmp_path / "a" / "b.jsonl"
    path.parent.mkdir()
    with path.open("w") as f:
        rec = fk.Recorder(f)
        rec.marker("1", rx=1.0)
        assert path.read_text().count("\n") == 1  # visible before close


def test_load_log_skips_garbage_and_sorts(tmp_path) -> None:
    p = tmp_path / "l.jsonl"
    p.write_text('{"rx": 2, "marker": "b"}\nnot json\n\n{"rx": 1, "marker": "a"}\n{"nope": 1}\n')
    assert [e["marker"] for e in fk.load_log(p)] == ["a", "b"]


async def test_record_writes_file_from_fake_bus(tmp_path, monkeypatch) -> None:
    from earmark_hub.client import BusClient

    class Fake:
        def __aiter__(self):
            return self

        def __init__(self) -> None:
            self.items = [UwbRange(anchor="uwb_2", distance_m=1.5, seq=3, t=1.0)]

        async def __anext__(self):
            if self.items:
                return self.items.pop()
            await asyncio.sleep(3600)

    seen: dict = {}

    async def fake_connect(component, subscribe=None, url=None, timeout=3.0):
        seen["subscribe"] = subscribe
        return Fake()

    monkeypatch.setattr(BusClient, "connect", fake_connect)
    out = tmp_path / "deep" / "dir" / "s.jsonl"
    stop = asyncio.Event()
    task = asyncio.create_task(fk.record(out, None, list(fk.DEFAULT_TYPES), stdin=False, stop=stop))
    for _ in range(50):
        await asyncio.sleep(0.02)
        if out.exists() and out.read_text():
            break
    stop.set()
    assert await task == 0
    entry = json.loads(out.read_text().splitlines()[0])
    assert entry["msg"]["type"] == "uwb_range" and entry["msg"]["anchor"] == "uwb_2"
    assert "listener_pose" in seen["subscribe"] and "tap_position" in seen["subscribe"]


# ---------------------------------------------------------------- ranging

def ranging_log(biases: dict[float, float], rate: float = 10.0, skip: float = 0.0) -> list[dict]:
    log: list[dict] = []
    t = 100.0
    for d, b in biases.items():
        log.append(mark(t, f"{d:g}"))
        n = int(2.0 * rate)
        for i in range(n):
            if skip and i % int(1 / skip) == 0:
                continue
            log.append(rng(t + 0.01 + i / rate, d + b))
        log.append(rng(t + 5.0, 99.0))  # outside the window
        t += 10.0
    return log


def test_ranging_pass_and_offset() -> None:
    res = fk.analyze_ranging(ranging_log({0.5: 0.02, 1: 0.03, 2: 0.04, 3: 0.03}), "uwb_1", [0.5, 1, 2, 3])
    assert res.passed
    assert [r.n for r in res.rows] == [20] * 4
    assert res.rows[0].mean == pytest.approx(0.52)
    assert res.rows[0].dropout == pytest.approx(0.0, abs=0.06)
    assert res.offset == pytest.approx(0.03)
    assert res.consistent
    assert "PASS" in fk.render_ranging(res, "uwb_1", 0.10)


def test_ranging_fail_and_inconsistent() -> None:
    res = fk.analyze_ranging(ranging_log({0.5: 0.0, 1: 0.0, 2: 0.0, 3: 0.15}), "uwb_1", [0.5, 1, 2, 3])
    assert not res.passed
    assert [r.passed for r in res.rows] == [True, True, True, False]
    assert not res.consistent


def test_ranging_no_data_in_window() -> None:
    log = [mark(1.0, "0.5"), rng(10.0, 0.5)]
    res = fk.analyze_ranging(log, "uwb_1", [0.5, 1])
    assert not res.passed
    assert res.rows[0].n == 0 and res.rows[0].mean is None
    assert res.offset is None and res.consistent is None
    assert "no data" in fk.render_ranging(res, "uwb_1", 0.1)


def test_ranging_ignores_other_anchor_and_text_markers() -> None:
    log = [mark(1.0, "turn"), mark(2.0, "1")] + [rng(2.1 + i * 0.1, 1.0, anchor="uwb_2") for i in range(5)]
    log += [rng(2.1 + i * 0.1, 1.0) for i in range(5)]
    res = fk.analyze_ranging(log, "uwb_1", [1])
    assert res.rows[0].n == 5 and res.passed


def test_ranging_dropout_rate() -> None:
    res = fk.analyze_ranging(ranging_log({1: 0.0}, skip=0.25), "uwb_1", [1])
    assert res.rows[0].dropout == pytest.approx(0.25, abs=0.07)


# ---------------------------------------------------------------- tracking

PATH = [(0.0, 0.0), (4.0, 0.0)]


def test_dist_to_polyline() -> None:
    assert fk.dist_to_polyline((2.0, 0.3), PATH) == pytest.approx(0.3)
    assert fk.dist_to_polyline((-1.0, 0.0), PATH) == pytest.approx(1.0)  # clamps to the end point
    assert fk.dist_to_polyline((1.0, 1.0), [(0.0, 0.0)]) == pytest.approx(2 ** 0.5)
    assert fk.parse_points("0,0; 1,2.5;") == [(0.0, 0.0), (1.0, 2.5)]


def test_track_pass() -> None:
    log = walk(0.0, 4.0, noise=0.05)
    res = fk.analyze_track(log, PATH)
    assert res.passed, res.checks
    assert res.median_err == pytest.approx(0.05)
    assert res.rate_hz == pytest.approx(10.0)
    assert res.max_jump < 0.3 and res.lost_durations == [] and res.fixed_count == 0
    assert "PASS" in fk.render_track(res, fk.TrackLimits())


def test_track_jump_over_limit() -> None:
    log = walk(0.0, 4.0)
    log[20]["msg"]["position"][0] += 0.5
    res = fk.analyze_track(log, PATH)
    assert res.max_jump > 0.3 and not res.checks["max jump"]
    assert not res.passed


def test_track_error_thresholds() -> None:
    log = walk(0.0, 4.0, noise=0.2)
    res = fk.analyze_track(log, PATH)
    assert not res.checks["median error"]
    relaxed = fk.analyze_track(log, PATH, limits=fk.TrackLimits(median_m=0.25, p95_m=0.25, jump_m=1.0))
    assert relaxed.checks["median error"] and relaxed.checks["p95 error"]


def test_track_single_lost_episode() -> None:
    log = walk(0.0, 4.0)
    for e in log[10:15]:
        e["msg"]["mode"] = "lost"
        e["msg"]["quality"] = "lost"
    res = fk.analyze_track(log, PATH)
    assert len(res.lost_durations) == 1
    assert res.lost_durations[0] == pytest.approx(0.5)
    assert res.checks["lost episodes"]
    long = fk.analyze_track(log, PATH, limits=fk.TrackLimits(lost_s=0.4))
    assert not long.checks["lost episodes"]
    for e in log[30:32]:
        e["msg"]["mode"] = "lost"
    assert not fk.analyze_track(log, PATH).checks["lost episodes"]  # two episodes


def test_track_lost_run_at_end_is_counted() -> None:
    log = walk(0.0, 1.0)
    log[-1]["msg"]["mode"] = "lost"
    log[-2]["msg"]["mode"] = "lost"
    assert fk.analyze_track(log, PATH).lost_durations == [pytest.approx(0.1)]


def test_track_rate_too_low() -> None:
    res = fk.analyze_track(walk(0.0, 4.0, hz=5.0), PATH)
    assert res.rate_hz == pytest.approx(5.0) and not res.checks["pose rate"]


def hold_log(fixed_at: int | None = None, drift: float = 0.0) -> list[dict]:
    log = [mark(0.0, "go")] + walk(0.1, 2.0)
    log.append(mark(2.05, "turn"))
    x0 = 1.5
    for i in range(50):
        log.append(pose(2.1 + i * 0.1, x0 + drift * i, mode="frozen"))
    if fixed_at is not None:
        log[-50 + fixed_at]["msg"]["mode"] = "fixed"
        log[-50 + fixed_at]["msg"]["position"] = [0.0, 0.0, 1.0]
    log.append(mark(7.15, "back"))
    return log


def test_track_hold_ok_and_markers() -> None:
    log = hold_log()
    t0 = fk.marker_time(log, "turn")
    t1 = fk.marker_time(log, "back", after=t0)
    res = fk.analyze_track(log, [(0.0, 0.0), (4.0, 0.0)], hold=(t0, t1))
    assert res.hold_displacement == pytest.approx(0.0) and res.hold_fixed == 0
    assert res.checks["hold"]


def test_track_hold_broken_by_fixed_pose() -> None:
    log = hold_log(fixed_at=20)
    res = fk.analyze_track(log, PATH, hold=(2.05, 7.15))
    assert res.hold_fixed == 1 and res.fixed_count == 1
    assert not res.checks["hold"]


def test_track_hold_drift() -> None:
    res = fk.analyze_track(hold_log(drift=0.01), PATH, hold=(2.05, 7.15))
    assert res.hold_displacement == pytest.approx(0.49) and not res.checks["hold"]


def test_track_time_span_limits_poses() -> None:
    log = [mark(5.0, "start")] + walk(0.0, 4.0) + [pose(5.5, 40.0)]  # outlier outside the span
    res = fk.analyze_track(log, PATH, t0=0.0, t1=4.0)
    assert res.n_poses == 41 and res.passed


def test_track_fixed_not_counted_as_jump_and_empty_log() -> None:
    log = walk(0.0, 2.0)
    log[5]["msg"]["mode"] = "fixed"
    log[5]["msg"]["position"] = [0.0, 0.0, 0.0]
    assert fk.analyze_track(log, PATH).max_jump < 0.3
    empty = fk.analyze_track([], PATH)
    assert empty.median_err is None and not empty.passed


def test_marker_time_missing() -> None:
    with pytest.raises(ValueError):
        fk.marker_time([mark(1.0, "a")], "zzz")
    assert fk.marker_time([], None) is None


# ---------------------------------------------------------------- taps

def test_taps_pass_fail_and_not_ok() -> None:
    spots = [(1.0, 1.0), (2.0, 2.0)]
    log = [tap(1.0, 1.05, 1.0), tap(2.0, 2.0, 2.3), tap(3.0, None, ok=False)]
    res = fk.analyze_taps(log, spots)
    assert [r.spot for r in res.rows] == [1, 2]
    assert [r.passed for r in res.rows] == [True, False]
    assert res.rows[1].error == pytest.approx(0.3)
    assert res.not_ok == 1 and not res.passed
    assert "ok=false: 1" in fk.render_taps(res, 0.1)


def test_taps_all_pass_and_none() -> None:
    assert fk.analyze_taps([tap(1.0, 1.0, 1.0)], [(1.0, 1.0)]).passed
    assert not fk.analyze_taps([], [(1.0, 1.0)]).passed


# ---------------------------------------------------------------- latency

def test_latency() -> None:
    log = [pose(0.5, 0.0), rng(1.0, 1.0), pose(1.05, 0.0), rng(1.1, 1.0), rng(1.2, 1.0), pose(1.3, 0.0)]
    res = fk.analyze_latency(log)  # the pose before any range is skipped
    assert res.n == 2
    assert res.median_ms == pytest.approx(75.0)
    assert res.max_ms == pytest.approx(100.0)
    assert res.p95_ms == pytest.approx(97.5)


def test_latency_no_data() -> None:
    res = fk.analyze_latency([pose(1.0, 0.0)])
    assert res.n == 0 and res.median_ms is None
    assert "n/a" in fk.render_latency(res)


# ---------------------------------------------------------------- CLI

def write_log(path, entries) -> None:
    path.write_text("".join(json.dumps(e) + "\n" for e in entries))


def test_cli_exit_codes(tmp_path, capsys) -> None:
    log = tmp_path / "s.jsonl"
    write_log(log, ranging_log({0.5: 0.0, 1: 0.0}))
    assert fk.main(["ranging", str(log), "--anchor", "uwb_1", "--truth", "0.5,1"]) == 0
    assert fk.main(["ranging", str(log), "--anchor", "uwb_1", "--truth", "0.5,1,2"]) == 1
    assert "| truth m |" in capsys.readouterr().out

    track = tmp_path / "t.jsonl"
    write_log(track, [mark(0.0, "go")] + walk(0.1, 4.0) + [mark(5.0, "end")])
    assert fk.main(["track", str(track), "--path", "0,0;4,0", "--from", "go", "--to", "end"]) == 0
    assert fk.main(["track", str(track), "--path", "0,5;4,5"]) == 1
    assert fk.main(["track", str(track), "--path", "0,0;4,0", "--from", "nope"]) == 2

    taps = tmp_path / "k.jsonl"
    write_log(taps, [tap(1.0, 1.0, 1.0)])
    assert fk.main(["taps", str(taps), "--spots", "1,1"]) == 0
    assert fk.main(["taps", str(taps), "--spots", "2,2"]) == 1
    assert fk.main(["latency", str(taps)]) == 0
