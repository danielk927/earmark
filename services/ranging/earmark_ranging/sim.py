"""Virtual phones: stand-ins for real iPhones so the whole service can be tested with no hardware.

Each virtual phone has its own clock (a random head start and a little drift), hears every chirp after the
time sound takes to travel, hears its own chirp almost at once, and adds room noise. The service cannot tell
them from real phones: they join over the same WebSocket and send the same audio chunks.
"""
from __future__ import annotations

import asyncio
import base64
import json
import math
import random
import time
from collections.abc import Callable
from dataclasses import dataclass

import numpy as np
from websockets.asyncio.client import connect

from .chirp import SPEED_OF_SOUND_M_S as C
from .chirp import ChirpSpec, synth_at
from .service import FS

CHUNK = 2400  # samples per message (50 ms)
Pos = tuple[float, float, float]


@dataclass
class Emission:
    t: float  # true time the sound left the speaker
    slot: int
    direction: str
    amplitude: float


class World:
    """Where each phone is, and every chirp played so far."""

    def __init__(self, positions: dict[int, Pos | Callable[[float], Pos]], speaker_to_mic_m: float = 0.03) -> None:
        self.positions, self.emissions, self.s2m = positions, [], speaker_to_mic_m

    def pos(self, slot: int, t: float) -> Pos:
        p = self.positions[slot]
        return p(t) if callable(p) else p

    def distance(self, a: int, b: int, t: float) -> float:
        return self.s2m if a == b else math.dist(self.pos(a, t), self.pos(b, t))


class VirtualPhone:
    def __init__(
        self, slot: int, world: World, spec: ChirpSpec, seed: int = 0, noise_rms: float = 0.002,
        drift_ppm: float | None = None, play_latency_s: tuple[float, float] = (0.005, 0.025),
        dropout: float = 0.0, speaker_gain: float = 1.0,
    ) -> None:
        r = random.Random(seed * 100 + slot)
        self.slot, self.world, self.spec = slot, world, spec
        self.start_count = r.randrange(0, 5_000_000)  # the phone's sample counter does not start at zero
        self.drift = (r.uniform(-40, 40) if drift_ppm is None else drift_ppm) * 1e-6
        self.noise_rms, self.play_latency, self.dropout, self.gain = noise_rms, play_latency_s, dropout, speaker_gain
        self.rng = np.random.default_rng(seed * 100 + slot)
        self.r = r
        self.t_start = time.monotonic()
        self.direction = "up"
        self.sent = 0

    def _sample_time(self, k: int) -> float:
        """True time of this phone's k-th sample since it started."""
        return self.t_start + k / (FS * (1 + self.drift))

    def _chunk(self, k0: int) -> np.ndarray:
        tt = self._sample_time(k0) + np.arange(CHUNK) / (FS * (1 + self.drift))
        out = self.rng.normal(0.0, self.noise_rms, CHUNK)
        for e in self.world.emissions:
            d = self.world.distance(e.slot, self.slot, e.t)
            arrive = e.t + d / C
            if arrive > tt[-1] or arrive + 0.02 < tt[0]:
                continue
            heard = synth_at(self.spec, e.direction, tt - arrive, e.amplitude / max(d, 0.1))
            out += heard * (self.gain if e.slot == self.slot else 1.0)
        return np.clip(out, -1.0, 1.0)

    async def run(self, url: str, stop: asyncio.Event) -> None:
        async with connect(url, max_size=None) as ws:
            await ws.send(json.dumps({"type": "join", "slot": self.slot, "name": f"virtual {self.slot}", "fs": FS}))
            cfg = json.loads(await ws.recv())
            self.direction = cfg["chirp"]["direction"]

            async def listen() -> None:
                async for raw in ws:
                    msg = json.loads(raw)
                    if msg.get("type") == "play":
                        te = time.monotonic() + self.r.uniform(*self.play_latency)
                        self.world.emissions.append(Emission(te, self.slot, self.direction, self.spec.amplitude))

            async def stream() -> None:
                k = self.start_count
                self.start_count_used = k
                n = 0
                while not stop.is_set():
                    end_true = self._sample_time(n * CHUNK + CHUNK)
                    # a beat after the chunk ends, so commands that arrived late are included
                    await asyncio.sleep(max(0.0, end_true + 0.03 - time.monotonic()))
                    if self.r.random() >= self.dropout:
                        pcm = (self._chunk(n * CHUNK) * 32767).astype("<i2").tobytes()
                        msg = {"type": "audio", "start": k + n * CHUNK, "pcm": base64.b64encode(pcm).decode()}
                        await ws.send(json.dumps(msg))
                    n += 1
                    self.sent = n

            tasks = [asyncio.create_task(listen()), asyncio.create_task(stream())]
            await stop.wait()
            for t in tasks:
                t.cancel()
