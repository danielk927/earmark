"""The listen service: the user's phone streams what it hears; nothing is ever told to play.

Same WebSocket protocol and port as the two-way service (join, then audio chunks; fixes go back), but the Mac
never sends "play". The beacons are self-timed (see listen.py) and do not connect at all.
"""
from __future__ import annotations

import asyncio
import base64
import csv
import json
import logging
import math
import time
from collections import deque
from collections.abc import Callable
from datetime import datetime

import numpy as np
from earmark_contracts import ListenerPose, StatusMsg
from websockets.asyncio.server import ServerConnection
from websockets.exceptions import ConnectionClosed

from .chirp import ChirpSpec
from .config import EAR_OFFSET_M
from .detect import Detector
from .listen import (
    CYCLE_S,
    SLOT_S,
    BeaconSchedule,
    CalibrationReport,
    Calibrator,
    ChirpFeed,
    Detection,
    Pos,
    Range,
    Tracker,
)
from .service import FS, BusPublisher, Phone, save_audio

log = logging.getLogger("earmark.ranging.listen")

OFF_WINDOW_S = 4.0  # a beacon heard at least once a second over this long, with no distance accepted, is off its schedule
OFF_MIN_HEARD = 4
ROOM_MARGIN_M = 4.0  # the listener is never farther from a beacon than the beacons' own span plus this


class RangeLog:
    """One CSV row per distance."""

    def __init__(self, path: str) -> None:
        self.f = open(path, "a", newline="")  # noqa: SIM115 - stays open for the life of the service
        self.w = csv.writer(self.f)
        if self.f.tell() == 0:
            self.w.writerow(["wall_time", "beacon", "distance_m", "snr", "cycle", "recording_time_s"])

    def write(self, wall: float | None, r: Range) -> None:
        stamp = datetime.fromtimestamp(wall).isoformat(timespec="milliseconds") if wall is not None else ""
        self.w.writerow([stamp, f"B{r.beacon}", f"{r.distance_m:.4f}", f"{r.snr:.1f}", r.cycle, f"{r.t:.6f}"])
        self.f.flush()


