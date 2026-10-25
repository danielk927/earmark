# Earmark spec B: core positioning engine

Owner: Person B.
Your folder: `ios/EarmarkCore/`, a Swift package with no UI.
Setup: see "Where the package goes" below.

## Your job in one paragraph

You build the math.
Audio samples come in, and out come chirp detections, a calibration, a live position and the guidance vector to the target.
Everything lives in a Swift package that builds and tests on a Mac with `swift test`, so you can work without phones, beacons or the room.
You use synthetic audio you generate yourself, plus A's recordings.
C's app calls your API from C6 and nothing else.

## What others need from you, and when

| Deliverable | Needed by | When |
|---|---|---|
| Package with the full C6 API as compiling stubs | C | CP0, in the first hour. C is blocked without it |
| Detector working on synthetic audio | C (debug view) | CP1 |
| Detector + calibrator working on A's fixtures | C | CP2 |
| Tracker + recovery | C | CP3 |
| Final guidance math | C | CP4 |

## Where the package goes and how to create it

The package lives at `ios/EarmarkCore/` inside the repo (layout in C0).
On a fresh machine, from the repo root:

```
mkdir -p ios/EarmarkCore && cd ios/EarmarkCore
swift package init --type library --name EarmarkCore
```

Then replace the generated Package.swift with:

```swift
// swift-tools-version:5.9
import PackageDescription

let package = Package(
    name: "EarmarkCore",
    platforms: [.iOS(.v16), .macOS(.v13)],
    products: [.library(name: "EarmarkCore", targets: ["EarmarkCore"])],
    targets: [
        .target(name: "EarmarkCore"),
        .testTarget(name: "EarmarkCoreTests", dependencies: ["EarmarkCore"])
    ],
    swiftLanguageVersions: [.v5]
)
```

Create `ios/EarmarkCore/CLAUDE.md` containing the single line `@../../docs/spec-B-core-engine.md`, and save this spec at `docs/spec-B-core-engine.md`.
Run Claude Code from `ios/EarmarkCore/`.

## Package rules

- Import only Foundation, simd and Accelerate.
  No UIKit, AVFoundation or CoreMotion, so `swift test` runs on a Mac.
- All tunable constants go in `Sources/EarmarkCore/Parameters.swift`, with the values in the parameter table at the end of this spec.
- Tests find the repo root from `#filePath` (go up from `Tests/EarmarkCoreTests/`) to read scene.json and fixtures/.

## B1. API stubs (do this first)

Implement every type and the `EarmarkEngineProtocol` from C6 exactly, with an `EarmarkEngine` that compiles and returns placeholder values:

- status `.notCalibrated`
- `valid == false` guidance
- empty diagnostics

Also implement `RoomConfig.load(from:)` for real, with a test that parses the C4 example.
Push to main and tell C.

Done when C's app builds against the package.

## B2. Test harness

1. Audio synthesizer (`Tests/Support/AudioSynth.swift`).
   It renders AudioBlocks of 4096 samples for:
   - a RoomConfig,
   - a receiver path p(t),
   - beacon clock offsets (±30 ms around each slot) and drift (±30 ppm),
   - speed of sound from the temperature, ±1 °C from the config,
   - white noise at a chosen SNR,
   - echoes: delayed and scaled copies of each chirp, 0.3–2.5 ms late, 0.3–1.2× the direct level,
   - body blocking: the direct path reduced by 15 dB for beacons behind the direction of travel,
   - Doppler: emit the chirp time-scaled by (1 − ṙ/c).
2. Detection simulator (`Tests/Support/DetectionSim.swift`), for tracker tests without signal processing.
   It produces arrival times with:
   - timing noise of 20 µs × (distance / 2 m),
   - 12% dropped chirps,
   - 6% echo detections, 0.3–2.5 ms late,
   - for beacons behind the walking direction, 50% dropped and 30% echoes,
   - the Doppler bias κ·ṙ/c.

Walk to use in tracker tests:

