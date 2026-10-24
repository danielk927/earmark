"""Write a test sweep WAV to play from any speaker (phone, laptop) when no beacon hardware exists yet.

Same shape as the firmware's `sweep` command: 2 s of silence, a linear sweep from 1 to 20 kHz over 10 s,
then 2 s of silence, at 48 kHz. Record it with another phone and run `make bandtest FILE=recording.wav`.

Usage: python3 tools/make_test_sweep.py [out.wav]
"""

import sys
import wave

import numpy as np

FS = 48000
SILENCE_S = 2.0
SWEEP_S = 10.0
F0, F1 = 1000.0, 20000.0
LEVEL = 0.9  # leave a little headroom so the speaker does not clip


def main() -> None:
    out = sys.argv[1] if len(sys.argv) > 1 else "out/test_sweep.wav"
    t = np.arange(int(SWEEP_S * FS)) / FS
    phase = 2 * np.pi * (F0 * t + (F1 - F0) / (2 * SWEEP_S) * t * t)
    sweep = LEVEL * np.sin(phase)
    fade = int(0.01 * FS)
    sweep[:fade] *= np.linspace(0, 1, fade)
    sweep[-fade:] *= np.linspace(1, 0, fade)
    pad = np.zeros(int(SILENCE_S * FS))
    samples = (np.concatenate([pad, sweep, pad]) * 32767).astype("<i2")
    import os

    os.makedirs(os.path.dirname(out) or ".", exist_ok=True)
    with wave.open(out, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(FS)
        w.writeframes(samples.tobytes())
    print(f"wrote {out}: {len(samples) / FS:.0f} s")


if __name__ == "__main__":
    main()