class ListenService:
    def __init__(
        self,
        beacons: dict[int, Pos],
        known_distance: dict[int, float],
        spec: ChirpSpec | None = None,
        c: float = 343.4,
        calibration_s: float = 10.0,
        cycle_s: float = CYCLE_S,
        slot_s: float = SLOT_S,
        publisher: BusPublisher | None = None,
        ear_offset: Pos = EAR_OFFSET_M,
        log_path: str | None = None,
        min_snr: float = 4.5,
        recorder=None,
    ) -> None:
        self.beacons, self.known, self.spec = dict(beacons), dict(known_distance), spec or ChirpSpec(12000.0, 16000.0)
        self.c, self.calibration_s, self.cycle, self.slot = c, calibration_s, cycle_s, slot_s
        self.publisher, self.ear_offset = publisher or BusPublisher(None), ear_offset
        self.detector = Detector(self.spec, FS, min_snr=min_snr)
        self.feed = ChirpFeed(self.detector, FS)
        self.phones: dict[int, Phone] = {}
        self.calibrator = Calibrator(self.known, c, calibration_s, cycle_s, slot_s, wall_time=self.wall_time)
        self.tracker: Tracker | None = None
        self.report: CalibrationReport | None = None
        self.state = "idle"  # idle (waiting to calibrate), calibrating, tracking
        self.idle_note = ""  # why we are idle, for the status line
        # A 30 ms shift of a restarted beacon reads as +10 m: farther than any room, so it is refused, not believed.
        # ponytail: one beacon has no span to go by, so it keeps the tracker's 15 m default.
        span = max(math.dist(p, q) for p in self.beacons.values() for q in self.beacons.values())
        self.d_max = span + ROOM_MARGIN_M if len(self.beacons) > 1 else 15.0
        self.off_schedule: set[int] = set()  # beacons heard but never accepted since calibration: probably restarted
        self._heard_t: dict[int, deque] = {k: deque(maxlen=50) for k in self.beacons}  # recording times, while tracking
        self.first_audio_at: float | None = None  # monotonic
        self.heard: dict[int, deque] = {k: deque(maxlen=50) for k in self.beacons}  # monotonic times, for rates
        self.ranges = 0
        self.fixes = 0
        self.log = RangeLog(log_path) if log_path else None
        self.recorder = recorder  # a record.SessionRecorder, or None
        self._start_requested = False
        # console hooks
        self.on_heard: Callable[[Detection, int | None, float | None], None] | None = None  # during idle/calibration
        self.on_range: Callable[[Range, float | None], None] | None = None
        self.on_fix: Callable[[object, ListenerPose], None] | None = None
        self.on_report: Callable[[CalibrationReport], None] | None = None
        self.on_notice: Callable[[str], None] | None = None  # something the operator must act on

    # ------------------------------------------------------------------ phones

    @property
    def target(self) -> Phone | None:
        return self.phones.get(0)

    def wall_time(self, t_rec: float) -> float | None:
        """Unix time at which the target recorded this sample time, from how late its chunks arrive (tens of ms)."""
        ph = self.target
        if ph is None or ph.lag is None:
            return None
        return t_rec + ph.lag + (time.time() - time.monotonic())

    async def handler(self, ws: ServerConnection) -> None:
        phone: Phone | None = None
        try:
            async for raw in ws:
                msg = json.loads(raw)
                kind = msg.get("type")
                if kind == "join":
                    slot = int(msg.get("slot", 0))
                    if slot == 0:
                        lost = self._phone_restarted()
                        if lost is not None:
                            await self.publisher.send(lost)  # the hub stops using the old position right now
                    phone = Phone(slot, str(msg.get("name", f"phone {slot}")), ws)
                    self.phones[slot] = phone
                    await ws.send(json.dumps({
                        "type": "config", "slot": slot, "fs": FS, "chunk_samples": 2400, "mode": "listen",
                        "chirp": {**self.spec.as_dict(), "direction": "none"},
                    }))
                    log.info("phone joined: slot %d (%s)", slot, phone.name)
                    if slot != 0:
                        log.warning("slot %d joined in listen mode; only the user's phone (slot 0) is used", slot)
                elif kind == "audio" and phone is not None:
                    pcm = base64.b64decode(msg["pcm"])
                    samples = np.frombuffer(pcm, dtype="<i2").astype(np.float32) / 32768.0
                    start = int(msg["start"])
                    phone.buf.write(start, samples)
                    if self.recorder is not None and phone.slot == 0:
                        self.recorder.write(start, pcm)
                    phone.lags.append(time.monotonic() - (start + len(samples)) / FS)
                    if phone.slot == 0 and self.first_audio_at is None:
                        self.first_audio_at = time.monotonic()
        except (ConnectionClosed, json.JSONDecodeError, KeyError, ValueError) as e:
            log.info("phone left: %s", e)
        finally:
            if phone is not None and self.phones.get(phone.slot) is phone:
                del self.phones[phone.slot]

    def _phone_restarted(self) -> ListenerPose | None:
        """The user's phone (re)joined. It stops its audio engine whenever the link drops, and its sample counter
        carries on while the seconds offline vanish from the recording, so the schedules no longer line up with
        anything. Forget all of it. Returns a "lost" pose if a position had gone out, else None.
        """
        if self.state == "idle" and self.feed.cursor is None:
            return None  # first connection (or nothing was heard yet): nothing to forget
        was = self.state
        lost = None
        if self.tracker is not None and self.tracker.last_fix is not None:
            pos = [round(self.tracker.last_fix.position[i] + self.ear_offset[i], 3) for i in range(3)]
            lost = ListenerPose(position=pos, quality="lost", beacons_heard=0, source="beacons")
        self.feed = ChirpFeed(self.detector, FS)
        self.calibrator.cancel()
        self._start_requested = False
        self.tracker, self.state, self.first_audio_at = None, "idle", None
        self.off_schedule.clear()
        for q in self._heard_t.values():
            q.clear()
        if was != "idle":
            self.idle_note = "phone reconnected: recalibrate"
            msg = ("the phone's audio restarted (it reconnected), so the calibration no longer holds. "
                   "Put it back at the calibration spot and press Enter.")
            log.warning(msg)
            if self.on_notice:
                self.on_notice(msg)
        return lost

    # ------------------------------------------------------------------ calibration control

    def start_calibration(self) -> None:
        """Begin (or redo) calibration at the next stretch of audio. The phone must be still at the known spot."""
        self._start_requested = True

    def calibration_remaining(self) -> float:
        return self.calibrator.remaining()

    # ------------------------------------------------------------------ the work

    def step(self) -> list[Range]:
        """Look at any new audio, feed the calibrator or tracker, return the new distances."""
        ph = self.target
        if ph is None:
            return []
        dets = self.feed.poll(ph.buf)
        cur = self.feed.cursor_s
        if cur is None:
            return []
        if self._start_requested:
            self._start_requested = False
            self.calibrator.start(cur)
            self.state, self.idle_note = "calibrating", ""
            self._mark("calibration_start", cur)
        out: list[Range] = []
        if self.state == "calibrating":
            for d in dets:
                self.calibrator.add(d)
                self._note_heard(d, self.calibrator.assign(d))
            self.calibrator.seen_up_to(cur)
            if self.calibrator.done():
                self.report = self.calibrator.fit()
                self._mark("calibration_done", cur, ok=self.report.ok, report=self.report.lines())
                if self.report.ok:
                    self.tracker = Tracker(
                        self.report.schedules, self.c, self.beacons, d_max=self.d_max, ear_offset=self.ear_offset)
                    self.state = "tracking"
                    self.off_schedule.clear()
                else:
                    self.state = "tracking" if self.tracker is not None else "idle"
                if self.on_report:
                    self.on_report(self.report)
        elif self.state == "tracking" and self.tracker is not None:
            out = self.tracker.add(dets, cur)
            for r in out:
                self.ranges += 1
                self.heard[r.beacon].append(time.monotonic())
                wall = self.wall_time(r.t)
                if self.log:
                    self.log.write(wall, r)
                if self.on_range:
                    self.on_range(r, wall)
            self._check_schedules(dets, cur)
        else:
            for d in dets:
                self._note_heard(d, self.calibrator.assign(d))
        return out

    def _check_schedules(self, dets: list[Detection], cur: float) -> None:
        """Flag a beacon whose chirps keep arriving but never become distances: its phone's beacon restarted and
        re-lined up with the wall clock, so its schedule moved against the calibration (30 ms is about 10 m)."""
        for d in dets:
            k = self.calibrator.assign(d)
            if k in self._heard_t:
                self._heard_t[k].append(d.t)
        for k, q in self._heard_t.items():
            while q and q[0] < cur - OFF_WINDOW_S:
                q.popleft()
            last = self.tracker.latest.get(k)
            if len(q) >= OFF_MIN_HEARD and (last is None or last.t < cur - OFF_WINDOW_S):
                if k not in self.off_schedule:
                    self.off_schedule.add(k)
                    msg = (f"B{k} is heard but off its calibrated schedule: its phone's beacon probably restarted. "
                           "Its distances are ignored; recalibrate.")
                    log.warning(msg)
                    if self.on_notice:
                        self.on_notice(msg)
            else:
                self.off_schedule.discard(k)  # distances are flowing again

    def _mark(self, what: str, cur: float, **extra) -> None:
        if self.recorder is not None and self.recorder.first is not None:
            self.recorder.mark(what, cur - self.recorder.first / FS, **extra)

    def _note_heard(self, d: Detection, beacon: int | None) -> None:
        if beacon is not None:
            self.heard[beacon].append(time.monotonic())
        if self.on_heard:
            self.on_heard(d, beacon, self.wall_time(d.t))

    async def run(self, auto_calibrate_after_s: float | None = None) -> None:
        """Forever: process new audio every 50 ms, publish fixes; optionally start calibrating on its own."""
        while True:
            await asyncio.sleep(0.05)
            if (
                auto_calibrate_after_s is not None and self.state == "idle" and self.first_audio_at is not None
                and time.monotonic() - self.first_audio_at >= auto_calibrate_after_s
            ):
                auto_calibrate_after_s = None
                self.start_calibration()
            try:
                new = self.step()
            except Exception:
                log.exception("processing failed")
                continue
            if new and self.tracker is not None and self.feed.cursor_s is not None:
                got = self.tracker.fix(self.feed.cursor_s)
                if got is not None:
                    await self._publish(*got)

    async def _publish(self, fix, pose: ListenerPose) -> None:
        self.fixes += 1
        await self.publisher.send(pose)
        ph = self.target
        if ph is not None:
            x, y, z = pose.position
            try:
                await ph.ws.send(json.dumps({"type": "fix", "x": x, "y": y, "z": z, "quality": pose.quality, "used": fix.used}))
            except ConnectionClosed:
                pass
        if self.on_fix:
            self.on_fix(fix, pose)

    # ------------------------------------------------------------------ console

    def rates(self, window_s: float = 4.0) -> dict[int, float]:
        now = time.monotonic()
        return {k: sum(1 for t in q if now - t <= window_s) / window_s for k, q in self.heard.items()}

    def status_line(self) -> str:
        rates = "  ".join(f"B{k} {r:.1f}/s" for k, r in sorted(self.rates().items()))
        idle = f"not calibrated ({self.idle_note})" if self.idle_note else "not calibrated"
        cal = {"idle": idle, "calibrating": f"calibrating, {self.calibration_remaining():.0f} s left",
               "tracking": "calibrated"}[self.state]
        ph = self.target
        lost = f"   lost audio {ph.buf.gaps} chunks" if ph is not None and ph.buf.gaps else ""
        names = ", ".join(f"B{k}" for k in sorted(self.off_schedule))
        off = f"   OFF SCHEDULE (recalibrate): {names}" if names else ""
        return (f"phones {sorted(self.phones)}   chirps heard: {rates}   {cal}   "
                f"{self.ranges} distances, {self.fixes} fixes{lost}{off}")

    def status(self) -> StatusMsg:
        return StatusMsg(component="locator", ok=self.state == "tracking" and not self.off_schedule, detail=self.status_line())

    def save_audio(self, folder: str) -> None:
        save_audio(self.phones, folder)

    @property
    def schedules(self) -> dict[int, BeaconSchedule]:
        return self.tracker.schedules if self.tracker else {}
