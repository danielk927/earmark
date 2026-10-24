"""fake_hub tests (LOCATOR_BRIEF.md sections 7.6 and 9.3).

Drives the stdlib WebSocket server with a minimal RFC 6455 client (masked
frames like a real browser/client would send). Covers: validation of every
contract type, rejection of malformed messages, both auth modes, pose
recording, the ptt toggle broadcast, and per-turn WAV saving.
"""

import array
import base64
import hashlib
import json
import os
import socket
import struct
import time
import wave
from pathlib import Path

import pytest

from tools import fake_hub

OP_TEXT = 0x1
OP_PING = 0x9
OP_CLOSE = 0x8


def wait_for(condition, timeout: float = 5.0, message: str = "condition") -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if condition():
            return
        time.sleep(0.01)
    raise AssertionError(f"{message} not met within {timeout:.1f}s")


def ws_frame(opcode: int, payload: bytes, fin: bool = True) -> bytes:
    """A masked client frame (RFC 6455 requires client-to-server masks)."""
    mask = os.urandom(4)
    masked = bytes(b ^ mask[i % 4] for i, b in enumerate(payload))
    header = bytearray([0x80 | opcode if fin else opcode])
    n = len(payload)
    if n < 126:
        header.append(0x80 | n)
    elif n < 65536:
        header.append(0x80 | 126)
        header += struct.pack(">H", n)
    else:
        header.append(0x80 | 127)
        header += struct.pack(">Q", n)
    header += mask
    return bytes(header) + masked


class WSClient:
    """Hand-rolled WebSocket client: enough RFC 6455 for the tests."""

    def __init__(self, port: int, path: str = "/") -> None:
        self.sock = socket.create_connection(("127.0.0.1", port), timeout=5.0)
        self.sock.settimeout(5.0)
        key = base64.b64encode(os.urandom(16)).decode()
        self.sock.sendall((
            f"GET {path} HTTP/1.1\r\nHost: 127.0.0.1\r\nUpgrade: websocket\r\n"
            f"Connection: Upgrade\r\nSec-WebSocket-Key: {key}\r\n"
            f"Sec-WebSocket-Version: 13\r\n\r\n"
        ).encode("latin-1"))
        raw = b""
        while b"\r\n\r\n" not in raw:
            chunk = self.sock.recv(4096)
            if not chunk:
                raise ConnectionError("closed during handshake")
            raw += chunk
        head = raw.split(b"\r\n\r\n", 1)[0]
        self.status_line = head.decode("latin-1").splitlines()[0]
        assert "101" in self.status_line, self.status_line
        accept = base64.b64encode(
            hashlib.sha1((key + fake_hub.WS_GUID).encode()).digest()
        ).decode()
        assert accept.encode() in head, "server Sec-WebSocket-Accept is wrong"

    def send_text(self, text: str) -> None:
        self.sock.sendall(ws_frame(OP_TEXT, text.encode("utf-8")))

    def send_json(self, message: dict) -> None:
        self.send_text(json.dumps(message))

    def send_raw(self, opcode: int, payload: bytes = b"", fin: bool = True) -> None:
        self.sock.sendall(ws_frame(opcode, payload, fin=fin))

    def _read_exact(self, n: int) -> bytes:
        chunks = []
        while n > 0:
            chunk = self.sock.recv(n)
            if not chunk:
                raise ConnectionError("connection closed")
            chunks.append(chunk)
            n -= len(chunk)
        return b"".join(chunks)

    def recv_frame(self, timeout: float = 5.0) -> tuple[int, bytes]:
        self.sock.settimeout(timeout)
        head = self._read_exact(2)
        opcode = head[0] & 0x0F
        masked = bool(head[1] & 0x80)
        n = head[1] & 0x7F
        if n == 126:
            n = struct.unpack(">H", self._read_exact(2))[0]
        elif n == 127:
            n = struct.unpack(">Q", self._read_exact(8))[0]
        payload = self._read_exact(n) if n else b""
        if masked:
            mask = self._read_exact(4)
            payload = bytes(b ^ mask[i % 4] for i, b in enumerate(payload))
        return opcode, payload

    def recv_text(self, timeout: float = 5.0) -> str:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            opcode, payload = self.recv_frame(timeout=deadline - time.monotonic())
            if opcode == OP_TEXT:
                return payload.decode("utf-8")
            if opcode == OP_CLOSE:
                raise ConnectionError("server closed")
        raise AssertionError("no text frame arrived")

    def expect_closed(self, timeout: float = 5.0) -> None:
        """The server closed the connection: a close frame, EOF, or reset."""
        try:
            opcode, _ = self.recv_frame(timeout)
        except (ConnectionError, OSError):
            return
        assert opcode == OP_CLOSE, f"expected a close frame, got opcode {opcode}"

    def close(self) -> None:
        try:
            self.send_raw(OP_CLOSE, struct.pack(">H", 1000))
        except OSError:
            pass
        self.sock.close()