1. 15 s still at the calibration point.
2. Walk to (1.0, 0.8, 1.1) over 6 s.
3. Search there for 6 s.
4. Walk to (−1.0, 0.9, 1.3) over 8 s, then to (−1.0, −1.0, 1.2) over 8 s.

Add hand jiggle throughout: about 6 cm at 0.7–1.1 Hz.

## B3. Chirp detector

**Template.**
Let fs be the sample rate, T = 0.012 s, f0 = 18 000 Hz, f1 = 20 000 Hz and s = (f1 − f0)/T = 166 667 Hz/s.
Set M = round(T·fs) (576 at 48 kHz) and R = round(0.001·fs).
For n = 0 … M−1, with t = n/fs:

- phase φ(n) = 2π·(f0·t + ½·s·t²)
- fade w(n) = 0.5 − 0.5·cos(π·n/R) for n < R; 0.5 − 0.5·cos(π·(M−1−n)/R) for n > M−1−R; otherwise 1
- template h(n) = w(n)·e^{jφ(n)} / √(Σ w²), a complex template with unit energy

**Correlation.**
For every possible chirp start sample p, compute c(p) = Σₙ x(p+n)·conj(h(n)) and envelope e(p) = |c(p)|.
Use overlap-save with vDSP (any vDSP FFT API is fine):

1. FFT size N = 8192 and step L = N − M + 1.
2. Kernel g(k) = conj(h(M−1−k)) for k < M, zero-padded to N; G = FFT(g), computed once.
3. For each input segment x[q … q+N−1]: Y = IFFT(FFT(segment)·G).
   For j = M−1 … N−1, c(q + j − (M−1)) = Y(j).
4. Stream across AudioBlocks by keeping the last M−1 samples.
   If sampleTime jumps (dropped buffers), restart the stream at the new sampleTime without inventing samples.

A chirp's arrival time is the audio-clock time of its first sample: t = p_peak / fs, with p_peak on the sampleTime scale.

**Noise and SNR.**
Keep a running RMS of e(p) over samples outside every search window, as an exponential average with a 2 s time constant.
SNR (dB) = 20·log₁₀(peak / noiseRMS).

**Search windows** (one detection per beacon per cycle):

- Before calibration: the wall-clock time of sample p is block.wallClock + (p − block.sampleTime)/fs, and its phase is that time mod 0.5 s.
  Beacon k's window covers phases from k·0.125 − 0.045 s to k·0.125 + 0.060 s (wrapping around 0.5).
  The extra 15 ms covers travel time.
- After calibration: predicted arrival t_pred = a_k + b_k·n + (|p̂ − B_k| − d_k)/c, with symbols as in B4 and B5 and n the next cycle number.
  The window is t_pred ± 8 ms.

**Peak choice (echo defense).**
In each window:

1. Find the maximum envelope value Emax.
2. Take the earliest local maximum with e ≥ 0.5·Emax and SNR ≥ 12 dB.
   If none qualifies, there's no detection this cycle.
3. Refine it with a parabola through e(p−1), e(p), e(p+1): δ = ½·(e(p−1) − e(p+1)) / (e(p−1) − 2e(p) + e(p+1)).
   Use 0 if |δ| ≥ 0.5.
   The arrival is (p + δ)/fs.
4. Set ambiguous = true if the window maximum is more than 0.25 ms away from the chosen peak.

Internally, a detection is (beaconID, arrivalTime, snrDB, ambiguous).
It isn't part of the public API.

**Tests**

- Timing error under 20 µs RMS at 20 dB SNR.
- A direct path plus a 3 dB stronger echo 0.6 ms later picks the direct path in ≥ 95% of trials.
- 60 s of noise only produces zero detections.
- All four beacons are found in `fixtures/cal-static-20s` once it exists.
- Speed: under 3 ms per 4096-sample block on a Mac.
  C measures it on the iPhone, where the target is under 15 ms.

## B4. Calibrator

Between `startCalibration()` and `finishCalibration()`, collect detections (15 s required).
The receiver is at C = calibrationPoint.
For each beacon k with arrival times t₁ … t_N:

1. Number the cycles: nᵢ = round((tᵢ − t₁) / 0.5).
2. Fit tᵢ ≈ a_k + b_k·nᵢ by least squares.
3. Make the fit robust, repeating three times: residuals rᵢ = tᵢ − (a_k + b_k·nᵢ); MAD = 1.4826 · median(|rᵢ − median(r)|); keep points with |rᵢ| < max(3·MAD, 30 µs); refit on those points.
4. Timing noise σ_k = the standard deviation of the kept residuals, at least 20 µs.
5. Distance d_k = |C − B_k|.
6. Phase_k = (wall-clock time of a_k) mod 0.5 s.

b_k is that beacon's cycle length as measured on the receiver's clock, which captures its clock drift.

Fail (ok = false, with a reason in problems) if:

- any beacon has fewer than 20 kept detections,
- any beacon's σ_k·c exceeds 3 cm,
- or any two beacons' phases are within 40 ms of each other, measured around the 0.5 s circle.
  Name both beacons in the reason.

On success, start the tracker at position C with velocity 0 (B5).

Test: on synthetic audio and on cal-static-20s, the range computed for each beacon at C matches its true distance within 1 cm.

## B5. Tracker and recovery

**Constants:** speed of sound c = 331.3 + 0.606·temperatureC (m/s).
Doppler constant κ = f_center / s = 19 000 / 166 667 = 0.114 s.

**State:** x = [p; v], where p is position and v is velocity, both 3D.
Initial covariance P₀ = diag(0.03², 0.03², 0.03², 0.05², 0.05², 0.05²).

**Predict** to each detection's arrival time t, with Δt = t − t_last:

- F = [[I₃, Δt·I₃], [0, I₃]]
- Q: for each axis, the 2×2 block [[Δt⁴/4, Δt³/2], [Δt³/2, Δt²]]·σ_a², with σ_a = 1.0 m/s²
- x ← F·x, P ← F·P·Fᵀ + Q

**Measured range** for a detection from beacon k at time t:

- n = round((t − a_k) / b_k)
- r = c·(t − a_k − b_k·n) + d_k

**Measurement model** (this includes the Doppler bias):

- ρ = |p − B_k|, u = (p − B_k)/ρ, ṙ = u·v
- h(x) = ρ + κ·ṙ
- H = [ u + κ·(v − ṙ·u)/ρ , κ·u ], a 1×6 row
- R = (c·σ_k)² + 0.01²

**Update:**

1. Innovation y = r − h, with S = H·P·Hᵀ + R.
2. Gate: reject if y²/S > 9 and |y| > 0.05 m.
   Skip the gate while recovering.
3. Otherwise K = P·Hᵀ/S, x ← x + K·y, P ← (I − K·H)·P, then symmetrize P.

**Fixed height:** if receiverHeight isn't null, after each accepted update apply a second scalar update with H = [0,0,1,0,0,0], measurement receiverHeight and R = 0.05².

**Recovery** (required; a filter with only gating drifted off by meters in simulation once echoes were common):

- Trigger if any of these happen: no accepted update for 1.0 s, 4 rejections in a row, or √(P₁₁ + P₂₂ + P₃₃) > 0.5 m.
  Set status to recovering.
- Batch solve: take the latest measured range from each beacon, no older than 0.6 s.
  Solve min Σ(|p − B_k| − r_k)² by Gauss–Newton (10 iterations), starting from the last good p, with z held at receiverHeight if set.
  With 4 ranges, also solve each 3-beacon subset and keep the solution with the lowest RMS residual over the beacons it used.
- Reset if that RMS is under 5 cm: p = the solution, v = 0, P = diag(0.1², 0.1², 0.1², 0.3², 0.3², 0.3²).
  Status returns to tracking.
- After 3 s without a successful recovery, status is lost.
  Keep trying.

`state(at: t)` returns p + v·(t − t_last) without changing the filter, uncertainty √(P₁₁ + P₂₂ + P₃₃), and the current status.

**Tests** with the detection simulator, over 20 random seeds:

- Standing still: median ≤ 5 cm.
- Walking: median ≤ 15 cm, 95th percentile ≤ 35 cm.
- Jump the filter 1 m off mid-walk: it must return within 10 cm in under 2 s.
- With κ set to 0, walking error gets measurably worse.
  This proves the Doppler term is wired in correctly.

A Python prototype of this tracker met about 6 cm on clean data and about 11 cm with dropped chirps.
It drifted off by meters once echoes were common, before recovery was added.

## B6. Guidance math

1. Head point: (px, py, earHeight).
2. Smoothing: smooth the room-frame head-to-target vector with an exponential filter, τ = 0.25 s.
   Then rotate it by the current, unsmoothed ψ:
   - forward = Δx·sinψ + Δy·cosψ
   - right = Δx·cosψ − Δy·sinψ
   - up = Δz
3. Angles: azimuth = atan2(right, forward) in degrees; elevation from up versus the horizontal distance.
4. Modes and height hints: as defined in C6.

**Tests**

- A target straight ahead with ψ = 0 gives azimuth 0.
- The same target with ψ = +90° (judge turned right) gives azimuth −90° (now on the left).
- A sudden 1 m jump in position moves the output only about 63% of the way within 0.25 s, while a change in ψ takes effect immediately.

## B7. Diagnostics and thread safety

- Fill Diagnostics from the latest detections: per-beacon SNR, range, phase, accepted, ambiguous and count over the last 5 s; plus totals, recoveries and processing time.
- `process` runs on C's serial capture queue.
  `state`, `guidance`, `diagnostics` and `calibrationProgress` can be called from any thread.
  Protect shared state with a lock, and keep those calls under 1 ms.
- Test: call `guidance` at 1 kHz from another thread while processing 60 s of synthetic audio.
  Nothing may crash and no data race may occur; run with the Thread Sanitizer on.

## B8. Fixture tests

Read A's fixtures with a minimal WAV reader inside the tests (16-bit PCM and float32), since the package can't use AVFoundation.
For each fixture, report the detection rate per beacon and, where the truth is known, the position error.
Skip missing fixtures rather than failing.

## Parameter table (Parameters.swift)

| Group | Name | Value |
|---|---|---|
| Signal | f0, f1, chirp length, fade | 18 000 Hz, 20 000 Hz, 0.012 s, 0.001 s |
| Timing | cycle, slot spacing | 0.5 s, 0.125 s |
| Detector | FFT size | 8192 |
| | Pre-calibration window | slot − 45 ms … slot + 60 ms |
| | Post-calibration window | ±8 ms |
| | Minimum SNR, leading-edge ratio, ambiguity gap | 12 dB, 0.5, 0.25 ms |
| | Noise average time constant | 2 s |
| Calibration | Duration, minimum detections | 15 s, 20 per beacon |
| | MAD multiplier, residual floor | 3, 30 µs |
| | Timing noise floor, maximum residual, minimum slot gap | 20 µs, 3 cm, 40 ms |
| Tracker | σ_a, range floor | 1.0 m/s², 0.01 m |
| | Gate | χ² 9 and \|y\| 0.05 m |
| | Lost after, rejections before recovery, uncertainty limit | 1.0 s, 4, 0.5 m |
| | Recovery range age, recovery accept RMS | 0.6 s, 0.05 m |
| | Height σ | 0.05 m |
| Physics | κ, speed of sound | 0.114 s, 331.3 + 0.606·T |
| Guidance | Smoothing τ | 0.25 s |
| | Modes (horizontal) | far > 0.9 m, near 0.45–0.9 m, found < 0.45 m |
| | Height hints vs ear | high > ear − 0.10, low < ear − 0.60, otherwise chest |

# Shared contract (v1). Identical in all three specs

This section is copied word for word into spec A, spec B and spec C.
Change it only when all three owners agree.
Then bump the version number and update all three files in the same commit.

## C0. Repo layout

Everyone uses this layout.
If you only have your own spec, create it yourself; the paths matter because the CLAUDE.md imports and B's test code depend on them.

