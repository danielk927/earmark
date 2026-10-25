import AVFoundation
import Foundation

public enum PhoneAudioError: Error, LocalizedError {
    case noInput
    public var errorDescription: String? { "There is no microphone input (check the microphone permission)." }
}

/// Why the system took the microphone engine away. Delivered by `PhoneAudio.onDisturbed` from an arbitrary queue.
enum AudioDisturbance: Sendable {
    /// An interruption (call, Siri, alarm) began. The engine is stopped by the system.
    case began
    /// The interruption ended; the audio can be started again.
    case ended
    /// The engine stopped itself (route, sample rate or channel change) or the media services were reset.
    case reset
}

/// Records the microphone as a continuous stream (numbered by sample) and plays chirps on command.
/// No processing is applied: the speaker-to-microphone path is part of what we measure.
final class PhoneAudio: @unchecked Sendable {
    // A fresh engine and player per `start` (a stopped or reset engine is not worth reusing).
    private var engine = AVAudioEngine()
    private var player = AVAudioPlayerNode()
    private var tapInstalled = false
    private var chirpBuffer: AVAudioPCMBuffer?
    private var converter: AVAudioConverter?
    private let io = DispatchQueue(label: "earmark.phone.audio")
    private var pending: [Int16] = []
    private var counter = 0  // sample number of pending[0]
    private var lastEnd: Int64?
    private var onChunk: ((Int, Data) -> Void)?
    private var onLevel: ((Float) -> Void)?
    /// Optional second consumer of the microphone: gets every raw input buffer (hardware format) on the audio
    /// thread, before the chirp-timeline processing. The buffer is only valid during the call, so convert or
    /// copy synchronously. Set before `start`. Used by the UWB app to share this one capture path with push-to-talk.
    var micTap: (@Sendable (AVAudioPCMBuffer) -> Void)?
    /// Told when the system interrupts, reconfigures or resets the audio after `start` (a call, Siri, a route or
    /// sample rate change, a media services reset). Any queue, never the audio thread. Set once, before `start`.
    var onDisturbed: (@Sendable (AudioDisturbance) -> Void)?
    private var observers: [NSObjectProtocol] = []
    private let startLock = NSLock()
    private var starting = false  // guarded by startLock: true inside `start`, so our own setup is not read as a disturbance
    private let format = AVAudioFormat(commonFormat: .pcmFormatFloat32, sampleRate: phoneSampleRate, channels: 1, interleaved: false)!

    func start(chirp: ChirpSpec, onChunk: @escaping (Int, Data) -> Void, onLevel: @escaping (Float) -> Void) throws {
        stop()
        setStarting(true)
        defer { setStarting(false) }
        engine = AVAudioEngine()
        player = AVAudioPlayerNode()
        engine.attach(player)
        watch()  // before anything that can throw, so an interruption that ends later still reaches the client
        self.onChunk = onChunk
        self.onLevel = onLevel
        #if os(iOS)
        let session = AVAudioSession.sharedInstance()
        try session.setCategory(.playAndRecord, mode: .measurement, options: [.defaultToSpeaker])
        try session.setPreferredSampleRate(phoneSampleRate)
        try session.setPreferredIOBufferDuration(0.005)
        try session.setActive(true)
        #endif
        chirpBuffer = makeBuffer(chirp.samples(sampleRate: phoneSampleRate))
        engine.connect(player, to: engine.mainMixerNode, format: format)
        let input = engine.inputNode
        let inFormat = input.outputFormat(forBus: 0)
        guard inFormat.sampleRate > 0, inFormat.channelCount > 0 else { throw PhoneAudioError.noInput }
        converter = (inFormat.sampleRate == phoneSampleRate && inFormat.channelCount == 1) ? nil : AVAudioConverter(from: inFormat, to: format)
        lastEnd = nil
        input.installTap(onBus: 0, bufferSize: 2048, format: inFormat) { [weak self] buffer, when in
            self?.process(buffer, when)
        }
        tapInstalled = true
        engine.prepare()
        try engine.start()
        player.play()
    }

    func stop() {
        for o in observers { NotificationCenter.default.removeObserver(o) }
        observers = []
        // The tap outlives an engine that stopped by itself (config change, interruption), so remove it regardless.
        if tapInstalled {
            engine.inputNode.removeTap(onBus: 0)
            tapInstalled = false
        }
        if engine.isRunning {
            player.stop()
            engine.stop()
        }
    }

