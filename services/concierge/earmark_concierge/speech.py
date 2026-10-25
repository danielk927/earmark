"""Speech output with a fallback chain.

1. No Mac app on the bus: run macOS `say` locally.
2. Text equal to a static phrase in config/phrases.json: speak_cached.
3. Cartesia Sonic streaming: speak chunks (text on seq 0, final=true on the last).
4. TTS unconfigured, failing, or first chunk later than tts_first_chunk_timeout_s: speak_text.

Utterances are serialized so their chunks never interleave on the bus.
"""
from __future__ import annotations

import asyncio
import json
import logging
import shutil
import time
from collections.abc import Awaitable, Callable
from pathlib import Path

from earmark_contracts import Phrases, Speak, SpeakCached, SpeakText

from .latency import LatencyLog
from .tts import SonicTts

log = logging.getLogger(__name__)
SAY_TIMEOUT_S = 20.0
TTS_RETRY_S = 30.0


def load_phrases(path: Path) -> dict[str, str]:
    """phrase_id -> text"""
    data = Phrases.model_validate(json.loads(path.read_text()))
    return {p.phrase_id: p.text for p in data.phrases}


class Speaker:
    def __init__(self, phrases: dict[str, str], tts: SonicTts | None, emit: Callable[[object], Awaitable[None]],
                 mac_app_present: Callable[[], bool], latency: LatencyLog, *,
                 first_chunk_timeout_s: float = 1.0, encoding: str = "pcm_f32le", sample_rate: int = 48000,
                 say_cmd: str = "say") -> None:
        self.phrases = phrases
        self.by_text = {t: pid for pid, t in phrases.items()}
        self.tts = tts
        self.emit = emit
        self.mac_app_present = mac_app_present
        self.latency = latency
        self.first_chunk_timeout_s = first_chunk_timeout_s
        self.encoding = encoding
        self.sample_rate = sample_rate
        self.say_cmd = say_cmd
        self.mode = "cartesia" if tts else "system"
        self.on_mode_change: Callable[[], object] | None = None
        self._tts_down_until = 0.0
        self._lock = asyncio.Lock()

    def _set_mode(self, mode: str) -> None:
        if mode != self.mode:
            self.mode = mode
            if self.on_mode_change is not None:
                self.on_mode_change()

    async def say(self, utterance_id: str, text: str | None = None, phrase_id: str | None = None,
                  turn: dict | None = None) -> str:
        """Speak one utterance. Returns the path taken: say | speak_cached | speak | speak_text."""
        if phrase_id and not text:
            text = self.phrases.get(phrase_id)
        if not text:
            return "none"
        pid = phrase_id if phrase_id in self.phrases else self.by_text.get(text)
        async with self._lock:
            t0 = time.perf_counter()
            if not self.mac_app_present():
                kind = await self._say_local(text)
                # Nothing on the bus speaks this, but the live room page shows it as a caption.
                await self.emit(SpeakText(utterance_id=utterance_id, text=text))
            elif pid:
                await self.emit(SpeakCached(phrase_id=pid, utterance_id=utterance_id, text=text))
                kind = "speak_cached"
            elif self.tts is None or time.monotonic() < self._tts_down_until:
                await self.emit(SpeakText(utterance_id=utterance_id, text=text))
                kind = "speak_text"
            else:
                kind = await self._stream(utterance_id, text, turn)
            self.latency.log("speech_out", turn=_tid(turn), utterance_id=utterance_id, kind=kind,
                             ms=round((time.perf_counter() - t0) * 1000, 1),
                             since_final_ms=_since(turn), text=text)
            return kind

    async def _stream(self, uid: str, text: str, turn: dict | None) -> str:
        assert self.tts is not None
        agen = self.tts.stream(text, uid)
        t0 = time.perf_counter()
        try:
            first = await asyncio.wait_for(agen.__anext__(), self.first_chunk_timeout_s)
        except (asyncio.TimeoutError, StopAsyncIteration, Exception) as e:
            await agen.aclose()
            await self.tts.cancel(uid)
            log.warning("tts failed before first chunk (%s); speak_text for %.0f s",
                        type(e).__name__, TTS_RETRY_S)
            # Circuit breaker: while Sonic is down, don't make every utterance wait for the timeout.
            self._tts_down_until = time.monotonic() + TTS_RETRY_S
            self._set_mode("system")
            await self.emit(SpeakText(utterance_id=uid, text=text))
            return "speak_text"
        self._set_mode("cartesia")
        self.latency.log("tts_first_chunk", turn=_tid(turn), utterance_id=uid, vendor="cartesia",
                         ms=round((time.perf_counter() - t0) * 1000, 1), since_final_ms=_since(turn))
        seq = 0
        await self.emit(self._chunk(uid, seq, first, text=text))
        try:
            async for data in agen:
                seq += 1
                await self.emit(self._chunk(uid, seq, data))
        except Exception as e:
            log.warning("tts stream broke after %d chunks (%s)", seq + 1, type(e).__name__)
        await self.emit(self._chunk(uid, seq + 1, "", final=True))
        return "speak"

    def _chunk(self, uid: str, seq: int, data: str, text: str | None = None, final: bool = False) -> Speak:
        kw = {"text": text} if text is not None else {}
        return Speak(utterance_id=uid, seq=seq, format=self.encoding, sample_rate=self.sample_rate,
                     chunk_b64=data, final=final, **kw)

    async def _say_local(self, text: str) -> str:
        exe = shutil.which(self.say_cmd.split()[0]) if self.say_cmd else None
        if exe is None:
            log.warning("no Mac app and no local `%s`; dropped speech: %s", self.say_cmd, text)
            return "dropped"
        proc = await asyncio.create_subprocess_exec(*self.say_cmd.split(), text)
        try:
            await asyncio.wait_for(proc.wait(), SAY_TIMEOUT_S)
        except asyncio.TimeoutError:
            proc.kill()
        return "say"


def _tid(turn: dict | None) -> str | None:
    return turn.get("id") if turn else None


def _since(turn: dict | None) -> float | None:
    if not turn or "t_final" not in turn:
        return None
    return round((time.time() - turn["t_final"]) * 1000, 1)