```
earmark/                               ← repo root (one git repo)
  CLAUDE.md                            ← shared rules
  scene.json                           ← A (until A pushes one, copy the C4 example)
  docs/
    spec-A-beacons-room-data.md
    spec-B-core-engine.md
    spec-C-ios-app.md
    setup.md, results.md               ← A
  beacon/                              ← A: index.html (beacon page) + CLAUDE.md
  fixtures/                            ← A: <name>.wav + <name>.json
  ios/
    EarmarkCore/                       ← B: Swift package
      Package.swift
      Sources/EarmarkCore/
      Tests/EarmarkCoreTests/
      CLAUDE.md
    EarmarkApp/                        ← C: Xcode project
      EarmarkApp.xcodeproj
      EarmarkApp/
      CLAUDE.md
  tools/dashboard/                     ← A (optional)
```

Each spec is self-contained: everything needed to build your part is in your spec plus this contract.

## C1. Who owns what

| Path | Owner | Others may |
|---|---|---|
| beacon/ | A | Read |
| fixtures/ | A (C's app may add recordings via A) | Read |
| scene.json | A | Read |
| docs/setup.md, docs/results.md | A | Read |
| tools/dashboard/ (optional) | A | Read |
| ios/EarmarkCore/ | B | Read; C depends on it as a local package |
| ios/EarmarkApp/ | C | Read |
| docs/spec-*.md, root CLAUDE.md | Shared | Change only by agreement |

Never edit a folder you don't own; ask its owner instead.
Each person works on their own branch and merges to main at each checkpoint (C9).
With no shared files, merges can't conflict.

Claude Code: run it from inside your own folder, and add a one-line CLAUDE.md there that imports your spec (shown at the top of your spec).
Claude Code loads both that file and the root CLAUDE.md.

## C2. Coordinates

Meters.
The origin is on the floor directly under the mat center.
+x is right, +y is forward (the direction of the mat's tape arrow), +z is up.

- A beacon's position is the center of the speaker grille that plays.
- A destination's position is where the item sits.
- The receiver's position is its microphone.

Head heading ψ is in radians, clockwise-positive, with 0 meaning facing +y.

## C3. Chirp signal and timing

| Item | Value |
|---|---|
| Chirp | Linear upward sweep 18 000 → 20 000 Hz, 12 ms long, raised-cosine fade 1 ms at each end, peak 0.9 of full scale |
| Output | One speaker only (one channel), device volume at maximum |
| Cycle | 0.5 s. Each beacon plays one chirp per cycle |
| Slots | B1 = slot 0, B2 = slot 1, B3 = slot 2, B4 = slot 3. Slot spacing 0.125 s |
| Slot alignment | Beacon in slot k starts its chirp at the speaker when unixTimeMs mod 500 == k × 125, using the device's own wall clock (set automatically) |
| Maximum beacons | 4 |

## C4. scene.json

A writes it, B parses it, and C bundles it into the app.
Field names are fixed:

```json
{
  "version": 1,
  "temperatureC": 21.0,
  "cycleSeconds": 0.5,
  "slotSeconds": 0.125,
  "chirp": { "f0": 18000, "f1": 20000, "duration": 0.012 },
  "beacons": [
    { "id": "B1", "slot": 0, "device": "iPhone (name)", "speaker": "left",  "position": [-1.50,  1.50, 1.90] },
    { "id": "B2", "slot": 1, "device": "iPhone (name)", "speaker": "left",  "position": [ 1.50,  1.50, 1.70] },
    { "id": "B3", "slot": 2, "device": "iPhone (name)", "speaker": "left",  "position": [ 1.50, -1.50, 2.00] },
    { "id": "B4", "slot": 3, "device": "MacBook",       "speaker": "right", "position": [-1.70, -0.30, 1.00] }
  ],
  "calibrationPoint": [0.0, 0.0, 1.45],
  "receiverHeight": 1.45,
  "earHeight": 1.62,
  "destinations": [
    { "name": "sugar jar",   "position": [ 1.20, 1.00, 0.90] },
    { "name": "keys",        "position": [-1.10, 0.90, 1.30] },
    { "name": "spice jar",   "position": [ 1.25, 1.05, 1.35] },
    { "name": "pill bottle", "position": [-1.00, -1.00, 0.45] }
  ]
}
```

- receiverHeight may be null, which means free 3D tracking.
- device and speaker are informational.
- The positions above are placeholders until A measures the room.

## C5. Fixture recordings

A records them, and C's app can record them too.
B and C use them for tests and replay.
Each fixture is two files with the same name:

- `fixtures/<name>.wav`: mono, 48 000 Hz (44 100 Hz allowed), 16-bit PCM or 32-bit float.
- `fixtures/<name>.json`:

```json
{
  "version": 1,
  "sampleRate": 48000,
  "wallClockAtFirstSample": 1792882334.512,
  "recorder": "mac-mic",
  "scene": "scene.json",
  "truth": { "type": "static", "position": [0.0, 0.0, 1.45] },
  "notes": "B3 blocked by a person from 8 s to 12 s"
}
```

| Field | Meaning |
|---|---|
| wallClockAtFirstSample | Unix seconds at the first sample, accurate to ±20 ms. Needed to assign slots |
| recorder | "mac-mic", "iphone-app" or "other" |
| scene | Path to the scene file that was in effect, relative to the repo root |
| truth | `{ "type": "static", "position": [...] }`, `{ "type": "route", "points": [[x,y,z], ...] }` (a walked route with no timing), or `{ "type": "none" }` |

## C6. Core engine API (Swift)

B implements this in ios/EarmarkCore; C calls it.
Use Swift 5 language mode.

```swift
import simd

public struct RoomConfig: Codable {          // mirrors scene.json; named to avoid SwiftUI's `Scene`
    public struct Chirp: Codable { public let f0: Double; public let f1: Double; public let duration: Double }
    public struct Beacon: Codable { public let id: String; public let slot: Int; public let device: String?; public let speaker: String?; public let position: [Double] }
    public struct Destination: Codable { public let name: String; public let position: [Double] }
    public let version: Int
    public let temperatureC: Double
    public let cycleSeconds: Double
    public let slotSeconds: Double
    public let chirp: Chirp
    public let beacons: [Beacon]
    public let calibrationPoint: [Double]
    public let receiverHeight: Double?
    public let earHeight: Double
    public let destinations: [Destination]
    public static func load(from data: Data) throws -> RoomConfig
}

public struct AudioBlock {
    public let samples: [Float]      // mono, nominally -1...1
    public let sampleRate: Double
    public let sampleTime: Int64     // audio-clock index of samples[0]; grows by samples.count unless buffers were dropped
    public let wallClock: Double     // Unix seconds at samples[0]; used only to assign slots before calibration
    public init(samples: [Float], sampleRate: Double, sampleTime: Int64, wallClock: Double)
}

public enum TrackStatus: String { case notCalibrated, calibrating, tracking, recovering, lost }

public struct TrackState {
    public let time: Double                 // audio-clock seconds this state describes
    public let position: SIMD3<Double>      // m, room frame
    public let velocity: SIMD3<Double>      // m/s
    public let uncertainty: Double          // m, sqrt(trace of position covariance)
    public let status: TrackStatus
}

public enum GuidanceMode: String { case far, near, found }
public enum HeightHint: String { case low, chest, high }

public struct Guidance {
    public let destination: String
    public let distance: Double             // m, 3D, head point to destination
    public let horizontalDistance: Double   // m, floor-plane distance; decides the mode
    public let headRelative: SIMD3<Double>  // m; x = right, y = forward, z = up
    public let azimuthDeg: Double           // clockwise from straight ahead, -180...180
    public let elevationDeg: Double
    public let mode: GuidanceMode           // far > 0.9 m, near 0.45–0.9 m, found < 0.45 m (horizontal)
    public let heightHint: HeightHint       // vs earHeight: high > ear-0.10 m, chest ear-0.60...ear-0.10, low < ear-0.60
    public let valid: Bool                  // false unless status is tracking or recovering
}

public struct BeaconDiagnostics {
    public let id: String
    public let lastSNRdB: Double?
    public let lastRangeM: Double?
    public let lastPhaseSeconds: Double?    // arrival phase within the cycle, wall-clock based
    public let lastAccepted: Bool
    public let lastAmbiguous: Bool
    public let detectionsLast5s: Int
}

public struct Diagnostics {
    public let beacons: [BeaconDiagnostics]
    public let acceptedTotal: Int
    public let rejectedTotal: Int
    public let recoveries: Int
    public let processingMsPerBlock: Double
}

public struct BeaconCalibration { public let id: String; public let detections: Int; public let residualCm: Double; public let phaseSeconds: Double }
public struct CalibrationReport { public let ok: Bool; public let beacons: [BeaconCalibration]; public let problems: [String] }
public struct CalibrationProgress { public let elapsed: Double; public let required: Double; public let detections: [String: Int] }

public protocol EarmarkEngineProtocol: AnyObject {
    init(config: RoomConfig) throws
    /// Call from one serial queue, in sampleTime order. Must return in < 15 ms for 4096 samples on an iPhone.
    func process(_ block: AudioBlock)
    /// Receiver at config.calibrationPoint, judge facing +y, holding still.
    func startCalibration()
    var calibrationProgress: CalibrationProgress { get }
    /// If ok == false, status returns to .notCalibrated and problems says why.
    func finishCalibration() -> CalibrationReport
    /// Call after an audio route change or engine restart.
    func invalidateCalibration()
    /// Extrapolates without changing the filter. Thread-safe, < 1 ms.
    func state(at audioTime: Double) -> TrackState
    /// headYaw = ψ (C2). Thread-safe, < 1 ms, called at 30 Hz.
    func guidance(at audioTime: Double, headYaw: Double, destination: String) -> Guidance
    var diagnostics: Diagnostics { get }
}

public final class EarmarkEngine: EarmarkEngineProtocol { /* B implements */ }
```

Audio time.
audioTime arguments are seconds on the same clock as AudioBlock.sampleTime / sampleRate.
C converts "now" to audio time from the latest captured buffer's AVAudioTime (sample time plus host time).

## C7. Telemetry (optional, only if time allows)

The app sends JSON at 10 Hz over a WebSocket to `ws://<mac-name>.local:8765/earmark`:

```json
{ "t": 123.45, "status": "tracking", "p": [0.41, 0.22, 1.45], "u": 0.04,
  "dest": "sugar jar", "dist": 1.23, "mode": "far",
  "beacons": [ { "id": "B1", "snr": 22.1, "ok": true } ] }
```

## C8. Design decisions to keep

1. The scene type in Swift is RoomConfig, not Scene, to avoid clashing with SwiftUI's Scene.
2. Guidance modes use horizontal (floor-plane) distance, because the judge can never stand inside a shelf.
3. Height hints are low, chest and high, relative to ear height.
4. Position smoothing happens in room coordinates before applying head rotation, so the sound responds instantly to head turns.
5. All beacons use one chirp shape; slots tell them apart.
   This keeps the full 2 kHz bandwidth for every beacon.

## C9. Checkpoints

| Checkpoint | A | B | C |
|---|---|---|---|
| CP0: first hour | Draft scene.json pushed | API stubs from C6 pushed; they compile and return placeholder values | Xcode project builds against the stubs, running on MockEngine |
| CP1 | Beacon mode on 4 devices; recorder makes fixtures | Detector passes synthetic-audio tests | Live capture into AudioBlock; raw recorder writes fixtures |
| CP2 | First fixture set in fixtures/ | Detector and calibrator pass on A's fixtures | Debug view shows real detections from the real engine, live |
| CP3 | Room measured; floor-mark test run | Tracker and recovery meet targets in simulation and on fixtures | Calibrate → track flow working on device |
| CP4 | Blindfold test run and logged | Guidance math final | Spatial audio and speech end to end |

At each checkpoint, everyone merges to main, pulls, and runs one combined test in the room.
