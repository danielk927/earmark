# Apple head tracking and spatial audio on macOS

Vendor notes for Earmark rule 11, brief sections 4.1, 5.E and Phase 0.5.
Researched 2026-10-24 against Apple's documentation JSON (`https://developer.apple.com/tutorials/data/documentation/<path>.json`) and the local SDK headers at `/Library/Developer/CommandLineTools/SDKs/MacOSX15.5.sdk`.
Environment checked: macOS 26.5.1 (25F80), Swift 6.1.2, Command Line Tools only, one signing identity `Apple Development: daniel214940@icloud.com (PDF7CUACBD)` with TeamIdentifier `29R3JXG54K`.
AirPods were not connected during research, so nothing here was tested on real AirPods.

Legend:
- **VERIFIED LOCALLY** means I compiled and ran it on this Mac (offline rendering, CoreAudio queries, bundle build, codesign, `open` launch, `swift test`).
- **UNVERIFIED** means the claim comes from community sources or inference and must be checked on real AirPods in Phase 0.5.
- `SDK:` paths are relative to `MacOSX15.5.sdk/System/Library/Frameworks/`.

---

## 0. Decisions in one screen

- **Coordinate mapping (VERIFIED LOCALLY):** Earmark `(x right, y forward, z up)` maps to `AVAudio3DPoint(x: x, y: z, z: -y)`.
  PHASE uses the same axes as AVAudio3D.
- **Listener yaw (VERIFIED LOCALLY):** `AVAudio3DAngularOrientation.yaw` in degrees, positive means turned right, which equals Earmark head yaw.
  Pitch in degrees, positive means looking up.
- **Head-tracking sign:** CoreMotion yaw is positive when the head turns LEFT (right-hand rule about the vertical +Z), so `yawSign = -1`.
  This is derived from Apple's right-hand-rule figure and agrees with community code, but it is UNVERIFIED on hardware.
- **Renderer recommendation: Option A** (`AVAudioEngine` + `AVAudioEnvironmentNode` + manual head tracking from `CMHeadphoneMotionManager`).
  It needs no special entitlement or provisioning profile.
- **Option B (PHASE):** PHASE has been on macOS since 12.0.
  Automatic head tracking (`automaticHeadTrackingFlags = .orientation`) and the Personalized Spatial Audio profile both need macOS 15+, plus the `com.apple.developer.coremotion.head-pose` and `com.apple.developer.spatial-audio.profile-access` entitlements.
  Those two capabilities are offered only to paid Apple Developer Program or Developer ID teams, never to free accounts.
  Using them means a provisioning profile embedded in the bundle.
  The same two entitlements also unlock automatic head tracking and the personal profile for `AVAudioEnvironmentNode`, so none of this is unique to PHASE.
- **Input device:** on macOS, `AVAudioEngine` input and output follow the system default devices.
  The robust rule is to make the built-in mic the system default input and re-assert it whenever it changes.
  Optionally, capture through `AVCaptureSession` pinned to UID `BuiltInMicrophoneDevice`, which delivers 16 kHz Int16 directly.
- **Info.plist:** `NSMicrophoneUsageDescription`, `NSSpeechRecognitionUsageDescription`, `NSMotionUsageDescription`.
- **Hardened runtime entitlement:** `com.apple.security.device.audio-input`.
- **No Xcode (VERIFIED LOCALLY):** the whole path works here.
  The SwiftPM SwiftUI executable builds, the hand-made `.app` is codesigned with `--options runtime` and the Apple Development identity, it launches via `open`, and TCC status is attributed to the bundle ID.
  `swift test` works with Swift Testing.
  XCTest is not installed.

---

## 1. `CMHeadphoneMotionManager` on macOS

### Availability and API surface

