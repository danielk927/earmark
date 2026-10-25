"""Record the whole session the user's phone heard, so a run can be replayed and studied offline.

The WAV is written as the audio arrives and its header is kept valid every flush, so a run that is stopped with
Ctrl-C (or crashes) still leaves a playable file. A sidecar `<file>.json` holds everything replay needs: the
sample counter the recording starts at, the wall-clock time of the first chunk, the chirp band, the beacons, the
known calibration distances, and the moments calibration started and finished (in seconds on the recording).
"""
from __future__ import annotations

import json
import struct
import time
from pathlib import Path

import numpy as np

MAX_GAP_FILL_S = 10.0  # a longer hole than this is not filled with silence (the phone probably reconnected)


def _wav_header(n_bytes: int, fs: int) -> bytes:
    return b"RIFF" + struct.pack("<I", 36 + n_bytes) + b"WAVE" + b"fmt " + struct.pack(
        "<IHHIIHH", 16, 1, 1, fs, fs * 2, 2, 16
    ) + b"data" + struct.pack("<I", n_bytes)


class SessionRecorder:
    def __init__(self, path: str, fs: int, meta: dict | None = None) -> None:
        self.path, self.fs = Path(path), fs
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.f = open(self.path, "wb")
        self.f.write(_wav_header(0, fs))
        self.n_bytes = 0
        self.first: int | None = None  # the phone's sample counter at the first chunk
        self.end: int | None = None  # first sample index not yet written
        self.gaps = 0
        self.lost_samples = 0
        self.wall_first: float | None = None
        self.meta: dict = dict(meta or {})
        self.meta.setdefault("fs", fs)
        self.meta["events"] = []
        self._last_flush = time.monotonic()

    # ------------------------------------------------------------------ audio

    def write(self, start: int, pcm: bytes) -> None:
        """One chunk of int16 little-endian PCM whose first sample is the phone's counter `start`."""
        n = len(pcm) // 2
        if self.first is None:
            self.first, self.end, self.wall_first = start, start, time.time()
            self.meta["first_sample_index"] = start
            self.meta["wall_time_first_chunk"] = self.wall_first
        assert self.end is not None
        if start > self.end:
            gap = start - self.end
            self.gaps += 1
            self.lost_samples += gap
            if gap <= MAX_GAP_FILL_S * self.fs:
                self._append(bytes(gap * 2))
            else:
                self.meta["events"].append({"what": "hole_not_filled", "rec_time_s": self.rec_time(self.end), "samples": gap})
        elif start < self.end:  # overlap or a repeat: keep only what is new
            skip = self.end - start
            if skip >= n:
                return
            pcm = pcm[skip * 2:]
            n -= skip
            start = self.end
        self._append(pcm)
        self.end = start + n
        if time.monotonic() - self._last_flush > 2.0:
            self.flush()

    def _append(self, data: bytes) -> None:
        self.f.write(data)
        self.n_bytes += len(data)

    def rec_time(self, sample_index: int) -> float:
        """Seconds into the file for a phone sample index (the file starts at `first`)."""
        return (sample_index - (self.first or 0)) / self.fs

    def mark(self, what: str, rec_time_s: float, **extra) -> None:
        self.meta["events"].append({"what": what, "rec_time_s": rec_time_s, "wall_time": time.time(), **extra})
        self.flush()

    # ------------------------------------------------------------------ files

    def flush(self) -> None:
        pos = self.f.tell()
        self.f.seek(0)
        self.f.write(_wav_header(self.n_bytes, self.fs))
        self.f.seek(pos)
        self.f.flush()
        self.meta["gaps"], self.meta["lost_samples"] = self.gaps, self.lost_samples
        self.meta["seconds"] = self.n_bytes / 2 / self.fs
        self.sidecar.write_text(json.dumps(self.meta, indent=2))
        self._last_flush = time.monotonic()

    @property
    def sidecar(self) -> Path:
        return self.path.with_name(self.path.name + ".json")

    def close(self) -> None:
        if not self.f.closed:
            self.flush()
            self.f.close()


def read_recording(path: str) -> tuple[np.ndarray, int, dict]:
    """The recording as float samples in -1..1, its sample rate, and the sidecar (empty dict if there is none)."""
    import wave

    with wave.open(path, "rb") as w:
        fs, n, width, ch = w.getframerate(), w.getnframes(), w.getsampwidth(), w.getnchannels()
        raw = w.readframes(n)
    if width == 2:
        x = np.frombuffer(raw, dtype="<i2").astype(np.float32) / 32768.0
    elif width == 4:
        x = np.frombuffer(raw, dtype="<f4").astype(np.float32)
    else:
        raise ValueError(f"unsupported sample width {width}")
    if ch > 1:
        x = x.reshape(-1, ch)[:, 0]
    side = Path(path + ".json")
    meta = json.loads(side.read_text()) if side.exists() else {}
    return x, fs, meta
