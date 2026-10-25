import AVFAudio
import EarmarkAudio
import EarmarkContracts
import Foundation
import Testing

private func tempDir() -> URL {
    let d = FileManager.default.temporaryDirectory.appendingPathComponent("earmark-tests-\(UUID().uuidString)")
    try! FileManager.default.createDirectory(at: d, withIntermediateDirectories: true)
    return d
}

/// Writes a 24 kHz mono Int16 WAV with a 440 Hz tone (like a Cartesia phrase file).
private func writeWav(_ url: URL, seconds: Double = 0.5, rate: Double = 24_000) throws {
    let settings: [String: Any] = [
        AVFormatIDKey: kAudioFormatLinearPCM, AVSampleRateKey: rate, AVNumberOfChannelsKey: 1,
        AVLinearPCMBitDepthKey: 16, AVLinearPCMIsFloatKey: false, AVLinearPCMIsBigEndianKey: false,
    ]
    let file = try AVAudioFile(forWriting: url, settings: settings, commonFormat: .pcmFormatFloat32, interleaved: false)
    let n = Int(seconds * rate)
    let s: [Float] = (0..<n).map { Float(0.4 * sin(2 * .pi * 440 * Double($0) / rate)) }
    try file.write(from: PCM.floatBuffer(s, format: PCM.monoFloat(rate)))
}

@Suite struct WavLoadingTests {
    @Test func loadsAndConvertsToMono48k() throws {
        let dir = tempDir()
        let url = dir.appendingPathComponent("ready.wav")
        try writeWav(url)
        let buf = try AudioFileLoader.loadMono(url, sampleRate: 48_000)
        #expect(buf.format.sampleRate == 48_000 && buf.format.channelCount == 1)
        #expect(abs(Int(buf.frameLength) - 24_000) < 64)            // 0.5 s at 48 kHz
        #expect(abs(PCM.peak(PCM.floatSamples(buf)) - 0.4) < 0.02)
    }

    @Test func phraseLibraryResolvesAndRejectsBadIDs() throws {
        let dir = tempDir()
        try writeWav(dir.appendingPathComponent("not_understood.wav"))
        let lib = PhraseLibrary(directories: [dir.appendingPathComponent("missing"), dir])
        #expect(lib.url(for: "not_understood")?.lastPathComponent == "not_understood.wav")
        #expect(lib.url(for: "ready") == nil)
        #expect(lib.url(for: "../etc/passwd") == nil)
    }
}

/// Plays speech through the real SpeechPlayer graph in offline mode and checks playback events.
@Suite(.serialized) struct SpeechPlayerTests {
    final class Events: @unchecked Sendable {
        private let lock = NSLock()
        private var items: [String] = []
        func add(_ s: String) { lock.withLock { items.append(s) } }
        var all: [String] { lock.withLock { items } }
    }

    private func makePlayer(_ dir: URL) throws -> (SpeechPlayer, Events) {
        let p = SpeechPlayer(phrases: PhraseLibrary(directories: [dir]),
                             offlineRenderFormat: AVAudioFormat(standardFormatWithSampleRate: 48_000, channels: 2)!,
                             callbackQueue: DispatchQueue(label: "speech-test-events"))
        let ev = Events()
        p.onPlayback = { id, e in ev.add("\(e.rawValue) \(id)") }
        p.onSpeakingChanged = { on in ev.add(on ? "duck" : "unduck") }
        try p.start()
        return (p, ev)
    }

    private func speak(_ id: String, seq: Int, samples: [Int16], final: Bool) -> Speak {
        let b64 = PCM.int16LEData(samples).base64EncodedString()
        let m = bus(#"{"type":"speak","utterance_id":"\#(id)","seq":\#(seq),"format":"pcm_s16le","sample_rate":24000,"chunk_b64":"\#(b64)","final":\#(final),"t":1}"#)
        guard case .speak(let s) = m else { fatalError() }
        return s
    }

    @Test func streamedChunksPlayAndFinish() async throws {
        let (p, ev) = try makePlayer(tempDir())
        let tone: [Int16] = (0..<2_400).map { Int16(8_000 * sin(Double($0) * 0.1)) }   // 100 ms at 24 kHz
        p.handle(speak("u-1", seq: 0, samples: tone, final: false))
        p.handle(speak("u-1", seq: 1, samples: tone, final: false))
        p.handle(speak("u-1", seq: 2, samples: [], final: true))
        p.drain()
        try p.renderOffline(frames: 48_000)
        p.drain()
        #expect(await waitUntil { ev.all.contains("finished u-1") })
        let all = ev.all
        #expect((all.firstIndex(of: "started u-1") ?? 99) < (all.firstIndex(of: "finished u-1") ?? -1))
        #expect(all.contains("duck"))
    }

    @Test func newUtteranceInterruptsTheCurrentOne() async throws {
        let (p, ev) = try makePlayer(tempDir())
        let tone = [Int16](repeating: 1_000, count: 24_000)
        p.handle(speak("u-1", seq: 0, samples: tone, final: false))
        p.handle(speak("u-2", seq: 0, samples: tone, final: true))
        p.handle(speak("u-1", seq: 1, samples: tone, final: true))   // late chunk of u-1 is dropped
        p.drain()
        try p.renderOffline(frames: 96_000)
        p.drain()
        #expect(await waitUntil { ev.all.contains("finished u-2") })
        #expect(ev.all.contains("interrupted u-1"))
        #expect(!ev.all.contains("finished u-1"))
    }

    @Test func cachedPhrasePlaysFromWav() async throws {
        let dir = tempDir()
        try writeWav(dir.appendingPathComponent("ready.wav"), seconds: 0.3)
        let (p, ev) = try makePlayer(dir)
        p.playCached(phraseId: "ready", utteranceId: "u-9", text: "Earmark is ready.")
        p.drain()
        try p.renderOffline(frames: 48_000)
        p.drain()
        #expect(await waitUntil { ev.all.contains("finished u-9") })
        #expect(ev.all.contains("started u-9"))
    }
}

@Suite struct RoutingPolicyTests {
    func dev(_ name: String, uid: String, _ t: AudioTransport, inCh: Int = 0, outCh: Int = 0, rate: Double = 48_000) -> AudioDeviceInfo {
        AudioDeviceInfo(id: UInt32(name.count), uid: uid, name: name, transport: t, inputChannels: inCh, outputChannels: outCh, nominalSampleRate: rate)
    }

