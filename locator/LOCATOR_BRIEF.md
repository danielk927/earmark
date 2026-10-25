# Earmark — Locator Brief (LOCATOR_BRIEF.md)

Cal Hacks 13.0 · submission deadline Sunday 9:00 AM PT.

Earmark is an assistive system that helps blind and low-vision people find household objects by sound. The user wears AirPods. When they ask for an item, a spatial-audio ping plays from the item's exact location. The ping stays fixed in the room as they turn their head, and it gets louder and faster as they walk toward it. Walking is the entire demo.

A separate repo, built by a teammate's Claude Code session, owns everything else: the hub (a WebSocket bus on the Mac), the Mac app (spatial audio rendering, AirPods head tracking, the arrival logic), voice (Cartesia STT and TTS, Moss), Convex, the dashboard, NFC pickup detection, and the sponsor integrations. This repo owns only the answer to "where is the user right now?", delivered to that hub as listener_pose messages, plus phone-microphone speech streaming during push-to-talk.

We build:

1. Beacon firmware for one ESP32 that drives 5 passive buzzers ("beacons") placed around the room. They chirp in turn on a fixed schedule.
2. The EarmarkLocator iPhone app. It listens to the beacons through the iPhone's microphone, computes the phone's 3D position GPS-style, and sends listener_pose to the hub. It also streams mic audio to the hub during push-to-talk.
3. Python tools: a beacon audio simulator, a reference detection-and-solver pipeline, a band test, a log analyzer, and a fake hub. Together these let all the software be built and tested before any hardware works.
4. Beginner-proof hardware docs: wiring and bring-up checklists. The humans have no hardware experience.

We must NOT build: spatial audio rendering, head tracking, voice or STT/TTS, an LLM anything, the dashboard, Convex, NFC, or anything with a camera. No camera, ARKit, or LiDAR, ever. That's a product requirement: no camera in the home and nothing strapped to the user.

Principles:
- A small system that works live beats an ambitious one that doesn't.
- All math lives in deterministic, tested code. Python is the reference implementation, and Swift must match it (section 9.4).
- Verify every Apple and Espressif API against current official docs before using it. Record what you verified, with URLs, in docs/vendor-notes/<vendor>.md. Don't invent APIs.
- Always runnable: small commits with clear messages. Keep docs/STATUS.md current.
- Ask the human only for physical facts, measurements, signing, or product decisions, and batch the questions.

## 1. The physical demo (what the system must support)

- Space: about 3.5 × 3.5 m at the team's table area in a crowded, noisy hackathon hall (Palace of Fine Arts, SF).
- Mat: a floor mat in the center with a tape arrow pointing "forward." The user starts standing on it.
- Containers around the mat: a cupboard (a cardboard box with a door and a shelf) in front, a drawer unit on the right, a bag on a chair on the left, and a box with a lid behind. The NFC "home spots" for salt and sugar are inside the cupboard; the other repo handles those.
- The user is blindfolded, wears AirPods Pro 2 (connected to the Mac, not the phone), and holds an iPhone 17 at chest height, upright, with the screen facing them and the bottom edge uncovered. The alternative to test is a shirt pocket, upside down, so the bottom microphone sticks out above the pocket. A pants pocket isn't supported.
- The Mac sits near the center edge of the space, running the hub and the Mac app. The phone and Mac share a network, preferably the iPhone's Personal Hotspot or a travel router, not the venue Wi-Fi.
- The beacons: 5 buzzers mounted around the perimeter at different heights, pointing toward the center. Wires run along table edges and walls, never across the walking area, because the user is blindfolded.
- The demo: the user walks from the mat to the cupboard by sound alone, opens it, and gets the wrong-jar correction (handled by the other repo). Then they ask for "my blood pressure pills" (in the box behind them), turn around, and walk there.

## 2. Shared conventions (MUST match the other repo exactly)

### 2.1 Coordinates

- Units are meters.
- +x = right, +y = forward, +z = up.
- The origin is the floor point directly under the center of the mat.
- "Forward" (+y) is the direction of the mat's tape arrow.
- Seconds for durations; Unix epoch seconds (float) for timestamps.

### 2.2 Placeholder geometry (real values come from tape-measuring in Phase C)

