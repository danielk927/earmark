"""Bring-up stand-in for the teammate's hub (LOCATOR_BRIEF.md section 7.6).

A WebSocket server on ws://0.0.0.0:8765 that lets the locator (and the
bring-up checklists) be exercised end-to-end before the real hub speaks
the locator's protocol. It validates EVERY inbound message against the
contracts/ JSON schemas, records listener_pose to JSONL, broadcasts ptt
on the keyboard toggle, and saves each push-to-talk turn's mic_audio to a
WAV for a listening check.

Verified hub facts (teammate's live source, mirrored in
docs/CONTRACT_NOTES.md facts 1-3 -- restate, do not guess):

- The real hub is an aiohttp server; its WebSocket route is
  ws://<mac-ip>:8765/ws and the operator dashboard sits at /.
- It has NO token auth: a hello message sets the client role from
  msg.get("role", "unknown"), accepted as any string. The locator sends
  {"type": "hello", "role": "sensor", "name": "locator"} and connects.
- It has NO listener_pose / mic_audio / ptt / status handlers yet:
  unknown message types fall through to a debug log and are ignored.

This tool therefore supports BOTH auth modes of brief section 2.3 --
``--auth query`` (the default; enforce ``?token=<token>`` when --token is
set) and ``--auth hello`` (the first message must be a hello; its token
must match --token when one is set) -- so the negotiation is ready either
way. ``--auth none`` (or leaving --token empty) reproduces today's hub:
no checks, hello roles accepted as any string. A hello is consumed and
logged in every mode, never validated as a bus payload.

A message that fails schema validation is printed as INVALID with the
reason and counted, and is NOT recorded -- but the connection stays up:
this is an instrument, and one bad message should not end a session.

The WebSocket implementation is stdlib-only (socket + hashlib + base64):
RFC 6455 handshake, masked client frames, text frames, ping/pong, close,
and text fragmentation. No third-party server dependency, matching the
tools' stdlib + jsonschema envelope.

Keyboard (POSIX TTY only): p toggles ptt start/stop, q quits. Without a
TTY the server just runs until Ctrl-C.

Python 3.11+, stdlib + jsonschema.

Usage: python3 tools/fake_hub.py [--port 8765] [--auth none|query|hello]
       [--token TOKEN] [--record out/fake_hub] [--contracts ../contracts]
"""

from __future__ import annotations

import argparse
import base64
import binascii
import hashlib
import json
import socket
import struct
import sys
import threading
import wave
from pathlib import Path
from typing import Any, Sequence
from urllib.parse import parse_qs, urlsplit

from jsonschema.validators import validator_for

if __package__ in (None, ""):  # pragma: no cover - exercised via script runs
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

LOCATOR_ROOT = Path(__file__).resolve().parents[1]
#: Contract message types the locator may send to the hub (brief 2.3-2.4).
CONTRACT_TYPES = ("listener_pose", "mic_audio", "ptt", "status")
WS_GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"
MAX_HTTP_HEADER_BYTES = 16384
MAX_FRAME_BYTES = 16 * 1024 * 1024
OP_TEXT = 0x1
OP_BINARY = 0x2
OP_CLOSE = 0x8
OP_PING = 0x9
OP_PONG = 0xA

AUTH_MODES = ("none", "query", "hello")


class WSClosed(ConnectionError):
    """The peer closed the connection (or the transport died)."""


