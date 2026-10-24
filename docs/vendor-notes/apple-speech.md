# Apple Speech framework - vendor notes for Earmark (fallback STT)

Researched 2026-10-24 for BUILD_BRIEF section 5.E ("Speech input", fallback path).
Environment: macOS 26.5.1, Command Line Tools only, Swift 6.1.2, and `xcrun --show-sdk-version` = **15.5**.
"SDK header" means I grepped `/Library/Developer/CommandLineTools/SDKs/MacOSX15.5.sdk/System/Library/Frameworks/Speech.framework`.
Anything I could not confirm is marked UNVERIFIED.

## 0. Recommendation

- **Use `SFSpeechRecognizer` + `SFSpeechAudioBufferRecognitionRequest`**, fed from the same `AVAudioEngine` input tap that captures mic audio for Cartesia.
  It compiles with the 15.5 SDK and runs on macOS 26.
- **`SpeechAnalyzer` / `SpeechTranscriber` cannot be compiled here.**
  They are macOS 26.0+, and the local 15.5 SDK has no public declarations for them (section 4).
  Using them would mean installing a macOS 26 SDK, either with Command Line Tools 26 or with Xcode 26.
  That is not worth it for a fallback path.
- **The app must run as a real `.app` bundle launched with `open`**, so that it is its own TCC responsible process (section 3).
  `swift run` from a terminal will crash or be refused at the permission check.

## 1. `SFSpeechRecognizer` on macOS

- Available on macOS 10.15+.
  The docs JSON for `SFSpeechRecognizer` and `SFSpeechAudioBufferRecognitionRequest` carries no deprecation (checked 2026-10-24).
  https://developer.apple.com/documentation/speech/sfspeechrecognizer
- Setup order from Apple:
  1. Request authorization.
  2. Create the recognizer.
  3. Check `isAvailable`.
  4. Prepare the audio.
  5. Create the request.
  6. Call `recognitionTask(with:resultHandler:)` or `recognitionTask(with:delegate:)`.

  Same page.
- `init(locale:)` returns nil if the locale is unsupported.
  `isAvailable` can change at runtime, and the delegate gets `speechRecognizer(_:availabilityDidChange:)` (SDK header `SFSpeechRecognizer.h`).
- **Authorization:**
  - `SFSpeechRecognizer.requestAuthorization { status in ... }` runs asynchronously.
  - The system prompts only the first time.
    Later calls return the recorded answer almost immediately.
  - Status is one of `.notDetermined`, `.denied`, `.restricted`, `.authorized`.
  - Apple's example hops to the main queue inside the handler.
  - Source: https://developer.apple.com/documentation/speech/asking-permission-to-use-speech-recognition
