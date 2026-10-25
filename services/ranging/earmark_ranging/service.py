"""The ranging service: phones connect, are told when to chirp, stream what they hear, and the position comes out."""
from __future__ import annotations

import asyncio
import base64
import json
import logging
import math
import statistics
import time
from collections import deque
from dataclasses import dataclass, field

import numpy as np
from earmark_contracts import Hello, ListenerPose, StatusMsg, dump
from websockets.asyncio.client import connect
from websockets.asyncio.server import ServerConnection
from websockets.exceptions import ConnectionClosed

from .chirp import ChirpSpec, direction_for_slot
from .config import EAR_OFFSET_M, HEIGHT_PRIOR
from .cycle import N_SLOTS, all_pair_distances, assign_slots, pair_distances
from .detect import Detector
from .solve import Fix, locate

log = logging.getLogger("earmark.ranging")

FS = 48000
LOST_AFTER_S = 1.5
MAX_JUMP_M = 2.0


class AudioBuffer:
    """The last few seconds a phone heard, indexed by that phone's own sample counter."""

    def __init__(self, seconds: float = 8.0) -> None:
        self.n = int(seconds * FS)
        self.data = np.zeros(self.n, dtype=np.float32)
        self.end = 0  # first sample not yet received
        self.started = False

    def write(self, start: int, samples: np.ndarray) -> None:
        if not self.started:
            self.end, self.started = start, True
        if start > self.end:  # a chunk went missing: keep the timeline honest with silence
            gap = min(start - self.end, self.n)
            self._put(start - gap, np.zeros(gap, dtype=np.float32))
        self._put(start, samples)
        self.end = max(self.end, start + len(samples))

    def _put(self, start: int, samples: np.ndarray) -> None:
        idx = (np.arange(len(samples)) + start) % self.n
        self.data[idx] = samples

    def get(self, a: int, b: int) -> np.ndarray | None:
        if a < 0 or b > self.end or b - a <= 0 or b - a > self.n or a < self.end - self.n:
            return None
        return self.data[(np.arange(a, b)) % self.n].astype(np.float64)


@dataclass
class Phone:
    slot: int
    name: str
    ws: ServerConnection
    buf: AudioBuffer = field(default_factory=AudioBuffer)
    lags: deque = field(default_factory=lambda: deque(maxlen=40))  # arrival time minus time on its own recording

    @property
    def lag(self) -> float | None:
        return statistics.median(self.lags) if self.lags else None


class BusPublisher:
    """Sends the user's position to the Earmark bus. If the bus is down, positions are dropped (never queued)."""

    def __init__(self, url: str | None) -> None:
        self.url, self.ws = url, None

    async def send(self, msg) -> None:
        if not self.url:
            return
        try:
            if self.ws is None:
                self.ws = await connect(self.url, open_timeout=1.0, max_size=None)
                await self.ws.send(dump(Hello(component="locator", subscribe=[])))
            await self.ws.send(dump(msg))
        except Exception as e:  # noqa: BLE001 - any failure means "try again at the next fix"
            log.debug("bus unavailable: %s", e)
            self.ws = None


