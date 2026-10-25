# Earmark ranging

Works out where the user's phone is from chirps played and heard by phones around the room.

```
cd services/ranging
uv run pytest -q          # tests
uvx ruff check .          # lint
uv run earmark-ranging --help
```

## Two modes

**Two-way (`earmark-ranging serve`).** The Mac tells every phone, over Wi-Fi, when to chirp. Every phone (the
user's and the beacons) records, and the distance between two phones comes from comparing their two recordings, so
no clock has to agree with any other. It needs every phone connected to the Mac. See `locator/docs/PHONE_BEACONS.md`.

**Calibrate-then-listen (`earmark-ranging listen`).** The beacon phones chirp on their own clocks, on a strict
schedule, with no network at all. Only the user's phone records and streams audio to the Mac. The Mac learns each
beacon's schedule once, while the user's phone sits still at a known spot ("calibration"). After that every chirp
heard gives a distance on its own: how late it arrived against the schedule, times the speed of sound. Three
beacons give a position. Two beacons also give one, by assuming the phone is held at chest height; the two
circles meet in two mirror-image points either side of the line between the beacons, and the Mac keeps the one on
the calibration spot's side (then the one nearest the last position), so the user must stay on one side of that
line. One beacon gives a distance only.

## Room setup with no tape measure (`listen --setup`)

Instead of measuring the beacons, the user's phone stands still on each of four taped floor marks (`setup_marks` in
`config/beacons.json`) for 10 s, Enter at each. Per beacon, every chirp heard at mark j obeys
`t = a + b*n + |p_j - q|/c`; with the marks p_j known, a robust least-squares fit over the whole walk gives the
beacon's floor position q (height fixed at 0.75 m) and its schedule (a, b) at once (`earmark_ranging/survey.py`).
The result is written back to `config/beacons.json` and tracking starts. `make room-setup` runs it;
`make room-setup-sim` runs it against virtual phones; `make room-recalibrate` redoes only the one-spot calibration
on the mat when the beacons have not moved. Simulator accuracy with real-phone timing wobble (0.15 ms per chirp):
beacons within about 5 to 15 cm.

## Calibrate-then-listen mode

### What the beacons do (shared with the iPhone app; do not change one side without the other)

- Cycle 0.5 s, four slots of 0.125 s. Beacon N (1 to 4, from the id `B1`..`B4` in `config/beacons.json`) starts a
  chirp when `unix_time mod 0.5 == (N-1)*0.125`, lined up once at startup to about ±30 ms. After that the chirps
  are exactly periodic in the beacon's own audio clock (every `round(0.5*fs)` output samples).
- The chirp: linear sweep, default 12000 to 16000 Hz (`--band`; the Mac's detector must use the same band), 40 ms,
  Tukey fade alpha 0.4, exactly the synth in `earmark_ranging/chirp.py`. Odd beacons (1, 3) sweep up, even (2, 4)
  sweep down.
- The user's phone is the app's ordinary "The user's phone" role: it connects to `ws://mac:8766`, sends
  `{"type":"join","slot":0,...}` then `{"type":"audio","start":<sample index>,"pcm":<base64 int16>}` at 48 kHz. In
  this mode the Mac never sends `{"type":"play"}`. It may send `{"type":"fix",...}` when it has a position.
  The phone's sample counter is the clock; a lost chunk is filled with silence so the timeline stays honest.
- Speed of sound `c = 331.3 + 0.606*T` m/s (`--temperature`, default 20 C, so 343.4 m/s). Fixed delays inside the
  phones (speaker to microphone, buffers) are absorbed by calibration, so there is no extra term.

On the user's recording, beacon k's chirps land at `t = a_k + b_k*n`. `b_k` is about 0.5 s, off by the two
phones' clock-rate difference (tens of ppm); `a_k` is unknown. Calibration fits both; the known distance to the
calibration spot turns the arrival line into the play line (`a_play = a - d/c`). Then a chirp heard at time `t`
in cycle `n = round((t - a)/b)` means distance `d = c*(t - a - b*n)`.

### The one-beacon test, step by step

1. Put the real beacon position in `config/beacons.json` (B1 is the first entry). Measure, with a tape, a spot
   exactly 1.00 m from the beacon phone's bottom edge where the user's phone will be held.
2. On the Mac:
   ```
   cd services/ranging
   uv run earmark-ranging listen --only B1 --calibrate-distance 1.0 --band 12000 16000 --no-bus --log out.csv
   ```
   It prints the address the phone should use (`ws://192.168.x.x:8766`) and the instruction to hold the phone at
   the spot. Options: `--calibration-seconds 10` (how long the phone must stay still), `--calibrate-after 5` (start
   calibrating by itself 5 s after the first audio arrives, instead of waiting for Enter), `--temperature 23`,
   `--save-audio DIR` (keeps the last 6 s the phone heard as `phone0.wav`), `--min-snr` (how clearly a chirp must
   stand out; raise it if noise is being mistaken for chirps).
3. Start beacon phone 1 in the app's beacon mode (number 1), screen on, volume up, bottom edge toward the room.
   It needs no network; it just chirps every half second.
4. Start the user's phone in "The user's phone" mode with the Mac's address. The Mac shows
   `phones [0]  chirps heard: B1 2.0/s  not calibrated` every 2 s, and one `B1 heard` line per chirp.
   If `B1 0.0/s`, the phone is not hearing the beacon: volume, distance, something over the speaker or mic.
5. Hold the user's phone still at the 1.00 m spot, bottom edge toward the beacon, and press Enter. The Mac counts
   down (`calibrating... 7.0 s left, keep still`) and then prints the report:
   ```
   calibration ok
     B1: 20/20 chirps kept, residual 0.004 ms, period 0.499981 s (-38 ppm), phase off by +12 ms
   ```
   - `kept`: chirps that fit the schedule; at least 12 are needed.
   - `residual`: how ragged the chirps were around the straight line; the limit is 0.3 ms (about 10 cm of sound).
     More than that means the phone moved, or echoes were chosen instead of direct sound.
   - `period`: the beacon's half second as seen by the user's phone. More than 150 ppm from 0.5 s means the phone
     was creeping during calibration (steady motion looks exactly like a clock error).
   - `phase off`: how far the beacon's chirps are from its wall-clock slot, as far as the Mac can tell (tens of ms
     of uncertainty). It tells you whether the phone you call B1 really is beacon 1.
   If it says `FAILED`, it names the beacon and the reason; put the phone back at the spot and press Enter again.
