# Apple Nearby Interaction (and the other iOS APIs in `ios/EarmarkUWB`) - vendor notes

Researched 2026-10-24 for `docs/UWB-PRD.md` section 7.
Source: Apple's documentation JSON (`https://developer.apple.com/tutorials/data/documentation/<path>.json`, the data behind each `developer.apple.com/documentation/<path>` page), read on 2026-10-24.
Signatures below are copied from those pages. Nothing here was compiled (written on Windows); anything not on an Apple page is marked UNVERIFIED.

## 0. What Earmark relies on

- Phone-to-phone UWB ranging with `NINearbyPeerConfiguration`: **distance only**. `direction` is ignored and camera assistance stays off (no camera, PRD pillar).
- One `NISession` per peer. Apple: "One session represents an interaction between the user and a single nearby object. To interact with multiple nearby objects, create a separate session for each." So each anchor has 1 session and the wearer has 3, each with its own discovery token.
- Discovery tokens are exchanged over our own bus (Apple explicitly allows "a custom server deployment"), archived with `NSKeyedArchiver` (secure coding) and base64-encoded into `uwb_token.token_b64`.
- Delegate callbacks are delivered on the main queue (`delegateQueue = .main`, also the default), so the app handles them as main-actor code.

## 1. Nearby Interaction

### NISession — https://developer.apple.com/documentation/nearbyinteraction/nisession
- `class NISession` (iOS 14+). Members we use:
  - `class var deviceCapabilities: any NIDeviceCapability { get }` (iOS 16+).
  - `var discoveryToken: NIDiscoveryToken? { get }` — "A temporary, random identifier for a device." Keeps its value across `run` restarts (note on `run(_:)`), changes only with a new session.
  - `func run(_ configuration: NIConfiguration)` — https://developer.apple.com/documentation/nearbyinteraction/nisession/run(_:) — starts or restarts; also used to resume after `pause()` and after suspension ends. The **first** `run` per install shows the Nearby Interaction permission prompt (`NSNearbyInteractionUsageDescription`); later runs consult Settings.
  - `var configuration: NIConfiguration? { get }` — used to "re-run the same configuration" after a suspension.
  - `var delegateQueue: dispatch_queue_t? { get set }` (Swift: `DispatchQueue?`) — https://developer.apple.com/documentation/nearbyinteraction/nisession/delegatequeue — "By default, NI invokes delegate callbacks on main." We set it to `.main` explicitly.
  - `var delegate: (any NISessionDelegate)?` (weak).
  - `func pause()` — https://developer.apple.com/documentation/nearbyinteraction/nisession/pause() — "Stops sending distance and direction updates to the peer." Resume with `run(_:)` and the same configuration. "If an app pauses the session for too long, the peer receives `session(_:didRemove:reason:)` with the `timeout` reason." (Used by the round-robin fallback.)
  - `func invalidate()` — ends the session for good.
  - `class var isSupported: Bool` — **deprecated** (iOS 14.0-16.0). Apple: equivalent to `deviceCapabilities.supportsPreciseDistanceMeasurement`. Not used (deployment target iOS 17).

### NIDeviceCapability — https://developer.apple.com/documentation/nearbyinteraction/nidevicecapability
- iOS 16+. `var supportsPreciseDistanceMeasurement: Bool` (our UWB check), `supportsDirectionMeasurement`, `supportsCameraAssistance`, `supportsExtendedDistanceMeasurement`, `supportsDLTDOAMeasurement`, `supportsBluetoothChannelSounding`.
- Check pattern from "Initiating and maintaining a session": `NISession.deviceCapabilities.supportsPreciseDistanceMeasurement` → distance-only interaction.
- In an iPhone app running on visionOS, all capabilities report unavailable. The simulator reports no UWB (UNVERIFIED but expected; the app then shows "UWB not supported").

### NIDiscoveryToken — https://developer.apple.com/documentation/nearbyinteraction/nidiscoverytoken
- `class NIDiscoveryToken` with `init?(coder: NSCoder)` (NSSecureCoding), so it archives with secure coding.
- `var deviceCapabilities: any NIDeviceCapability` — the peer's capabilities (not used).