class RangingService:
    def __init__(
        self,
        anchors: dict[int, tuple[float, float, float]],
        spec: ChirpSpec | None = None,
        gap_ms: float = 60.0,
        period_ms: float = 450.0,
        publisher: BusPublisher | None = None,
        mic_to_speaker_m: float = 0.03,
        ear_offset: tuple[float, float, float] = EAR_OFFSET_M,
    ) -> None:
        self.anchors, self.spec = anchors, spec or ChirpSpec()
        self.gap, self.period = gap_ms / 1000.0, period_ms / 1000.0
        self.publisher = publisher or BusPublisher(None)
        self.mic_to_speaker_m, self.ear_offset = mic_to_speaker_m, ear_offset
        self.detector = Detector(self.spec, FS)
        self.phones: dict[int, Phone] = {}
        self.cycle_id = 0
        self.last_fix: Fix | None = None
        self.last_fix_at: float | None = None
        self.last_distances: dict[int, float] = {}
        self.diag: dict[int, dict] = {}  # per phone: what it heard last round, for the console
        self.pairs: dict[tuple[int, int], float] = {}
        self.fixes = 0
        self._lost_sent = False
        self._outliers = 0
        self.on_fix = None  # optional callback(fix, pose message), used by tests and the console

    # ------------------------------------------------------------------ phones

    async def handler(self, ws: ServerConnection) -> None:
        phone: Phone | None = None
        try:
            async for raw in ws:
                msg = json.loads(raw)
                kind = msg.get("type")
                if kind == "join":
                    slot = int(msg["slot"])
                    if not 0 <= slot < N_SLOTS:
                        await ws.send(json.dumps({"type": "error", "detail": "slot must be 0 to 5"}))
                        continue
                    phone = Phone(slot, str(msg.get("name", f"phone {slot}")), ws)
                    self.phones[slot] = phone
                    await ws.send(json.dumps({
                        "type": "config", "slot": slot, "fs": FS, "chunk_samples": 2400,
                        "chirp": {**self.spec.as_dict(), "direction": direction_for_slot(slot)},
                    }))
                    log.info("phone joined: slot %d (%s)", slot, phone.name)
                elif kind == "audio" and phone is not None:
                    samples = np.frombuffer(base64.b64decode(msg["pcm"]), dtype="<i2").astype(np.float32) / 32768.0
                    start = int(msg["start"])
                    phone.buf.write(start, samples)
                    phone.lags.append(time.monotonic() - (start + len(samples)) / FS)
        except (ConnectionClosed, json.JSONDecodeError, KeyError, ValueError) as e:
            log.info("phone left: %s", e)
        finally:
            if phone is not None and self.phones.get(phone.slot) is phone:
                del self.phones[phone.slot]

    # ------------------------------------------------------------------ rounds

    async def run(self) -> None:
        """Forever: tell the phones to chirp in turn, then work out what they heard."""
        while True:
            t0 = time.monotonic() + 0.05
            self.cycle_id += 1
            cid = self.cycle_id
            asyncio.create_task(self._play_round(cid, t0))
            asyncio.create_task(self._process_later(cid, t0))
            await asyncio.sleep(self.period)
            await self._check_lost()

    async def _play_round(self, cid: int, t0: float) -> None:
        for slot in range(N_SLOTS):
            await asyncio.sleep(max(0.0, t0 + slot * self.gap - time.monotonic()))
            ph = self.phones.get(slot)
            if ph is not None:
                try:
                    await ph.ws.send(json.dumps({"type": "play", "cycle": cid}))
                except ConnectionClosed:
                    pass

    async def _process_later(self, cid: int, t0: float) -> None:
        await asyncio.sleep(max(0.0, t0 + N_SLOTS * self.gap + 0.55 - time.monotonic()))
        try:
            await self.process_cycle(t0)
        except Exception:
            log.exception("round %d failed", cid)

    def hear(self, t0: float) -> dict[int, dict[int, float]]:
        """For every phone: slot -> when it heard that slot's chirp, on its own recording."""
        heard: dict[int, dict[int, float]] = {}
        for slot, ph in list(self.phones.items()):
            lag = ph.lag
            if lag is None:
                continue
            expected = t0 + slot * self.gap - lag + 0.06  # when its own chirp should land on its recording
            a = int((expected - slot * self.gap - 0.15) * FS)  # from just before the first slot...
            b = int((expected + (N_SLOTS - slot) * self.gap + 0.20) * FS)  # ...to just after the last
            audio = ph.buf.get(a, b)
            if audio is None:
                continue
            events = [type(e)(a / FS + e.t, e.shape, e.score, e.snr) for e in self.detector.find(audio)]
            near = [e for e in events if abs(e.t - expected) <= 0.2]
            slots = assign_slots(events, slot, self.gap, own_pool=near)
            self.diag[slot] = {
                "own": round(max((e.score for e in near), default=0.0)), "heard": sorted(slots) if slot in slots else [],
                "chirps": len(events),
            }
            if slot in slots:
                heard[slot] = slots
        return heard

    async def process_cycle(self, t0: float) -> Fix | None:
        heard = self.hear(t0)
        dists = pair_distances(heard, 0, self.mic_to_speaker_m)
        self.last_distances = dists
        self.pairs = all_pair_distances(heard, self.mic_to_speaker_m)
        names = {f"B{s}": p for s, p in self.anchors.items()}
        fix = locate(
            names, {f"B{s}": d for s, d in dists.items()},
            start=self.last_fix.position if self.last_fix else None, z_prior=HEIGHT_PRIOR,
        )
        now = time.monotonic()
        if fix is None:
            return None
        if self.last_fix is not None and self.last_fix_at is not None and now - self.last_fix_at < 1.5:
            jump = math.dist(fix.position, self.last_fix.position)
            if jump > MAX_JUMP_M and self._outliers < 1:
                self._outliers += 1  # one wild fix is ignored; two in a row means the user really moved
                return None
        self._outliers = 0
        self.last_fix, self.last_fix_at, self._lost_sent = fix, now, False
        self.fixes += 1
        pos = [round(fix.position[i] + self.ear_offset[i], 3) for i in range(3)]
        quality = "ok" if fix.used >= 3 and fix.rms_m <= 0.10 else "degraded"
        pose = ListenerPose(position=pos, quality=quality, beacons_heard=fix.used, source="beacons")
        await self.publisher.send(pose)
        listener = self.phones.get(0)
        if listener is not None:
            try:
                await listener.ws.send(json.dumps({
                    "type": "fix", "x": pos[0], "y": pos[1], "z": pos[2], "quality": quality, "used": fix.used,
                }))
            except ConnectionClosed:
                pass
        if self.on_fix:
            self.on_fix(fix, pose)
        return fix

    async def _check_lost(self) -> None:
        if self.last_fix is None or self.last_fix_at is None or self._lost_sent:
            return
        if time.monotonic() - self.last_fix_at > LOST_AFTER_S:
            self._lost_sent = True
            pos = [round(self.last_fix.position[i] + self.ear_offset[i], 3) for i in range(3)]
            await self.publisher.send(ListenerPose(position=pos, quality="lost", beacons_heard=0, source="beacons"))

    def save_audio(self, folder: str) -> None:
        """Write what each phone heard recently, so it can be opened in any audio tool or run through the band test."""
        import os
        import wave

        os.makedirs(folder, exist_ok=True)
        for slot, ph in self.phones.items():
            audio = ph.buf.get(max(ph.buf.end - 6 * FS, 0), ph.buf.end) if ph.buf.started else None
            if audio is None:
                continue
            with wave.open(os.path.join(folder, f"phone{slot}.wav"), "wb") as w:
                w.setnchannels(1)
                w.setsampwidth(2)
                w.setframerate(FS)
                w.writeframes((np.clip(audio, -1, 1) * 32767).astype("<i2").tobytes())

    def status(self) -> StatusMsg:
        have = sorted(self.phones)
        return StatusMsg(
            component="locator", ok=self.last_fix is not None and not self._lost_sent,
            detail=f"phones {have}, {self.fixes} fixes",
        )