class _Connection:
    """One accepted WebSocket client: framing plus a send lock."""

    def __init__(self, sock: socket.socket, addr: str) -> None:
        self.sock = sock
        self.addr = addr
        self.send_lock = threading.Lock()
        self.greeted = False  # hello auth mode: set by the first hello message
        self._handshake_key: str | None = None

    def accept(self) -> None:
        """Complete the upgrade: send the 101 only after auth has passed."""
        if self._handshake_key is None:
            raise RuntimeError("accept() called before the handshake")
        accept = base64.b64encode(
            hashlib.sha1((self._handshake_key + WS_GUID).encode()).digest()
        ).decode()
        self.sock.sendall((
            "HTTP/1.1 101 Switching Protocols\r\n"
            "Upgrade: websocket\r\nConnection: Upgrade\r\n"
            f"Sec-WebSocket-Accept: {accept}\r\n\r\n"
        ).encode("latin-1"))

    def read_exact(self, n_bytes: int) -> bytes:
        chunks: list[bytes] = []
        remaining = n_bytes
        while remaining > 0:
            chunk = self.sock.recv(remaining)
            if not chunk:
                raise WSClosed(f"{self.addr}: connection closed mid-frame")
            chunks.append(chunk)
            remaining -= len(chunk)
        return b"".join(chunks)

    def read_frame(self) -> tuple[bool, int, bytes]:
        """(fin, opcode, payload); client masks are stripped per RFC 6455."""
        head = self.read_exact(2)
        fin = bool(head[0] & 0x80)
        opcode = head[0] & 0x0F
        masked = bool(head[1] & 0x80)
        length = head[1] & 0x7F
        if length == 126:
            length = struct.unpack(">H", self.read_exact(2))[0]
        elif length == 127:
            length = struct.unpack(">Q", self.read_exact(8))[0]
        if length > MAX_FRAME_BYTES:
            raise WSClosed(f"{self.addr}: frame of {length} bytes exceeds the cap")
        mask = self.read_exact(4) if masked else None
        payload = self.read_exact(length) if length else b""
        if mask is not None:
            payload = bytes(b ^ mask[i % 4] for i, b in enumerate(payload))
        return fin, opcode, payload

    def send_frame(self, opcode: int, payload: bytes) -> None:
        header = bytes([0x80 | opcode])
        length = len(payload)
        if length < 126:
            header += bytes([length])
        elif length < 65536:
            header += bytes([126]) + struct.pack(">H", length)
        else:
            header += bytes([127]) + struct.pack(">Q", length)
        with self.send_lock:
            self.sock.sendall(header + payload)

    def send_text(self, text: str) -> None:
        self.send_frame(OP_TEXT, text.encode("utf-8"))

    def close(self) -> None:
        try:
            self.send_frame(OP_CLOSE, b"")
        except OSError:
            pass  # the peer may already be gone; the socket close below is the point
        try:
            self.sock.close()
        except OSError:
            pass


def _http_403() -> bytes:
    return b"HTTP/1.1 403 Forbidden\r\nContent-Length: 0\r\nConnection: close\r\n\r\n"


def _handshake(sock: socket.socket) -> tuple[_Connection, str]:
    """Read one HTTP upgrade request; return (connection, request path)."""
    raw = b""
    while b"\r\n\r\n" not in raw:
        if len(raw) > MAX_HTTP_HEADER_BYTES:
            raise WSClosed("handshake header larger than 16 KiB")
        chunk = sock.recv(4096)
        if not chunk:
            raise WSClosed("connection closed during handshake")
        raw += chunk
    head = raw.split(b"\r\n\r\n", 1)[0].decode("latin-1")
    lines = head.split("\r\n")
    parts = lines[0].split(" ")
    if len(parts) < 2 or parts[0] != "GET":
        raise WSClosed(f"not a GET handshake: {lines[0]!r}")
    path = parts[1]
    headers: dict[str, str] = {}
    for line in lines[1:]:
        if ":" in line:
            key, value = line.split(":", 1)
            headers[key.strip().lower()] = value.strip()
    key = headers.get("sec-websocket-key")
    if not key or "websocket" not in headers.get("upgrade", "").lower():
        raise WSClosed("missing WebSocket upgrade headers")
    # The 101 goes out only after authorization (query-token mode rejects here).
    connection = _Connection(sock, path)
    connection._handshake_key = key
    return connection, path


def _query_token(path: str) -> str | None:
    """The ``token`` query parameter of the handshake path, if present."""
    values = parse_qs(urlsplit(path).query).get("token", [])
    return values[0] if values else None


