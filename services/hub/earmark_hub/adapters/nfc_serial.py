"""NFC spot readers over USB serial.

Firmware prints one line per poll and spot:
    SPOT <n> TAG <uid_hex>    -> detection seen
    SPOT <n> EMPTY            -> detection removed, tag "EMPTY"
    SPOT <n> ERROR <reason>   -> logged and published as a hub `status`
Anything else (boot banners, debug prints) is ignored. Raw lines go to logs/serial.log.
The port is auto-detected (or NFC_SERIAL_PORT) and re-opened when the board is unplugged.
"""
from __future__ import annotations

import asyncio
import glob
import logging
import re
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import AsyncIterator, Callable

from earmark_contracts import DetectionEvent, StatusMsg

from ..clock import Clock
from ..config import NfcCfg
from ..registry import normalize_tag
from .base import Adapter

log = logging.getLogger("earmark.hub.nfc")

_LINE = re.compile(r"^SPOT\s+(\d+)\s+(?:(TAG)\s+([0-9A-Fa-f:\-]+)|(EMPTY)|(ERROR)(?:\s+(.*))?)\s*$", re.I)


@dataclass(frozen=True)
class SerialLine:
    spot: int
    kind: str  # "tag" | "empty" | "error"
    tag: str | None = None
    reason: str | None = None


def parse_line(line: str) -> SerialLine | None:
    m = _LINE.match(line.strip())
    if not m:
        return None
    spot = int(m.group(1))
    if m.group(2):
        return SerialLine(spot, "tag", tag=normalize_tag(m.group(3)))
    if m.group(4):
        return SerialLine(spot, "empty")
    return SerialLine(spot, "error", reason=(m.group(6) or "").strip() or "unspecified")


def to_event(parsed: SerialLine, t: float) -> DetectionEvent | None:
    if parsed.kind == "tag":
        return DetectionEvent(source="nfc", tag=parsed.tag, kind="seen", where={"spot": parsed.spot},
                              precision="exact", rssi=None, t=t)
    if parsed.kind == "empty":
        return DetectionEvent(source="nfc", tag="EMPTY", kind="removed", where={"spot": parsed.spot},
                              precision="exact", rssi=None, t=t)
    return None


def find_port(globs: list[str]) -> str | None:
    for pattern in globs:
        ports = sorted(glob.glob(pattern))
        if ports:
            return ports[0]
    return None


def _open_serial(port: str, baud: int):
    import serial

    return serial.Serial(port, baudrate=baud, timeout=0.5)


class NfcSerialAdapter(Adapter):
    name = "nfc_serial"

    def __init__(self, clock: Clock, cfg: NfcCfg, log_dir: Path, *,
                 serial_factory: Callable[[str, int], object] = _open_serial,
                 port_finder: Callable[[list[str]], str | None] = find_port) -> None:
        self.clock, self.cfg = clock, cfg
        self.serial_log = log_dir / "serial.log"
        self.serial_factory, self.port_finder = serial_factory, port_finder
        self._stop = threading.Event()

    async def events(self) -> AsyncIterator[DetectionEvent]:
        loop = asyncio.get_running_loop()
        queue: asyncio.Queue = asyncio.Queue()
        self._stop.clear()
        def put(item) -> None:
            try:
                loop.call_soon_threadsafe(queue.put_nowait, item)
            except RuntimeError:  # event loop closed during shutdown
                self._stop.set()

        thread = threading.Thread(target=self._read_forever, args=(put,), name="nfc-serial", daemon=True)
        thread.start()
        self.serial_log.parent.mkdir(parents=True, exist_ok=True)
        with self.serial_log.open("a", buffering=1) as raw_log:
            try:
                while True:
                    kind, payload = await queue.get()
                    if kind == "status":
                        ok, detail = payload
                        self.ctx.adapter_status(self.name, ok, detail)
                        continue
                    t = self.clock.now()
                    raw_log.write(f"{t:.3f}\t{payload}\n")
                    parsed = parse_line(payload)
                    if parsed is None:
                        log.debug("ignored serial line", extra={"line": payload[:200]})
                    elif parsed.kind == "error":
                        log.warning("spot reader error", extra={"spot": parsed.spot, "reason": parsed.reason})
                        await self.ctx.publish(StatusMsg(component="hub", ok=False, t=t,
                                                         detail=f"nfc spot {parsed.spot} error: {parsed.reason}"), "hub")
                    else:
                        yield to_event(parsed, t)
            finally:
                self._stop.set()

    def _read_forever(self, put: Callable) -> None:
        """Blocking reader thread: find the port, read lines, reconnect on failure."""
        reported_missing = False
        while not self._stop.is_set():
            port = self.cfg.port or self.port_finder(self.cfg.port_globs)
            if port is None:
                if not reported_missing:
                    put(("status", (False, f"no serial port found ({', '.join(self.cfg.port_globs)})")))
                    reported_missing = True
                self._stop.wait(self.cfg.reconnect_s)
                continue
            reported_missing = False
            try:
                ser = self.serial_factory(port, self.cfg.baud)
            except Exception as e:  # pyserial raises SerialException (an OSError subclass) or OSError
                put(("status", (False, f"cannot open {port}: {e}")))
                self._stop.wait(self.cfg.reconnect_s)
                continue
            put(("status", (True, f"connected {port} @ {self.cfg.baud}")))
            try:
                while not self._stop.is_set():
                    raw = ser.readline()
                    if raw:
                        line = raw.decode("utf-8", errors="replace").strip()
                        if line:
                            put(("line", line))
            except Exception as e:  # unplugged: SerialException / OSError
                put(("status", (False, f"disconnected from {port}: {e}; retrying")))
            finally:
                try:
                    ser.close()
                except Exception:
                    pass
            self._stop.wait(self.cfg.reconnect_s)

    async def close(self) -> None:
        self._stop.set()