def handshake_status(port: int, path: str) -> str:
    """The handshake status line without asserting (for 403 cases)."""
    sock = socket.create_connection(("127.0.0.1", port), timeout=5.0)
    sock.settimeout(5.0)
    key = base64.b64encode(os.urandom(16)).decode()
    try:
        sock.sendall((
            f"GET {path} HTTP/1.1\r\nHost: 127.0.0.1\r\nUpgrade: websocket\r\n"
            f"Connection: Upgrade\r\nSec-WebSocket-Key: {key}\r\n"
            f"Sec-WebSocket-Version: 13\r\n\r\n"
        ).encode("latin-1"))
        data = b""
        while b"\r\n\r\n" not in data:
            chunk = sock.recv(4096)
            if not chunk:
                break
            data += chunk
        return data.decode("latin-1").splitlines()[0]
    finally:
        sock.close()


def chunk_b64(samples: list[int]) -> str:
    return base64.b64encode(array.array("h", samples).tobytes()).decode()


@pytest.fixture
def hub_factory(tmp_path):
    hubs = []

    def make(**kwargs) -> fake_hub.FakeHub:
        hub = fake_hub.FakeHub(port=0, record_dir=tmp_path / "rec", **kwargs)
        hub.start()
        assert hub.port != 0
        hubs.append(hub)
        return hub

    yield make
    for hub in hubs:
        hub.shutdown()


VALID_POSE = {
    "type": "listener_pose",
    "position": [0.1, -0.2, 1.6],
    "quality": "ok",
    "beacons_heard": 5,
    "source": "beacons",
    "t": 1761350400.123,
}


def test_end_to_end_ptt_turn(hub_factory) -> None:
    hub = hub_factory()
    client = WSClient(hub.port)

    client.send_json({"type": "hello", "role": "sensor", "name": "locator"})
    wait_for(lambda: hub.counters.get("hello", 0) == 1, message="hello consumed")

    client.send_json(VALID_POSE)
    wait_for(lambda: len(hub.recorded_poses) == 1, message="pose recorded")
    assert hub.recorded_poses[0]["position"] == [0.1, -0.2, 1.6]

    client.send_json({"type": "status", "component": "locator", "ok": True, "detail": "fine"})
    wait_for(lambda: hub.counters.get("status", 0) == 1, message="status consumed")

    assert hub.toggle_ptt() is True
    assert json.loads(client.recv_text()) == {"type": "ptt", "state": "start"}
    samples = list(range(-50, 50)) * 8  # 800 samples = 1600 bytes of fake PCM
    for seq in range(3):
        client.send_json({
            "type": "mic_audio", "seq": seq, "sample_rate": 16000,
            "encoding": "pcm_s16le", "chunk_b64": chunk_b64(samples),
        })
    wait_for(lambda: hub.counters.get("mic_audio", 0) == 3, message="chunks buffered")

    assert hub.toggle_ptt() is False
    assert json.loads(client.recv_text()) == {"type": "ptt", "state": "stop"}
    wait_for(lambda: len(hub.saved_wavs) == 1, message="turn WAV saved")
    wav_path = hub.saved_wavs[0]
    assert wav_path.name == "ptt_turn_001.wav"
    with wave.open(str(wav_path), "rb") as handle:
        assert handle.getnchannels() == 1
        assert handle.getsampwidth() == 2
        assert handle.getframerate() == 16000
        assert handle.getnframes() == 3 * len(samples)
    assert hub.counters.get("valid", 0) == 5  # pose + status + 3 chunks (hello is separate)
    assert hub.counters.get("invalid", 0) == 0
    client.close()


