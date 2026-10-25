"""Run the listen pipeline over a recorded session (record.py) exactly as it would have run live, offline.

Nothing here touches the network. The recording is fed in 50 ms chunks into the same ListenService that the
live `listen` command uses, calibration starts at a chosen second of the recording, and every distance comes
back with its time on the recording. Used to study a real run and to prove a change against real audio.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

import numpy as np

from .chirp import ChirpSpec
from .listen import CYCLE_S, SLOT_S, Range, known_distances, speed_of_sound
from .record import read_recording
from .service import FS, Phone
from .service_listen import ListenService

CHUNK = 2400
Pos = tuple[float, float, float]


class _ReplayService(ListenService):
    """The live service with the wall clock taken from the recording instead of from network lag."""

    def __init__(self, *a, first_index: int = 0, wall_first: float | None = None, **kw) -> None:
        super().__init__(*a, **kw)
        self.first_index, self.wall_first = first_index, wall_first

    def wall_time(self, t_rec: float) -> float | None:
        if self.wall_first is None:
            return None
        return self.wall_first + (t_rec - self.first_index / FS)


@dataclass
class ReplayResult:
    ranges: list[tuple[float, Range]] = field(default_factory=list)  # (seconds into the file, range)
    fixes: list = field(default_factory=list)
    reports: list = field(default_factory=list)
    heard: list[tuple[float, int | None, float]] = field(default_factory=list)  # (file time, beacon, snr) before tracking
    seconds: float = 0.0

    def distances(self, beacon: int, t_from: float = 0.0, t_to: float = float("inf")) -> np.ndarray:
        return np.array([r.distance_m for t, r in self.ranges if r.beacon == beacon and t_from <= t <= t_to])

    def summary(self, truth: dict[int, float] | None = None) -> list[str]:
        out = []
        for k in sorted({r.beacon for _, r in self.ranges}):
            d = self.distances(k)
            line = (f"B{k}: {len(d)} distances, median {np.median(d):.3f} m, std {np.std(d):.3f} m, "
                    f"min {d.min():.3f}, max {d.max():.3f}")
            if truth and k in truth:
                err = d - truth[k]
                within = np.mean(np.abs(err) < 0.1) * 100
                line += f"; vs {truth[k]:.2f} m: median error {np.median(err):+.3f}, within 10 cm {within:.0f}%"
            out.append(line)
        if not out:
            out.append("no distances (did calibration succeed?)")
        return out


def replay(
    path: str,
    beacons: dict[int, Pos],
    *,
    calibrate_from_s: float | None = None,
    calibration_s: float = 10.0,
    calibrate_distance: float | None = None,
    calibrate_at: Pos | None = None,
    band: tuple[float, float] | None = None,
    cycle_s: float | None = None,
    slot_s: float | None = None,
    temperature_c: float = 20.0,
    min_snr: float | None = None,
    log_path: str | None = None,
    quiet: bool = False,
    service_factory=None,
) -> ReplayResult:
    """Replay one recording. Settings left as None are read from the sidecar, then fall back to the live defaults."""
    audio, fs, meta = read_recording(path)
    if fs != FS:
        raise SystemExit(f"recording is {fs} Hz; the pipeline expects {FS}")
    band = band or (tuple(meta["band"]) if "band" in meta else (12000.0, 16000.0))
    cycle_s = cycle_s or meta.get("cycle_s", CYCLE_S)
    slot_s = slot_s or meta.get("slot_s", SLOT_S)
    min_snr = meta.get("min_snr", 4.5) if min_snr is None else min_snr
    first_index = int(meta.get("first_sample_index", 0))
    if calibrate_distance is None and calibrate_at is None:
        if "calibrate_distance" in meta and meta["calibrate_distance"] is not None:
            calibrate_distance = float(meta["calibrate_distance"])
        elif meta.get("calibrate_at"):
            calibrate_at = tuple(meta["calibrate_at"])
        elif len(beacons) == 1:
            calibrate_distance = 1.0
    if calibrate_from_s is None:
        starts = [e["rec_time_s"] for e in meta.get("events", []) if e.get("what") == "calibration_start"]
        calibrate_from_s = starts[0] if starts else 2.0
    known = known_distances(beacons, calibrate_distance, calibrate_at)
    c = speed_of_sound(temperature_c)
    factory = service_factory or _ReplayService
    svc = factory(
        beacons, known, ChirpSpec(band[0], band[1]), c=c, calibration_s=calibration_s, cycle_s=cycle_s, slot_s=slot_s,
        log_path=log_path, min_snr=min_snr, first_index=first_index, wall_first=meta.get("wall_time_first_chunk"),
    )
    res = ReplayResult(seconds=len(audio) / FS)

    def ftime(t_rec: float) -> float:
        return t_rec - first_index / FS

    def clock(t: float) -> str:
        w = svc.wall_time(t)
        return datetime.fromtimestamp(w).strftime("%H:%M:%S.%f")[:-3] if w is not None else f"{ftime(t):8.3f}s"

    def on_heard(det, beacon, wall) -> None:
        res.heard.append((ftime(det.t), beacon, det.snr))
        if not quiet and beacon is not None:
            print(f"{clock(det.t)}  B{beacon}  heard   snr {det.snr:5.1f}   ({svc.state})")

    def on_range(r, wall) -> None:
        res.ranges.append((ftime(r.t), r))
        if not quiet:
            print(f"{clock(r.t)}  B{r.beacon}  d {r.distance_m:6.3f} m  snr {r.snr:5.1f}  cycle {r.cycle}")

    def on_report(rep) -> None:
        res.reports.append(rep)
        if not quiet:
            print("\n".join(rep.lines()))

    svc.on_heard, svc.on_range, svc.on_report = on_heard, on_range, on_report
    phone = Phone(0, "recording", None)  # type: ignore[arg-type]
    svc.phones[0] = phone
    pcm_all = (np.clip(audio, -1, 1) * 32767).astype("<i2")
    started = False
    for k0 in range(0, len(pcm_all), CHUNK):
        phone.buf.write(first_index + k0, pcm_all[k0:k0 + CHUNK].astype(np.float32) / 32768.0)
        if not started and k0 / FS >= calibrate_from_s:
            svc.start_calibration()
            started = True
            if not quiet:
                print(f"--- calibration starts at {k0 / FS:.1f} s into the file, for {calibration_s:.0f} s")
        new = svc.step()
        if new and svc.tracker is not None and svc.feed.cursor_s is not None:
            got = svc.tracker.fix(svc.feed.cursor_s)
            if got is not None:
                res.fixes.append(got)
                if not quiet:
                    fix, pose = got
                    x, y, z = pose.position
                    print(f"fix  x {x:6.2f}  y {y:6.2f}  z {z:5.2f}   {pose.quality:<8} {fix.used} beacons"
                          f"   fit {fix.rms_m * 100:4.1f} cm")
    return res
