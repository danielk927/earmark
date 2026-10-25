# Earmark UWB iPhone app (`ios/EarmarkUWB`)

One app, four iPhones: three fixed **UWB Reader/Emitter 1/2/3** anchors and one handheld **Wearer**.
The wearer measures its distance to each anchor with Nearby Interaction and streams `uwb_range` and `motion_state` to the hub, which solves the position and publishes `listener_pose`.
Spec: `docs/project/UWB-PRD.md` section 7. API notes: `docs/sponsors/vendor-notes/apple-nearby-interaction.md`.

This code was written on Windows without a Swift toolchain, so **it has never been compiled**.
Expect a few small fixes on the first build (see "If it doesn't compile" below).

## Files

| File | What it does |
|---|---|
| `project.yml` | XcodeGen spec: iOS 17 SwiftUI app `EarmarkUWB`, local package `../../contracts/swift` (`EarmarkContracts`), logic test target. |
| `Info.plist` | Usage strings (PRD 7.1) and the ATS `NSAllowsLocalNetworking` exception (iOS 17 blocks plain `ws://<ip>` otherwise). Merged with Xcode's generated plist. |
| `Sources/EarmarkUWBApp.swift` | `@main`, root view, scene-phase forwarding. |
| `Sources/AppModel.swift` | `DeviceRole` (uwb_1/2/3/wearer), remembered role / hub address / secret, starts and stops a role, idle timer off while running. |
| `Sources/HubConnection.swift` | WebSocket bus client: `hello` (with `device_id`, `role`, `secret`), snapshot labels, ping every 5 s, reconnect 0.5 s to 5 s. |
| `Sources/CapabilityCheck.swift` | `NISession.deviceCapabilities.supportsPreciseDistanceMeasurement`. |
| `Sources/SessionRecovery.swift` | `PeerSession`: one NISession to one peer plus every PRD 7.6 recovery rule; `TokenCodec` (NSKeyedArchiver, base64). |
| `Sources/AnchorController.swift` | Anchor role: one session to the wearer, status every 5 s, never sends ranges. |
| `Sources/WearerController.swift` | Wearer role: three sessions, `uwb_range` (per-anchor seq, max 20 Hz), rate meters, round-robin fallback, `motion_state`, push-to-talk, status. |
| `Sources/MotionDetector.swift` | CoreMotion device motion at 50 Hz into `MotionClassifier`. |
| `Sources/PushToTalk.swift` | Built-in mic, 16 kHz mono Int16, 100 ms chunks, as `mic_audio` (same format as the Mac app). |
| `Sources/*View.swift` | Role picker, anchor screen, wearer screen, shared rows. |
| `Sources/Logic/` | Pure, unit-tested: motion RMS + hysteresis, 20 Hz decimator, rate meter, backoff, hub address parsing. |
| `Tests/LogicTests.swift` | XCTest for `Sources/Logic` (no host app; runs on any simulator). |

## Mac build checklist

1. **Install Xcode** from the App Store (large; start it first), open it once, accept the license, let it install the iOS platform.
   Then `xcode-select -p` should print `/Applications/Xcode.app/...`; if not: `sudo xcode-select -s /Applications/Xcode.app`.