- **On-device:**
  - `supportsOnDeviceRecognition` says whether the recognizer can work without network access (https://developer.apple.com/documentation/speech/sfspeechrecognizer/supportsondevicerecognition).
  - `request.requiresOnDeviceRecognition = true` keeps audio on the device, "however, on-device requests won't be as accurate" (https://developer.apple.com/documentation/speech/sfspeechrecognitionrequest/requiresondevicerecognition).
  - The setting is honored only when `supportsOnDeviceRecognition` is true (same page).
  - Brief 5.E says to prefer on-device: `request.requiresOnDeviceRecognition = recognizer.supportsOnDeviceRecognition`.
- **Partial results:**
  - `shouldReportPartialResults` defaults to true.
    The result handler is then called "repeatedly with partial results, then finally with a final result or an error" (SDK headers `SFSpeechRecognitionRequest.h`, `SFSpeechRecognizer.h`).
  - Read `result.bestTranscription.formattedString` and `result.isFinal` (SDK header `SFSpeechRecognitionResult.h`).
  - Handlers run on `recognizer.queue`, which "defaults to the main queue" (SDK header).
  - Send a `transcript` bus message only on `isFinal`, or on our own end-of-speech timer.
- **Task handling** (SDK header `SFSpeechRecognitionTask.h`, https://developer.apple.com/documentation/speech/sfspeechaudiobufferrecognitionrequest):
  - The request "continuously analyzes the audio you appended, stopping only when you call the `endAudio()` method".
    "You must call endAudio() explicitly."
  - `task.finish()` stops accepting audio but completes processing on what is already buffered.
  - `task.cancel()` aborts.
  - Before starting a new task, cancel the old one and create a fresh request, because a request is used once.
  - Push-to-talk: start on Space down, then `endAudio()` on Space up.
  - Always-listening: restart a new request and task after each final result.
- **Limits** (https://developer.apple.com/documentation/speech/sfspeechrecognizer):
  - "Plan for a one-minute limit on audio duration ... the framework stops speech recognition tasks that last longer than one minute."
  - "Individual devices may be limited in the number of recognitions that can be performed per day, and each app may be throttled globally."
    A failure within 1 to 2 seconds of starting usually means the service is unavailable.
  - Older third-party articles say on-device recognition removes the one-minute cap.
    A 2026 guide says it does not (https://picovoice.ai/blog/ios-speech-recognition/).
    UNVERIFIED.
    Design for the cap anyway: in always-listening mode, roll to a new task at about 50 s even without a final result.
- **Vocabulary (object names):**
  - `request.contextualStrings: [String]` holds "phrases which should be recognized even if they are not in the system vocabulary" (SDK header).
  - Keep each phrase to "one or two words whenever possible", and "limit the total number of phrases to no more than 100" (https://developer.apple.com/documentation/speech/sfspeechrecognitionrequest/contextualstrings).
  - Fill it from the registry's object names and aliases, for example "AirPods case", "keys", "wallet".
  - Heavier options exist: `customizedLanguageModel` (`SFSpeechLanguageModel`, macOS 14+) and `addsPunctuation` (macOS 13+) (SDK header).
    We do not need them.
- `taskHint` can be `.dictation`, `.search` or `.confirmation` (SDK header `SFSpeechRecognitionTaskHint.h`).
  `.search` might suit short queries like "where are my keys".
  Any accuracy benefit is UNVERIFIED.
- **Siri/Dictation dependency:** iOS developers report recognition failing with "Siri and Dictation are disabled" (kLSRErrorDomain 201) while `isAvailable` still returns true (https://developer.apple.com/forums/thread/739006, https://developer.apple.com/forums/thread/690736).
  The same behavior on macOS is UNVERIFIED.
  Enable Dictation on the demo Mac (System Settings > Keyboard > Dictation), and handle task errors rather than trusting `isAvailable`.

## 2. Feeding it from `AVAudioEngine` on macOS

- **macOS has no `AVAudioSession`.**
  The SDK header marks it `API_UNAVAILABLE(macos)` (`AVFAudio.framework/Headers/AVAudioSession.h`).
  Drop the `AVAudioSession.sharedInstance()` lines found in iOS samples.
- **One tap per bus.**
  The tap block "may [run] on a thread other than the main thread" (https://developer.apple.com/documentation/avfaudio/avaudionode/installtap(onbus:buffersize:format:block:)).
  Use a single input tap and fan each buffer out to both the Cartesia PCM converter and, when the fallback is active, `request.append(buffer)`.
- That docs page marks `installTap` deprecated in the 27.0 SDKs in favor of `installAudioTap(onBus:bufferSize:format:tapProvider:)`.
  This does not matter with the 15.5 SDK.
- `SFSpeechAudioBufferRecognitionRequest.nativeAudioFormat` is "the preferred audio format for optimal speech recognition" (https://developer.apple.com/documentation/speech/sfspeechaudiobufferrecognitionrequest).
  The usual pattern appends buffers in the input node's own format (`inputNode.outputFormat(forBus: 0)`).
  Whether the recognizer converts other formats internally is UNVERIFIED.
  If results are empty, convert to `nativeAudioFormat` with `AVAudioConverter`.
- The "Recognizing speech in live audio" sample now targets iOS 27 and uses `SpeechAnalyzer` + `DictationTranscriber` + `CaptureInputSequenceProvider`, so it no longer shows the `AVAudioEngine` pattern (https://developer.apple.com/documentation/speech/recognizing-speech-in-live-audio).
  The sketch below is mine, assembled from the API docs above.
  It passes `swiftc -typecheck -target arm64-apple-macos14.0` with the local 15.5 SDK, but I have not run it.

```swift
import AVFoundation
import Speech

final class AppleSTT {
    private let recognizer = SFSpeechRecognizer(locale: Locale(identifier: "en-US"))!
    private var request: SFSpeechAudioBufferRecognitionRequest?
    private var task: SFSpeechRecognitionTask?

    /// Call from the shared input tap (any thread).
    func append(_ buffer: AVAudioPCMBuffer) { request?.append(buffer) }

    func start(vocabulary: [String], onFinal: @escaping (String) -> Void) {
        task?.cancel()
        let req = SFSpeechAudioBufferRecognitionRequest()
        req.shouldReportPartialResults = true
        req.requiresOnDeviceRecognition = recognizer.supportsOnDeviceRecognition
        req.contextualStrings = Array(vocabulary.prefix(100))
        request = req
        task = recognizer.recognitionTask(with: req) { [weak self] result, error in
            if let result, result.isFinal { onFinal(result.bestTranscription.formattedString) }
            if error != nil || result?.isFinal == true { self?.request = nil; self?.task = nil }
        }
    }

    func stop() { request?.endAudio() }  // push-to-talk release; task delivers the final result
}
```

## 3. Permissions, Info.plist, and the app bundle

- **`NSSpeechRecognitionUsageDescription` is required.**
  "This applies regardless of whether you set requiresOnDeviceRecognition to true or false. If this key isn't present, your app crashes when it calls requestAuthorization(_:)." (https://developer.apple.com/documentation/bundleresources/information-property-list/nsspeechrecognitionusagedescription)
- **`NSMicrophoneUsageDescription` is required** for microphone use (https://developer.apple.com/documentation/bundleresources/information-property-list/nsmicrophoneusagedescription).
  If it is missing, "the system terminates your app" (https://developer.apple.com/documentation/bundleresources/requesting-authorization-for-media-capture-on-macos).
  Check `AVCaptureDevice.authorizationStatus(for:)` first, and call `requestAccess(for:)` while the status is `.notDetermined`.
  Apple's example uses `.video`, and `.audio` is the mic equivalent (same page).
  Reset during testing with `tccutil reset Microphone` (same page).
- Hardened runtime builds also need the `com.apple.security.device.audio-input` entitlement (https://developer.apple.com/documentation/bundleresources/entitlements/com.apple.security.device.audio-input).
  Plain ad-hoc builds without `--options runtime` should not need it.
  That last point is UNVERIFIED.
- Motion permission for `CMHeadphoneMotionManager` (`NSMotionUsageDescription`) is outside this note.
  See the Apple audio and head-tracking notes.
- **Why a bundle is required (TCC "responsible process"):**
  - TCC charges a permission request to the responsible process.
    For anything launched from a shell, that is the terminal or IDE app, not our binary.
    If that app lacks the usage string, TCC kills our process (https://www.qt.io/blog/the-curious-case-of-the-responsible-process, https://github.com/Mudlet/Mudlet/issues/11021).
  - Mudlet's crash log shows "Responsible Process: Code ... Termination Reason: Namespace TCC" even though Mudlet's own `Info.plist` had the key (same issue, Sep 2026).
  - Launching with `open` (LaunchServices) makes the app its own responsible process, and this "only works for application bundles and not for standalone executables" (Qt blog).
  - Local `plutil` check: `Terminal.app` declares neither `NSMicrophoneUsageDescription` nor `NSSpeechRecognitionUsageDescription`.
    Running the bare binary from Terminal will likely be killed at `requestAuthorization`.
    That is UNVERIFIED, but it matches the cases above.
  - Embedding a plist into a bare executable (`-Xlinker -sectcreate -Xlinker __TEXT -Xlinker __info_plist -Xlinker Info.plist`) is a community technique (https://steipete.me/posts/2025/applescript-cli-macos-complete-guide).
    It does not change the responsible process when the binary is launched from a terminal.
    Prefer a real bundle.
- **Recipe without Xcode:**
  1. Run `swift build -c release`.
  2. Create `Earmark.app/Contents/MacOS/EarmarkApp` and `Earmark.app/Contents/Info.plist`.
     The plist needs `CFBundleIdentifier`, `CFBundleExecutable`, `CFBundlePackageType=APPL`, `LSMinimumSystemVersion=14.0`, and the usage keys.
  3. Sign it with `codesign --force --sign - --identifier <bundle id> Earmark.app`.
  4. Launch it with `open -W Earmark.app --stdout logs/mac.out --stderr logs/mac.err`.
     The `--stdout`/`--stderr` trick keeps logs (Mudlet issue).
- **Rebuilds can drop TCC grants:** with ad-hoc signing, the designated requirement is the cdhash, so each rebuild can look like a new app and re-prompt.
  This is community-reported, for example https://github.com/YARC-Official/YARG/issues/1695 and https://github.com/NousResearch/hermes-agent/issues/74331.
  To avoid it, sign with a stable self-signed or Apple Development identity, or accept one re-prompt per rebuild during dev.

## 4. `SpeechAnalyzer` / `SpeechTranscriber` (macOS 26) and our SDK

- Availability, from the Apple docs JSON metadata:
  - `SpeechAnalyzer`, `SpeechTranscriber` and `AnalysisContext` are iOS/macOS/tvOS/visionOS **26.0+**.
  - `DictationTranscriber` is 26.0+ on everything except tvOS.
  - https://developer.apple.com/documentation/speech/speechanalyzer, https://developer.apple.com/documentation/speech/speechtranscriber, https://developer.apple.com/documentation/speech/dictationtranscriber
- **Local SDK grep (2026-10-24):**
  - Neither `SpeechAnalyzer` nor `SpeechTranscriber` appears in `Speech.framework/Headers/*.h` or in `Modules/Speech.swiftmodule/arm64e-apple-macos.swiftinterface` (0 matches).
  - `Versions/A/Speech.tbd` exports only private Objective-C `SFSpeechAnalyzer*` classes, with no public header, so they are SPI and unusable.
  - **Compile test:** `import Speech; let a = SpeechAnalyzer(modules: [])` with `swiftc -typecheck -target arm64-apple-macos26.0` fails with "cannot find 'SpeechAnalyzer' in scope".
  - **Conclusion:** `SpeechAnalyzer` cannot be compiled with the 15.5 SDK.
- `softwareupdate --list` on this Mac did not offer a newer Command Line Tools package (2026-10-24).
  Whether CLT 26 (with the macOS 26 SDK) can be installed from https://developer.apple.com/download/all/ without Xcode is UNVERIFIED.
- Benefits if we ever switch:
  - The API uses async sequences, and `AssetInventory` manages on-device model downloads.
  - `SpeechTranscriber.isAvailable` checks hardware support, with `DictationTranscriber` "compatible with older devices" as the fallback (https://developer.apple.com/documentation/speech/speechtranscriber).
  - `AnalysisContext.contextualStrings` (100 phrases max) works "with the DictationTranscriber module", so custom vocabulary means `DictationTranscriber`, not `SpeechTranscriber` (https://developer.apple.com/documentation/speech/analysiscontext/contextualstrings).
  - A third-party guide says SpeechAnalyzer drops the session time limit (https://picovoice.ai/blog/ios-speech-recognition/).
    UNVERIFIED.
