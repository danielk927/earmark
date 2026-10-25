# Earmark macOS app and spatial spike

Earmark's Mac side: it renders the head-tracked spatial ping through AirPods (brief rule 11), plays speech, captures the mic, and talks to the hub over the local bus.
Everything is one SwiftPM package built without Xcode (Command Line Tools only).

| Product | What it is |
|---|---|
| `EarmarkAudio` (library) | Everything testable: head tracking, renderers, cues, guidance math, CoreAudio devices and routing, mic capture and voice gate, speech player, Apple Speech, bus client, and `EarmarkCore`, which wires bus messages to all of it. |
| `EarmarkUI` (library) | SwiftUI pieces shared by both apps: theme, status pills, angle dial, key monitor. |
| `SpatialSpike` -> `build/EarmarkSpatialSpike.app` | Phase 0.5 gate app. No bus, no network, no mic. |
| `EarmarkApp` -> `build/Earmark.app` | The judge-facing app (brief 5.E). |

Screenshots (mock head, no AirPods) are in `docs/screenshots/`.

## Build and run

On a Mac, run `scripts/mac_check.sh` (or `/mac-bringup` in Claude Code) to build and test everything.

```bash
mac/build_app.sh                                   # swift build -c release, bundle, sign, codesign --verify --strict
mac/build_app.sh --open spike -- --mock-head       # build, then launch the spike via `open -n`
mac/build_app.sh --open app                        # build, then launch Earmark.app (real AirPods, real mic)
mac/build_app.sh --open app -- --mock-head --no-mic
cd mac && swift test                               # 70 Swift Testing tests (no XCTest on this Mac)
```

- The script signs with the first `Apple Development` identity in the keychain, so permissions survive rebuilds.
  With no identity it signs ad-hoc and warns: macOS then re-asks for every permission after each rebuild.
- Bundles use the hardened runtime and the `com.apple.security.device.audio-input` entitlement, with `NSMicrophoneUsageDescription`, `NSSpeechRecognitionUsageDescription`, and `NSMotionUsageDescription`.
- `config/phrases/` (if present) is copied into `Contents/Resources/phrases`, and `config/space.json` into `Contents/Resources`.
- The repo root is written into Info.plist (`EarmarkRepoRoot`), so `logs/` and `config/` resolve from either app.
- Always launch with `open` (the script does), never by running `Contents/MacOS/...` from a shell: TCC charges permission prompts to the responsible process, and a shell-launched binary is attributed to Terminal.
- Logs of launched apps go to `logs/earmark_app.out.log` and `logs/spatial_spike.out.log`.

### Launch flags

Value flags must be one token, `--key=value`.
A separate bare value (`--bus-url ws://...`) is treated by AppKit as a document to open at launch, and then SwiftUI opens no window at all.

| Flag | App | Effect |
|---|---|---|
| `--mock-head` | both | Virtual head instead of AirPods (arrow keys, slider, or Sweep turn it). |
| `--no-mic` | app | No mic capture, so no permission prompt (unattended runs). |
| `--silent` | both | Cue and speech output at zero gain; the whole pipeline still runs. |
| `--renderer=<kind>` | both | `avaudio_hrtfhq` (default), `avaudio_auto`, `phase_manual`, `stereo_pan`. |
| `--bus-url=<url>` | app | Overrides `EARMARK_BUS_URL` (default `ws://127.0.0.1:8765`). |
| `--listen=ptt` / `--listen=always` | app | Push to talk (default) or always listening. |
| `--debug` | app | Opens the debug panel. |
| `--appearance=light` / `dark` | both | Overrides the system appearance. |
| `--mock-yaw=<deg>` | app | Initial virtual-head yaw (screenshots of behind or locked states). |
| `--log=<path>` | spike | Results log, repo-relative (default `logs/spatial_gate.jsonl`). |

