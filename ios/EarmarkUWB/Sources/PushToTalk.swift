import AVFoundation
import Foundation

/// Wearer push-to-talk (UWB-PRD 13.2): while "Talk" is held, the iPhone's built-in mic is streamed as
/// `mic_audio`, exactly like the Mac app: 16 kHz mono pcm_s16le in 100 ms chunks (1600 frames).
///
/// Audio session: category `.record` (it also silences all output, so this phone never plays a sound that
/// could pull the AirPods away from the Mac) with no Bluetooth options (`.allowBluetoothHFP` absent, so a
/// Bluetooth headset mic is never used), mode `.default` (keeps Apple's gain control; `.measurement` turns it
/// off), preferred input = built-in mic.
///
/// Shared microphone: when the sound listener (`PhoneCore.PhoneClient`) is capturing, it already owns the
/// microphone and the audio session (`.playAndRecord`, `.measurement`). Then `setShared(true)` makes Talk consume
/// the listener's raw buffers (`feed`) through the same resample-to-16 kHz path, and `start`/`stop` neither open an
/// engine nor touch the session (stopping the session would kill the listener). With the listener off, Talk keeps
/// its own engine and session exactly as before.
///
/// Threading: `start`/`stop`/`setShared` from the main actor; the tap block (own engine) or the listener's tap
/// (`feed`) runs on an audio thread, converts with AVAudioConverter, chunks, and hops each chunk to the main
/// actor. State shared with the audio thread is behind `lock`.
final class PushToTalk: @unchecked Sendable {
    enum MicError: LocalizedError {
        case noInput, converter

        var errorDescription: String? {
            switch self {
            case .noInput: "No microphone input is available."
            case .converter: "Could not convert microphone audio to 16 kHz."
            }
        }
    }

    /// Same as the Mac app (`PCM.micSampleRate`, `PCM.micChunkFrames`).
    static let sampleRate = 16_000
    static let chunkFrames = 1_600

    /// 100 ms of little-endian Int16 mono at 16 kHz, on the main actor, in capture order.
    var onChunk: (@MainActor @Sendable (Data) -> Void)?
    private(set) var isRunning = false

    private let engine = AVAudioEngine()
    private let lock = NSLock()
    /// Guarded by `lock`: true while Talk is on (buffers are accepted), and whether they come from the listener.
    private var accepting = false
    private var shared = false
    private var ownEngineRunning = false
    private let target = AVAudioFormat(commonFormat: .pcmFormatInt16, sampleRate: Double(PushToTalk.sampleRate),
                                       channels: 1, interleaved: true)!
    // Guarded by `lock`.
    private var converter: AVAudioConverter?
    private var pending: [Int16] = []

    /// Asks once (shows NSMicrophoneUsageDescription); later calls return the remembered answer.
    static func requestPermission() async -> Bool {
        await AVAudioApplication.requestRecordPermission()
    }

    /// True while Talk reads the listener's buffers instead of running its own engine.
    var isShared: Bool { lock.withLock { shared } }

    /// Call (main actor) whenever the sound listener starts or stops capturing. Safe while Talk is running:
    /// switching to shared closes this class's own engine without touching the audio session, because the
    /// listener now owns it.
    func setShared(_ on: Bool) {
        let wasShared = lock.withLock { shared }
        guard on != wasShared else { return }
        if on, ownEngineRunning { stopOwnEngine() }
        lock.withLock {
            shared = on
            converter = nil
            pending.removeAll()
        }
    }

    func start() throws {
        guard !isRunning else { return }
        if isShared {
            lock.withLock { converter = nil; pending.removeAll(); accepting = true }
            isRunning = true
            Log.mic.info("talk: using the sound listener's microphone")
            return
        }
        let audio = AVAudioSession.sharedInstance()
        try audio.setCategory(.record, mode: .default, options: [])
        try audio.setActive(true)
        // Apple: set the preferred input only after category/mode are set and the session is active.
        if let builtIn = audio.availableInputs?.first(where: { $0.portType == .builtInMic }) {
            try? audio.setPreferredInput(builtIn)
        }

        let input = engine.inputNode
        let format = input.outputFormat(forBus: 0)
        guard format.sampleRate > 0, format.channelCount > 0 else { throw MicError.noInput }
        guard let conv = AVAudioConverter(from: format, to: target) else { throw MicError.converter }
        lock.withLock { converter = conv; pending.removeAll(); accepting = true }

        input.installTap(onBus: 0, bufferSize: 4_096, format: format) { [weak self] buffer, _ in
            self?.process(buffer, fromOwnEngine: true)
        }
        engine.prepare()
        do {
            try engine.start()
        } catch {
            input.removeTap(onBus: 0)
            lock.withLock { accepting = false }
            throw error
        }
        ownEngineRunning = true
        isRunning = true
        Log.mic.info("talk: capturing \(format.sampleRate) Hz x\(format.channelCount) -> 16 kHz Int16")
    }

    /// Stops capture. A partial (< 100 ms) last chunk is dropped, as on the Mac. In shared mode only stops
    /// consuming; the session and the listener's engine are left alone.
    func stop() {
        guard isRunning else { return }
        isRunning = false
        lock.withLock { accepting = false }
        if ownEngineRunning {
            stopOwnEngine()
            try? AVAudioSession.sharedInstance().setActive(false, options: .notifyOthersOnDeactivation)
        }
    }

    private func stopOwnEngine() {
        ownEngineRunning = false
        engine.inputNode.removeTap(onBus: 0)
        engine.stop()
    }

    /// Entry for the listener's microphone buffers (any thread, raw hardware format). Ignored unless Talk is on
    /// and shared. Converts synchronously, so the buffer need not outlive the call.
    func feed(_ buffer: AVAudioPCMBuffer) {
        process(buffer, fromOwnEngine: false)
    }

    // MARK: Tap thread

    private func process(_ buffer: AVAudioPCMBuffer, fromOwnEngine: Bool) {
        guard buffer.frameLength > 0 else { return }
        var chunks: [Data] = []
        lock.lock()
        defer {
            lock.unlock()
            if let cb = onChunk { for data in chunks { onMain { cb(data) } } }
        }
        guard accepting, shared != fromOwnEngine else { return }
        if converter == nil || converter!.inputFormat != buffer.format {
            converter = AVAudioConverter(from: buffer.format, to: target)   // shared source: first buffer or route change
        }
        guard let converter else { return }
        let capacity = AVAudioFrameCount(Double(buffer.frameLength) * target.sampleRate / buffer.format.sampleRate) + 512
        guard let out = AVAudioPCMBuffer(pcmFormat: target, frameCapacity: capacity) else { return }
        // Feed exactly one buffer per call, then .noDataNow, so the resampler keeps its state between taps
        // (same pattern as the Mac app's PCMResampler).
        var fed = false
        var error: NSError?
        let status = converter.convert(to: out, error: &error) { _, inputStatus in
            if fed {
                inputStatus.pointee = .noDataNow
                return nil
            }
            fed = true
            inputStatus.pointee = .haveData
            return buffer
        }
        guard status != .error, error == nil, out.frameLength > 0, let channel = out.int16ChannelData else { return }
        pending.append(contentsOf: UnsafeBufferPointer(start: channel[0], count: Int(out.frameLength)))

        while pending.count >= Self.chunkFrames {
            let chunk = pending.prefix(Self.chunkFrames).map { $0.littleEndian }
            pending.removeFirst(Self.chunkFrames)
            chunks.append(chunk.withUnsafeBufferPointer { Data(buffer: $0) })
        }
    }
}
