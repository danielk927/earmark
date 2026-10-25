"""Cartesia Sonic streaming TTS over one shared WebSocket (docs/sponsors/vendor-notes/cartesia.md, section 4).

The whole sentence is sent in one generation request with continue=false and
max_buffer_delay_ms=0 (our text is complete before TTS). Chunks are routed by
context_id; their base64 `data` goes straight into speak.chunk_b64.
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from collections.abc import AsyncIterator

from websockets.asyncio.client import ClientConnection, connect
from websockets.exceptions import ConnectionClosed

from .config import Settings

log = logging.getLogger(__name__)


class TtsError(Exception):
    pass


def _close_code(e: ConnectionClosed) -> int | None:
    return e.rcvd.code if e.rcvd is not None else None


class SonicTts:
    STABLE_S = 30.0       # a socket that lived this long reopens at once; shorter-lived ones back off
    MAX_BACKOFF_S = 60.0

    def __init__(self, settings: Settings) -> None:
        self.s = settings
        self._ws: ClientConnection | None = None
        self._reader: asyncio.Task | None = None
        self._queues: dict[str, asyncio.Queue] = {}
        self._lock = asyncio.Lock()
        self._keep_warm = False
        self._closed = False
        self._warmer: asyncio.Task | None = None
        self._opened_at = 0.0
        self._backoff = 0.0

    @property
    def output_format(self) -> dict:
        return {"container": "raw", "encoding": self.s.tts_encoding, "sample_rate": self.s.tts_sample_rate}

    async def _ensure(self) -> ClientConnection:
        async with self._lock:
            if self._ws is not None and self._reader is not None and not self._reader.done():
                return self._ws
            url = f"{self.s.tts_url}?cartesia_version={self.s.cartesia_version}"
            headers = {"Authorization": f"Bearer {self.s.cartesia_api_key}",
                       "Cartesia-Version": self.s.cartesia_version}
            self._ws = await connect(url, additional_headers=headers, open_timeout=None, max_size=None)
            self._opened_at = time.monotonic()
            self._reader = asyncio.create_task(self._read(self._ws))
            return self._ws

    def warm(self) -> None:
        """Keep a socket open: connect now, and reconnect whenever Cartesia closes it (idle TTS sockets close
        after 5 minutes). A cold connect takes most of the first-chunk budget, and missing it means the
        system voice."""
        self._keep_warm = True
        if not self._closed and (self._warmer is None or self._warmer.done()):
            self._warmer = asyncio.create_task(self._warm())

    async def _warm(self) -> None:
        while not self._closed:
            if self._backoff:
                await asyncio.sleep(self._backoff)
            try:
                await self._ensure()
                return
            except Exception as e:
                self._backoff = min(max(1.0, self._backoff * 2), self.MAX_BACKOFF_S)
                log.warning("tts connect failed (%s); retrying in %.0f s", type(e).__name__, self._backoff)

    async def _read(self, ws: ClientConnection) -> None:
        err: Exception = TtsError("tts socket closed")
        try:
            async for raw in ws:
                if isinstance(raw, bytes):
                    continue
                msg = json.loads(raw)
                q = self._queues.get(msg.get("context_id", ""))
                if q is not None:
                    q.put_nowait(msg)
        except ConnectionClosed as e:
            err = TtsError(f"tts socket closed ({_close_code(e)})")
        except Exception as e:
            err = TtsError(f"tts reader failed ({type(e).__name__})")
        finally:
            if self._ws is ws:
                self._ws = None
            for q in self._queues.values():
                q.put_nowait(err)
            if self._keep_warm and not self._closed:
                lived = time.monotonic() - self._opened_at
                self._backoff = 0.0 if lived >= self.STABLE_S else min(max(1.0, self._backoff * 2), self.MAX_BACKOFF_S)
                log.info("%s after %.0f s; reopening in %.0f s", err, lived, self._backoff)
                self.warm()

    async def stream(self, text: str, context_id: str) -> AsyncIterator[str]:
        """Yield base64 audio chunks. Raises TtsError."""
        try:
            ws = await self._ensure()
        except Exception as e:
            raise TtsError(f"tts connect failed ({type(e).__name__})") from e
        q: asyncio.Queue = asyncio.Queue()
        self._queues[context_id] = q
        try:
            await ws.send(json.dumps({
                "model_id": self.s.tts_model,
                "transcript": text,
                "voice": self.s.voice_id,
                "language": "en",
                "context_id": context_id,
                "output_format": self.output_format,
                "continue": False,
                "max_buffer_delay_ms": 0,
            }))
            while True:
                msg = await q.get()
                if isinstance(msg, Exception):
                    raise msg
                typ = msg.get("type")
                if typ == "chunk" and msg.get("data"):
                    yield msg["data"]
                elif typ == "error":
                    raise TtsError(f"tts error {msg.get('status_code')} {msg.get('error_code') or msg.get('title')}")
                elif typ == "done" or (msg.get("done") is True and typ != "chunk"):
                    return
        except ConnectionClosed as e:
            raise TtsError(f"tts socket closed ({_close_code(e)})") from e
        finally:
            self._queues.pop(context_id, None)

    async def cancel(self, context_id: str) -> None:
        ws = self._ws
        if ws is not None:
            try:
                await ws.send(json.dumps({"context_id": context_id, "cancel": True}))
            except Exception:
                pass

    async def close(self) -> None:
        self._closed = True
        if self._warmer is not None:
            self._warmer.cancel()
        if self._ws is not None:
            await self._ws.close()