6. Now walk about. One line per chirp:
   ```
   12:34:56.789  B1  d 1.032 m  snr 11.4  cycle 231
   ```
   wall-clock time the chirp was heard, the beacon, the distance from the phone to it, how clearly it stood out
   of the background (the detector's peak-over-background ratio), and which half-second cycle since calibration
   it was. The same goes to `out.csv` (`wall_time, beacon, distance_m, snr, cycle, recording_time_s`).
   With three or more beacons a `fix x y z` line follows, as in the two-way mode, and the position goes to the
   Earmark bus (leave out `--no-bus`) and back to the phone.
7. Press Enter at any time to calibrate again (put the phone back at the spot first).

### With three or more beacons

Use the whole config (no `--only`) and give the calibration spot as a point in room coordinates instead of a
single distance: `--calibrate-at 0 0 1.25` (x right, y forward, z up, meters; the position of the phone itself).
Calibration then fits every beacon at once and tells any two same-shape beacons (B1/B3, B2/B4) apart by where in
the half second they chirp.

### Try it with no phones

```
uv run earmark-ranging listen --sim --only B1 --calibrate-distance 1.0 --no-bus
uv run earmark-ranging listen --sim --calibrate-at 0.3 0.5 1.2 --sim-echo --sim-dropout 0.02 --no-bus
```
A virtual phone connects, stands at the calibration spot (calibration starts by itself after 2 s), and then paces
back and forth at 0.5 m/s. `--sim-noise`, `--sim-echo` and `--sim-dropout` make the pretend room harder.

### Where the code is

- `earmark_ranging/listen.py`: the pure part. `ChirpFeed` runs the detector over audio as it arrives and reports
  each chirp once; `Calibrator` assigns chirps to beacons and fits the schedules; `Tracker` turns chirps into
  `Range`s (earliest strong peak in each cycle's window, since echoes are always late) and fresh ranges into a
  position with `solve.locate`.
- `earmark_ranging/service_listen.py`: `ListenService`, the WebSocket side (same protocol as `service.py`, never
  sends play), per-chirp callbacks, CSV log, status line.
- `earmark_ranging/sim_listen.py`: `SelfTimedWorld` (self-timed beacons with their own offsets and drifts, a
  moving target, echoes) and `VirtualTargetPhone` (streams like the real app, or hands over chunks for tests).
- `tests/test_listen.py`.

### Known limits

- A phone that creeps very slowly during calibration (under about 0.05 m/s) cannot be told from a clock error;
  distances will then drift slowly with time. Recalibrate.
- The schedule is only as good as the phones' clocks stay steady; after a long time, or if a phone's audio engine
  restarts, recalibrate.

## Recording a run and replaying it

Add `--record FILE.wav` to any `listen` command to keep everything the user's phone heard, for the whole run.
The file is playable even if the run is stopped with Ctrl-C, and `FILE.wav.json` beside it remembers the band,
the beacons, the calibration distance and the exact moments calibration started and finished.
The status line also shows `lost audio N chunks` when Wi-Fi dropped part of the stream.

```
uv run earmark-ranging listen --only B1 --calibrate-distance 1.0 --no-bus --record runs/one_beacon.wav
```

Replay runs the same pipeline over the file, offline, and prints the same lines plus a summary:

```
uv run earmark-ranging replay runs/one_beacon.wav --only B1 --truth B1 1.0
uv run earmark-ranging replay runs/one_beacon.wav --only B1 --quiet --min-snr 8 --calibrate-from 12
```

Settings default to what the live run used; pass them to try something different on the same audio.
A good test recording to send for analysis: 30 s still at exactly 1.00 m (calibrate during it), then 30 s still at 0.30 m.