class FakeHub:
    """Section 7.6 stand-in hub.

    Start with :meth:`start` (background accept thread, ephemeral port via
    ``port=0``) or run :meth:`serve_forever` directly. Counters,
    ``recorded_poses``, and ``saved_wavs`` are plain attributes for tests.
    """

    def __init__(
        self,
        host: str = "0.0.0.0",
        port: int = 8765,
        token: str = "",
        auth: str = "query",
        contracts_dir: str | Path | None = None,
        record_dir: str | Path | None = None,
    ) -> None:
        if auth not in AUTH_MODES:
            raise ValueError(f"auth must be one of {AUTH_MODES}, got {auth!r}")
        self.host = host
        self.port = port
        self.auth = auth
        self.token = token
        self.contracts_dir = Path(contracts_dir or LOCATOR_ROOT / "contracts")
        self.record_dir = Path(record_dir) if record_dir else None
        self.counters: dict[str, int] = {
            "valid": 0, "invalid": 0, "hello": 0, "rejected_handshakes": 0,
            "mic_audio_outside_ptt": 0, "connections": 0,
        }
        self.invalid_log: list[str] = []
        self.recorded_poses: list[dict[str, Any]] = []
        self.saved_wavs: list[Path] = []
        self.ptt_active = False
        self.turn_index = 0
        self._turn_samples: bytearray | None = None
        self._turn_rate = 0
        self._validators = self._load_validators()
        self._sock: socket.socket | None = None
        self._accept_thread: threading.Thread | None = None
        self._clients: list[_Connection] = []
        self._clients_lock = threading.Lock()
        self._stopping = threading.Event()
        self._turn_lock = threading.Lock()

    # ---- setup -----------------------------------------------------------

    def _load_validators(self) -> dict[str, Any]:
        validators: dict[str, Any] = {}
        for msg_type in CONTRACT_TYPES:
            schema_path = self.contracts_dir / f"{msg_type}.schema.json"
            try:
                schema = json.loads(schema_path.read_text(encoding="utf-8"))
            except FileNotFoundError as exc:
                raise RuntimeError(f"contract schema not found: {schema_path}") from exc
            cls = validator_for(schema)
            cls.check_schema(schema)
            validators[msg_type] = cls(schema)
        return validators

    # ---- lifecycle -------------------------------------------------------

    def start(self) -> None:
        """Bind, listen, and run the accept loop on a daemon thread."""
        self._bind()
        self._accept_thread = threading.Thread(
            target=self.serve_forever, name="fake-hub-accept", daemon=True
        )
        self._accept_thread.start()

    def serve_forever(self) -> None:
        """Blocking accept loop; ``start()`` runs this on a thread."""
        self._bind()
        assert self._sock is not None
        self._sock.settimeout(0.2)
        print(f"fake_hub listening on ws://{self.host}:{self.port} "
              f"(auth={self.auth}, token={'on' if self.token else 'off'})")
        print("keyboard: p toggles ptt, q quits (POSIX TTY only)")
        while not self._stopping.is_set():
            try:
                sock, addr = self._sock.accept()
            except socket.timeout:
                continue
            except OSError:
                break  # shutdown closed the listener
            threading.Thread(
                target=self._handle_client, args=(sock, f"{addr[0]}:{addr[1]}"),
                name="fake-hub-client", daemon=True,
            ).start()

    def _bind(self) -> None:
        if self._sock is not None:
            return
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._sock.bind((self.host, self.port))
        self._sock.listen(8)
        self.port = self._sock.getsockname()[1]

    def shutdown(self) -> None:
        self._stopping.set()
        with self._clients_lock:
            for client in list(self._clients):
                client.close()
            self._clients.clear()
        if self._sock is not None:
            try:
                self._sock.close()
            except OSError:
                pass
        if self.ptt_active:
            self._set_ptt("stop", broadcast=False)
        if self._accept_thread is not None:
            self._accept_thread.join(timeout=2.0)

    # ---- client handling ---------------------------------------------------

    def _handle_client(self, sock: socket.socket, addr: str) -> None:
        try:
            connection, path = _handshake(sock)
        except (WSClosed, OSError):
            sock.close()
            return
        if not self._authorize(path, connection):
            return
        connection.accept()
        with self._clients_lock:
            self._clients.append(connection)
        self.counters["connections"] += 1
        print(f"[conn] {addr} connected ({path})")
        fragment_buffer = ""
        try:
            while True:
                fin, opcode, payload = connection.read_frame()
                if opcode == OP_CLOSE:
                    break
                if opcode == OP_PING:
                    connection.send_frame(OP_PONG, payload)
                    continue
                if opcode == OP_PONG:
                    continue
                if opcode == OP_BINARY:
                    self._flag_invalid(f"{addr}: binary frame (contracts are text JSON)")
                    continue
                text = fragment_buffer + payload.decode("utf-8", errors="replace")
                if not fin:
                    fragment_buffer = text
                    continue
                fragment_buffer = ""
                self._process_message(text, addr, connection)
        except (WSClosed, OSError):
            pass
        finally:
            with self._clients_lock:
                if connection in self._clients:
                    self._clients.remove(connection)
            connection.close()
            print(f"[conn] {addr} disconnected")

    def _authorize(self, path: str, connection: _Connection) -> bool:
        """Query-mode auth happens at the handshake; hello-mode on the first message."""
        if self.auth == "query" and self.token:
            if _query_token(path) != self.token:
                self.counters["rejected_handshakes"] += 1
                try:
                    connection.sock.sendall(_http_403())
                except OSError:
                    pass
                connection.close()
                print(f"[auth] rejected handshake {path} (bad or missing token)")
                return False
        return True

    # ---- message handling --------------------------------------------------

    def _flag_invalid(self, reason: str) -> None:
        self.counters["invalid"] += 1
        self.invalid_log.append(reason)
        print(f"[INVALID] {reason}")

    def _validate(self, msg_type: str, message: dict[str, Any]) -> str | None:
        """A schema error string, or None when the message is valid."""
        validator = self._validators.get(msg_type)
        if validator is None:
            return (f"unknown message type {msg_type!r}: not in contracts/ "
                    "(the real hub ignores these silently)")
        errors = sorted(validator.iter_errors(message), key=lambda e: list(e.absolute_path))
        if not errors:
            return None
        error = errors[0]
        where = "/".join(str(p) for p in error.absolute_path)
        return f"{msg_type}{'.' + where if where else ''}: {error.message}"

    def _process_message(self, text: str, addr: str, connection: _Connection) -> None:
        try:
            message = json.loads(text)
        except json.JSONDecodeError as exc:
            self._flag_invalid(f"{addr}: not JSON ({exc.msg})")
            return
        if not isinstance(message, dict):
            self._flag_invalid(f"{addr}: message is not a JSON object")
            return
        if message.get("type") == "hello":
            # Consumed and logged in every mode; roles accepted as any string
            # (verified hub fact: today's hub has no token check at all).
            self.counters["hello"] += 1
            if self.auth == "hello" and self.token and message.get("token") != self.token:
                self._flag_invalid(f"{addr}: hello token mismatch in hello auth mode")
                connection.close()
                return
            connection.greeted = True
            print(f"[hello] {addr} role={message.get('role', 'unknown')!r}")
            return
        if self.auth == "hello" and self.token and not connection.greeted:
            # Brief 2.3: in hello mode the hello must be the FIRST message.
            self._flag_invalid(f"{addr}: first message must be hello in hello auth mode")
            connection.close()
            return
        msg_type = message.get("type")
        if not isinstance(msg_type, str):
            self._flag_invalid(f"{addr}: message has no 'type' field")
            return
        reason = self._validate(msg_type, message)
        if reason is not None:
            self._flag_invalid(f"{addr}: {reason}")
            return
        self.counters["valid"] += 1
        self.counters[msg_type] = self.counters.get(msg_type, 0) + 1
        if msg_type == "listener_pose":
            self._record_pose(message)
        elif msg_type == "mic_audio":
            self._handle_mic_audio(message, addr)
        elif msg_type == "ptt":
            # A locator's backup button sends ptt to the bus; mirror the
            # state so its mic_audio lands in a turn (do not re-broadcast).
            self._set_ptt(message["state"], broadcast=False)
        elif msg_type == "status":
            print(f"[status] {addr} ok={message['ok']} {message['detail']}")

    def _record_pose(self, message: dict[str, Any]) -> None:
        self.recorded_poses.append(message)
        print(f"[pose] {message['position']} q={message['quality']} "
              f"heard={message['beacons_heard']} src={message['source']}")
        if self.record_dir is None:
            return
        self.record_dir.mkdir(parents=True, exist_ok=True)
        path = self.record_dir / "listener_pose.jsonl"
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(message, separators=(",", ":")) + "\n")

    # ---- push-to-talk ------------------------------------------------------

    def toggle_ptt(self) -> bool:
        """Keyboard 'p': flip PTT state and broadcast it to every client."""
        self._set_ptt("stop" if self.ptt_active else "start", broadcast=True)
        return self.ptt_active

    def _set_ptt(self, state: str, broadcast: bool) -> None:
        want_active = state == "start"
        broadcast_text: str | None = None
        with self._turn_lock:
            if want_active == self.ptt_active:
                return
            self.ptt_active = want_active
            if want_active:
                self.turn_index += 1
                self._turn_samples = bytearray()
                self._turn_rate = 0
                print(f"[ptt] start (turn {self.turn_index})")
            else:
                self._save_turn_locked()
            if broadcast:
                broadcast_text = json.dumps(
                    {"type": "ptt", "state": state}, separators=(",", ":")
                )
        if broadcast_text is not None:
            with self._clients_lock:
                clients = list(self._clients)
            for client in clients:
                try:
                    client.send_text(broadcast_text)
                except OSError:
                    pass  # a dead client is reaped by its own reader thread
            print(f"[ptt] {state} broadcast to {len(clients)} client(s)")

    def _handle_mic_audio(self, message: dict[str, Any], addr: str) -> None:
        if not self.ptt_active:
            self.counters["mic_audio_outside_ptt"] += 1
            print(f"[WARN] {addr}: mic_audio outside an active PTT turn (the "
                  "contract sends it only while PTT is active); buffering anyway")
            with self._turn_lock:
                if self._turn_samples is None:
                    self.turn_index += 1
                    self._turn_samples = bytearray()
                    self._turn_rate = 0
        try:
            chunk = base64.b64decode(message["chunk_b64"], validate=True)
        except binascii.Error as exc:
            self._flag_invalid(f"{addr}: mic_audio chunk_b64 does not decode: {exc}")
            return
        with self._turn_lock:
            if self._turn_samples is None:
                return  # a stop raced us; drop rather than mislabel the chunk
            self._turn_samples.extend(chunk)
            self._turn_rate = self._turn_rate or int(message["sample_rate"])
        print(f"[mic] {addr} seq={message['seq']} {len(chunk)}B (turn {self.turn_index})")

    def _save_turn_locked(self) -> None:
        """Finalize the current PTT turn; caller holds ``_turn_lock``."""
        samples = self._turn_samples
        rate = self._turn_rate or 16000
        self._turn_samples = None
        self._turn_rate = 0
        if samples is None or not samples:
            return
        if self.record_dir is None:
            print(f"[ptt] turn {self.turn_index} had {len(samples)} bytes but no "
                  "--record dir: not saved")
            return
        self.record_dir.mkdir(parents=True, exist_ok=True)
        path = self.record_dir / f"ptt_turn_{self.turn_index:03d}.wav"
        with wave.open(str(path), "wb") as handle:
            handle.setnchannels(1)
            handle.setsampwidth(2)
            handle.setframerate(rate)
            handle.writeframes(bytes(samples))
        self.saved_wavs.append(path)
        duration = len(samples) / (2 * rate)
        print(f"[ptt] turn {self.turn_index}: saved {path} "
              f"({len(samples) // 2} samples @ {rate} Hz, {duration:.2f} s)")


