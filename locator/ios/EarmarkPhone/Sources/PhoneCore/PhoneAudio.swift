import AVFoundation
import Foundation

public enum PhoneAudioError: Error, LocalizedError {
    case noInput
    public var errorDescription: String? { "There is no microphone input (check the microphone permission)." }
}

/// Records the microphone as a continuous stream (numbered by sample) and plays chirps on command.
/// No processing is applied: the speaker-to-microphone path is part of what we measure.
final class PhoneAudio: @unchecked Sendable {
    private let engine = AVAudioEngine()
    private let player = AVAudioPlayerNode()
    private var attached = false
    private var chirpBuffer: AVAudioPCMBuffer?
    private var converter: AVAudioConverter?
    private let io = DispatchQueue(label: "earmark.phone.audio")
    private var pending: [Int16] = []
    private var counter = 0  // sample number of pending[0]
    private var lastEnd: Int64?
    private var onChunk: ((Int, Data) -> Void)?
    private var onLevel: ((Float) -> Void)?
    private let format = AVAudioFormat(commonFormat: .pcmFormatFloat32, sampleRate: phoneSampleRate, channels: 1, interleaved: false)!

    func start(chirp: ChirpSpec, onChunk: @escaping (Int, Data) -> Void, onLevel: @escaping (Float) -> Void) throws {
        stop()
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
        if !attached {
            engine.attach(player)
            attached = true
        }
        engine.connect(player, to: engine.mainMixerNode, format: format)
        let input = engine.inputNode
        let inFormat = input.outputFormat(forBus: 0)
        guard inFormat.sampleRate > 0, inFormat.channelCount > 0 else { throw PhoneAudioError.noInput }
        converter = (inFormat.sampleRate == phoneSampleRate && inFormat.channelCount == 1) ? nil : AVAudioConverter(from: inFormat, to: format)
        lastEnd = nil
        input.installTap(onBus: 0, bufferSize: 2048, format: inFormat) { [weak self] buffer, when in
            self?.process(buffer, when)
        }
        engine.prepare()
        try engine.start()
        player.play()
    }

    func stop() {
        if engine.isRunning {
            engine.inputNode.removeTap(onBus: 0)
            player.stop()
            engine.stop()
        }
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
