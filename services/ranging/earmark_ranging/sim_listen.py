"""A pretend room for calibrate-then-listen: self-timed beacons and one recording phone, no hardware.

Each beacon chirps every 0.5 s of its own slightly-wrong clock, starting a little off its wall-clock slot, like
the real app does. The target's recording is made from those chirps (quieter with distance, optionally with an
echo), room noise, and the target's own clock. `VirtualTargetPhone` streams it over the WebSocket exactly like the
real app, or hands over chunks directly for tests with no network.
"""
from __future__ import annotations

import asyncio
import base64
import json
import math
import random
import time
from collections.abc import Callable

import numpy as np
from websockets.asyncio.client import connect

from .chirp import ChirpSpec, synth_at
from .listen import CYCLE_S, SLOT_S, Pos, beacon_phase, beacon_shape, speed_of_sound
from .service import FS

CHUNK = 2400  # samples per message (50 ms)


class SelfTimedWorld:
    """Where the beacons and the target are, and when every beacon chirps, in true (unix) seconds."""

    def __init__(
        self,
        beacons: dict[int, Pos],
        target: Pos | Callable[[float], Pos],
        spec: ChirpSpec,
        t0: float,
        c: float | None = None,
        cycle_s: float = CYCLE_S,
        slot_s: float = SLOT_S,
        seed: int = 0,
        align_jitter_s: float = 0.03,
        max_drift_ppm: float = 40.0,
        amplitude_at_1m: float = 0.3,
        echo: bool = False,
        offsets_s: dict[int, float] | None = None,
        drifts_ppm: dict[int, float] | None = None,
        jitter_s: float = 0.0,
    ) -> None:
        self.beacons, self.target, self.spec = dict(beacons), target, spec
        self.jitter, self.seed = jitter_s, seed  # real phones: each chirp lands a fraction of a ms early or late
        self.c = speed_of_sound() if c is None else c
        self.cycle, self.slot, self.amp, self.echo = cycle_s, slot_s, amplitude_at_1m, echo
        r = random.Random(seed)
        self.offset: dict[int, float] = {}
        self.period: dict[int, float] = {}
        self.first: dict[int, float] = {}
        for k in sorted(self.beacons):
            off = offsets_s[k] if offsets_s and k in offsets_s else r.uniform(-align_jitter_s, align_jitter_s)
            drift = drifts_ppm[k] if drifts_ppm and k in drifts_ppm else r.uniform(-max_drift_ppm, max_drift_ppm)
            self.offset[k], self.period[k] = off, cycle_s / (1 + drift * 1e-6)
            started = t0 + r.uniform(0.0, 2.0)  # each beacon was switched on at its own moment...
            grid = math.ceil((started - beacon_phase(k, slot_s)) / cycle_s) * cycle_s + beacon_phase(k, slot_s)
            self.first[k] = grid + off  # ...and lined its first chirp up with the next slot, give or take

    def target_pos(self, t: float) -> Pos:
        return self.target(t) if callable(self.target) else self.target

    def emission_time(self, beacon: int, m: int) -> float:
        return self.first[beacon] + m * self.period[beacon]

    def distance(self, beacon: int, t: float) -> float:
        return math.dist(self.target_pos(t), self.beacons[beacon])

    def emissions(self, t_a: float, t_b: float) -> list[tuple[int, int, float]]:
        """(beacon, cycle, true play time) for every chirp that could be heard between these true times."""
        out = []
        for k in self.beacons:
            m_lo = max(0, math.ceil((t_a - 0.1 - self.first[k]) / self.period[k]))
            m_hi = math.floor((t_b - self.first[k]) / self.period[k])
            out.extend((k, m, self.emission_time(k, m)) for m in range(m_lo, m_hi + 1))
        return out

    def render(self, times: np.ndarray) -> np.ndarray:
        """What a perfect microphone at the target would record at these true times (no noise)."""
        out = np.zeros(len(times))
        length = self.spec.length_ms / 1000.0
        for k, m, te in self.emissions(times[0], times[-1]):
            d = self.distance(k, te)
            late = 0.0
            if self.jitter:
                late = float(np.random.default_rng((self.seed, k, m)).normal(0.0, self.jitter))
            copies = [(te + d / self.c + late, self.amp / max(d, 0.1))]
            if self.echo:
                delay = 0.001 + 0.002 * ((m * 0.618 + k * 0.1) % 1.0)  # 1 to 3 ms later, half as loud
                copies.append((copies[0][0] + delay, copies[0][1] * 0.5))
            for arrive, amp in copies:
                i0, i1 = np.searchsorted(times, arrive), np.searchsorted(times, arrive + length, side="right")
                if i1 > i0:
                    out[i0:i1] += synth_at(self.spec, beacon_shape(k), times[i0:i1] - arrive, amp)
        return out