Beacons (the same objects as the other repo's config/space.json → "beacons"):

```json
{
  "beacons": [
    { "id": "B1", "position": [-1.5,  1.5, 1.8], "slot": 0 },
    { "id": "B2", "position": [ 1.5,  1.5, 0.3], "slot": 1 },
    { "id": "B3", "position": [ 1.5, -1.5, 1.8], "slot": 2 },
    { "id": "B4", "position": [-1.5, -1.5, 0.3], "slot": 3 },
    { "id": "B5", "position": [-1.8,  0.0, 1.0], "slot": 4 }
  ]
}
```

That's B1 front-left high, B2 front-right low, B3 back-right high, B4 back-left low, and B5 left side mid-height.

For reference only (owned by the other repo), the item spots are:
- cupboard salt [-0.08, 1.5, 1.0] and sugar [0.08, 1.5, 1.0]
- drawer [1.5, 0, 0.4]
- bag [-1.5, 0, 0.5]
- pill box [0, -1.5, 0.8]

Beacon-config import rule: the app and tools must accept either a bare `{"beacons":[...]}` file or the other repo's full space.json, reading only its beacons key and ignoring everything else.

### 2.3 Bus connection

- The hub runs a WebSocket server on the Mac at ws://<mac-ip>:8765, bound to 0.0.0.0, with a shared token.
- The auth method is configurable, because the other repo decides it. Support:
  - query: append `?token=<token>` to the URL. This is the default.
  - hello: send `{"type":"hello","component":"locator","token":"<token>"}` as the first message.
- All messages are JSON with a type field.
- Ignore every incoming message type except ptt.
- Send only these types: listener_pose, mic_audio, status, and ptt (the backup button only). Never invent other bus message types. Debug data stays local.

### 2.4 Contracts (exact; send no extra fields)

listener_pose (locator → hub):

```json
{ "type": "listener_pose",
  "position": [x, y, z],
  "quality": "ok | degraded | lost",
  "beacons_heard": 5,
  "source": "beacons | steps | sim | manual",
  "t": 1761350400.123 }
```

- position is the user's EAR position (center of the head), in the room frame. It equals the filtered microphone position plus the configured ear offset (section 6.8).
- t is the Unix time the position refers to (the measurement time), not the send time.
- beacons_heard is the number of beacons actually used in the solve.
- Publish rules:
  - Send one pose for each new fix (about 3.33 Hz when everything's working).
  - Don't send when a cycle produced no valid fix.
  - After 1.5 s with no valid fix, send exactly one pose with quality: "lost" (containing the last position), then send nothing until fixes resume.
  - The other repo's Mac app holds the last position after 1.5 s without a pose and falls back to the mat origin after 5 s. This rule keeps its timeouts meaningful.
- Quality is defined in section 6.9.

mic_audio (locator → hub, only while push-to-talk is active):

```json
{ "type": "mic_audio", "seq": 0, "sample_rate": 16000, "encoding": "pcm_s16le", "chunk_b64": "<base64>" }
```

- Mono, 16-bit little-endian PCM.
- sample_rate is configurable, default 16000. It must equal what the hub expects for Cartesia STT, so confirm it with the other repo.
- Chunks are 40 ms (640 samples at 16 kHz).
- seq resets to 0 at each PTT start and increments by 1 per chunk.

ptt (Mac app → bus, consumed by the locator; also sent by the locator's backup button):

```json
{ "type": "ptt", "state": "start | stop" }
```

status (locator → hub, every 2 s and whenever something changes):

```json
{ "type": "status", "component": "locator", "ok": true,
  "detail": "beacons 5/5, 3.3 fix/s, quality ok, src beacons" }
```

- ok is false when quality is lost, the mic isn't running, or the config is invalid.

Write all of this into contracts/ as JSON Schemas with examples, and validate the examples in tests. Also write docs/CONTRACT_NOTES.md, which summarizes sections 2.3–2.4 for the other team, including the publish rules, seq semantics, auth modes and t semantics.

## 3. Hardware available (the hardware desk catalog only; no piezo discs, no Bluetooth fobs, no speakers)

The relevant items:
- ESP32 (6 available)
- Passive buzzer, bare (21), and small passive buzzer module (5)
- NPN transistors: S8050 (70) and PN2222 (84)
- Resistors: 1 kΩ, 100 Ω and 10 Ω
- Diode 1N4007
- Wire: Dupont jumpers (male-to-male and female-to-male) and Ethernet cables (57), which may be cut only if the desk allows
- Boards: prototype expansion board, and the Arduino UNO R3 kit, which includes a breadboard (the standalone breadboard is unavailable)
- Power: USB charger block
- DHT11 temperature module (optional, for the speed of sound)

Not usable: the active buzzer (fixed tone, can't chirp) and the HC-SR04 ultrasonic sensor (40 kHz, above what the iPhone can record).

Facts to confirm with the human in Phase A (batch these):
1. The ESP32 board's exact module. Is it WROOM or WROVER? Read the metal can. On WROVER boards, GPIO16 and 17 are unavailable (used for PSRAM).
2. Whether the bare passive buzzers are magnetic (usually marked with + and −, with a coil inside) or piezo.
3. Whether the "small passive buzzer module" has 2 or 3 pins, and whether it has an on-board transistor, plus its pin labels. Some modules with an on-board transistor are active-low.
4. The transistor markings.
5. Whether a soldering station and hookup wire are available, and whether Ethernet cables can be cut.

## 4. Beacon firmware (firmware/beacons/beacons.ino)

### 4.1 Platform

- Arduino-ESP32 core 3.x, buildable with arduino-cli (so it also opens in the Arduino IDE).
- Verify the installed core version and its RMT API (rmtInit / rmtWrite / rmtWriteAsync, or the IDF 5 rmt_* driver) before writing code.
- Provide scripts/flash.sh, which compiles and uploads. It must print beginner instructions, including "hold BOOT if the upload hangs."

### 4.2 Pins

- Default (WROOM): B1 = GPIO16, B2 = GPIO17, B3 = GPIO18, B4 = GPIO19, B5 = GPIO21.
- WROVER alternative: B1 = 25, B2 = 26, B3 = 27, B4 = 32, B5 = 33. Selected by a #define BOARD_WROVER or a serial command `pins wrover`, and saved.
- Each pin idles inactive: LOW normally, HIGH when that beacon's invert flag is set. Never leave a buzzer driven with DC.
- Heartbeat: blink the onboard LED (GPIO2, if present) once per cycle.

### 4.3 The chirp waveform (shared definition; the app and tools use the identical definition)

- A square-wave linear frequency sweep of duration T = length_ms, from f_start to f_end.
- Rising sweep (B2–B5): f_start = f_lo, f_end = f_hi. Falling sweep (B1, the cycle marker): f_start = f_hi, f_end = f_lo.
- The instantaneous phase is φ(t) = 2π (f_start·t + (f_end − f_start)·t² / (2T)), for 0 ≤ t ≤ T.
- Edges happen where φ crosses k·π, for k = 1, 2, …. Output HIGH (active) on even half-cycles starting at t = 0, and toggle at each edge. Quantize edge times to a 0.1 µs tick (10 MHz).
- Defaults: f_lo = 2000 Hz, f_hi = 4500 Hz, length_ms = 12. Allowed: f_lo/f_hi from 1000 to 20000 Hz with f_hi − f_lo ≥ 1000 Hz; length_ms from 5 to 40.
- The final band is chosen in Phase B with the band test (section 7.3). 17–20 kHz is allowed if the buzzers are loud enough there.

### 4.4 The schedule

- Slot length slot_ms: default 50, allowed 30–100. There are 6 slots per cycle: slots 0–4 are B1–B5, and slot 5 is silent. Cycle = 6 × slot_ms = 300 ms by default.
- Each beacon's chirp starts exactly at the start of its slot.
- Timing requirement: slot-start jitter ≤ 20 µs RMS relative to the ESP32 crystal, and no cumulative drift beyond the crystal's own tolerance. Choose a mechanism that meets this and verify it. Candidates:
  - a hardware timer (gptimer) alarm notifying a high-priority task pinned to a core, which starts the RMT transmission
  - RMT channels started together through the IDF sync manager, in loop mode, if the chip supports it
  - on chips with fewer than 5 RMT TX channels (S3, C3), re-binding one channel to the next pin each slot
- Document the choice in docs/vendor-notes/espressif.md. The acceptance test is BRINGUP step B5 (section 10).

### 4.5 Serial interface (115200 baud, line-based, case-insensitive, prints OK or ERR <reason>)

| Command | Behavior |
|---|---|
| help | List the commands |
| run | Start the schedule |
| stop | Stop the schedule; all pins inactive |
| test | Chirp B1, B2, …, B5 once each, 1 s apart, printing `>> B1 chirp` before each (a wiring check) |
| beep <n> | Chirp beacon n (1–5) every 300 ms until stop |
| sweep <n> | On beacon n: 2 s of silence, print SWEEP START, sweep 1→20 kHz linearly over 10 s, print SWEEP END. Square wave, same tick |
| band <lo> <hi> | Set f_lo/f_hi in Hz, validated |
| len <ms> | Set the chirp length |
| slot <ms> | Set the slot length |
| invert <n> <0\|1> | Set beacon n's invert flag |
| pins <wroom\|wrover> | Select the pin map |
| status | Print running/stopped, settings and uptime |
| config | Print the chirp config JSON (section 4.6) on one line |
| save / defaults | Persist settings to NVS / restore the defaults |

Boot:
1. Print a banner with the version, the pin map and the config JSON.
2. Load settings from NVS.
3. After 2 s, auto-start run, so it works on a USB charger with no computer attached.
4. Print RUNNING and the cycle length.

### 4.6 Chirp config JSON (the single source of truth shared with the app and tools)

```json
{ "f_lo": 2000, "f_hi": 4500, "length_ms": 12, "slot_ms": 50, "n_slots": 6,
  "marker": { "beacon": "B1", "direction": "down" }, "others_direction": "up", "version": 1 }
```

The app has a "Paste chirp config" field. Firmware, app and tools must all use the same values.

## 5. Wiring (write docs/WIRING.md for absolute beginners: photos are optional, but describe the physical identification of every part)

Standard beacon circuit (repeat ×5):

```
ESP32 GPIO ──[1 kΩ]──► NPN BASE            (S8050 or PN2222)
                       NPN EMITTER ──► ESP32 GND
ESP32 5V/VIN ──[10 Ω]──► buzzer (+) ── buzzer (−) ──► NPN COLLECTOR
1N4007 across the buzzer: striped end (cathode) to the +5V side
```

- Transistor legs: the order varies by manufacturer. The doc must explain how to read the part number, find its datasheet pinout, and use a "flat face toward you, legs down" convention, with a note to swap the legs if there's no sound.
- Direct-drive test first (no transistor): GPIO ──[100 Ω]──► buzzer (+), buzzer (−) ──► GND. If the phone detects it at 4 m in the hall (Phase B), the team may skip the transistors entirely.
- 3-pin buzzer module: S/I/O → GPIO, + / VCC → 3.3V, − / GND → GND. If it sounds inverted (silent during beep, or clicking at idle), run `invert <n> 1`.
- Long runs (2–3 m): a cut Ethernet cable (one twisted pair per beacon; 4 beacons per cable) is preferred. Otherwise use chained Dupont wires with every joint taped. Label both ends of every wire (B1…B5).
- Mounting: buzzer opening facing the room's center; heights per section 2.2; tape firmly so nothing shifts after measuring.
- Power: a USB charger block or the Mac's USB port. Only one buzzer sounds at a time.
- "If no sound" checklist: the ESP32 is running (RUNNING printed, LED blinking) → test prints → the 5V pin has 5V → the transistor legs are right → the diode is oriented correctly → the invert flag → try direct drive.

## 6. The positioning algorithm (the spec; implement it identically in Python and Swift)

All parameters live in one config object (section 8.6), with these defaults.

### 6.1 Signal model

The phone records at sample rate fs (prefer 48000; use the actual rate reported). Beacon i (slot s_i) emits its chirp at time τ + s_i·slot, where τ is unknown, in the phone's sample clock. Its direct-path arrival at the microphone is:

a_i = τ + s_i·slot + |p − b_i| / c

where p is the mic position (unknown), b_i the beacon's position (known), and c the speed of sound.

- c = 331.3 + 0.606 × T_celsius m/s. The default T is 22 °C; it's editable, or comes from a DHT11 later (stretch).
- The ESP32-to-phone clock-rate difference (≤ about 50 ppm) is negligible within one cycle. Re-solve τ every cycle; never carry it over.

### 6.2 Templates

- Synthesized template: the section 4.3 waveform at fs, used for acquisition, the simulator, and before any captured templates exist.
- Captured template (preferred once available): per beacon, recorded during calibration (section 8.3). Captured templates include each buzzer's real frequency response.

### 6.3 Preprocessing

- Band-pass from f_lo − 300 to f_hi + 300 Hz (an FFT-domain mask or a linear-phase FIR; same behavior in both languages).
- Work in overlapping windows aligned to the cycle. Keep at least 1.0 s of history in a ring buffer indexed by an absolute sample counter.

### 6.4 Matched filter and envelope

- Correlate the window with the template via FFT.
- Compute the analytic correlation: zero the negative frequencies, take the inverse FFT, and use the magnitude as the envelope.
- SNR = envelope peak ÷ median envelope over the search window.

### 6.5 Cycle acquisition and tracking

- Acquire: search the last 400 ms for B1's falling-sweep marker, requiring SNR ≥ 10. Confirm it with a second marker 1 cycle later, within ±1 ms. This sets cycle phase.
- Track: the expected next marker = previous marker + cycle length, refined by a running estimate of the clock-rate ratio.
- Reacquire if the marker is missed for 3 consecutive cycles.

### 6.6 Per-beacon detection

- Search window:
  - Before the first valid fix: from the slot start (relative to the marker-derived τ estimate) to slot start + slot − 5 ms.
  - After a fix: the predicted arrival from the last filtered position, ±3.0 ms (gate_ms).
- First-arrival rule: let P be the largest envelope peak in the window. Pick the earliest local envelope peak with amplitude ≥ 0.5·P (−6 dB) that lies no more than 2.0 ms before P (lookback_ms). Refine it to a sub-sample position with parabolic interpolation over the 3 samples around the peak.
- Valid detection: SNR ≥ 8 (snr_min).
- During PTT the user's voice may reduce detections. That's acceptable; don't special-case it.

### 6.7 Solver (Gauss–Newton)

- Unknowns: θ = [x, y, z, τ] for the mic position.
- Measurements: valid arrivals a_i. Residual r_i = a_i − (τ + s_i·slot + |p − b_i|/c). Jacobian row = [ −(p − b_i)ᵀ / (c·|p − b_i|), −1 ].
- Height prior (a pseudo-measurement on z): mean 1.25 m, σ 0.25 m in hand mode (shirt pocket: mean 1.30 m, σ 0.20 m). Weight it as a measurement with σ converted consistently.
- Initialization: the last filtered mic position; otherwise [0, 0, 1.25]. Run at most 10 iterations; stop when |Δp| < 1 mm.
- Outlier handling: if there are 5 detections and any |r_i| > 0.30 ms (resid_max_ms), drop the worst one and re-solve with 4.
- Minimum detections: 4 for a normal fix; 3 is allowed only with the height prior, and yields degraded.
- Report the residual RMS in ms and the beacons used.

### 6.8 Filtering and output

- A 3D constant-velocity Kalman filter on the mic position: process noise acceleration σ = 1.5 m/s². Measurement σ = 0.05 m for ok fixes and 0.15 m for degraded ones.
- Ear position = filtered mic position + ear_offset. The default is [0, 0, +0.35] for hand mode and [0, 0, +0.30] for shirt-pocket mode. Mode is selected in settings.
- t = the Unix time of the cycle's mean arrival time, converted from the phone sample clock using hostTime anchors (section 8.1).

### 6.9 Quality

- ok: ≥ 4 beacons used, residual RMS ≤ 0.15 ms, and the fix is from the current cycle.
- degraded: 3 beacons used plus the height prior, or residual RMS between 0.15 and 0.30 ms.
- lost: no valid fix for 1.5 s. Send once, then stop (see section 2.4).

### 6.10 Latency

Time from the B5 chirp arriving at the mic to the listener_pose being sent: ≤ 100 ms on an iPhone 17.

## 7. Python tools (tools/, Python 3.11, managed with uv or pip + venv; tests with pytest)

### 7.1 tools/common/ (shared constants and definitions)

- Chirp synthesis exactly per section 4.3, the config loaders, and the beacon-config import rule from section 2.2.

### 7.2 tools/sim_beacons.py (the synthetic mic recording)

- Inputs: beacon config, chirp config, fs (default 48000), duration, a path (waypoints with times, or presets: stand_on_mat, walk_to_cupboard, walk_past_target, turn_around_walk_back, pocket_mode), the hand/pocket mode, noise level (SNR at 1 m), and random seed.
- Effects to model:
  - true time-varying propagation delay, including Doppler, implemented by resampling
  - 1/r spreading
  - a buzzer frequency response: a resonant band-pass centered at 2.7 kHz with Q ≈ 3, togglable
  - a floor reflection (coefficient 0.5) and one wall reflection (0.3)
  - body shadowing: −10 dB for beacons behind the user's facing direction (in the path spec)
  - an unknown start offset τ
  - an ESP32 clock error of ±50 ppm
  - hall-like noise (pink noise plus random speech-band bursts)
- Outputs: a WAV file (mono, 16-bit) plus truth.json (mic positions over time, beacon positions, parameters).

### 7.3 tools/band_test.py

- Input: a WAV recorded during the firmware's `sweep <n>` (detect the sweep onset automatically).
- Compute the received level versus frequency from 1 to 20 kHz, and save a plot.
- Recommend the 2.5 kHz-wide band that maximizes the minimum level across the band, and print the exact firmware command, for example `band 2100 4600`, plus the matching chirp config JSON.

### 7.4 tools/pipeline.py (the reference implementation of section 6)

- Run it on a WAV file (from the simulator or recorded on the phone). Output fixes.jsonl, with one line per cycle: t, mic position, ear position, quality, beacons used, the per-beacon SNR and arrival, and the residual RMS.
- Unit tests:
  - exact arrivals produce an exact solve
  - noisy arrivals produce bounded error
  - outlier rejection works
  - the 3-beacon height-prior path works
  - acquisition and reacquisition work
  - the first-arrival rule picks the direct path over a stronger echo

### 7.5 tools/analyze_log.py

- Plot per-beacon SNR over time, arrival times, residuals, the estimated position versus truth (when truth exists), the fix rate and the quality states.
- Print the median, 95th-percentile and max errors.

### 7.6 tools/fake_hub.py

- A WebSocket server on 0.0.0.0:8765 supporting both auth modes.
- Prints every incoming message (mic_audio summarized), validates them against contracts/, and records listener_pose to JSONL.
- Keyboard: p toggles ptt start/stop. It saves the received mic_audio of each push-to-talk turn to WAV for a listening check.

### 7.7 Acceptance (all automated)

- Simulator stand_on_mat and walk_to_cupboard, clean: median error < 3 cm, max < 5 cm.
- The same paths with echoes, noise, the buzzer response, Doppler and body shadowing: median < 8 cm, 95th percentile < 15 cm.
- fixes.jsonl shows ≥ 3.2 fixes per second while standing.

## 8. iPhone app (ios/EarmarkLocator/, Swift + SwiftUI)

### 8.1 Project and audio

- Deployment target iOS 17.0+ (the demo phone is an iPhone 17 on current iOS). Free Xcode personal-team signing must work: the app needs no special entitlements.
- Info.plist: NSMicrophoneUsageDescription, NSLocalNetworkUsageDescription (required for the LAN WebSocket), and NSMotionUsageDescription (for the steps fallback). Verify any other required keys.
- Audio session: category .record, mode .measurement (no AGC or noise suppression). Preferred input: the built-in mic. Data source: Bottom, omnidirectional polar pattern if available. Preferred sample rate 48000; read back and use the actual rate.
- The phone plays no audio. If AirPods or any Bluetooth device connect to the phone, input must stay the built-in mic. Show the current input route on screen.
- Capture: an AVAudioEngine input tap with a 2400-frame buffer (verify what iOS actually delivers). Keep an absolute sample counter from AVAudioTime.sampleTime. Detect discontinuities (dropped buffers). On a gap, reset tracking and log it.
- Clock mapping: for each buffer, store the pair (sampleTime, hostTime). Convert hostTime to Unix time via a mach-absolute-to-wall-clock offset computed at startup and refreshed every 10 s. Subtract inputLatency from AVAudioSession.
- Keep the screen awake while running. The app is foreground-only; it doesn't need to run in the background.
- Do all signal processing off the audio thread, on a serial queue, using Accelerate/vDSP for FFTs.

### 8.2 Screens (large text, high contrast, VoiceOver labels on every control)

1. Run (the main screen):
   - a big status line: TRACKING (ok) / DEGRADED / LOST / ACQUIRING
   - the ear position x, y, z with 2 decimals
   - beacons heard (B1…B5 as five indicators showing each one's SNR number)
   - fixes per second
   - hub connection state
   - a big Push to talk backup button
2. Debug: per-beacon SNR history sparklines, residual RMS, arrival offsets, the cycle-lock state, an input-route readout, a dropped-buffer counter, and a Record toggle.
3. Calibrate (section 8.3).
4. Manual (testing only): a mini top-down map of the room (beacons and the mat) with a joystick that moves a virtual ear position at walking speed (max 1.2 m/s) at z = 1.60 m. It sends listener_pose at 5 Hz with source: "manual", quality: "ok" and beacons_heard: 0. Show a clear banner whenever manual mode is active.
5. Settings:
   - hub URL, token and auth mode
   - mode (hand / shirt pocket), which sets the ear offset and height prior
   - air temperature
   - all section 6 parameters, with their defaults shown
   - "Paste chirp config," and "Import beacon config," which accepts a bare file or a full space.json
   - "Export all settings," which copies one JSON blob to the clipboard, and "Import all settings"

### 8.3 Calibrate screen (the guided flow; each step shows clear instructions and a pass/fail)

1. Beacon positions: edit or import. Show them as a list and a mini map; warn if all heights are within 0.5 m of each other.
2. Template capture: for each beacon B1…B5:
   - "Hold the phone about 10 cm from beacon Bn, bottom edge facing it. Tap Capture."
   - Record 3 s (10 cycles). Detect that beacon's chirp in its slot using the synthesized template. Align the 10 copies to sub-sample precision and average them coherently. Store the result as that beacon's template.
   - Show its SNR. Fail if SNR < 20 or fewer than 8 of 10 copies are detected.
3. Verify: "Stand on the mat, phone at chest." Show the solved mic position and its distance from [0, 0, 1.25]. Pass: horizontal error < 10 cm, and the height is plausible.
4. Check marks (optional): the human enters the coordinates of taped floor marks, stands on each, and the app shows the error.
5. Save point: "Hold the phone where the item lives, still for 2 seconds." Average the mic position (not the ear position) over 2 s. Require a standard deviation < 2 cm. Show `{"label": "...", "position": [x, y, z]}` with a Copy button, and keep a list exportable as JSON. These values go into the other repo's space.json spots.
6. Self-survey (stretch): with the phone held 2–3 cm from beacon k, the inter-beacon arrival differences give d_jk ≈ c·((a_j − s_j·slot) − (a_k − s_k·slot)) + 0.02 m. After visiting all beacons, use classical MDS for the geometry. Fix orientation using the human-entered beacon heights plus two designations: "Which beacon is front-left?" and "Which is front-right?". The result fills in the beacon positions; tape-measuring remains the default.

### 8.4 Networking

- URLSessionWebSocketTask with auto-reconnect (exponential backoff from 0.5 s to 5 s).
- Never queue stale poses. If not connected, drop them.
- Send status every 2 s and on any state change.
- Log every sent message type and its rate (not its contents) on the Debug screen.

### 8.5 Push-to-talk speech streaming

- On receiving ptt start (or pressing the backup button, which also sends ptt start / ptt stop to the bus):
  - Take the same 48 kHz mic stream, low-pass it, and decimate to sample_rate (default 16000) with vDSP.
  - Apply a simple gain normalization (target about −20 dBFS RMS, max gain +20 dB), since measurement mode has no auto-gain.
  - Convert to s16le and send 40 ms mic_audio chunks, with seq from 0.
- On ptt stop: flush the last partial chunk and stop sending.
- The beacon chirps will be faintly audible in the speech audio. That's expected; don't filter it, because filtering would also remove speech frequencies.
- Positioning continues during PTT.

### 8.6 Config object (persisted as JSON in the app's Documents folder; the same schema is used by the Python tools)

| Parameter | Default |
|---|---|
| fs (preferred) | 48000 |
| chirp config | per section 4.6 |
| gate_ms | 3.0 |
| lookback_ms | 2.0 |
| snr_min / snr_acquire | 8 / 10 |
| resid_max_ms / resid_ok_ms | 0.30 / 0.15 |
| height prior, hand mode | 1.25 m, σ 0.25 m |
| height prior, pocket mode | 1.30 m, σ 0.20 m |
| ear offset, hand mode | [0, 0, 0.35] |
| ear offset, pocket mode | [0, 0, 0.30] |
| Kalman acceleration σ | 1.5 m/s² |
| Kalman measurement σ (ok / degraded) | 0.05 / 0.15 m |
| lost timeout | 1.5 s |
| air temperature | 22 °C |
| mic_audio sample_rate / chunk | 16000 / 40 ms |
| hub URL / token / auth mode | (empty) / (empty) / query |

### 8.7 Record and file input

- Record: save the raw mic audio (mono, 16-bit, at the actual fs) plus log.jsonl (every detection, fix, quality change and sent pose, with sample index and Unix time). Share via AirDrop from the share sheet.
- File input (Debug → "Run on file"): process a WAV from the Files app through the same pipeline in real time. Send poses with source: "sim", and write fixes.jsonl for the parity check (section 9.4).

### 8.8 Steps fallback (stretch, only after Phase C passes)

- When beacon quality has been lost for over 1.5 s, and only if the user turns it on in Settings, dead-reckon from the last good fix.
- Use CMPedometer step events times a step length (default 0.65 m), along the walking heading from CMDeviceMotion (calibrated once against the beacon track while the user walks forward).
- Send poses with source: "steps" and quality: "degraded". Resume beacons the moment a valid fix returns.

## 9. Repo layout, tooling, tests

### 9.1 Layout

```
earmark-locator/
  LOCATOR_BRIEF.md
  contracts/            # listener_pose, mic_audio, ptt, status schemas + examples
  config/               # beacons.json, chirp.json, locator_params.json (defaults)
  firmware/beacons/     # beacons.ino (+ any headers)
  tools/                # common/, sim_beacons.py, pipeline.py, band_test.py, analyze_log.py, fake_hub.py
  tests/                # pytest: contracts, chirp synthesis, pipeline, solver
  ios/EarmarkLocator/   # Xcode project
  scripts/              # flash.sh, sim_all.sh, parity_check.sh
  docs/                 # STATUS.md, WIRING.md, BRINGUP.md, CONTRACT_NOTES.md, vendor-notes/
```

### 9.2 Task runner

A Makefile with targets test, sim, parity, flash, fakehub, and bandtest FILE=....

### 9.3 Tests

Contract examples validate; chirp edges match the formula; the pipeline acceptance criteria (section 7.7); and the firmware compiles in CI-style with arduino-cli compile.

### 9.4 Parity (required)

scripts/parity_check.sh runs both pipeline.py and the iOS file-input mode on the same simulator WAV, then compares the two fixes.jsonl files. Pass: the per-fix position difference is < 1 cm, and the quality labels are identical on ≥ 95% of fixes. Port the algorithm until this passes; don't "tune" Swift separately.

## 10. Phases and checkpoints

**Phase A: no hardware (you, autonomously)**
1. Check the toolchain: Xcode, Swift, iOS SDK, Python 3.11+, arduino-cli and the ESP32 core 3.x. Install what's missing, or tell the human how.
2. Build the contracts, configs, tools/common, the simulator, the pipeline, the tests and fake_hub. Make section 7.7 pass.
3. Write the firmware and make it compile for ESP32 (WROOM pin map by default).
4. Build the iOS app with every screen. Confirm file-input mode plus fake_hub work (run in the simulator where possible), then the parity check.
5. Write docs/WIRING.md, docs/BRINGUP.md and docs/CONTRACT_NOTES.md.
6. Checkpoint: report status, ask the section 3 facts in one batch, and tell the human the exact first hardware step. Stop.

**Phase B: one beacon (human-in-the-loop, guided by BRINGUP.md)**
- B1. Upload the firmware. Pass: RUNNING is printed and the LED blinks.
- B2. Wire one direct-drive beacon on B1's pin and run test. Pass: an audible chirp.
- B3. Band test. Run sweep 1, recording with the app's Record function from 1 m, then band_test.py. Set the recommended band and paste the chirp config into the app.
- B4. Detection range, in the actual hall. Run beep 1 with the phone at 1, 2, 3 and 4 m, and once with the beacon inside a closed cardboard box. Pass: SNR ≥ 10 at 4 m. If it fails, switch to the transistor circuit and retest. If it still fails, lower the band or lengthen the chirp to 20 ms, and report.
- B5. Timing. Wire a second beacon and place both side by side about 30 cm from the phone. Run the schedule for 60 s. Pass: B2 − B1 arrival differences = 50.000 ms ± 0.03 ms (std ≤ 0.02 ms).

**Phase C: five beacons, live positioning**
- C1. Wire and mount all 5 beacons per section 2.2, with different heights, wires off the floor and labels on.
- C2. Tape-measure the beacon positions relative to the mat origin (x right, y forward, z up) and enter them.
- C3. Template capture (section 8.3).
- C4. Verify on the mat. Pass: horizontal error < 10 cm.
- C5. Taped marks: 4 marks at 1–1.5 m from the origin in different directions. Pass: median error < 10 cm, max < 20 cm, quality ok at ≥ 90% of fixes.
- C6. Walking test with fake_hub recording, and the phone in both hand and pocket mode. Pass: a continuous track with no lost periods during a normal walk around the space. Run analyze_log.py on the recording and report.

**Phase D: integration with the real hub**
- Point the app at the Mac's hub. Confirm that the other repo's Mac app moves the listener and that the walking cue responds. Confirm PTT streaming reaches the concierge.
- Run docs/CONTRACT_NOTES.md against the other repo's actual schemas and report any mismatch to the human immediately, with the exact field difference.

**Phase E: demo hardening**
- Setup from scratch in ≤ 15 minutes, written as docs/SETUP_CHECKLIST.md: mount → measure → paste configs → template capture → verify → save points → hand off to the other repo's calibration.
- The firmware auto-runs on power.
- Settings export/import is used to sync the demo phone and a backup phone.
- Run a 30-minute soak test while walking: no crashes, no growing latency, no memory growth.

## 11. Fallback ladder (in order)

1. Weak detection: switch from direct drive to the transistor circuit → remove the 10 Ω resistors → aim the buzzers at the center → lengthen the chirp to 20 ms → lower the band → add the 6th buzzer.
2. Echo errors: reduce gate_ms to 2.0, raise slot_ms to 70, and check the first-arrival parameters with recorded logs.
3. Body shadowing: mount more beacons high; rely on the 3-beacon path with the height prior.
4. Beacons fail entirely: the steps fallback (section 8.8). Beyond that, the other repo's Mac app falls back to the fixed mat origin on its own.

## 12. Reporting format (at every checkpoint)

1. A table of components with status (done / partial / blocked), what's verified, and what's simulated.
2. Measured numbers (errors, SNR, fix rate, latency).
3. Blockers needing the human, as a numbered list.
4. The next three actions.

## Appendix A: decisions already made (do not revisit)

- Acoustic beacons as "GPS for the room"; the phone is the receiver and never transmits sound.
- No camera, ARKit or LiDAR. No UWB or Bluetooth Channel Sounding hardware this weekend.
- The phone plays no audio; the AirPods connect to the Mac.
- The chirp band defaults to 2.0–4.5 kHz, because passive buzzers are loud there. Change it only via the band test.
- Push-to-talk audio comes from the phone because the user walks away from the Mac.
- Python is the reference implementation; Swift matches it.

## Appendix B: message for the other repo's session (the human pastes this there)

LOCATOR INTERFACE NOTES (from the locator repo). Please confirm or flag conflicts:
1. listener_pose has exactly the fields: type, position [x,y,z] (EAR position, room frame, origin = floor under mat center, +x right, +y forward, +z up), quality (ok|degraded|lost), beacons_heard, source (beacons|steps|sim|manual), t (Unix seconds of the MEASUREMENT time).
2. Poses are sent about 3.3 Hz, only on valid fixes. After 1.5 s without a fix, the locator sends ONE pose with quality "lost", then nothing until it recovers. Treat "lost" as no pose; your 1.5 s hold and 5 s fallback timers still apply.
3. The Mac app derives velocity from successive poses for its 25+ Hz prediction (no velocity field).
4. mic_audio: pcm_s16le mono, sample_rate 16000 by default (configurable; tell us if Cartesia STT needs something else), 40 ms chunks, seq resets to 0 at each ptt start.
5. The locator listens for {"type":"ptt","state":"start|stop"} and may also send it from its backup button.
6. Bus auth: the locator supports ?token= on the URL (default) or a first message {"type":"hello","component":"locator","token":...}. Tell us which one the hub implements.
7. The locator also sends {"type":"status","component":"locator","ok":bool,"detail":str} every 2 s.
8. The locator reads beacon positions from the "beacons" key of your space.json: [{id, position, slot}].
9. Item spot coordinates are measured with the locator app's "Save point" (the mic position when the phone is held at the spot) and pasted into your space.json spots.