- Class availability: macOS 14.0, iOS 14.0, watchOS 7.0 (`SDK: CoreMotion.framework/Headers/CMHeadphoneMotionManager.h`, https://developer.apple.com/documentation/coremotion/cmheadphonemotionmanager).
- `isDeviceMotionAvailable`, `authorizationStatus()`, `startDeviceMotionUpdates(to:withHandler:)`, `startDeviceMotionUpdates()` plus polling `deviceMotion`, and `stopDeviceMotionUpdates()` are all macOS 14.0 per the docs.
- `startConnectionStatusUpdates()`, `stopConnectionStatusUpdates()` and `isConnectionStatusActive` are in the 15.5 SDK header but not in the 14.5 SDK header.
  The docs list them as macOS 14.0.
  They are fine on macOS 26.
  Use them to get connect and disconnect callbacks before motion starts.
- Delegate `CMHeadphoneMotionManagerDelegate` has optional `headphoneMotionManagerDidConnect(_:)` and `headphoneMotionManagerDidDisconnect(_:)`.
  The header says these are "Invoked when a headphone is connected / disconnected", and that they run on the operation queue used for motion updates, or on the main thread if none was given (`SDK: CoreMotion.framework/Headers/CMHeadphoneMotionManagerDelegate.h`).
- `CMAuthorizationStatus`: `notDetermined = 0`, `restricted`, `denied`, `authorized` (`SDK: CoreMotion.framework/Headers/CMAuthorization.h`).
- VERIFIED LOCALLY: with no AirPods connected, `isDeviceMotionAvailable == true` and `authorizationStatus() == .notDetermined`, both from a CLI binary and from the signed bundle.
  So `isDeviceMotionAvailable` means "this Mac supports the service", not "AirPods are connected".
  Drive the "connected" UI from the delegate callbacks and from motion samples actually arriving.
- `CMDeviceMotion.sensorLocation` reports `.headphoneLeft` or `.headphoneRight` (which bud is streaming) (`SDK: CoreMotion.framework/Headers/CMDeviceMotion.h`).

### Info.plist and entitlements

- `NSMotionUsageDescription` is required.
  Apple: "If this key is absent, the system crashes your app when you start device-motion updates" (https://developer.apple.com/documentation/coremotion/cmheadphonemotionmanager, https://developer.apple.com/documentation/bundleresources/information-property-list/nsmotionusagedescription).
- No entitlement is needed for `CMHeadphoneMotionManager` itself in a non-sandboxed app.
  None is documented, and the class page lists only the plist key.
- `com.apple.developer.coremotion.head-pose` is a different thing.
  It is required only for the system's automatic head tracking inside AVAudioEnvironmentNode, AUSpatialMixer or PHASE (section 4).
- UNVERIFIED: whether macOS shows a motion permission prompt on first `startDeviceMotionUpdates`.
  The `notDetermined` status suggests a prompt will appear.
  Plan for it and handle `.denied` with an on-screen message.

### Reference frame, axes, sign conventions

- Headphone axes are shown in the figure on the class page, which has the alt text "positive x-axis, positive y-axis, and positive z-axis for motion-capable Apple headphones".
  The image is at https://developer.apple.com/tutorials/images/com.apple.coremotion/media-4302074@2x.png.
  Z points up out of the top of the head.
  X and Y are horizontal.
- Attitude angles are in radians, in the range -pi to pi.
  They are 0 when the device matches the reference frame (https://developer.apple.com/documentation/coremotion/getting-processed-device-motion-data).
- The default reference frame is `xArbitraryZVertical`: "the z-axis perpendicular to the ground", with x and y set from the device's orientation at start (same doc, and `SDK: CoreMotion.framework/Headers/CMAttitude.h`).
  So yaw is a rotation about the world vertical, and yaw 0 is the head direction when updates started.
- Rotation signs follow the right-hand rule.
  Apple's figure (https://developer.apple.com/tutorials/images/com.apple.coremotion/media-4251993@2x.png) shows a thumb along each +axis with positive rotation counterclockwise.
  With +Z up, positive yaw is counterclockwise seen from above, which is turning LEFT.
  So `earmarkYaw = -cmYaw`.
  UNVERIFIED on hardware.
  The community project zankyo-apple reached the same conclusion and also marked it unverified: "z 軸まわり = 首振り（左を向くと正）なので... z の符号を反転する" (https://github.com/shilokuma-inc/zankyo-apple/pull/22).
- Pitch is rotation about the headphone X axis.
  If X points out the right ear (which zankyo-apple assumes), looking up gives positive pitch, so `pitchSign = +1`.
  UNVERIFIED.
  If nodding moves `roll` instead of `pitch`, the axes are swapped for that model.
  Mach1 reports that AirPods Pro and AirPods Max produce different relative Euler outputs (https://research.mach1.tech/posts/feedback-on-apple-spatial-audio/), so log pitch and roll while nodding on the demo AirPods.
- Recenter: keep a reference `CMAttitude` and use `multiply(byInverseOf:)`, which "gives the attitude change from the specified attitude" (`SDK: CoreMotion.framework/Headers/CMAttitude.h`).

### Update rate, drift, known issues

- Update rate is not documented by Apple.
  Community reports put it around 25 Hz: "CMDeviceMotion with an attitude quaternion and fused gyro and accel at around 25 Hz" (https://anandchowdhary.com/notes/2025/airpods-based-head-motion-racing).
  UNVERIFIED.
  Measure it in the spike and show it in the debug panel.
  Smooth with a short exponential filter (time constant of about 40 ms or less) so the filter adds no noticeable lag.
- Yaw drift: AirPods attitude is IMU-based, and `xArbitraryZVertical` has no magnetometer correction.
  Expect slow yaw drift, so keep the Recenter button and the R shortcut.
  UNVERIFIED magnitude.
- An Apple forum thread from Sep 2026 (no replies) reports that on macOS the yaw "appears to recenter" as soon as audio starts playing with system Spatial Audio set to Head Tracked or Fixed (https://developer.apple.com/forums/thread/844940).
  This is another reason to set system Spatial Audio to Off for Earmark and to recenter after the engine starts.
- UNVERIFIED: whether motion is delivered only while the AirPods are the active output, and whether the app must be frontmost.
  Neither is documented.
  Test both in Phase 0.5.
- SwiftPM bundle launch: VERIFIED LOCALLY that a SwiftPM-built, hand-wrapped, hardened-runtime-signed bundle launches via `open` and gets its own TCC identity (bundle ID shown, all statuses `notDetermined`).
  UNVERIFIED that motion samples actually flow from such a bundle, because no AirPods were connected.

### Snippet (compiles with Swift 6.1.2, macOS 15.5 SDK, Swift 5 and 6 modes)

```swift
enum HeadSigns {
    /// CoreMotion yaw is + when turning LEFT (right-hand rule about vertical +Z); Earmark wants + right.
    static let yawSign: Double = -1
    /// UNVERIFIED: confirm on device that looking up makes attitude.pitch positive.
    static let pitchSign: Double = 1
}

final class HeadTracker: NSObject, CMHeadphoneMotionManagerDelegate {
    private let manager = CMHeadphoneMotionManager()
    private let queue = OperationQueue()
    private var reference: CMAttitude?
    private var latest: CMAttitude?
    var onPose: ((_ yawDeg: Double, _ pitchDeg: Double) -> Void)?
    var onConnection: ((Bool) -> Void)?

    func start() -> String? {
        guard manager.isDeviceMotionAvailable else { return "Headphone motion not available on this Mac" }
        switch CMHeadphoneMotionManager.authorizationStatus() {
        case .denied, .restricted: return "Motion access denied: System Settings > Privacy & Security"
        default: break
        }
        queue.maxConcurrentOperationCount = 1
        manager.delegate = self
        manager.startConnectionStatusUpdates()
        manager.startDeviceMotionUpdates(to: queue) { [weak self] motion, error in
            guard let self, let motion, error == nil else { return }
            self.latest = motion.attitude
            if self.reference == nil { self.reference = motion.attitude.copy() as? CMAttitude }
            guard let rel = motion.attitude.copy() as? CMAttitude, let ref = self.reference else { return }
            rel.multiply(byInverseOf: ref)
            self.onPose?(HeadSigns.yawSign * rel.yaw * 180 / .pi, HeadSigns.pitchSign * rel.pitch * 180 / .pi)
        }
        return nil
    }

    func recenter() { queue.addOperation { self.reference = self.latest?.copy() as? CMAttitude } }
    func headphoneMotionManagerDidConnect(_ manager: CMHeadphoneMotionManager) { onConnection?(true) }
    func headphoneMotionManagerDidDisconnect(_ manager: CMHeadphoneMotionManager) { onConnection?(false) }
}
```

---

## 2. `AVAudioEngine` + `AVAudioEnvironmentNode`

### Facts from headers and docs

- `AVAudioEnvironmentNode` is a "Mixer node that simulates a 3D environment", available since macOS 10.10 (`SDK: AVFAudio.framework/Headers/AVAudioEnvironmentNode.h`).
- Mono requirement: "Spatialization applies only to inputs with a mono channel connection format. This class doesn't spatialize stereo inputs" (https://developer.apple.com/documentation/avfaudio/avaudioenvironmentnode).
  The default `sourceMode` is `.spatializeIfMono`: "An input bus with more than one channel is bypassed" (`SDK: AVFAudio.framework/Headers/AVAudioMixing.h`).
  VERIFIED LOCALLY: a stereo player into the environment node with the source at +x rendered dead center (0.0 dB).
- `renderingAlgorithm` (set per source via `AVAudio3DMixing`; the default is `.equalPowerPanning`):
  - `.equalPowerPanning (0)` is a plain pan.
  - `.sphericalHead (1)` uses interaural time delays.
  - `.HRTF (2)`.
  - `.soundField (3)`.
  - `.stereoPassThrough (5)`.
  - `.HRTFHQ (6)` is "Improvements have been made to the overall frequency response and localization".
  - `.auto (7)` is "Automatically pick the highest-quality rendering algorithm available for current playback hardware" (`SDK: AVFAudio.framework/Headers/AVAudioMixing.h`).
- VERIFIED LOCALLY: `applicableRenderingAlgorithms` for stereo output was `[0, 1, 2, 6, 3, 7]`.
- `outputType` (macOS 10.15+) can be `.auto`, `.headphones`, `.builtInSpeakers` or `.externalSpeakers`.
  Apple: "An app choosing a value other than ...Auto should listen to route change notifications and update the output type accordingly" (`SDK: AVFAudio.framework/Headers/AVAudioEnvironmentNode.h`).
  Set `.headphones` explicitly when AirPods are the output, and update it on route change.
- `listenerPosition` is in meters, default origin.
- `listenerVectorOrientation` defaults to forward `(0, 0, -1)` and up `(0, 1, 0)`, "looking directly along the negative Z axis" (header).
- `listenerAngularOrientation` angles are in degrees (header).
  The header definition reads:
  - Yaw axis "directed towards the bottom of the listener's head. A positive yaw is in the clockwise direction".
  - Pitch "positive pitch is the upwards direction".
  - Roll "positive roll is to the right" (`SDK: AVFAudio.framework/Headers/AVAudioTypes.h`).
- Source `position` (`AVAudio3DPoint`, meters) is set on the source node through `AVAudio3DMixing` (`AVAudioPlayerNode` and `AVAudioSourceNode` both conform).
- Distance attenuation (`env.distanceAttenuationParameters`):
  - `distanceAttenuationModel` defaults to `.inverse`.
  - `referenceDistance` defaults to 1.0 m, and is "The minimum distance at which attenuation is applied".
  - `maximumDistance` defaults to 100000 m.
  - `rolloffFactor` defaults to 1.0 (header).
  Earmark targets are under 1 m away, so the defaults give no distance attenuation, which is what we want (the cue is direction only).
- Reverb (`env.reverbParameters`): `enable` (default NO), `level` (-40 to 40 dB), `loadFactoryReverbPreset(_:)`, plus a per-source `reverbBlend` from 0 to 1 (headers).
  Keep reverb off for the gate test.
  A small room reverb can help externalization later.
- `isListenerHeadTrackingEnabled` (macOS 15+): "listener orientation will be automatically rotated based on user's head-orientation if enabled".
  Apple: "To enable head tracking, your app must have the com.apple.developer.coremotion.head-pose entitlement" (https://developer.apple.com/documentation/avfaudio/avaudioenvironmentnode/islistenerheadtrackingenabled).
  VERIFIED LOCALLY: the property can be set to `true` in an unentitled CLI without error.
  UNVERIFIED whether it does anything without the entitlement (assume it does not).
- Engine output latency: `engine.outputNode.presentationLatency` (seconds) "corresponds to kAudioDevicePropertyLatency and kAudioStreamPropertyLatency" (`SDK: AVFAudio.framework/Headers/AVAudioIONode.h`).
  Show it in the debug panel, because Bluetooth latency matters for the fixed-in-room test.

### VERIFIED LOCALLY: conventions by offline rendering

Method: an `AVAudioEngine` in `.offline` manual rendering mode with broadband noise into the environment node, `outputType = .headphones`, and right/left RMS compared.
| case | HRTFHQ | auto | HRTF |
|---|---|---|---|
| source `(+1, 0, 0)` | R +14.2 dB | R +14.2 dB | R +15.8 dB |
| source `(-1, 0, 0)` | L 14.8 dB | L 14.8 dB | L 12.6 dB |
| source `(0, 0, -1)` (front) | center (+0.5) | center (+0.5) | +2.5 |
| front source, listener yaw +90 | L 14.8 dB | L 14.8 dB | L 12.6 dB |
| front source, listener yaw -90 | R 14.2 dB | R 14.2 dB | R 15.8 dB |

- +x is the right ear, -z is in front, and positive listener yaw turns the listener to the RIGHT (a front source then sounds on the left).
- Reading back `listenerVectorOrientation`:
  - yaw +90 gives forward `(+1, 0, 0)`.
  - pitch +30 gives forward `(0, +0.5, -0.87)`, which is looking up.
- `.auto` gave numbers identical to `.HRTFHQ` in offline manual rendering.
  UNVERIFIED whether `.auto` picks a different renderer when the output is real AirPods.
  Test both in the gate.
- `.sphericalHead` showed 0.0 dB level difference, which fits its ITD-based design (RMS cannot see time delay).
  It is not a useful candidate.
- These checks are packaged as a `swift test` suite (section 8), and it passes.

### Exact mapping from Earmark coordinates

Earmark is +x right, +y forward, +z up, meters, yaw positive turning right (brief 4.1).
AVAudio3D and PHASE are +x right, +y up, -z forward, a right-handed OpenGL-style frame (header defaults, plus `PHASEObject.right/up/forward` printed at runtime as `(1,0,0)`, `(0,1,0)`, `(0,0,-1)`).

```swift
/// Earmark world point -> AVAudio3DPoint / PHASE (both: +x right, +y up, -z forward).
func avPoint(_ e: SIMD3<Float>) -> AVAudio3DPoint { AVAudio3DPoint(x: e.x, y: e.z, z: -e.y) }

// Earmark head pose (deg; yaw + = turned right, pitch + = looking up) -> listener.
env.listenerAngularOrientation = AVAudio3DAngularOrientation(yaw: yawDeg, pitch: pitchDeg, roll: 0)
```

- The matrix is `[[1,0,0],[0,0,1],[0,-1,0]]` with determinant +1, so it is a proper rotation with no mirror.
- Example: spot 3 "center right" `[0.16, 0.58, 0.0]` maps to `AVAudio3DPoint(0.16, 0.0, -0.58)`.
- Full chain for the sign check: head turns left, CoreMotion yaw goes positive, Earmark yaw goes negative, listener yaw goes negative, and a front ping moves to the RIGHT ear.
  That matches brief Phase 0.5.
- Rotate the listener rather than the source, so that one place owns the head pose.
  Motion arrives at about 25 Hz (UNVERIFIED), not per audio frame, so set the listener orientation on each motion sample.
  Brief 5.E's "each audio frame" is not literally possible.

### Renderer snippet (compiles)

```swift
final class EnvRenderer {
    let engine = AVAudioEngine()
    let env = AVAudioEnvironmentNode()
    let ping = AVAudioPlayerNode()
    let speech = AVAudioPlayerNode()
    let mono = AVAudioFormat(standardFormatWithSampleRate: 48_000, channels: 1)!

    func start() throws {
        engine.attach(env); engine.attach(ping); engine.attach(speech)
        let hwRate = engine.outputNode.outputFormat(forBus: 0).sampleRate
        let stereo = AVAudioFormat(standardFormatWithSampleRate: hwRate > 0 ? hwRate : 48_000, channels: 2)!
        engine.connect(ping, to: env, format: mono)                   // mono in = spatialized
        engine.connect(env, to: engine.mainMixerNode, format: stereo)
        engine.connect(speech, to: engine.mainMixerNode, format: nil) // speech bypasses env = centered
        env.outputType = .headphones
        ping.renderingAlgorithm = .HRTFHQ                              // or .auto (needed for personalized HRTF)
        ping.sourceMode = .pointSource
        env.reverbParameters.enable = false
        try engine.start()
        ping.play()
    }

    func setTarget(_ earmark: SIMD3<Float>) { ping.position = avPoint(earmark) }
    func setHead(yawDeg: Double, pitchDeg: Double) {
        env.listenerAngularOrientation = AVAudio3DAngularOrientation(yaw: Float(yawDeg), pitch: Float(pitchDeg), roll: 0)
    }
    func firePing(_ buf: AVAudioPCMBuffer) { ping.scheduleBuffer(buf, at: nil, options: [], completionHandler: nil) }
}
```

- Ducking: lower `ping.volume`, or `env.outputVolume` (0.0 to 1.0), while the speech player is playing.
- Personalized HRTF applies only "with kSpatializationAlgorithm_UseOutputType and kSpatialMixerOutputType_Headphones" (`SDK: AudioToolbox.framework/Headers/AudioUnitProperties.h`, `kAudioUnitProperty_SpatialMixerPersonalizedHRTFMode`).
  `.auto` in AVFAudio corresponds to `UseOutputType (7)`, so `.HRTFHQ` never uses the personal profile.

---

## 3. Procedural ping

- Both paths spatialize when the connection to the environment node is mono (VERIFIED LOCALLY).
  - `AVAudioPlayerNode` with a scheduled mono `AVAudioPCMBuffer` gave R +14.2 dB at +x with HRTFHQ.
  - `AVAudioSourceNode` with a mono render block gave the same result.
- Recommendation: precompute the ping and "behind" buffers once and `scheduleBuffer` them on an `AVAudioPlayerNode` from a timer.
  This is simpler and has no real-time-thread rules.
  An `AVAudioSourceNode` render block (https://developer.apple.com/documentation/avfaudio/avaudiosourcenode) runs on the real-time audio thread, so it must not allocate or lock.
- Keep a separate player for the "locked" tone if it may overlap a ping.

```swift
/// Short bright blip: sine + 2nd harmonic, 4 ms raised-cosine attack, exponential decay (~70 ms total).
func makePing(format: AVAudioFormat, hz: Float = 1_000, ms: Float = 70) -> AVAudioPCMBuffer {
    let n = AVAudioFrameCount(Float(format.sampleRate) * ms / 1000)
    let buf = AVAudioPCMBuffer(pcmFormat: format, frameCapacity: n)!
    buf.frameLength = n
    let p = buf.floatChannelData![0], sr = Float(format.sampleRate), attack = 0.004 * sr
    for i in 0..<Int(n) {
        let t = Float(i) / sr
        let a = Float(i) < attack ? 0.5 - 0.5 * cos(.pi * Float(i) / attack) : exp(-(t - 0.004) / 0.018)
        p[i] = 0.6 * a * (sin(2 * .pi * hz * t) + 0.3 * sin(4 * .pi * hz * t))
    }
    return buf
}
```

- The brief's 880 to 1,200 Hz blip is fine for lateral cues.
  Pure tones localize poorly front-to-back, because the HRTF spectral cues need broadband energy.
  Consider adding a short noise burst or more harmonics if the pointing test fails.
  This is a psychoacoustics note, not an Apple doc claim.

---

## 4. PHASE and system head tracking on macOS; Option A vs Option B

### What exists (docs and headers)

- PHASE framework: macOS 12.0+ (https://developer.apple.com/documentation/phase).
  Apple's note on that page: "If the audio in your game or app doesn't incorporate environmental events or cues, you can use AVFoundation or CoreAudio".
- `PHASEListener.automaticHeadTrackingFlags`: macOS 15.0+, with flag `.orientation`, "On capable devices, listener orientation will be automatically rotated based on user's head-orientation" (`SDK: PHASE.framework/Headers/PHASEListener.h`, `PHASETypes.h`, https://developer.apple.com/documentation/phase/phaselistener/automaticheadtrackingflags).
- Apple guide "Personalizing spatial audio in your app" (macOS 15.0+, https://developer.apple.com/documentation/phase/personalizing-spatial-audio-in-your-app):
  - Head tracking requires adding `com.apple.developer.coremotion.head-pose`, then opting in per framework:
    - `AVAudioEnvironmentNode.isListenerHeadTrackingEnabled = true` for AVAudioEngine.
    - `PHASEListener.automaticHeadTrackingFlags = .orientation` for PHASE.
    - `kAudioUnitProperty_SpatialMixerEnableHeadTracking` for AUSpatialMixer.
  - The personal profile requires `com.apple.developer.spatial-audio.profile-access`.
    Then "the system automatically takes the personal spatial audio profile into account" for AUSpatialMixer, AVAudioEngine and PHASE.
- `com.apple.developer.coremotion.head-pose`: Boolean, macOS 15.0+, "Add this entitlement to your app by enabling the Head Pose capability in Xcode" (https://developer.apple.com/documentation/bundleresources/entitlements/com.apple.developer.coremotion.head-pose).
- `com.apple.developer.spatial-audio.profile-access`: macOS 15.0+, "Spatial Audio Profile capability" (https://developer.apple.com/documentation/bundleresources/entitlements/com.apple.developer.spatial-audio.profile-access).
- Capability matrix (https://developer.apple.com/help/account/reference/supported-capabilities-macos/), parsed from the page HTML:
  - "Head Pose": ADP yes, Developer ID yes, free Apple Developer account no.
  - "Spatial Audio Profile": ADP yes, Developer ID yes, free Apple Developer account no.
- Low-level AUSpatialMixer properties in the 15.5 SDK (`SDK: AudioToolbox.framework/Headers/AudioUnitProperties.h`):
  - `kAudioUnitProperty_SpatialMixerEnableHeadTracking` (macOS 12.3+): "Enables or disables head-tracking using AirPods motion sensors. This tracking will apply a second rotation on top of head yaw, pitch, and roll parameters".
  - `kAudioUnitProperty_SpatialMixerPersonalizedHRTFMode` (macOS 13+): off, on, or auto.
  - `kAudioUnitProperty_SpatialMixerAnyInputIsUsingPersonalizedHRTF` (macOS 14+).
- `AVGameBypassSystemSpatialAudio` is iOS, iPadOS and tvOS only, so there is no macOS equivalent (https://developer.apple.com/documentation/bundleresources/information-property-list/avgamebypasssystemspatialaudio).

### What it takes to use the entitlements without Xcode (UNVERIFIED end to end)

1. Confirm team `29R3JXG54K` is a paid Apple Developer Program team.
   This is UNVERIFIED, because the keychain cert alone does not say.
   Free accounts cannot get Head Pose at all.
2. On developer.apple.com, create these:
   - An explicit App ID with the Head Pose (and optionally Spatial Audio Profile) capabilities.
   - A registered device for this Mac (Provisioning UDID from `system_profiler SPHardwareDataType`).
   - A macOS App Development provisioning profile for that App ID, cert and Mac.
3. Copy it to `Contents/embedded.provisionprofile` (location per https://developer.apple.com/documentation/bundleresources/placing-content-in-a-bundle).
4. Sign with an entitlements plist containing these keys:
   - `com.apple.developer.coremotion.head-pose = true`
   - `com.apple.application-identifier = 29R3JXG54K.<bundle id>`
   - `com.apple.developer.team-identifier = 29R3JXG54K`
   - `com.apple.security.device.audio-input = true`
   UNVERIFIED: the exact keys AMFI checks for this profile type.

This is extra signing risk on the critical path, so keep it as a stretch experiment.

### Option B with manual tracking (compiles)

PHASE can also be driven by our own `CMHeadphoneMotionManager` pose with no entitlement.
That makes a fair A vs B renderer comparison possible without provisioning.

```swift
/// PHASE rotations are right-handed about +Y (up): + angle turns LEFT, so negate Earmark yaw.
func setHead(yawDeg: Float, pitchDeg: Float) {
    let q = simd_quatf(angle: -yawDeg * .pi / 180, axis: [0, 1, 0]) * simd_quatf(angle: pitchDeg * .pi / 180, axis: [1, 0, 0])
    listener.transform = simd_float4x4(q)   // VERIFIED LOCALLY: yaw +90 -> forward (1,0,0); pitch +30 -> forward y +0.5
}
// Setup outline: PHASEEngine(updateMode: .automatic); engine.outputSpatializationMode = .alwaysUseBinaural;
// rootObject.addChild(listener/source); assetRegistry.registerSoundAsset(data:identifier:format:normalizationMode:);
// PHASESpatialMixerDefinition(spatialPipeline: PHASESpatialPipeline(flags: [.directPathTransmission])!);
// PHASESamplerNodeDefinition(soundAssetIdentifier:mixerDefinition:) with .oneShot; registerSoundEventAsset;
// PHASEMixerParameters().addSpatialMixerParameters(identifier:source:listener:); PHASESoundEvent(...).start().
// Optional, entitlement-gated: if #available(macOS 15.0, *) { listener.automaticHeadTrackingFlags = .orientation }
```

- `PHASESpatializationMode.alwaysUseBinaural`: "Always use binaural rendering, whether playing back on headphones or speakers" (`SDK: PHASE.framework/Headers/PHASETypes.h`).
- UNVERIFIED: PHASE's binaural renderer versus AVAudioEnvironmentNode `.HRTFHQ` or `.auto`.
  Apple does not say whether they share an HRTF.

### Recommendation

- **Build Option A first, with manual head tracking.** It is the only path with no entitlement, provisioning or paid-team dependency.
  Its conventions are verified by an automated offline test, and it matches the brief's protocol design.
- In the gate, compare these three:
  - A-HRTFHQ.
  - A-auto with `outputType = .headphones`.
  - B-manual (PHASE driven by the same HeadTracker).
- Only if A and B-manual both fail on front/back, and the team is paid, try the entitlement build.
  It enables automatic tracking (`isListenerHeadTrackingEnabled` for A, or `automaticHeadTrackingFlags` for B) and the personal profile (needs `.auto` rendering).
- Rule 11 is satisfied in every variant, because the app renders the spatial scene itself either way.
  Even the automatic flags are app-level API opt-ins, not the system Spatial Audio menu.

---

## 5. macOS audio routing

### No AVAudioSession on macOS

- `AVAudioSession` is listed for iOS, iPadOS, Mac Catalyst, tvOS, visionOS and watchOS only, not macOS (https://developer.apple.com/documentation/avfaudio/avaudiosession).
- "on macOS, AVAudioInputNode and AVAudioOutputNode communicate with the system's default input and output devices" (`SDK: AVFAudio.framework/Headers/AVAudioIONode.h`).

### (a) Detecting output (and input) changes

- `AVAudioEngineConfigurationChangeNotification`: "When the engine's I/O unit observes a change to the audio input or output hardware's channel count or sample rate, the engine stops itself ... and issues this notification".
  "the engine must not be deallocated from within the client's notification handler" (`SDK: AVFAudio.framework/Headers/AVAudioEngine.h`).
  Use it with `object: engine`.
- CoreAudio listeners on the system object for `kAudioHardwarePropertyDefaultOutputDevice` and `kAudioHardwarePropertyDefaultInputDevice`.
  VERIFIED LOCALLY: `AudioObjectAddPropertyListenerBlock` and `AudioObjectRemovePropertyListenerBlock` returned 0.
- On either event, debounce (route changes arrive in bursts) and do these steps in order:
  1. Re-read devices.
  2. Re-assert the input rule.
  3. Reconnect the env-to-mixer connection at the new hardware rate.
  4. Restart the engine.
  5. Update `env.outputType`.
  6. Re-check head tracking.
  7. Recenter.
  The macparakeet issue on macOS 26.5.1 shows "restart storms" from duplicate route notifications, and tap format mismatches (-10868) when the tap keeps the old sample rate (https://github.com/moona3k/macparakeet/issues/481).

```swift
func watchDefaultDevices(_ onChange: @escaping () -> Void) {
    for sel in [kAudioHardwarePropertyDefaultOutputDevice, kAudioHardwarePropertyDefaultInputDevice] {
        var addr = AudioObjectPropertyAddress(mSelector: sel, mScope: kAudioObjectPropertyScopeGlobal,
                                              mElement: kAudioObjectPropertyElementMain)
        AudioObjectAddPropertyListenerBlock(AudioObjectID(kAudioObjectSystemObject), &addr, .main) { _, _ in onChange() }
    }
}
let token = NotificationCenter.default.addObserver(forName: .AVAudioEngineConfigurationChange,
                                                   object: engine, queue: .main) { _ in /* schedule restart */ }
```

### (b) Choosing the input device separately from output

- Evidence that AVAudioEngine does not cleanly support separate devices on macOS:
  - AudioKit: "AVAudioEngine, which is limited to a single audio device for both input and output" (https://github.com/AudioKit/AudioKit/issues/2130).
  - A 2026 write-up: setting `kAudioOutputUnitProperty_CurrentDevice` on `inputNode` "returns noErr but the engine quietly keeps reading the default input" (https://dgrlabs.co/blog/2026-04-25-capturing-system-audio-on-macos-in-2026.html).
  - Older forum threads report it works.
    Treat setting `CurrentDevice` on `inputNode.audioUnit` as UNVERIFIED and do not rely on it.
- AirPods-specific trap (Chris Liscio, Jan 2021): `AVAudioEngine` "smushes" the default input and output into an aggregate device.
  Touching `outputNode` or `mainMixerNode` "appears to trigger this", when the app is unsandboxed or has audio-input access.
  If the default input is the AirPods, even a playback-only engine pulls them into hands-free mode.
  His fix: "make absolutely sure that your Mac's default input device is _not_ set to your AirPods" (https://supermegaultragroovy.com/2021/01/28/more-on-avaudioengine-airpods/).
  UNVERIFIED on macOS 26, so test it.
- **Recommended approach:**
  1. At launch, and on every default-input change, if the default input is Bluetooth (`kAudioDeviceTransportTypeBluetooth`), set the system default input to the built-in mic.
     Then log it and show it in the UI.
     Check with the human first: this changes a user-visible system setting, and macOS tends to switch the input to AirPods when they connect.
  2. Build the playback engine only after that.
     The playback engine never touches `inputNode`.
  3. Capture on a separate path.
     Either a second `AVAudioEngine` used only for its `inputNode` tap (it then follows the now-built-in default input), or `AVCaptureSession` pinned to the built-in mic by UID.
     The latter is independent of the default and delivers 16 kHz Int16 itself (section 6).
  4. HFP detector: read `kAudioDevicePropertyNominalSampleRate` of the AirPods output device.
     A2DP is 48 kHz, and hands-free drops it to 16 or 24 kHz.
     The AirPods Pro mic device runs at 16 kHz per Liscio, and macparakeet logged AirPods at 24 kHz.
     Show it in the status bar, and fail the gate if it drops.

```swift
/// Makes `dev` the system default input (non-sandboxed apps only). Changes a user-visible system setting.
func setDefaultInput(_ dev: AudioDeviceID) -> OSStatus {
    var addr = AudioObjectPropertyAddress(mSelector: kAudioHardwarePropertyDefaultInputDevice,
                                          mScope: kAudioObjectPropertyScopeGlobal, mElement: kAudioObjectPropertyElementMain)
    var d = dev
    return AudioObjectSetPropertyData(AudioObjectID(kAudioObjectSystemObject), &addr, 0, nil,
                                      UInt32(MemoryLayout<AudioDeviceID>.size), &d)
}
```

- `setDefaultInput` compiles but was not executed during research, to avoid changing the user's settings.

### (c) Reading device names and IDs

- Use these properties:
  - `kAudioHardwarePropertyDevices`.
  - `kAudioHardwarePropertyDefaultOutputDevice` and `kAudioHardwarePropertyDefaultInputDevice`.
  - `kAudioObjectPropertyName` (a `CFString`, retained).
  - `kAudioDevicePropertyDeviceUID`.
  - `kAudioDevicePropertyTransportType` (`'bltn'` built-in, `'blue'` Bluetooth).
  - `kAudioDevicePropertyStreams` with input or output scope, to tell input from output devices.
  - `kAudioDevicePropertyNominalSampleRate`.
- VERIFIED LOCALLY on this Mac:
  - Devices are `MacBook Pro Microphone` (id 78, built-in, 1 input stream, UID `BuiltInMicrophoneDevice`, 48 kHz) and `MacBook Pro Speakers` (id 71, built-in).
  - `AVCaptureDevice.uniqueID` for the built-in mic is the same string as its CoreAudio UID, `BuiltInMicrophoneDevice`.
  - The discovery session also listed `Daniel's iPhone Microphone` (Continuity).
    Never auto-select a non-built-in mic.

### AirPods microphone forces low-quality mode

- Apple Support (https://support.apple.com/en-us/102217): sound quality and volume can drop when you play through Bluetooth headphones and an app uses the headphones' microphone.
  The fix is to "Quit any apps that use the microphone of your Bluetooth headphones", make sure System Settings is not showing Sound, or reselect the headphones.
- Liscio (link above): "the AirPods must drop their playback quality down to 16kHz whenever the microphone is activated".
  He says AirPods Pro appear as a 2-channel 48 kHz output device and a separate 1-channel 16 kHz input device.
- System Spatial Audio for AirPods on a Mac (Off, Fixed, Head Tracked) is set from the AirPods icon in the menu bar.
  "You can turn Spatial Audio and head tracking on or off for each supported app".
  It needs Apple silicon with macOS 12.3+ (https://support.apple.com/guide/airpods/control-spatial-audio-and-head-tracking-dev00eb7e0a3/web).
  Set it to Off for Earmark, per the brief.

---

## 6. Mic capture to 16-bit PCM at 16 kHz

- Target per `docs/vendor-notes/cartesia.md`: raw mono `pcm_s16le` at 16000 Hz, 100 ms chunks (1600 samples, 3200 bytes).
- `installTap(onBus:bufferSize:format:block:)`: the "Supported range is [100, 400] ms" for buffer size (`SDK: AVFAudio.framework/Headers/AVAudioNode.h`).
  "When rendering from an audio device, the input node does not support format conversion" (`SDK: AVFAudio.framework/Headers/AVAudioIONode.h`).
  So tap at the hardware format and convert with `AVAudioConverter`.
- VERIFIED LOCALLY: a 48 kHz Float32 mono to 16 kHz Int16 interleaved conversion works.
  4800 input frames gave 1360 output frames with peak 16384 for a 0.5 amplitude sine.
  The missing ~240 frames are resampler latency that comes out on the next call, so reuse one converter and return `.noDataNow` (not `.endOfStream`) after each buffer.
- Rebuild the converter if the tap's hardware format changes after a configuration change.

```swift
let target = AVAudioFormat(commonFormat: .pcmFormatInt16, sampleRate: 16_000, channels: 1, interleaved: true)!
let hw = engine.inputNode.outputFormat(forBus: 0)
let converter = AVAudioConverter(from: hw, to: target)!
engine.inputNode.installTap(onBus: 0, bufferSize: 4_800, format: hw) { buf, _ in
    let cap = AVAudioFrameCount(Double(buf.frameLength) * 16_000 / hw.sampleRate) + 64
    guard let out = AVAudioPCMBuffer(pcmFormat: target, frameCapacity: cap) else { return }
    var fed = false
    var err: NSError?
    _ = converter.convert(to: out, error: &err) { _, status in
        if fed { status.pointee = .noDataNow; return nil }   // keep converter state across taps
        fed = true; status.pointee = .haveData; return buf
    }
    if err == nil, out.frameLength > 0 { send(Data(bytes: out.int16ChannelData![0], count: Int(out.frameLength) * 2)) }
}
```

- Device-pinned alternative: `AVCaptureSession` + `AVCaptureDeviceInput(device: AVCaptureDevice(uniqueID: "BuiltInMicrophoneDevice")!)` + `AVCaptureAudioDataOutput`.
  `audioSettings` is set to `[AVFormatIDKey: kAudioFormatLinearPCM, AVSampleRateKey: 16_000, AVNumberOfChannelsKey: 1, AVLinearPCMBitDepthKey: 16, AVLinearPCMIsFloatKey: false, AVLinearPCMIsBigEndianKey: false, AVLinearPCMIsNonInterleaved: false]`.
  `audioSettings` is macOS-only (`API_UNAVAILABLE(ios, macCatalyst, watchos, tvos, visionos)` in `SDK: AVFoundation.framework/Headers/AVCaptureAudioDataOutput.h`).
  It compiles.
  Delivering exact 16 kHz chunks is UNVERIFIED at runtime.
- Use `AVCaptureDevice.DiscoverySession(deviceTypes: [.microphone], ...)`, because `.builtInMicrophone` is deprecated since macOS 14 (`SDK: AVFoundation.framework/Headers/AVCaptureDevice.h`).
- Do not enable voice processing on the playback engine.
  "Voice processing requires both input and output nodes to be in the voice processing mode" (`SDK: AVFAudio.framework/Headers/AVAudioIONode.h`), which ties capture to the AirPods route.

---

## 7. Info.plist keys and entitlements (macOS 14+)

| Item | Needed for | Source |
|---|---|---|
| `NSMicrophoneUsageDescription` | mic capture; "This key is required if your app uses APIs that access the device's microphone" | https://developer.apple.com/documentation/bundleresources/information-property-list/nsmicrophoneusagedescription |
| `NSSpeechRecognitionUsageDescription` | `SFSpeechRecognizer`; "If this key isn't present, your app crashes when it calls requestAuthorization(_:)" (on-device too) | https://developer.apple.com/documentation/bundleresources/information-property-list/nsspeechrecognitionusagedescription |
| `NSMotionUsageDescription` | `CMHeadphoneMotionManager`; crash on start if missing | https://developer.apple.com/documentation/coremotion/cmheadphonemotionmanager |
| `com.apple.security.device.audio-input` (entitlement) | mic under hardened runtime; "may record audio using the built-in microphone and access audio input using Core Audio" | https://developer.apple.com/documentation/bundleresources/entitlements/com.apple.security.device.audio-input |
| `com.apple.security.device.microphone` | sandboxed apps only; Earmark is not sandboxed, so skip | https://developer.apple.com/documentation/bundleresources/entitlements/com.apple.security.device.microphone |
| `com.apple.developer.coremotion.head-pose` | only for automatic head tracking (section 4); needs profile | link in section 4 |
| `com.apple.developer.spatial-audio.profile-access` | only for the personal profile; needs profile | link in section 4 |

- Permission APIs:
  - `AVAudioApplication.requestRecordPermission()` (macOS 14+, https://developer.apple.com/documentation/avfaudio/avaudioapplication/requestrecordpermission(completionhandler:)) or `AVCaptureDevice.requestAccess(for: .audio)`.
    Apple: "Calling this method or attempting to start a capture session without a usage description raises an exception", and "until the [user] grants permission, the system only vends ... silent audio samples" (https://developer.apple.com/documentation/avfoundation/avcapturedevice/requestaccess(for:completionhandler:)).
  - `SFSpeechRecognizer.requestAuthorization(_:)`.
- Hardened runtime: "The default value of these Boolean entitlements is false ... Don't include an entitlement if the value is false" (https://developer.apple.com/documentation/security/hardened-runtime).

---

## 8. Building the SwiftUI app without Xcode (VERIFIED LOCALLY)

- What works here:
  - `swift build -c release` for an `executableTarget` with `@main struct App: App` (SwiftUI).
  - A hand-made `.app`.
  - `codesign --force --options runtime --timestamp=none --entitlements ent.plist --sign "Apple Development" X.app`.
  - `codesign --verify --strict` passes, and the signature shows `flags=0x10000(runtime)`.
  - `open -W -n X.app --args ...` launched it.
  - Inside, `Bundle.main.bundleIdentifier` was the bundle ID and the mic, speech and motion statuses were readable (all `notDetermined`).
- Bundle layout (https://developer.apple.com/documentation/bundleresources/placing-content-in-a-bundle):
  - `Contents/Info.plist`.
  - `Contents/MacOS/<executable>`.
  - `Contents/Resources/`.
  - `Contents/embedded.provisionprofile` (only if a profile is used).
- Minimal Info.plist keys used: `CFBundleIdentifier`, `CFBundleName`, `CFBundleExecutable`, `CFBundlePackageType=APPL`, `CFBundleShortVersionString`, `CFBundleVersion`, `LSMinimumSystemVersion=14.0`, `NSHighResolutionCapable`, plus the three usage strings.
  Run `plutil -lint` on it.
- Package.swift that built: `// swift-tools-version:6.0`, `platforms: [.macOS(.v14)]`, `swiftLanguageModes: [.v5]` (avoids Swift 6 strict-concurrency friction around CoreMotion and audio callbacks).
- Tests: only `Testing.framework` (Swift Testing) ships with the Command Line Tools here.
  There is no XCTest.
  `swift test` ran a Swift Testing suite that renders offline and asserts three things:
  - The +x target is in the right ear.
  - With the head turned left, a front target is in the right ear.
  - With the head turned right, a front target is in the left ear.
  All 3 passed in 0.83 s.
  Put `avPoint` in a library target so the tests can import it.
- TCC pitfalls:
  - Launch with `open` (or Finder), not by running `Contents/MacOS/X` from a shell.
    A shell-launched process is attributed to Terminal, and `open` "parents it under launchd" so the bundle is its own responsible process (https://www.qt.io/blog/the-curious-case-of-the-responsible-process).
  - Keep signing with the same Apple Development identity and bundle ID.
    The designated requirement here is `identifier "<id>" and anchor apple generic and certificate leaf[subject.CN] = "Apple Development: ..."`, which is stable across rebuilds.
    Ad-hoc signatures are cdhash-bound, so permissions reset every build (community reports, e.g. https://github.com/YARC-Official/YARG/issues/1695).
  - Reset prompts with `tccutil reset Microphone <bundle id>` (likewise `SpeechRecognition`, and so on).
  - Capture logs with `open --stdout PATH --stderr PATH`, or `os_log` plus `log stream`.
  - Use `open -n` or quit the old instance, otherwise `open` just activates the running copy.
  - The linker already ad-hoc signs arm64 binaries, so `codesign` prints "replacing existing signature".
    That is expected.
  - `--timestamp=none` avoids a network call during dev signing.
    Notarization is not needed for local runs.

---

## 9. Brief vs official docs

1. Brief 5.E Option B says "Apple documents how PHASE can track head movement and apply the user's Personalized Spatial Audio profile".
   This is true, but on macOS it needs macOS 15+ (fine on 26.5.1) **and** two entitlements available only to paid or Developer ID teams via a provisioning profile.
   The same Apple guide also gives AVAudioEngine (`isListenerHeadTrackingEnabled`) and AUSpatialMixer the same features, so these benefits are not PHASE-only.
2. Brief 5.E Option A: "Each audio frame, rotate the listener".
   Head motion arrives at a much lower rate (about 25 Hz, UNVERIFIED), so update per motion sample.
3. Option A's `.HRTFHQ` cannot use the Personalized Spatial Audio profile.
   Personalization applies only with `UseOutputType` (`.auto`) plus headphones output.
4. Brief 5.E Robustness speaks of "route changes ... and interruptions".
   macOS has no AVAudioSession route-change or interruption notifications.
   Use `AVAudioEngineConfigurationChange` plus CoreAudio default-device listeners instead.
5. The brief's routing rule (built-in mic in, AirPods output only) is correct and supported by Apple Support 102217.
   One addition: the *system default input* must not be the AirPods, because macOS AVAudioEngine follows system defaults and may aggregate the default input even for playback.
   Pinning only the capture path is not enough.
6. Phase 0.5 sign check "looking up moves it down" is consistent with the verified AVAudio pitch convention.
   Elevation is weakly perceived with a generic HRTF, though, so verify the pitch sign from the numeric readout as well as by ear.
7. Brief 2.5 and 5.E say to verify plist keys for macOS 14+.
   The three keys in the brief are correct.
   Under `--options runtime` the mic also needs `com.apple.security.device.audio-input`, which the brief does not mention.

---

## 10. Must test on real AirPods in Phase 0.5 (all UNVERIFIED here)

- `yawSign = -1` and `pitchSign = +1`, and whether nodding shows up in `pitch` or `roll`.
- The motion update rate, and whether motion flows from the SwiftPM bundle when AirPods are connected but the app is not frontmost, or the AirPods are not the active output.
- Whether a motion permission prompt appears, and what `authorizationStatus()` says after it.
- That AirPods output stays at 48 kHz in three situations: with the playback engine running, with capture running on the built-in mic, and after reconnecting the AirPods.
- `.HRTFHQ` vs `.auto` vs PHASE-manual on the pointing test and front/back trials.
- Yaw drift over 5 minutes, and whether system Spatial Audio being Off prevents the yaw recentering reported in forum thread 844940.
- `engine.outputNode.presentationLatency` with AirPods, and whether it smears the fixed-in-room test.

## Sources

- CMHeadphoneMotionManager: https://developer.apple.com/documentation/coremotion/cmheadphonemotionmanager
- CMHeadphoneMotionManagerDelegate: https://developer.apple.com/documentation/coremotion/cmheadphonemotionmanagerdelegate
- Processed device motion and attitude: https://developer.apple.com/documentation/coremotion/getting-processed-device-motion-data
- AVAudioEnvironmentNode: https://developer.apple.com/documentation/avfaudio/avaudioenvironmentnode
- isListenerHeadTrackingEnabled: https://developer.apple.com/documentation/avfaudio/avaudioenvironmentnode/islistenerheadtrackingenabled
- listenerAngularOrientation: https://developer.apple.com/documentation/avfaudio/avaudioenvironmentnode/listenerangularorientation
- AVAudio3DMixingRenderingAlgorithm: https://developer.apple.com/documentation/avfaudio/avaudio3dmixingrenderingalgorithm
- AVAudioSourceNode: https://developer.apple.com/documentation/avfaudio/avaudiosourcenode
- PHASE: https://developer.apple.com/documentation/phase
- PHASEListener: https://developer.apple.com/documentation/phase/phaselistener
- Personalizing spatial audio in your app: https://developer.apple.com/documentation/phase/personalizing-spatial-audio-in-your-app
- Head pose entitlement: https://developer.apple.com/documentation/bundleresources/entitlements/com.apple.developer.coremotion.head-pose
- Spatial audio profile entitlement: https://developer.apple.com/documentation/bundleresources/entitlements/com.apple.developer.spatial-audio.profile-access
- macOS capability matrix: https://developer.apple.com/help/account/reference/supported-capabilities-macos/
- Placing content in a bundle: https://developer.apple.com/documentation/bundleresources/placing-content-in-a-bundle
- Hardened runtime: https://developer.apple.com/documentation/security/hardened-runtime
- Audio input entitlement: https://developer.apple.com/documentation/bundleresources/entitlements/com.apple.security.device.audio-input
- AVAudioSession platforms: https://developer.apple.com/documentation/avfaudio/avaudiosession
- Bluetooth quality on Mac: https://support.apple.com/en-us/102217
- AirPods Spatial Audio controls: https://support.apple.com/guide/airpods/control-spatial-audio-and-head-tracking-dev00eb7e0a3/web
- Yaw recenter forum thread: https://developer.apple.com/forums/thread/844940
- AVAudioEngine + AirPods aggregate device: https://supermegaultragroovy.com/2021/01/28/more-on-avaudioengine-airpods/
- AudioKit device limitation: https://github.com/AudioKit/AudioKit/issues/2130
- inputNode CurrentDevice report: https://dgrlabs.co/blog/2026-04-25-capturing-system-audio-on-macos-in-2026.html
- macparakeet AirPods route issue: https://github.com/moona3k/macparakeet/issues/481
- Responsible process and `open`: https://www.qt.io/blog/the-curious-case-of-the-responsible-process
- zankyo-apple yaw sign: https://github.com/shilokuma-inc/zankyo-apple/pull/22
- AirPods motion rate note: https://anandchowdhary.com/notes/2025/airpods-based-head-motion-racing
- Mach1 AirPods Euler differences: https://research.mach1.tech/posts/feedback-on-apple-spatial-audio/
