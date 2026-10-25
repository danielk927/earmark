# Apple API verification

Retrieved 2026-10-24 from official Apple documentation JSON (page fetches, not search snippets). These verify API declarations, not device behavior. macOS CI is the compile gate; microphone routes, latency and screen behavior require iPhone testing.

- [measurement](https://developer.apple.com/tutorials/data/documentation/avfaudio/avaudiosession/mode-swift.struct/measurement.json): A mode that indicates that your app is performing measurement of audio input or output.
- [installTap(onBus:bufferSize:format:block:)](https://developer.apple.com/tutorials/data/documentation/avfaudio/avaudionode/installtap(onbus:buffersize:format:block:).json): Installs an audio tap on a bus you specify to record, monitor, and observe the output of the node.
- [AVAudioTime](https://developer.apple.com/tutorials/data/documentation/avfaudio/avaudiotime.json): An object you use to represent a moment in time.
- [URLSessionWebSocketTask](https://developer.apple.com/tutorials/data/documentation/foundation/urlsessionwebsockettask.json): A URL session task that communicates over the WebSockets protocol standard.
- [vDSP_fft_zipD](https://developer.apple.com/tutorials/data/documentation/accelerate/vdsp_fft_zipd.json): Computes a forward or inverse in-place, double-precision complex FFT.
- [vDSP_dotprD](https://developer.apple.com/tutorials/data/documentation/accelerate/vdsp_dotprd.json): Calculates the dot product of two double-precision vectors.
- [builtInMic](https://developer.apple.com/tutorials/data/documentation/avfaudio/avaudiosession/port/builtinmic.json): An input from a device’s built-in microphone.
- [bottom](https://developer.apple.com/tutorials/data/documentation/avfaudio/avaudiosession/orientation/bottom.json): A data source that points downward.
- [requestRecordPermission(completionHandler:)](https://developer.apple.com/tutorials/data/documentation/avfaudio/avaudioapplication/requestrecordpermission(completionhandler:).json): Determines whether the app has permission to record audio.
- [inputLatency](https://developer.apple.com/tutorials/data/documentation/avfaudio/avaudiosession/inputlatency.json): The latency for audio input, in seconds.
- [isIdleTimerDisabled](https://developer.apple.com/tutorials/data/documentation/uikit/uiapplication/isidletimerdisabled.json): A Boolean value that controls whether the idle timer is disabled for the app.

Additional page fetches: [microphone selection QA1799](https://developer.apple.com/library/archive/qa/qa1799/_index.html) verifies category/mode activation before selecting availableInputs, builtInMic, dataSources, setPreferredDataSource, and supportedPolarPatterns before setPreferredPolarPattern. [Hardware guide](https://developer.apple.com/library/archive/documentation/Audio/Conceptual/AudioSessionProgrammingGuide/OptimizingForDeviceHardware/OptimizingForDeviceHardware.html) verifies preferred sample rate before activation, readback afterward, and warns simulator cannot test route changes/interruption.

Additional JSON page fetch on 2026-10-24: [ScenePhase](https://developer.apple.com/tutorials/data/documentation/swiftui/scenephase.json) defines inactive as foreground but paused and background as not visible, with resource-cleanup guidance on background entry. The locator stops on background, not transient inactive, to avoid invalidating pending permission requests. Permission-prompt behavior still needs device interaction testing.

The installTap declaration explicitly says bufferSize is a preference; log delivered frameLength. AVAudioTime represents host time using mach_absolute_time and/or sample time; validate both flags. measurement minimizes system processing and supports record. URLSessionWebSocketTask queues writes before handshake: the client must gate its own sends to prevent stale pose queues. inputLatency is seconds. requestRecordPermission requires NSMicrophoneUsageDescription.
