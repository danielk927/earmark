"""Cartesia Sonic streaming TTS over one shared WebSocket (docs/sponsors/vendor-notes/cartesia.md, section 4).

The whole sentence is sent in one generation request with continue=false and
max_buffer_delay_ms=0 (our text is complete before TTS). Chunks are routed by
context_id; their base64 `data` goes straight into speak.chunk_b64.
"""
from __future__ import annotations

import asyncio
import json
import logging
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
    def __init__(self, settings: Settings) -> None:
        self.s = settings
        self._ws: ClientConnection | None = None
        self._reader: asyncio.Task | None = None
        self._queues: dict[str, asyncio.Queue] = {}
        self._lock = asyncio.Lock()

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
            self._reader = asyncio.create_task(self._read(self._ws))
            return self._ws

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
        if self._ws is not None:
            await self._ws.close()
