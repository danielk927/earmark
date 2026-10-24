"""NFC serial adapter: line parsing, events, error status, raw log, reconnect. No real ports."""
from __future__ import annotations

import asyncio

import pytest

from earmark_hub.adapters.nfc_serial import NfcSerialAdapter, SerialLine, find_port, parse_line
from earmark_hub.clock import SystemClock
from earmark_hub.config import NfcCfg


@pytest.mark.parametrize("line,expected", [
    ("SPOT 3 TAG 04A1B2C3D4E502", SerialLine(3, "tag", tag="04A1B2C3D4E502")),
    ("spot 3 tag 04a1b2c3d4e502\r", SerialLine(3, "tag", tag="04A1B2C3D4E502")),
    ("SPOT 1 TAG 04:A1:B2:C3", SerialLine(1, "tag", tag="04A1B2C3")),
    ("SPOT 2 EMPTY", SerialLine(2, "empty")),
    ("  SPOT 12   EMPTY  ", SerialLine(12, "empty")),
    ("SPOT 4 ERROR no reader on CS 4", SerialLine(4, "error", reason="no reader on CS 4")),
    ("SPOT 4 ERROR", SerialLine(4, "error", reason="unspecified")),
])
def test_parse_valid_lines(line, expected):
    assert parse_line(line) == expected


@pytest.mark.parametrize("line", ["", "ets Jun  8 2016 boot", "SPOT x EMPTY", "SPOT 3 TAG", "SPOT 3 TAG zz",
                                  "SPOT 3 FULL", "TAG 04A1"])
def test_parse_ignores_other_lines(line):
    assert parse_line(line) is None


def test_find_port_uses_globs_in_order(tmp_path):
    (tmp_path / "cu.usbmodem2").touch()
    (tmp_path / "cu.usbserial-1").touch()
    globs = [str(tmp_path / "cu.usbserial*"), str(tmp_path / "cu.usbmodem*")]
    assert find_port(globs) == str(tmp_path / "cu.usbserial-1")
    assert find_port([str(tmp_path / "cu.nothing*")]) is None


class FakeSerial:
    def __init__(self, lines, fail_after=True):
        self.lines = list(lines)
        self.fail_after = fail_after
        self.closed = False

    def readline(self):
        if self.lines:
            return self.lines.pop(0)
        if self.fail_after:
            raise OSError("device disconnected")
        return b""

    def close(self):
        self.closed = True


class Ctx:
    def __init__(self):
        self.statuses, self.published = [], []

    def adapter_status(self, name, ok, detail):
        self.statuses.append((ok, detail))

    async def publish(self, msg, origin):
        self.published.append(msg)


async def test_adapter_reads_lines_logs_raw_and_reconnects(tmp_path):
    opened = []
    sessions = [
        FakeSerial([b"boot banner\n", b"SPOT 3 TAG 04a1b2c3d4e502\n", b"SPOT 4 ERROR antenna\n"]),
        FakeSerial([b"SPOT 3 EMPTY\n"], fail_after=False),
    ]

    def factory(port, baud):
        opened.append((port, baud))
        return sessions[len(opened) - 1]

    cfg = NfcCfg(port_globs=["/dev/none*"], reconnect_s=0.01, baud=115200)
    adapter = NfcSerialAdapter(SystemClock(), cfg, tmp_path, serial_factory=factory,
                               port_finder=lambda globs: "/dev/cu.usbserial-TEST")
    ctx = Ctx()
    adapter.attach(ctx)
    events = []

    async def consume():
        async for ev in adapter.events():
            events.append(ev)
            if len(events) == 2:
                return

    await asyncio.wait_for(consume(), 5)
    await adapter.close()
    assert [(e.source, e.kind, e.tag, e.where.spot) for e in events] == [
        ("nfc", "seen", "04A1B2C3D4E502", 3), ("nfc", "removed", "EMPTY", 3)]
    assert opened[:2] == [("/dev/cu.usbserial-TEST", 115200)] * 2
    assert sessions[0].closed
    assert [m.detail for m in ctx.published] == ["nfc spot 4 error: antenna"]
    assert ctx.published[0].ok is False and ctx.published[0].component == "hub"
    assert any(not ok and "disconnected" in d for ok, d in ctx.statuses)
    assert any(ok and d.startswith("connected /dev/cu.usbserial-TEST") for ok, d in ctx.statuses)
    raw = (tmp_path / "serial.log").read_text()
    assert "boot banner" in raw and "SPOT 3 TAG 04a1b2c3d4e502" in raw and "SPOT 4 ERROR antenna" in raw


async def test_adapter_reports_missing_port(tmp_path):
    adapter = NfcSerialAdapter(SystemClock(), NfcCfg(reconnect_s=0.01), tmp_path,
                               serial_factory=lambda p, b: pytest.fail("must not open"),
                               port_finder=lambda globs: None)
    ctx = Ctx()
    adapter.attach(ctx)
    gen = adapter.events()
    task = asyncio.create_task(gen.__anext__())
    for _ in range(100):
        await asyncio.sleep(0.01)
        if ctx.statuses:
            break
    task.cancel()
    await adapter.close()
    assert ctx.statuses and ctx.statuses[0][0] is False and "no serial port found" in ctx.statuses[0][1]