class VirtualTargetPhone:
    """The user's phone: records the world on its own clock and streams it like the real app (join, then audio)."""

    def __init__(
        self, world: SelfTimedWorld, t_start: float, seed: int = 0, noise_rms: float = 0.03,
        drift_ppm: float | None = None, dropout: float = 0.0, send_delay_s: float = 0.03,
    ) -> None:
        r = random.Random(seed * 7 + 1)
        self.world, self.t_start = world, t_start
        self.start_count = r.randrange(0, 5_000_000)  # the phone's sample counter does not start at zero
        self.drift = (r.uniform(-40, 40) if drift_ppm is None else drift_ppm) * 1e-6
        self.noise_rms, self.dropout, self.send_delay = noise_rms, dropout, send_delay_s
        self.rng = np.random.default_rng(seed * 7 + 1)
        self.r = r
        self.sent = 0

    def sample_time(self, k: int) -> float:
        """True time of this phone's k-th recorded sample (counting from the first one)."""
        return self.t_start + k / (FS * (1 + self.drift))

    def rec_time(self, true_t: float) -> float:
        """Where a true time lands on the recording's timeline (seconds; sample index / FS, counting from 0)."""
        return (true_t - self.t_start) * (1 + self.drift)

    def chunk(self, k0: int, n: int = CHUNK) -> np.ndarray:
        tt = self.sample_time(k0) + np.arange(n) / (FS * (1 + self.drift))
        out = self.world.render(tt) + self.rng.normal(0.0, self.noise_rms, n)
        return np.clip(out, -1.0, 1.0)

    def pcm(self, k0: int, n: int = CHUNK) -> bytes:
        return (self.chunk(k0, n) * 32767).astype("<i2").tobytes()

    async def run(self, url: str, stop: asyncio.Event, unix_minus_monotonic: float | None = None) -> None:
        """Stream live. The world's clock is unix time; chunks go out shortly after they would have been recorded."""
        shift = time.time() - time.monotonic() if unix_minus_monotonic is None else unix_minus_monotonic
        async with connect(url, max_size=None) as ws:
            await ws.send(json.dumps({"type": "join", "slot": 0, "name": "virtual target", "fs": FS}))
            await ws.recv()  # config

            async def listen() -> None:
                async for _ in ws:
                    pass  # fixes; nothing to do with them here

            async def stream() -> None:
                n = 0
                while not stop.is_set():
                    end_true = self.sample_time(n * CHUNK + CHUNK)
                    await asyncio.sleep(max(0.0, end_true + self.send_delay - shift - time.monotonic()))
                    if self.r.random() >= self.dropout:
                        pcm = base64.b64encode(self.pcm(n * CHUNK)).decode()
                        msg = {"type": "audio", "start": self.start_count + n * CHUNK, "pcm": pcm}
                        await ws.send(json.dumps(msg))
                    n += 1
                    self.sent = n

            tasks = [asyncio.create_task(listen()), asyncio.create_task(stream())]
            await stop.wait()
            for t in tasks:
                t.cancel()


def calibration_spot(beacons: dict[int, Pos], distance: float | None, at: Pos | None) -> Pos:
    """Where the pretend user stands to calibrate: the given point, or exactly `distance` from the lone beacon."""
    if at is not None:
        return at
    (k, b), = beacons.items()
    toward = np.array([0.0, 0.0, 1.25]) - np.array(b)  # from the beacon toward the middle of the room, chest height
    toward /= np.linalg.norm(toward)
    return tuple(float(v) for v in np.array(b) + (distance or 1.0) * toward)


def tour(
    marks: list[Pos], t_start: float, dwell_s: float, walk_s: float, then_walk: bool = True,
) -> tuple[Callable[[float], Pos], list[float], float]:
    """Stand on each mark for `dwell_s`, walking `walk_s` between them (the room-setup walk), then optionally pace.

    Returns the path, the true time the user arrives at each mark, and when the last stop ends.
    """
    arrivals = [t_start + j * (dwell_s + walk_s) for j in range(len(marks))]
    t_end = arrivals[-1] + dwell_s
    pace = still_then_walk(marks[0], t_end + walk_s, reach=0.8)

    def path(t: float) -> Pos:
        if t <= arrivals[0]:
            return marks[0]
        for j, ta in enumerate(arrivals):
            if t <= ta + dwell_s:
                return marks[j]
            if j + 1 < len(marks) and t < arrivals[j + 1]:
                f = (t - ta - dwell_s) / walk_s
                return tuple(a + f * (b - a) for a, b in zip(marks[j], marks[j + 1], strict=True))  # type: ignore[return-value]
        if not then_walk:
            return marks[-1]
        f = min((t - t_end) / walk_s, 1.0)  # back to the mat, then pace
        if f < 1.0:
            return tuple(a + f * (b - a) for a, b in zip(marks[-1], marks[0], strict=True))  # type: ignore[return-value]
        return pace(t)

    return path, arrivals, t_end


def still_then_walk(spot: Pos, t_move: float, speed: float = 0.5, reach: float = 1.0) -> Callable[[float], Pos]:
    """Stand at `spot` until true time `t_move`, then pace back and forth along x at `speed` m/s."""

    def path(t: float) -> Pos:
        if t <= t_move:
            return spot
        s = (t - t_move) * speed
        leg = s % (2 * reach)
        dx = leg if leg <= reach else 2 * reach - leg
        return (spot[0] + dx, spot[1], spot[2])

    return path