def _keyboard_loop(hub: FakeHub) -> bool:
    """POSIX single-key loop; returns False when stdin is not a TTY."""
    if not sys.stdin.isatty():
        print("stdin is not a TTY: keyboard disabled, running until Ctrl-C")
        return True
    import termios
    import tty

    old_settings = termios.tcgetattr(sys.stdin.fileno())
    tty.setcbreak(sys.stdin.fileno())
    print("press p to toggle PTT, q to quit")
    try:
        while True:
            key = sys.stdin.read(1)
            if key == "p":
                state = hub.toggle_ptt()
                print(f"ptt {'start' if state else 'stop'}")
            elif key == "q":
                return False
    except KeyboardInterrupt:
        return False
    finally:
        termios.tcsetattr(sys.stdin.fileno(), termios.TCSADRAIN, old_settings)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Stand-in WebSocket hub for bring-up (brief section 7.6)."
    )
    parser.add_argument("--host", default="0.0.0.0", help="bind address, default 0.0.0.0")
    parser.add_argument("--port", type=int, default=8765, help="bind port, default 8765")
    parser.add_argument("--auth", default="query", choices=AUTH_MODES,
                        help="auth mode (brief 2.3): query token on the URL, hello "
                             "first message, or none like today's real hub")
    parser.add_argument("--token", default="", help="shared token; empty disables auth")
    parser.add_argument("--record", default=str(LOCATOR_ROOT / "out" / "fake_hub"),
                        help="recording directory (default: out/fake_hub)")
    parser.add_argument("--contracts", default=None,
                        help="contracts/ directory (default: the repo's)")
    args = parser.parse_args(argv)

    hub = FakeHub(
        host=args.host,
        port=args.port,
        token=args.token,
        auth=args.auth,
        contracts_dir=args.contracts,
        record_dir=args.record,
    )
    hub.start()
    try:
        running = _keyboard_loop(hub)
        if running:
            import signal

            signal.pause()
    except KeyboardInterrupt:
        pass
    finally:
        hub.shutdown()
    print(f"done: {hub.counters['valid']} valid messages, "
          f"{hub.counters['invalid']} invalid, "
          f"{len(hub.recorded_poses)} poses recorded, "
          f"{len(hub.saved_wavs)} PTT WAV(s)")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