    @Test func bluetoothDefaultInputSwitchesToBuiltInMic() {
        let builtIn = dev("MacBook Pro Microphone", uid: AudioDevices.builtInMicUID, .builtIn, inCh: 1)
        let airpodsIn = dev("AirPods Pro", uid: "AA-BB:input", .bluetooth, inCh: 1, rate: 16_000)
        let iphone = dev("iPhone Microphone", uid: "cont", .continuity, inCh: 1)
        let usb = dev("USB Mic", uid: "usb", .usb, inCh: 1)
        let all = [iphone, airpodsIn, builtIn, usb]
        #expect(RoutingPolicy.inputSwitchTarget(defaultInput: airpodsIn, devices: all) == builtIn)
        #expect(RoutingPolicy.inputSwitchTarget(defaultInput: builtIn, devices: all) == nil)
        #expect(RoutingPolicy.inputSwitchTarget(defaultInput: usb, devices: all) == nil)       // user's wired mic is kept
        #expect(RoutingPolicy.inputSwitchTarget(defaultInput: airpodsIn, devices: [airpodsIn]) == nil)
    }

    @Test func hfpDetector() {
        #expect(RoutingPolicy.hfpSuspected(dev("AirPods Pro", uid: "a", .bluetooth, outCh: 2, rate: 48_000)) == false)
        #expect(RoutingPolicy.hfpSuspected(dev("AirPods Pro", uid: "a", .bluetooth, outCh: 1, rate: 24_000)) == true)
        #expect(RoutingPolicy.hfpSuspected(dev("AirPods Pro", uid: "a", .bluetooth, outCh: 1, rate: 16_000)) == true)
        #expect(RoutingPolicy.hfpSuspected(dev("Speakers", uid: "s", .builtIn, outCh: 2, rate: 16_000)) == false)
    }

    @Test func liveDeviceQueriesWork() {
        // This Mac always has some default output; names and rates must be readable.
        let out = AudioDevices.defaultOutput()
        #expect(out != nil)
        #expect((out?.nominalSampleRate ?? 0) > 0)
        let name = out?.name ?? ""
        #expect(name.count > 0)
        let latency = AudioDevices.outputLatency(AudioDevices.defaultOutputID())
        #expect(latency > 0 && latency < 1)
    }

    @Test func debouncerCoalescesBursts() async {
        let q = DispatchQueue(label: "debounce-test")
        let fired = SpeechPlayerTests.Events()
        // minSpacing leaves ~330 ms between the "not yet" check below and the deferred fire: with 0.3 s that margin
        // was ~30 ms, which sleep overshoot ate when the whole suite ran in parallel.
        let d = DebouncedTrigger(delay: 0.05, minSpacing: 0.6, queue: q) { fired.add("fire") }
        // One block on the serial queue: the burst spans ~45 ms, but the pending fire cannot run in between, so a
        // busy machine (make test) cannot split it the way separate asyncAfter calls could.
        q.async { for _ in 0..<10 { d.trigger(); usleep(5_000) } }
        #expect(await waitUntil { fired.all.count == 1 })
        try? await Task.sleep(nanoseconds: 150_000_000)
        #expect(fired.all.count == 1)                    // a burst of 10 changes -> one restart
        q.async { d.trigger() }                          // within minSpacing: deferred, not dropped
        try? await Task.sleep(nanoseconds: 100_000_000)
        #expect(fired.all.count == 1)
        #expect(await waitUntil { fired.all.count == 2 })
    }
}