Environment: `EARMARK_BUS_URL`, `EARMARK_PHRASES_DIR` (cached phrase WAVs), `EARMARK_MIC_UID` (pin a USB mic by its CoreAudio UID), `EARMARK_REPO_ROOT`.

### Keys

- `R`: recenter (both apps).
- `P`: switch the positioning system between UWB and Sound (app).
- `Space` (hold): push to talk.
- Left and right arrows: turn the virtual head 15 deg (Shift: 5 deg) when the mock head is on.
- These never fire while typing in a text field.

### End-to-end check without the hub

```bash
uv run --with 'websockets>=13,<16' python mac/tools/fake_bus.py --port 8799 &
open -n mac/build/Earmark.app --args --mock-head --no-mic --silent --bus-url=ws://127.0.0.1:8799
```

`mac/tools/fake_bus.py` sends a snapshot, `guide_start` (sugar), `speak_text`, a streamed `speak` (pcm_f32le, 48 kHz), a `guide_start` behind the listener, `speak_cached`, and `guide_stop`.
It checks that the app sent `hello` subscribing to `speak`, a `status` with every required `info` key, `playback` started and finished for all three speech kinds, exactly one `guide_feedback` behind (turn right), and `head_pose` at 10 Hz or less, then exits 0 or 1.
Use `--hold` to keep guidance active (for screenshots).
`mac/tools/window_id.swift` prints a window id for `screencapture -l`.

## Phase 0.5 spatial gate: procedure for the human

Do this before anything else (brief rule 11).
Record results in `docs/project/STATUS.md` (spatial gate table).

### 0. Set up

1. Connect the demo AirPods to this Mac and put them in.
2. From the AirPods icon in the menu bar, set Spatial Audio to **Off** (not Fixed, not Head Tracked).
   The app renders spatial audio itself; the system setting would process it a second time, and a forum report says it can also recenter the yaw while audio plays.
3. In System Settings > Sound > Input, check the input is **MacBook Pro Microphone**, not the AirPods.
   The spike also enforces this automatically and shows a notice when it switches.
4. Quit any app that uses the AirPods microphone (FaceTime, Zoom, Discord, dictation).
5. Run `mac/build_app.sh --open spike`.
6. Accept the motion permission prompt if one appears (it says "Earmark uses AirPods head tracking...").
   If you denied it earlier: `tccutil reset Motion com.earmark.spike`, then relaunch.
7. Check the header: HEAD TRACKING says "Tracking" with a rate (expect about 25 Hz or more), OUTPUT shows the AirPods at **48 kHz** with a check mark.
   If OUTPUT shows 16 or 24 kHz with a red X, the AirPods are in hands-free mode: fix that first (step 4, then reselect the AirPods as output).
   Note the LATENCY value.

### 1. Sign check (per renderer, at least for A - AVAudio HRTF-HQ)

1. Face straight ahead and press **R**.
2. Click **0 deg** under "Place the ping".
3. Turn your head **left**: the YAW readout must go **negative**, and the ping must move into your **right** ear.
4. Turn your head **right**: yaw positive, ping moves to your **left** ear.
5. Look **up**: PITCH must go **positive** (the ping may move slightly down; elevation is a weak cue, so trust the number).
6. Nod and watch PITCH and ROLL: if nodding moves ROLL instead of PITCH, note it in `docs/project/STATUS.md`.
7. If yaw has the wrong sign: in `mac/Sources/EarmarkAudio/HeadSigns.swift` change `yawSign` from `-1` to `1`, run `mac/build_app.sh --open spike`, and repeat from step 1.
   Same for `pitchSign`.
   These two constants are the only place the CoreMotion signs are applied.

### 2. Fixed-in-room test

1. Ping at 0 deg, press R facing forward.
2. Turn slowly 90 deg left, then 90 deg right, then back.
3. Pass: the ping stays put in the room (it moves across your ears as you turn) instead of following your head.
4. Then turn quickly and note any lag or smearing (Bluetooth latency).
5. Repeat for each renderer: A - AVAudio HRTF-HQ, A - AVAudio auto, B - PHASE manual tracking.