2. `brew install xcodegen`
3. Generate and open:
   ```sh
   cd ios/EarmarkUWB
   xcodegen generate
   open EarmarkUWB.xcodeproj
   ```
   Re-run `xcodegen generate` after adding or renaming files (the `.xcodeproj` is generated; don't hand-edit it).
4. **Signing:** Xcode > Settings > Accounts > add your Apple ID.
   Target `EarmarkUWB` > Signing & Capabilities > Team = your personal team (free is fine; profiles expire after 7 days, just reinstall).
   If the bundle id `com.earmark.uwb` is rejected as taken, change `PRODUCT_BUNDLE_IDENTIFIER` in `project.yml` (for example `com.<yourname>.earmark.uwb`) and regenerate.
   Free teams have small provisioning limits (devices and app ids per week); if Xcode refuses the 4th phone, sign that one with a second teammate's Apple ID (change the bundle id for it) or use a paid team.
5. **Run the logic tests** once: scheme `EarmarkUWB`, pick any iPhone simulator, Product > Test (Cmd-U).
   The app itself also launches in the simulator, but it will show "UWB not supported" (expected).
6. **Phones** (all four must be iPhone 11 or later, not SE):
   - Connect each phone by cable, unlock it, tap "Trust This Computer".
   - Developer Mode: run once from Xcode; then on the phone Settings > Privacy & Security > Developer Mode > On, restart, confirm.
   - Pick the phone as the run destination, Run (Cmd-R).
   - First launch of a free-team app: Settings > General > VPN & Device Management > your Apple ID > Trust.
7. **AirPods auto-switch fix (PRD 13.1)** on the wearer phone: Settings > Bluetooth > (i) next to the AirPods > Connect to This iPhone > **When Last Connected to This iPhone**, or forget the AirPods on that phone, or sign it into another Apple ID.
   The app records with `AVAudioSession` category `.record`, which plays nothing, but a notification sound could still pull the AirPods over.
8. **Focus / Do Not Disturb** on all four phones. Auto-Lock is handled by the app (idle timer off while a role runs), but keep anchors plugged in and set brightness low (PRD 13.5). Guided Access (Settings > Accessibility) keeps a judge from leaving the app on an anchor.
9. **Network (PRD 13.3):** all phones and the Mac on the team's private router or hotspot (not venue Wi-Fi, not an anchor/wearer hotspot). Note the Mac's IP (`ipconfig getifaddr en0`).
10. **Hub settings (PRD 9.4):** in the repo `.env` set `EARMARK_BUS_SECRET=<something>`, and set the bus host to `0.0.0.0` (`bus.host` in `config/hub.json`) so the phones can reach it. Restart the hub.
11. **On each phone:** pick the role, enter `ws://<mac-ip>:8765` and the secret, tap Connect.
    - iOS asks for **Local Network** access on the first connect: Allow. (If denied: Settings > Privacy & Security > Local Network > Earmark UWB.)
    - iOS asks for **Nearby Interaction** the first time a session runs: Allow. (If denied, the screen says so: Settings > Privacy & Security > Nearby Interactions.)
    - Wearer only: **Motion & Fitness** may be asked; **Microphone** is asked on the first Talk.
    - The hub dot turns green once the hub answers `hello` with a snapshot. If the hub refuses the phone, its reason is shown in red (e.g. "wrong or missing bus secret in hello"; it then closes with code 1008). A red dot with no reason usually means a wrong IP, a different network, or the hub still bound to 127.0.0.1.

## On-device gates (PRD 12.2, in order; record each result in `docs/project/STATUS.md`)

Watch the wearer screen (per-anchor distance, "Hz sent", "Hz measured") and the hub (`listener_pose`).

1. **Ranging gate:** one anchor + wearer, tape measure at 0.5 / 1 / 2 / 3 m. Pass: each within ±0.10 m averaged over 2 s.
   Record: true distance, mean reading, spread, phone models.
2. **Concurrency gate:** wearer with all three anchors for 2 minutes. Pass: at least 5 Hz per anchor ("Hz sent" on every row) the whole time.
   If a row drops out or the app shows "round-robin was turned on", record it, then try the round-robin toggle and record the per-anchor rate with it.
3. **Position gate:** stand on 5 floor marks. Pass: median error ≤ 0.20 m, max ≤ 0.35 m.
4. **Freeze gate:** walk to the counter 10 times, stop naturally. Pass: frozen point within 0.15 m of the mark in 8 of 10.
5. **Body-block check:** walk with your body between the phone and one anchor. Pass: the anchor is flagged in `blocked` and the pose doesn't jump more than 0.3 m.
6. **Walk gate:** eyes closed, start mark to the sugar, 5 attempts with a spotter. Pass: 4 of 5 correct (NFC-confirmed).

For each gate write in `docs/project/STATUS.md`: date/time, phone models and iOS versions, anchor positions used, the numbers, pass/fail, and anything odd (session restarts, rates, round-robin needed or not).

## Manual Xcode fallback (no XcodeGen)

1. Xcode > File > New > Project > iOS App. Product name `EarmarkUWB`, interface SwiftUI, language Swift, no tests, no Core Data. Save it inside `ios/EarmarkUWB/` (Xcode creates a subfolder; that's fine).
2. Delete the template's `ContentView.swift` and `<Name>App.swift`.
3. Drag the `Sources` folder into the project (Copy items: off; "Create groups"; target EarmarkUWB checked).
4. File > Add Package Dependencies > Add Local… > choose `contracts/swift` > add product `EarmarkContracts` to the app target.
5. Target > General: Minimum Deployments iOS 17.0, iPhone only.
6. Target > Build Settings: `Info.plist File` = path to `ios/EarmarkUWB/Info.plist` (relative to the project), `Generate Info.plist File` = Yes, `Swift Language Version` = Swift 5, `Strict Concurrency Checking` = Minimal. If your Xcode adds `Default Actor Isolation = MainActor` or "Approachable Concurrency" to new projects, set them back to `nonisolated` / No.
   Alternatively, copy the five keys from `Info.plist` into the target's Info tab.
7. Signing as in step 4 above.

## If it doesn't compile: first things to check

- **Concurrency diagnostics.** The code is written for Swift 5 language mode with minimal checking. If the project ended up in Swift 6 mode or with default MainActor isolation (Xcode 26 templates), set `SWIFT_VERSION` 5 and `SWIFT_STRICT_CONCURRENCY` minimal and remove `SWIFT_DEFAULT_ACTOR_ISOLATION`. Sendable warnings in Swift 5 mode are expected and harmless.
- **`MainActor.assumeIsolated`** (iOS 17+) is used in NISession and URLSession delegate callbacks; it relies on the delegate queue being main (`session.delegateQueue = .main`, `URLSession(..., delegateQueue: .main)`). If a callback ever arrives off main it traps; the fix is to hop with `onMain { }` instead.
- **Package not found:** `project.yml` points at `../../contracts/swift`. Run `xcodegen` from `ios/EarmarkUWB/`. File > Packages > Reset Package Caches if Xcode is confused.
- **`AVAudioConverter.convert(to:error:withInputFrom:)` closure** captures a local `var fed`; this is the same pattern as `mac/Sources/EarmarkAudio/PCM.swift` (`PCMResampler`), which builds.
- **`installTap(onBus:...)`** is marked deprecated in the iOS 27 SDK docs; a deprecation warning is fine.
- **`Task.sleep(for:)`** needs iOS 16+ (we target 17).
- **Info.plist duplicated** ("Multiple commands produce Info.plist"): make sure `Info.plist` is not in Copy Bundle Resources (it lives outside `Sources/` for that reason).

## Known risks

- **Three concurrent NISessions** on the wearer are the main open risk (PRD 7.6). Apple documents only that the limit "varies across device type and platform" (`NIError.activeSessionsLimitExceeded`). The app switches to round-robin automatically if it sees that error; it can also be toggled by hand.
- Round-robin uses `NISession.pause()` and re-`run`. If the anchor side times out during the 2 s rest, it re-runs with the same token (its timeout rule), which may add a short gap each rotation. Tune `WearerController.roundRobinPeriod` if needed.
- A session invalidated while the app is in the background is recreated with a new token; the token reaches the peer when the bus reconnects (the hub relays and stores it).
- Distances are raw UWB slant ranges from the phone; the hub does slant and head-offset correction.
- The bus secret is stored in UserDefaults (fine for a private demo network).
