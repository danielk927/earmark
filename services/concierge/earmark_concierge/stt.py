"""Cartesia Ink streaming STT on the turns WebSocket (docs/sponsors/vendor-notes/cartesia.md, section 3).

Credit saving: the socket opens lazily on the first mic_audio of a burst (audio
is buffered while connecting) and closes with {"type":"close"} after
stt_idle_close_s without audio. Fallback to Apple Speech (stt_mode apple) when
there is no key, the socket does not report `connected` within
stt_connect_timeout_s of the burst's first audio, no turn.* event arrives within
stt_first_event_timeout_s while audio flows, or the server errors. While on
Apple, Cartesia is probed every stt_probe_interval_s and restored when it works.
"""
from __future__ import annotations

import asyncio
import base64
import json
import logging
import time
from typing import Callable, Protocol
from urllib.parse import urlencode

from websockets.asyncio.client import connect
from websockets.exceptions import ConnectionClosed

from earmark_contracts import MicAudio

from .config import Settings

log = logging.getLogger(__name__)
MAX_KEYTERMS = 100
MAX_KEYTERM_CHARS = 1200
PREROLL_MAX_S = 3.0  # audio buffered while the socket connects
LOUD_PEAK = 500  # s16 peak that counts as sound (about -36 dBFS), not room hush


class SttListener(Protocol):
    async def on_stt_partial(self, text: str) -> None: ...
    async def on_stt_eager(self, text: str) -> None: ...
    async def on_stt_resume(self) -> None: ...
    async def on_stt_final(self, text: str) -> None: ...
    async def on_stt_engine(self, engine: str, reason: str) -> None: ...


class SttFailure(Exception):
    pass


def stt_url(settings: Settings, sample_rate: int, keyterms: list[str]) -> str:
    params = [
        ("model", settings.stt_model), ("encoding", "pcm_s16le"),
        ("sample_rate", str(sample_rate)), ("cartesia_version", settings.cartesia_version),
    ]
    total = 0
    for t in dict.fromkeys(k.strip() for k in keyterms if k.strip()):
        if len(params) - 4 >= MAX_KEYTERMS or total + len(t) > MAX_KEYTERM_CHARS:
            break
        params.append(("keyterm", t))
        total += len(t)
    return f"{settings.stt_url}?{urlencode(params)}"