def test_pose_recording_writes_jsonl(hub_factory, tmp_path) -> None:
    hub = hub_factory()
    client = WSClient(hub.port)
    client.send_json(VALID_POSE)
    wait_for(lambda: len(hub.recorded_poses) == 1, message="pose recorded")
    jsonl = tmp_path / "rec" / "listener_pose.jsonl"
    wait_for(
        lambda: jsonl.exists() and jsonl.read_text(encoding="utf-8").strip() != "",
        message="pose flushed to JSONL",
    )
    lines = jsonl.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 1
    assert json.loads(lines[0]) == VALID_POSE
    client.close()


def test_malformed_json_rejected_but_connection_survives(hub_factory) -> None:
    hub = hub_factory()
    client = WSClient(hub.port)
    client.send_text("this is not json {")
    wait_for(lambda: hub.counters.get("invalid", 0) == 1, message="invalid counted")
    assert "not JSON" in hub.invalid_log[0]
    assert hub.recorded_poses == []
    # The rejection case must not end the session: a valid message still lands.
    client.send_json(VALID_POSE)
    wait_for(lambda: len(hub.recorded_poses) == 1, message="connection still usable")
    client.close()


def test_schema_violations_rejected(hub_factory) -> None:
    hub = hub_factory()
    client = WSClient(hub.port)
    extra_field = dict(VALID_POSE, extra=1)  # contracts set additionalProperties: false
    bad_quality = dict(VALID_POSE, quality="fine")
    bad_source = dict(VALID_POSE, source="telepathy")
    unknown_type = {"type": "pose", "position": [0, 0, 1]}

    for message in (extra_field, bad_quality, bad_source, unknown_type):
        client.send_json(message)
    wait_for(lambda: hub.counters.get("invalid", 0) == 4, message="all four rejected")
    assert any("unknown message type" in line for line in hub.invalid_log)
    assert hub.counters.get("valid", 0) == 0
    assert hub.recorded_poses == []
    client.close()


def test_non_object_and_binary_rejected(hub_factory) -> None:
    hub = hub_factory()
    client = WSClient(hub.port)
    client.send_text('"a bare JSON string"')
    client.send_raw(0x2, b"\x00\x01")  # binary frame
    wait_for(lambda: hub.counters.get("invalid", 0) == 2, message="both rejected")
    assert any("not a JSON object" in line for line in hub.invalid_log)
    assert any("binary frame" in line for line in hub.invalid_log)
    client.close()


def test_query_auth_enforces_token(hub_factory) -> None:
    hub = hub_factory(token="s3cr3t", auth="query")
    good = WSClient(hub.port, "/?token=s3cr3t")
    good.send_json({"type": "hello", "role": "sensor"})
    wait_for(lambda: hub.counters.get("hello", 0) == 1, message="good token accepted")
    good.close()

    assert "403" in handshake_status(hub.port, "/?token=wrong")
    assert "403" in handshake_status(hub.port, "/")
    wait_for(lambda: hub.counters.get("rejected_handshakes", 0) == 2, message="rejects counted")
    assert hub.counters.get("connections", 0) == 1


