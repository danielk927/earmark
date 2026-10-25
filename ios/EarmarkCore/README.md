# EarmarkCore

The positioning engine from spec B (`docs/spec-B-core-engine.md`).
Audio blocks go in; chirp detections, calibration, a tracked position and guidance to a destination come out.
It imports only Foundation, simd and Accelerate, so it builds and tests on a Mac.

## Using it from the app

Add `ios/EarmarkCore` to the Xcode project as a local package and link the `EarmarkCore` library.

```swift
let config = try RoomConfig.load(from: Data(contentsOf: sceneURL))
let engine = try EarmarkEngine(config: config)

// Capture queue, in sampleTime order:
engine.process(AudioBlock(samples: mono, sampleRate: 48_000, sampleTime: time.sampleTime, wallClock: Date().timeIntervalSince1970))

// Calibration: judge at config.calibrationPoint, facing +y, holding still.
engine.startCalibration()
// ... poll engine.calibrationProgress until elapsed >= required (15 s) ...
let report = engine.finishCalibration()     // report.problems says what to fix when !report.ok

// Any thread:
let guidance = engine.guidance(at: audioNow, headYaw: psi, destination: "sugar jar")
let state = engine.state(at: audioNow)
let diagnostics = engine.diagnostics
```

- `process` must run on one serial queue.
  `state`, `guidance`, `diagnostics` and `calibrationProgress` are safe from any thread and take about 0.01 ms each.
- `audioNow` is in seconds on the `sampleTime / sampleRate` clock.
- Call `invalidateCalibration()` after an audio route change or engine restart, then calibrate again.
- Until calibration succeeds, `state` reports the calibration point with `uncertainty` 0 and status `.notCalibrated`, and `guidance` has `valid == false`.
- The value types have public memberwise initializers, so a `MockEngine` can build them.

## Tests

```
cd ios/EarmarkCore && swift test
```

The Command Line Tools ship without XCTest, so the tests use Swift Testing (`import Testing`), which also runs in Xcode 16+.
They print their measurements; the numbers below are from the current code.

| What | Result | Spec target |
|---|---|---|
| Timing error, 20 dB input SNR | 1.6 µs RMS | < 20 µs |
| Direct path vs a 3 dB stronger echo 0.6 ms later | 100% | ≥ 95% |
| 60 s of noise | 0 detections | 0 |
| `process`, 4096 samples, Mac | 0.5 ms CPU debug, 0.04 ms release | < 3 ms |
| Ranges at the calibration point after calibrating | worst 0.12 cm | < 1 cm |
| Tracker, still (fixed height) | median 2.2 cm | ≤ 5 cm |
| Tracker, walk (fixed height) | median 3.1 cm, p95 15.5 cm | ≤ 15 cm, ≤ 35 cm |
| Tracker, 1 m jump (fixed height) | back within 10 cm after median 1.0 s; 17 of 19 seeds under 2 s, worst 2.5 s | < 2 s |
| Doppler term (median walk error, κ vs κ = 0) | 3.2 vs 4.4 cm | worse without κ |
| End to end on synthetic audio (8 walks) | median 3.8 cm, p95 13.9 cm | (not in spec) |

Tracker numbers use the detection simulator over 20 seeds.
About one seed in 20 fails calibration because a beacon keeps fewer than 20 of its 30 chirps at a 12% drop rate; those seeds are skipped, as the app would recalibrate.

`fixtures/` is read when present: every fixture's per-beacon detection rate and position error are printed, and `cal-static-20s` must find all four beacons and give ranges within 1 cm.
A synthetic recording in the same format tests that path until A's recordings land.

## Where this differs from spec B, and why

- **σ_a is 0.5 m/s², not 1.0.**
  With 1.0, the predicted range spread for a beacon heard about once a second grows to about 25 cm, the χ² gate admits most echoes, and simulated walks diverged by meters.
- **Late ranges more than 10 cm beyond the prediction are rejected, also while recovering** (`echoRejectAbove`).
  Echoes are at least 0.3 ms (10 cm) late and never early, so this rejects them without affecting direct paths.
  This was the largest single improvement.
- **Recovery triggers on 4 rejections among the last 8 updates**, not only 4 in a row.
  A diverged filter that still accepts one beacon's ranges while sliding along its circle never produced 4 in a row.
- **Entering recovery raises P** to at least 0.3 m and 0.3 m/s, so the ungated updates can actually move the state.
- **Calibration starts from a Theil–Sen line and trims on |r − median(r)|.**
  Trimming on |r| as written fails when a clump of echoes tilts the first least-squares fit.
- **Recovery solves only overdetermined beacon sets.**
  A 3-beacon subset in free 3D has as many ranges as unknowns, always fits with zero residual, and would always win.
- **`state(at:)` extrapolates at most 1 s past the last detection**, so a stale velocity can't carry the position across the room.
- `RoomConfig.load` rejects a scene whose chirp or timing differs from C3, duplicate slots, or positions without three numbers.

## Known limits

- **Free 3D** (`receiverHeight: null`) misses the walking targets: median 7.1 cm but p95 58 cm, and the jump test takes a median 2.1 s.
  The placeholder beacons span only 1.0–2.0 m in height, so height is weakly observed.
  Fixed height (the scene default) meets the targets; free 3D needs beacons spread further in height.
- **Echoes close to the direct path.**
  An echo's phase depends on its exact delay.
  Within about 0.8 ms of the direct path (the chirp resolves 0.5 ms), some phases merge the two peaks, and the earliest-local-maximum rule then picks the echo.
  The spec's 0.6 ms echo test passes because a pure delayed copy has a favourable phase.
  The printed phase sweep shows the rest.
- **Thread Sanitizer** can't run on the development Mac (macOS 26.5.1 with Command Line Tools): even a C hello world built with `-fsanitize=thread` crashes.
  The concurrency test runs without it.
  Run it under Xcode's Thread Sanitizer to complete B7.