### NINearbyPeerConfiguration — https://developer.apple.com/documentation/nearbyinteraction/ninearbypeerconfiguration
- `init(peerToken: NIDiscoveryToken)`; `var peerDiscoveryToken: NIDiscoveryToken`.
- `var isCameraAssistanceEnabled: Bool` (iOS 16+, **default false**) — we never set it. It uses ARKit (camera) to give distance and direction in more conditions. https://developer.apple.com/documentation/nearbyinteraction/ninearbypeerconfiguration/iscameraassistanceenabled
- `var isExtendedDistanceMeasurementEnabled: Bool` — not used (booth is ~3 m).

### NINearbyObject — https://developer.apple.com/documentation/nearbyinteraction/ninearbyobject
- `var distance: Float? { get }` — meters, `nil` when unavailable (out of range). "The framework doesn't implement secure ranging" (irrelevant for us). https://developer.apple.com/documentation/nearbyinteraction/ninearbyobject/distance-676dm
- `var direction: simd_float3? { get }` — ignored. On iPhone, direction for third-party accessories needs camera assistance.
  The PRD's "on iPhone 14 and later direction typically needs camera assistance" is not stated on the pages read; UNVERIFIED and irrelevant (we use distance only).
- `enum RemovalReason { case peerEnded, timeout }` — https://developer.apple.com/documentation/nearbyinteraction/ninearbyobject/removalreason (imported from Obj-C, so `switch` needs `@unknown default`).

### NISessionDelegate — https://developer.apple.com/documentation/nearbyinteraction/nisessiondelegate
All `optional`, `protocol NISessionDelegate : NSObjectProtocol`:
- `func session(_ session: NISession, didUpdate nearbyObjects: [NINearbyObject])` — new measurements; distance `nil` when out of range.
- `func session(_ session: NISession, didRemove nearbyObjects: [NINearbyObject], reason: NINearbyObject.RemovalReason)` — after this, no more `didUpdate` for those objects. Apple's sample retries on `.timeout` by calling `session.run(session.configuration)`, with app logic deciding how many retries. https://developer.apple.com/documentation/nearbyinteraction/nisessiondelegate/session(_:didremove:reason:)
- `func sessionWasSuspended(_ session: NISession)` — "NI suspends a session when the user backgrounds the app"; also "for internal reasons". "A suspended session won't resume on its own." If the app stays backgrounded too long, NI invalidates the session and the peer gets `didRemove` with `.timeout`. https://developer.apple.com/documentation/nearbyinteraction/nisessiondelegate/sessionwassuspended(_:)
- `func sessionSuspensionEnded(_ session: NISession)` — "An app may resume a suspended session only after NI invokes this callback ... call `run(_:)`, passing in your session's configuration." Suspension is local (a phone call can also cause it).
- `func sessionDidStartRunning(_ session: NISession)` — iOS 16+, session started or resumed.
- `func session(_ session: NISession, didInvalidateWith error: any Error)` — "the app can't restart the session ... begin a new session". https://developer.apple.com/documentation/nearbyinteraction/nisessiondelegate/session(_:didinvalidatewith:)

### NIError — https://developer.apple.com/documentation/nearbyinteraction/nierror
- `struct NIError`, `enum Code`: `activeSessionsLimitExceeded`, `invalidConfiguration` (e.g. invalid peer token), `resourceUsageTimeout`, `sessionFailed`, `unsupportedPlatform`, `userDidNotAllow` (user declined the prompt), `invalidARConfiguration`, `incompatiblePeerDevice`, `accessoryPeerDeviceUnavailable`, `activeExtendedDistanceSessionsLimitExceeded`.
- **Concurrent session limit:** `activeSessionsLimitExceeded` — "The maximum number of concurrent Nearby Interaction sessions varies across device type and platform." https://developer.apple.com/documentation/nearbyinteraction/nierror/activesessionslimitexceeded
  Apple publishes no number. Three peer sessions on the wearer is the PRD's open risk; the app switches to round-robin on this error.

### Usage description — https://developer.apple.com/documentation/bundleresources/information-property-list/nsnearbyinteractionusagedescription
- `NSNearbyInteractionUsageDescription` (iOS 15+). Shown on the first `run`; the choice is stored in Settings (Privacy & Security > Nearby Interactions).