def test_hello_auth_requires_hello_first(hub_factory) -> None:
    hub = hub_factory(token="tok", auth="hello")
    early = WSClient(hub.port)
    early.send_json(VALID_POSE)  # no hello yet
    early.expect_closed()
    wait_for(
        lambda: any("first message must be hello" in line for line in hub.invalid_log),
        message="hello-first enforced",
    )

    good = WSClient(hub.port)
    good.send_json({"type": "hello", "role": "x", "token": "tok"})
    good.send_json(VALID_POSE)
    wait_for(lambda: len(hub.recorded_poses) == 1, message="pose after hello accepted")
    good.close()

    bad = WSClient(hub.port)
    bad.send_json({"type": "hello", "role": "x", "token": "nope"})
    bad.expect_closed()
    wait_for(
        lambda: any("token mismatch" in line for line in hub.invalid_log),
        message="bad hello token rejected",
    )


def test_inbound_ptt_from_backup_button(hub_factory) -> None:
    hub = hub_factory()
    client = WSClient(hub.port)
    client.send_json({"type": "ptt", "state": "start"})
    wait_for(lambda: hub.ptt_active, message="ptt active from bus message")
    client.send_json({
        "type": "mic_audio", "seq": 0, "sample_rate": 16000,
        "encoding": "pcm_s16le", "chunk_b64": chunk_b64([100, -100] * 320),
    })
    wait_for(lambda: hub.counters.get("mic_audio", 0) == 1, message="chunk buffered")
    client.send_json({"type": "ptt", "state": "stop"})
    wait_for(lambda: len(hub.saved_wavs) == 1, message="turn saved")
    assert hub.counters.get("invalid", 0) == 0
    client.close()


def test_ptt_broadcast_reaches_every_client(hub_factory) -> None:
    hub = hub_factory()
    a = WSClient(hub.port)
    b = WSClient(hub.port)
    wait_for(lambda: len(hub._clients) == 2, message="both clients registered")
    hub.toggle_ptt()
    assert json.loads(a.recv_text()) == {"type": "ptt", "state": "start"}
    assert json.loads(b.recv_text()) == {"type": "ptt", "state": "start"}
    a.close()
    b.close()


def test_ping_gets_pong(hub_factory) -> None:
    hub = hub_factory()
    client = WSClient(hub.port)
    client.send_raw(OP_PING, b"stayin alive")
    opcode, payload = client.recv_frame()
    assert opcode == 0xA  # pong
    assert payload == b"stayin alive"
    client.close()


def test_fragmented_text_message_is_reassembled(hub_factory) -> None:
    hub = hub_factory()
    client = WSClient(hub.port)
    text = json.dumps(VALID_POSE)
    half = len(text) // 2
    client.send_raw(OP_TEXT, text[:half].encode(), fin=False)   # first fragment
    client.send_raw(0x0, text[half:].encode(), fin=True)        # continuation
    wait_for(lambda: len(hub.recorded_poses) == 1, message="fragmented pose processed")
    client.close()


def test_mic_audio_with_corrupt_base64_is_flagged(hub_factory) -> None:
    hub = hub_factory()
    client = WSClient(hub.port)
    client.send_json({"type": "ptt", "state": "start"})
    wait_for(lambda: hub.ptt_active, message="ptt active")
    client.send_json({
        "type": "mic_audio", "seq": 0, "sample_rate": 16000,
        "encoding": "pcm_s16le", "chunk_b64": "!!!not base64!!!",
    })
    wait_for(lambda: hub.counters.get("invalid", 0) == 1, message="bad base64 flagged")
    assert "chunk_b64" in hub.invalid_log[0]
    client.close()


def test_missing_contracts_dir_fails_fast(tmp_path) -> None:
    with pytest.raises(RuntimeError, match="contract schema not found"):
        fake_hub.FakeHub(contracts_dir=tmp_path / "nope")