### 3. Pointing test (the gate: at least 8 of 10 within 20 deg)

The operator runs the spike; the tester wears the AirPods with eyes closed.

1. Pick the renderer and the ping timbre (start with Tone; try Broadband if front/back is confused).
2. Under Blind pointing test, choose **Front half**, type a tester pseudonym (never a real name), and press **New session**.
3. Tester faces forward; press R.
4. Press **Next trial**: a ping starts at a hidden random angle (front half, 5 deg steps, never within 15 deg of the last one), at a fixed rate so the rhythm gives nothing away.
5. The tester points at the sound with eyes closed.
6. The operator clicks the pointed direction on the dial (front is up, right is right; the stepper adjusts by 5 deg) and presses **Record response**.
   The true angle, the error, and any front/back confusion appear, and the trial is appended to `logs/spatial_gate.jsonl`.
7. Repeat to 10 trials; the Tally shows PASS or FAIL against 8 of 10 within 20 deg for this renderer and timbre.
8. Switch to **Behind** and run 4 trials; the Tally counts front/back confusions.
9. Repeat steps 1-8 for each renderer you want to compare (A-HRTFHQ, A-auto, B-PHASE).
10. Pick the renderer with the best pointing accuracy that passes, and set it as the default in Earmark.app Settings (or launch with `--renderer=...`).
11. If none passes, report the numbers and the failure (sign, drift, front/back, latency, hands-free) and try, in order: recheck routing (48 kHz), Broadband timbre, then the fallback ladder.

Each log line has `t`, `session_id`, `trial`, `set`, `renderer`, `timbre`, `target_deg`, `response_deg`, `error_deg`, `abs_error_deg`, `within20`, `front_back_confusion`, `head_tracking`, `yaw_at_response_deg`, `output_device`, `output_sample_rate`, `mock_head`, `tester`.

### 4. Routing check for Earmark.app

1. With the AirPods connected, run `mac/build_app.sh --open app` and allow the microphone.
2. The status bar must show MIC = MacBook Pro Microphone and OUTPUT = AirPods at 48 kHz, also while you hold Space and talk.
3. If OUTPUT drops below 44.1 kHz, a red banner appears: record it in `docs/project/STATUS.md` (audio routing check).

## Audio routing rule (what the app changes)

- On macOS `AVAudioEngine` follows the system default devices, and an engine can pull the default input into an aggregate device even for playback.
  If the default input is the AirPods mic, the AirPods drop to hands-free mode: mono, 16-24 kHz, no spatial cues.
- So at launch, before any playback engine is built, and whenever the default input changes, both apps check the system default input.
  If it is Bluetooth, they set it to the built-in microphone, log it, and show a notice ("Switched the system input from ... to MacBook Pro Microphone...").
  A USB or other wired mic you chose yourself is left alone.
  This changes a user-visible system setting; turn it off in Earmark Settings ("Keep the system input on the built-in microphone").
- Mic capture is pinned to the built-in mic separately (see Decisions), so even a brief AirPods default never opens the AirPods mic.
- The output device's nominal sample rate is watched; below 44.1 kHz on a Bluetooth output is flagged as hands-free mode in the UI and in `status` (`hfp_suspected`).
- Route changes (default input or output, device list, output sample rate, `AVAudioEngineConfigurationChange`) are debounced into one restart (0.4 s quiet, at most one restart per 1.5 s), then head tracking is re-checked and recentered.
  Device-list notifications that do not change the set of real devices (engines create private aggregates) are ignored, and the engines' own configuration notifications for 1 s after a restart are ignored, so there are no restart storms.

## Permissions