    private func setStarting(_ on: Bool) {
        startLock.lock(); starting = on; startLock.unlock()
    }

    private var isStarting: Bool {
        startLock.lock(); defer { startLock.unlock() }
        return starting
    }

    /// Same observers as `SelfTimedBeacon.watchEngine`, but they report to `onDisturbed` instead of the UI.
    private func watch() {
        let nc = NotificationCenter.default
        observers.append(nc.addObserver(forName: .AVAudioEngineConfigurationChange, object: engine, queue: nil) { [weak self] note in
            // The engine stops itself on a real change; one still running (or still being set up by us) is not ours to react to.
            guard let self, !self.isStarting, (note.object as? AVAudioEngine)?.isRunning == false else { return }
            self.onDisturbed?(.reset)
        })
        #if os(iOS)
        observers.append(nc.addObserver(forName: AVAudioSession.interruptionNotification, object: nil, queue: nil) { [weak self] note in
            guard let raw = note.userInfo?[AVAudioSessionInterruptionTypeKey] as? UInt,
                  let type = AVAudioSession.InterruptionType(rawValue: raw) else { return }
            self?.onDisturbed?(type == .began ? .began : .ended)
        })
        observers.append(nc.addObserver(forName: AVAudioSession.mediaServicesWereResetNotification, object: nil, queue: nil) { [weak self] _ in
            self?.onDisturbed?(.reset)
        })
        #endif
    }

    func playChirp() {
        guard let b = chirpBuffer, engine.isRunning else { return }
        if !player.isPlaying { player.play() }
        player.scheduleBuffer(b, at: nil, options: .interrupts, completionHandler: nil)
    }

    func playTestSweep() {
        guard engine.isRunning, let b = makeBuffer(ChirpSpec.testSweep(sampleRate: phoneSampleRate)) else { return }
        if !player.isPlaying { player.play() }
        player.scheduleBuffer(b, at: nil, options: .interrupts, completionHandler: nil)
    }

    private func makeBuffer(_ samples: [Float]) -> AVAudioPCMBuffer? {
        guard let b = AVAudioPCMBuffer(pcmFormat: format, frameCapacity: AVAudioFrameCount(samples.count)) else { return nil }
        b.frameLength = AVAudioFrameCount(samples.count)
        samples.withUnsafeBufferPointer { b.floatChannelData![0].update(from: $0.baseAddress!, count: samples.count) }
        return b
    }

    // MARK: Recording

    private func process(_ buffer: AVAudioPCMBuffer, _ when: AVAudioTime) {
        micTap?(buffer)
        var floats: [Float]
        var gap = 0
        if let c = converter {
            let ratio = phoneSampleRate / buffer.format.sampleRate
            guard let out = AVAudioPCMBuffer(pcmFormat: format, frameCapacity: AVAudioFrameCount(Double(buffer.frameLength) * ratio) + 16) else { return }
            var fed = false
            var err: NSError?
            c.convert(to: out, error: &err) { _, status in
                if fed { status.pointee = .noDataNow; return nil }
                fed = true
                status.pointee = .haveData
                return buffer
            }
            guard err == nil, let data = out.floatChannelData else { return }
            floats = Array(UnsafeBufferPointer(start: data[0], count: Int(out.frameLength)))
        } else {
            guard let data = buffer.floatChannelData else { return }
            floats = Array(UnsafeBufferPointer(start: data[0], count: Int(buffer.frameLength)))
            if when.isSampleTimeValid {
                if let last = lastEnd, when.sampleTime - last > 2 { gap = Int(when.sampleTime - last) }
                lastEnd = when.sampleTime + Int64(buffer.frameLength)
            }
        }
        io.async { [self] in
            if gap > 0 && gap < Int(phoneSampleRate) * 2 { pending.append(contentsOf: [Int16](repeating: 0, count: gap)) }  // keep the timeline honest
            var sum: Float = 0
            for f in floats {
                pending.append(Int16(max(-1, min(1, f)) * 32767))
                sum += f * f
            }
            while pending.count >= chunkSamples {
                let chunk = Array(pending.prefix(chunkSamples))
                pending.removeFirst(chunkSamples)
                let data = chunk.withUnsafeBufferPointer { Data(buffer: $0) }  // little-endian on every Apple device
                onChunk?(counter, data)
                counter += chunkSamples
            }
            onLevel?(floats.isEmpty ? 0 : (sum / Float(floats.count)).squareRoot())
        }
    }
}