### Range, orientation, background (article "Initiating and maintaining a session")
https://developer.apple.com/documentation/nearbyinteraction/initiating-and-maintaining-a-session
- Works best within 9 m, portrait, "facing each other with their back camera". Obstacles (people) degrade it — matches the PRD's body-block risk. Anchors should face the walking area.
- Backgrounding suspends sessions (so: idle timer off, app in front, Guided Access on anchors).
- Peers that close the app or leave range time out (`didRemove` `.timeout`).

## 2. How `ios/EarmarkUWB` maps PRD 7.6 onto these APIs

| Event | Code (`Sources/SessionRecovery.swift`, `PeerSession`) |
|---|---|
| `sessionWasSuspended` | phase "Paused"; anchors send `status` at once |
| `sessionSuspensionEnded` | `session.run(session.configuration)` |
| `didRemove .timeout` | `run` again with the stored peer token; 3rd consecutive timeout → new `NISession` → new token published |
| `didRemove .peerEnded` | wait; the next `uwb_token` from that peer runs it |
| `didInvalidateWith` | `userDidNotAllow` → show "turn on in Settings", no retry; otherwise new session + new token after 1, 2, 4, 8, 10 s |
| app backgrounded | NI suspends by itself; foreground resumes via the two suspension callbacks; the bus reconnects at once |

## 3. Foundation (tokens, WebSocket)

- `NSKeyedArchiver.archivedData(withRootObject:requiringSecureCoding:)` — `class func archivedData(withRootObject object: Any, requiringSecureCoding requiresSecureCoding: Bool) throws -> Data` (iOS 11+). https://developer.apple.com/documentation/foundation/nskeyedarchiver/archiveddata(withrootobject:requiringsecurecoding:)
- `NSKeyedUnarchiver.unarchivedObject(ofClass:from:)` — `static func unarchivedObject<DecodedObjectType>(ofClass cls: DecodedObjectType.Type, from data: Data) throws -> DecodedObjectType? where DecodedObjectType : NSObject, DecodedObjectType : NSCoding`. https://developer.apple.com/documentation/foundation/nskeyedunarchiver/unarchivedobject(ofclass:from:)
- `URLSessionWebSocketTask.receive(completionHandler:)` — `@preconcurrency func receive(completionHandler: @escaping @Sendable (Result<URLSessionWebSocketTask.Message, any Error>) -> Void)`; one message per call, so the client re-arms it after each message. https://developer.apple.com/documentation/foundation/urlsessionwebsockettask/receive(completionhandler:)
- `URLSessionWebSocketTask.sendPing(pongReceiveHandler:)` — `func sendPing(pongReceiveHandler: @escaping @Sendable ((any Error)?) -> Void)`. https://developer.apple.com/documentation/foundation/urlsessionwebsockettask/sendping(pongreceivehandler:)
- Client pattern (hello on open, ping 5 s, backoff 0.5 → 5 s) copied from `mac/Sources/EarmarkAudio/BusClient.swift`.

## 4. App Transport Security and local network

- `NSAllowsLocalNetworking` — https://developer.apple.com/documentation/bundleresources/information-property-list/nsapptransportsecurity/nsallowslocalnetworking — "In iOS 17 ... ATS no longer allows connections to IP addresses by default." The key re-enables unqualified names, `.local`, and IP addresses. Needed for `ws://192.168.x.x:8765`.
- `NSLocalNetworkUsageDescription` — https://developer.apple.com/documentation/bundleresources/information-property-list/nslocalnetworkusagedescription — any app that makes "direct unicast or multicast connections to local hosts" should include it; iOS prompts on the first local connection.

## 5. CoreMotion (moving vs still)