| Permission | Prompted when | Reset |
|---|---|---|
| Microphone | Earmark.app starts mic capture (not with `--no-mic`) | `tccutil reset Microphone com.earmark.app` |
| Speech recognition | The concierge switches to Apple Speech, or the bus is down, with the mic on | `tccutil reset SpeechRecognition com.earmark.app` |
| Motion (head tracking) | The first real head-tracking start (not with `--mock-head`) | `tccutil reset Motion com.earmark.app` (or `com.earmark.spike`) |

- Apple Speech also needs Dictation enabled (System Settings > Keyboard > Dictation) or it can fail even when it reports available.
- Denied motion shows "Not authorized" with the System Settings path, and guidance continues at ladder level 2.

## Fallback ladder

Applied automatically; the status bar shows "GUIDANCE - LEVEL n OF 4", and `status.info.guidance_mode` reports it.

1. `spatial_tracked`: spatial renderer plus head tracking (a mock head counts, with `head_tracking: mock`).
2. `spatial_untracked`: spatial renderer, head tracking unavailable, disconnected, or denied; the listener is fixed at yaw 0 (the calibrated forward) and the concierge adds clock-face directions.
3. `stereo_pan`: the chosen spatial renderer failed to start; exaggerated stereo panning (full pan at 45 deg; anything beyond 90 deg pans fully to the shorter-turn side).
4. `speech_only`: no renderer could start; guidance math and `guide_feedback` still run, so the concierge can speak directions.

## UWB walking guidance (docs/project/UWB-PRD.md section 10)