def _peak(pcm: bytes) -> int:
    samples = memoryview(pcm[:len(pcm) // 2 * 2]).cast("h")
    return max(max(samples, default=0), -min(samples, default=0))


class _Burst:
    def __init__(self, sample_rate: int) -> None:
        self.sample_rate = sample_rate
        self.queue: asyncio.Queue[bytes] = asyncio.Queue()
        self.queued_bytes = 0
        self.first_loud: float | None = None
        self.first_audio = time.monotonic()
        self.last_audio = self.first_audio
        self.connected = asyncio.Event()
        self.turn_seen = asyncio.Event()
        self.turn_open = False
        self.closing = False
        self.task: asyncio.Task | None = None


class CartesiaStt:
    def __init__(self, settings: Settings, keyterms: Callable[[], list[str]]) -> None:
        self.s = settings
        self.keyterms = keyterms
        self.listener: SttListener | None = None
        self.engine = "cartesia" if settings.cartesia_enabled else "apple"
        self.reason = "cartesia configured" if settings.cartesia_enabled else "no CARTESIA_API_KEY"
        self._burst: _Burst | None = None
        self._probe_task: asyncio.Task | None = None

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.s.cartesia_api_key}",
                "Cartesia-Version": self.s.cartesia_version}

    # ------------------------------------------------------------ audio in

    async def on_mic_audio(self, msg: MicAudio) -> None:
        if self.engine != "cartesia":
            return
        try:
            pcm = base64.b64decode(msg.chunk_b64)
        except ValueError:
            return
        b = self._burst
        if b is None or b.closing:
            b = self._burst = _Burst(msg.sample_rate)
            if msg.sample_rate != self.s.stt_sample_rate:
                log.warning("mic_audio at %d Hz (expected %d); declaring %d to Cartesia",
                            msg.sample_rate, self.s.stt_sample_rate, msg.sample_rate)
            b.task = asyncio.create_task(self._run_burst(b))
        b.last_audio = time.monotonic()
        if b.first_loud is None and _peak(pcm) >= LOUD_PEAK:
            b.first_loud = b.last_audio
        if b.queued_bytes < PREROLL_MAX_S * b.sample_rate * 2:
            b.queued_bytes += len(pcm)
            b.queue.put_nowait(pcm)

    async def _run_burst(self, b: _Burst) -> None:
        url = stt_url(self.s, b.sample_rate, self.keyterms())
        try:
            async with asyncio.timeout(self.s.stt_connect_timeout_s):
                ws = await connect(url, additional_headers=self._headers(), open_timeout=None)
        except Exception as e:
            await self._fallback(f"cartesia stt connect failed ({type(e).__name__})", b)
            return
        tasks = [asyncio.create_task(c) for c in (self._read(ws, b), self._watchdog(b), self._send(ws, b))]
        reader, pending = tasks[0], set(tasks)
        try:
            while not reader.done():  # the burst ends when the server closes the socket
                done, pending = await asyncio.wait(pending, return_when=asyncio.FIRST_COMPLETED)
                for t in done:
                    if t.exception() is not None:
                        raise t.exception()
        except SttFailure as e:
            await self._fallback(str(e), b)
        except Exception as e:
            await self._fallback(f"cartesia stt error ({type(e).__name__})", b)
        finally:
            for t in tasks:
                t.cancel()
            await ws.close()
            if self._burst is b:
                self._burst = None

    async def _send(self, ws, b: _Burst) -> None:
        silence = bytes(int(b.sample_rate * 0.1) * 2)  # 100 ms of s16le zeros
        while time.monotonic() - b.last_audio < self.s.stt_idle_close_s:
            try:
                chunk = await asyncio.wait_for(b.queue.get(), 0.1)
            except asyncio.TimeoutError:
                # The server waits for audio instead of hearing silence, so pad zeros
                # while a turn is open; otherwise turn.end may never fire (cartesia.md 3.8).
                if b.turn_open and time.monotonic() - b.last_audio >= 0.2:
                    await ws.send(silence)
                continue
            b.queued_bytes -= len(chunk)
            await ws.send(chunk)
        b.closing = True
        await ws.send(json.dumps({"type": "close"}))
        await asyncio.sleep(3.0)  # let the server drain and close; then force it
        await ws.close()

    async def _watchdog(self, b: _Burst) -> None:
        connect_left = self.s.stt_connect_timeout_s - (time.monotonic() - b.first_audio)
        try:
            await asyncio.wait_for(b.connected.wait(), max(0.0, connect_left))
        except asyncio.TimeoutError:
            raise SttFailure("cartesia stt not connected within "
                             f"{self.s.stt_connect_timeout_s:g} s") from None
        # Push-to-talk streams silence while the key is held, so only sound counts: the clock
        # starts at the first loud chunk, not at the first audio.
        while not b.turn_seen.is_set():
            try:
                await asyncio.wait_for(b.turn_seen.wait(), 0.1)
            except asyncio.TimeoutError:
                now = time.monotonic()
                if now - b.last_audio >= 0.5:  # audio stopped
                    return
                if b.first_loud is not None and now - b.first_loud >= self.s.stt_first_event_timeout_s:
                    raise SttFailure("no transcript from cartesia within "
                                     f"{self.s.stt_first_event_timeout_s:g} s of speech") from None

    async def _read(self, ws, b: _Burst) -> None:
        try:
            await self._read_events(ws, b)
        except ConnectionClosed:
            if not b.closing:
                raise SttFailure("cartesia stt socket closed unexpectedly") from None
        if not b.closing:
            raise SttFailure("cartesia stt socket closed unexpectedly")

    async def _read_events(self, ws, b: _Burst) -> None:
        async for raw in ws:
            if isinstance(raw, bytes):
                continue
            ev = json.loads(raw)
            typ = ev.get("type", "")
            if typ == "connected":
                b.connected.set()
            elif typ.startswith("turn."):
                b.turn_seen.set()
                b.turn_open = typ != "turn.end"
                text = (ev.get("transcript") or "").strip()
                if self.listener is None:
                    continue
                if typ == "turn.update" and text:
                    await self.listener.on_stt_partial(text)
                elif typ == "turn.eager_end" and text:
                    await self.listener.on_stt_eager(text)
                elif typ == "turn.resume":
                    await self.listener.on_stt_resume()
                elif typ == "turn.end" and text:
                    await self.listener.on_stt_final(text)
            elif typ == "error":
                code = ev.get("error_code") or ev.get("title")
                raise SttFailure(f"cartesia stt error {ev.get('status_code')} {code}")

    # ------------------------------------------------------------ fallback and recovery

    async def _fallback(self, reason: str, b: _Burst | None = None) -> None:
        if b is not None:
            b.closing = True
        if self.engine == "apple":
            return
        log.warning("stt fallback to apple: %s", reason)
        self.engine, self.reason = "apple", reason
        if self.listener:
            await self.listener.on_stt_engine("apple", reason)
        self._start_probe()

    def _start_probe(self) -> None:
        if self.s.cartesia_enabled and (self._probe_task is None or self._probe_task.done()):
            self._probe_task = asyncio.create_task(self._probe_loop())

    async def _probe_loop(self) -> None:
        while self.engine == "apple":
            await asyncio.sleep(self.s.stt_probe_interval_s)
            if await self.probe():
                self.engine, self.reason = "cartesia", "cartesia reachable again"
                log.info("stt restored to cartesia")
                if self.listener:
                    await self.listener.on_stt_engine("cartesia", self.reason)
                return

    async def probe(self) -> bool:
        """Open a socket, wait for `connected`, close it. Sends no audio, so it costs no credits."""
        url = stt_url(self.s, self.s.stt_sample_rate, [])
        try:
            async with asyncio.timeout(max(2.0, self.s.stt_connect_timeout_s * 2)):
                async with connect(url, additional_headers=self._headers(), open_timeout=None) as ws:
                    async for raw in ws:
                        if isinstance(raw, str) and json.loads(raw).get("type") == "connected":
                            await ws.send(json.dumps({"type": "close"}))
                            return True
        except Exception as e:
            log.info("stt probe failed (%s)", type(e).__name__)
        return False

    async def close(self) -> None:
        for t in (self._probe_task, self._burst.task if self._burst else None):
            if t is not None and not t.done():
                t.cancel()
