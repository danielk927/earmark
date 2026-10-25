"""The session recorder writes a valid, gap-filled WAV with a sidecar, and replay reproduces the live result."""
from __future__ import annotations

import json
import time
import wave

import numpy as np

from earmark_ranging.chirp import ChirpSpec
from earmark_ranging.record import SessionRecorder, read_recording
from earmark_ranging.replay import replay
from earmark_ranging.service import FS
from earmark_ranging.sim_listen import CHUNK, SelfTimedWorld, VirtualTargetPhone, still_then_walk

B1 = {1: (-1.6, 1.5, 0.75)}
SPOT = (-1.6 + 1.0, 1.5, 0.75)  # exactly 1 m from B1


def test_recorder_fills_gaps_and_keeps_a_valid_header(tmp_path):
    path = tmp_path / "s.wav"
    rec = SessionRecorder(str(path), FS, meta={"band": [12000, 16000]})
    a = (np.ones(CHUNK) * 1000).astype("<i2").tobytes()
    rec.write(5_000_000, a)
    rec.write(5_000_000 + CHUNK, a)
    rec.write(5_000_000 + 3 * CHUNK, a)  # one chunk missing
    rec.write(5_000_000 + 3 * CHUNK + 100, a)  # overlapping repeat: only the new 100 samples count
    rec.mark("calibration_start", 0.1)
    rec.flush()  # header valid before close, as after Ctrl-C
    with wave.open(str(path), "rb") as w:
        assert w.getframerate() == FS and w.getnchannels() == 1 and w.getsampwidth() == 2
        assert w.getnframes() == 4 * CHUNK + 100
    rec.close()
    x, fs, meta = read_recording(str(path))
    assert fs == FS and len(x) == 4 * CHUNK + 100
    assert np.all(x[2 * CHUNK:3 * CHUNK] == 0.0)  # the hole is silence
    assert meta["first_sample_index"] == 5_000_000 and meta["gaps"] == 1 and meta["lost_samples"] == CHUNK
    assert meta["events"][0]["what"] == "calibration_start" and meta["band"] == [12000, 16000]
    assert json.loads(rec.sidecar.read_text())["seconds"] > 0


def _synthetic_recording(tmp_path, seconds=22.0, seed=3):
    """A target phone standing 1 m from B1 for 14 s, then walking away, written through the recorder."""
    spec = ChirpSpec(12000.0, 16000.0)
    t0 = time.time()
    world = SelfTimedWorld(B1, still_then_walk(SPOT, t0 + 14.0, speed=0.4), spec, t0, seed=seed, echo=True)
    phone = VirtualTargetPhone(world, t0 + 0.5, seed=seed, noise_rms=0.1)
    path = tmp_path / "run.wav"
    rec = SessionRecorder(str(path), FS, meta={
        "band": [12000.0, 16000.0], "cycle_s": 0.5, "slot_s": 0.125, "min_snr": 4.5, "calibrate_distance": 1.0,
    })
    n = int(seconds * FS)
    for k0 in range(0, n, CHUNK):
        rec.write(phone.start_count + k0, phone.pcm(k0))
    rec.mark("calibration_start", 2.0)
    rec.close()
    return str(path), world, phone


def test_replay_calibrates_and_tracks_a_recording(tmp_path):
    path, world, phone = _synthetic_recording(tmp_path)
    res = replay(path, B1, calibration_s=10.0, quiet=True)
    assert res.reports and res.reports[0].ok, res.reports[0].lines() if res.reports else "no calibration"
    still = res.distances(1, 12.5, 13.4)  # calibrated at 12 s, still until 13.5 s on the file clock
    assert len(still) >= 2 and np.all(np.abs(still - 1.0) < 0.03), still
    walking = [(t, r.distance_m) for t, r in res.ranges if t > 15.0]
    assert len(walking) >= 10
    for t, d in walking:
        true_t = phone.sample_time(int(t * FS))
        assert abs(d - world.distance(1, true_t)) < 0.05, (t, d, world.distance(1, true_t))
    lines = res.summary({1: 1.0})
    assert lines and lines[0].startswith("B1:")