- The app subscribes to `listener_pose` and moves the audio listener there (any source: UWB, sound, simulator), gliding over `uwb.blend_s` from `config/hub.json` (default 0.4 s; Settings > Walking guidance overrides it). `fixed`, or no pose for 2 s, puts the listener back at the origin: the seated demo, unchanged.
- Guidance angles, behind, lock, and the clock face use the vector target - listener. The ping interval is the angle curve times a distance factor (1.0 within 1 m, 1.6 at 4 m and beyond).
- Distance attenuation (inverse, full volume within 0.6 m, no quieter beyond 8 m, rolloff 1) is tunable by ear in Settings. PHASE takes the rolloff only, and only when its renderer is built.
- `listener_command recenter` (the concierge's "recenter") recenters the AirPods like the R key. `head_pose` goes out at 10 Hz whenever head tracking runs.
- Dual positioning: UWB and sound chirps run together. The UWB / Sound picker (or `P`) sends `positioning_select`; the hub then sends only the chosen system as `listener_pose`, so the audio path is unchanged. The app subscribes to `positioning` (about 5 Hz) and mirrors `active` in the picker. The map draws the other system as a hollow dashed ring (hidden when its fix is older than 2 s or lost) and the list says e.g. "Sound: 0.18 m from UWB, 0.3 s old", "Sound: not heard" or "UWB: not tracking".
- `status.info` adds `uwb_mode` (`off` when no pose), `uwb_anchors_used`, `uwb_residual_m`.
- Settings > Calibrate UWB anchors: anchor positions in cm from the origin mark (same convention as `scripts/calibrate.py`), phone height and head offset, a five-mark verify against the PRD targets, recenter, and Save, which writes `config/space.json` (old file kept as `space.json.bak`) and sends `reset` so the hub reloads it. The file is found through `EARMARK_REPO_ROOT`, the `EarmarkRepoRoot` key `build_app.sh` writes, or a parent folder containing `BUILD_BRIEF.md`; without one, Save is off.

## Architecture

```
bus (BusClient) --> EarmarkCore --> SpatialRenderer (A: AVAudioCueRenderer env node | B: PHASECueRenderer | stereo pan | mock)
                       |   ^            ^ setListener on every motion sample, straight from the motion queue
                       |   |            |
                       |   +---- HeadTracking (HeadphoneMotionTracker | MockHeadTracker)
                       |
                       +--> Guidance (pure math, 50 Hz tick) -> ping interval, behind cue, locked tone, guide_feedback
                       +--> SpeechOutput (SpeechPlayer: speak chunks, cached WAVs, system voice) -> ducks the renderer
                       +<-- MicCapture (AVCaptureSession, built-in mic) -> MicPipeline/VoiceGate -> mic_audio | AppleSpeechRecognizer
AudioRouteController: input rule, device watcher, debounced restarts -> EarmarkCore.restartAudio
```

- `HeadTracking`: state (`connected`, `waiting`, `disconnected`, `not_available`, `not_authorized`, `mock`, `off`), message, latest pose (Earmark degrees relative to calibration), measured rate, `recenter()`.
  The CoreMotion tracker keeps a reference attitude (`multiply(byInverseOf:)`), smooths with a 30 ms wrap-aware filter, marks itself connected only when samples arrive, and drops to disconnected after 1 s without samples.
- `SpatialRenderer`: start, stop, restart, target (Earmark coordinates), listener yaw and pitch, ping interval, repeating cue (ping or behind), one-shot cues (`playLockedTone`, `playBehindCue`), duck, timbre, master gain, latency, and name.
  Option A maps `(x, y, z) -> AVAudio3DPoint(x, z, -y)`, uses `outputType = .headphones`, reverb off, no distance attenuation, mono sources, and rotates the listener.
  Option B drives a PHASE listener with the same head tracker (no entitlements) and plays each cue as a one-shot sound event.
- Cues are synthesized procedurally and precomputed: a 70 ms 1 kHz blip with soft attack (or a broadband blip plus high-passed noise), a two-note locked chime, and a low, muffled 190 ms behind thud.
- `Guidance`: signed azimuth error (head yaw vs `atan2(x, y)`), ping interval 900 ms at 90 deg or more down to 150 ms under 10 deg (smoothstep), locked under 8 deg for more than 300 ms (unlock above 12 deg), behind above 100 deg (front again under 95 deg) with the shorter turn.
- `EarmarkCore` is the only place that knows the bus; it is what the bus-handling tests drive with mocks.

## Decisions

- Guidance uses azimuth only (orchestrator decision): spots sit 30-45 cm below ear level and blind users orient horizontally before reaching, so a user facing the jar with a level head reaches "locked".
  Rendering still uses the full 3D position with yaw and pitch; elevation is shown in the debug panel.
- Mic capture uses `AVCaptureSession` pinned to UID `BuiltInMicrophoneDevice`, not a second `AVAudioEngine` input tap.
  The tap follows the system default input, so if macOS flips the default to the AirPods (it does on reconnect) capture would open the AirPods mic before the routing rule reacts; the capture session only ever opens the pinned device and never touches an output unit.
  The delivered format is checked per buffer and converted to 16 kHz mono Int16 if it differs, then cut into 100 ms chunks.
- Cues and speech run in separate `AVAudioEngine`s, so swapping renderers never interrupts speech and the layers can never mix through the environment node; ducking is a protocol call (-12 dB while speech plays, released 200 ms after it ends).
- Push to talk is the default listening mode: the judging hall is loud and Cartesia bills every streamed second.
  Always-listening uses an energy gate with a rolling 3 s noise floor, opens on 2 of 3 chunks 12 dB above it, sends 300 ms of pre-roll and 1 s of trailing audio, and caps an utterance at 30 s.
  Push to talk also sends 1 s of trailing audio after release so Cartesia's turn detection can finish.
- A new speech utterance interrupts the current one (`interrupted` is reported); late chunks of an interrupted utterance are dropped.
- `speak_text` and missing cached phrases use `AVSpeechSynthesizer.write`, rendered into the speech player so ducking and `playback` events work; if it produces nothing within 2.5 s, `/usr/bin/say` is the last resort.
- Apple Speech runs one recognition task per gated utterance (push-to-talk press or detected speech), on device when supported, with `contextualStrings` from object names and aliases, rolled over at 50 s.
  Only final results are sent as `transcript` (source `apple`); partials are shown as live captions.
- While the bus is down, mic audio is not buffered, but Apple Speech transcripts are queued for up to 10 s and delivered on reconnect.
- The locked tone is spatialized at the target and pings continue at 150 ms while locked, so the sound still marks where to reach.
- While the target is behind, the repeating cue becomes the behind thud at the guidance interval (900 ms).
- `head_pose` is sent at 10 Hz only while head tracking (or the mock head) is live; `status` is sent on any change of its fields and as a 10 s heartbeat.
- The default renderer is A - AVAudio HRTF-HQ until the gate picks one; the choice persists in user defaults.
- The spike places targets 1 m away, at ear level by default, with -20 deg and -35 deg (table) heights; blind trials use a fixed ping rate and 5 deg steps.
- A front/back confusion is a response in the other hemisphere that is closer to the target's mirror image across the ears than to the target; targets within 10 deg of the ears never count.
- Value flags are single-token `--key=value` (AppKit treats a bare value as a document to open and SwiftUI then opens no window).
- `.dataPlayedBack` completion callbacks drive `playback finished` (audible at the device); offline tests use `.dataRendered`, because `.dataPlayedBack` never fires in offline rendering.
- PHASE reports no latency, so the app shows the output device's CoreAudio latency for it.

## What is mocked tonight

- Head tracking: `MockHeadTracker` (virtual head) in every screenshot and in the end-to-end run; the CoreMotion path compiles and is wired but has not seen a real sample.
- Audio output: built-in speakers at zero gain (`--silent`); rendering conventions are verified by offline rendering through the production graph.
- Mic and Apple Speech: not started (`--no-mic`); the conversion, chunking, and gating are unit-tested, and routing to bus or Apple Speech is tested with a mock transcriber.
- The hub: `mac/tools/fake_bus.py`.

## Only real AirPods can verify (from docs/sponsors/vendor-notes/apple-spatial-audio.md section 10)

- `yawSign = -1` and `pitchSign = +1`, and whether nodding shows up in pitch or roll.
- The motion update rate, and whether motion flows from this SwiftPM-built bundle, when the app is not frontmost, or when the AirPods are not the active output.
- Whether a motion permission prompt appears and what `authorizationStatus()` reports after it.
- That the AirPods output stays at 48 kHz with the playback engine running, with capture running on the built-in mic, and after reconnecting the AirPods.
- `.HRTFHQ` vs `.auto` vs PHASE-manual on the pointing test and the front/back trials.
- Yaw drift over 5 minutes, and whether system Spatial Audio Off prevents the yaw recentering reported in Apple forum thread 844940.
- `presentationLatency` with AirPods, and whether it smears the fixed-in-room test.
- Also: that `AVCaptureSession` delivers 16 kHz Int16 as requested, and that Apple Speech accepts our 16 kHz buffers.

## Tests

`swift test` covers: the coordinate mapping and its determinant; offline-rendered conventions through the production renderer for HRTF-HQ and auto (+x target louder in the right ear, head turned left puts a front target in the right ear, head turned right puts it in the left ear, a front target is centered, the production ping is lateralized in both timbres), stereo-pan conventions and ducking depth; the PHASE listener and source transforms (PHASE has no offline rendering); guidance curve endpoints, monotonicity, smoothness, lock dwell and hysteresis, behind detection with the shorter turn, wrap-around at +-180, and elevation not affecting the error; `speak` decoding for both PCM formats including odd chunk boundaries; WAV loading and phrase lookup; speech playback events through the real player graph offline; the voice gate (silence, pre-roll, trailing audio, clicks, pauses, push to talk, noise floor); 48 kHz float to 16 kHz Int16 conversion; routing policy and the HFP detector; debouncing; the gate logger and tally; launch flags; and bus handling with a mock renderer and head tracker (guide_start, guide_stop, reset, stt_mode switching, exactly one behind feedback with jitter, locked tone, head_pose rate, status keys, ducking, captions, snapshot, the fallback ladder).