- `CMMotionManager.startDeviceMotionUpdates(to:withHandler:)` — `func startDeviceMotionUpdates(to queue: OperationQueue, withHandler handler: @escaping CMDeviceMotionHandler)`; Apple: "using the main operation queue is not recommended" for high rates, so we use a private serial queue. https://developer.apple.com/documentation/coremotion/cmmotionmanager/startdevicemotionupdates(to:withhandler:)
- `var deviceMotionUpdateInterval: TimeInterval` (seconds; clamped to hardware limits; check timestamps if exact intervals matter). We use 1/50 s.
- `CMDeviceMotion.userAcceleration: CMAcceleration` — total acceleration minus gravity, in g. https://developer.apple.com/documentation/coremotion/cmdevicemotion/useracceleration
- `isDeviceMotionAvailable` — needs accelerometer + gyro (every UWB iPhone has both).
- Device motion needs no runtime permission (UNVERIFIED: Apple ties the Motion & Fitness prompt to activity/pedometer APIs); `NSMotionUsageDescription` is in the plist anyway per the PRD.

## 6. Audio (push-to-talk on the wearer)

- `AVAudioApplication.requestRecordPermission()` — `class func requestRecordPermission() async -> Bool` (iOS 17+). Without permission the mic records silence; without `NSMicrophoneUsageDescription` the app exits. https://developer.apple.com/documentation/avfaudio/avaudioapplication/requestrecordpermission(completionhandler:)
- `AVAudioSession.setCategory(_:mode:options:)` — `func setCategory(_ category: AVAudioSession.Category, mode: AVAudioSession.Mode, options: AVAudioSession.CategoryOptions = []) throws`.
- Category `.record`: "recording audio while also silencing playback audio" — https://developer.apple.com/documentation/avfaudio/avaudiosession/category-swift.struct/record . Chosen so the wearer phone plays nothing (no reason for the AirPods to switch to it).
- No `CategoryOptions`: in particular not `.allowBluetoothHFP` (the old `.allowBluetooth` is now deprecated), so a Bluetooth headset is never offered as input.
- Mode `.default`. `.measurement` "minimize[s] the amount of system-supplied signal processing" and uses the primary mic; it would remove gain control, which helps speech from a hand-held phone. Switch in `PushToTalk.start()` if recordings clip or pump.
- `setPreferredInput(_:)` with the `.builtInMic` port from `availableInputs` — "set a preferred input port only after setting the audio session's category and mode and activating the session." https://developer.apple.com/documentation/avfaudio/avaudiosession/setpreferredinput(_:)
- `AVAudioNode.installTap(onBus:bufferSize:format:block:)` — tap block may run off the main thread; one tap per bus. Shown as deprecated in iOS 27 in the docs (fine for an iOS 17 target). https://developer.apple.com/documentation/avfaudio/avaudionode/installtap(onbus:buffersize:format:block:)
- `AVAudioConverter.convert(to:error:withInputFrom:)` — returns `.noDataNow` after one buffer to keep resampler state, the same pattern as the Mac app's `PCMResampler`.
- Format: 16 kHz mono `pcm_s16le`, 1600-frame (100 ms) chunks, `mic_audio.seq` increasing — identical to `mac/Sources/EarmarkAudio/PCM.swift` and what the concierge's Cartesia STT expects.

## 7. UIKit

- `UIApplication.isIdleTimerDisabled` — set while a role runs (anchors must not lock; NI suspends in the background). https://developer.apple.com/documentation/uikit/uiapplication/isidletimerdisabled
- `UIDevice.batteryLevel` — 0.0-1.0, `-1.0` unless `isBatteryMonitoringEnabled` is true. https://developer.apple.com/documentation/uikit/uidevice/batterylevel

## 8. UWB accessories (production path, PRODUCTION.md 3.1)

Read 2026-10-25 on developer.apple.com.
- Nearby Interaction page: "Implement the Nearby Interaction accessory protocol with a Nearby Interaction-enabled UWB chipset ... Contact your UWB chipset vendor to confirm feature support." No vendors are named. https://developer.apple.com/nearby-interaction/
- `NINearbyAccessoryConfiguration` (iOS 15+): "In iOS 16, third-party UWB accessories paired to the device through Bluetooth can interact with your app while it's in the background." `init(accessoryData:bluetoothPeerIdentifier:)` is iOS 16+. https://developer.apple.com/documentation/nearbyinteraction/ninearbyaccessoryconfiguration
- WWDC21 session 10165 names no vendors. Qorvo's pages were not reachable from the build environment (proxy 403), so no module model or price is claimed.
