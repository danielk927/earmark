import AVFAudio
import EarmarkContracts
import Foundation

/// PCM helpers shared by cues, speech playback, and mic capture.
public enum PCM {
    /// Mono Float32 (deinterleaved standard format), used for every cue and speech buffer.
    public static func monoFloat(_ sampleRate: Double) -> AVAudioFormat {
        AVAudioFormat(standardFormatWithSampleRate: sampleRate, channels: 1)!
    }

    /// 16 kHz mono interleaved Int16: what Cartesia Ink expects (docs/sponsors/vendor-notes/cartesia.md section 3.4).
    public static let micFormat = AVAudioFormat(commonFormat: .pcmFormatInt16, sampleRate: 16_000, channels: 1, interleaved: true)!
    public static let micSampleRate = 16_000
    /// 100 ms of 16 kHz audio.
    public static let micChunkFrames = 1_600

    public static func floatBuffer(_ samples: [Float], format: AVAudioFormat) -> AVAudioPCMBuffer {
        let buf = AVAudioPCMBuffer(pcmFormat: format, frameCapacity: AVAudioFrameCount(max(samples.count, 1)))!
        buf.frameLength = AVAudioFrameCount(samples.count)
        if let ch = buf.floatChannelData {
            for c in 0..<Int(format.channelCount) {
                samples.withUnsafeBufferPointer { src in
                    if let base = src.baseAddress { ch[c].update(from: base, count: samples.count) }
                }
            }
        }
        return buf
    }

    public static func floatSamples(_ buffer: AVAudioPCMBuffer, channel: Int = 0) -> [Float] {
        guard let ch = buffer.floatChannelData, channel < Int(buffer.format.channelCount) else { return [] }
        return Array(UnsafeBufferPointer(start: ch[channel], count: Int(buffer.frameLength)))
    }

    /// Samples of an interleaved mono Int16 buffer.
    public static func int16Samples(_ buffer: AVAudioPCMBuffer) -> [Int16] {
        guard let ch = buffer.int16ChannelData else { return [] }
        return Array(UnsafeBufferPointer(start: ch[0], count: Int(buffer.frameLength)))
    }

    public static func int16Buffer(_ samples: [Int16], sampleRate: Double = 16_000) -> AVAudioPCMBuffer {
        let fmt = AVAudioFormat(commonFormat: .pcmFormatInt16, sampleRate: sampleRate, channels: 1, interleaved: true)!
        let buf = AVAudioPCMBuffer(pcmFormat: fmt, frameCapacity: AVAudioFrameCount(max(samples.count, 1)))!
        buf.frameLength = AVAudioFrameCount(samples.count)
        samples.withUnsafeBufferPointer { src in
            if let base = src.baseAddress { buf.int16ChannelData![0].update(from: base, count: samples.count) }
        }
        return buf
    }

    public static func int16LEData(_ samples: [Int16]) -> Data {
        var d = Data(capacity: samples.count * 2)
        for s in samples {
            let v = UInt16(bitPattern: s.littleEndian)
            d.append(UInt8(v & 0xFF)); d.append(UInt8(v >> 8))
        }
        return d
    }

    /// RMS level in dBFS (0 = full scale); -120 for digital silence.
    public static func rmsDBFS(_ samples: [Int16]) -> Double {
        guard !samples.isEmpty else { return -120 }
        var acc = 0.0
        for s in samples { let x = Double(s) / 32_768; acc += x * x }
        let rms = (acc / Double(samples.count)).squareRoot()
        return rms > 0 ? max(-120, 20 * log10(rms)) : -120
    }

    public static func peak(_ samples: [Float]) -> Float { samples.reduce(0) { max($0, abs($1)) } }
}

/// Decodes `speak.chunk_b64` payloads to Float32 samples.
/// Carries a partial sample across chunk boundaries so odd-sized chunks never misalign the stream.
public struct SpeakChunkDecoder: Sendable {
    public let format: Speak.Format
    private var carry = Data()

    public init(format: Speak.Format) { self.format = format }

    public var bytesPerSample: Int { format == .pcmS16le ? 2 : 4 }

    public mutating func decode(base64: String) -> [Float]? {
        if base64.isEmpty { return [] }
        guard let data = Data(base64Encoded: base64) else { return nil }
        return decode(data)
    }

    public mutating func decode(_ data: Data) -> [Float] {
        var bytes = carry
        bytes.append(data)
        let whole = bytes.count / bytesPerSample
        let usable = whole * bytesPerSample
        carry = usable < bytes.count ? bytes.subdata(in: usable..<bytes.count) : Data()
        guard whole > 0 else { return [] }
        var out = [Float](repeating: 0, count: whole)
        bytes.withUnsafeBytes { raw in
            switch format {
            case .pcmS16le:
                for i in 0..<whole {
                    let v = Int16(littleEndian: raw.loadUnaligned(fromByteOffset: i * 2, as: Int16.self))
                    out[i] = Float(v) / 32_768
                }
            case .pcmF32le:
                for i in 0..<whole {
                    let bits = UInt32(littleEndian: raw.loadUnaligned(fromByteOffset: i * 4, as: UInt32.self))
                    out[i] = Float(bitPattern: bits)
                }
            }
        }
        return out
    }
}

/// Stateful sample-rate / format converter around `AVAudioConverter`.
/// Returns `.noDataNow` after each input so the resampler keeps its filter state across calls
/// (docs/sponsors/vendor-notes/apple-spatial-audio.md section 6); `flush()` drains the tail at end of stream.
public final class PCMResampler {
    public let input: AVAudioFormat
    public let output: AVAudioFormat
    private let converter: AVAudioConverter

    public init?(from input: AVAudioFormat, to output: AVAudioFormat) {
        guard let c = AVAudioConverter(from: input, to: output) else { return nil }
        self.input = input
        self.output = output
        self.converter = c
    }

    private func capacity(for frames: AVAudioFrameCount) -> AVAudioFrameCount {
        AVAudioFrameCount(Double(frames) * output.sampleRate / input.sampleRate) + 512
    }

    /// Converts one buffer. Output can be a little shorter than the ideal length (resampler latency);
    /// the missing frames come out on the next call or on flush().
    public func convert(_ buffer: AVAudioPCMBuffer) -> AVAudioPCMBuffer? {
        guard buffer.frameLength > 0,
              let out = AVAudioPCMBuffer(pcmFormat: output, frameCapacity: capacity(for: buffer.frameLength)) else { return nil }
        var fed = false
        var error: NSError?
        let status = converter.convert(to: out, error: &error) { _, outStatus in
            if fed { outStatus.pointee = .noDataNow; return nil }
            fed = true
            outStatus.pointee = .haveData
            return buffer
        }
        if status == .error || error != nil { return nil }
        return out
    }

    /// Drains frames held by the resampler and resets it for the next stream.
    public func flush() -> AVAudioPCMBuffer? {
        guard let out = AVAudioPCMBuffer(pcmFormat: output, frameCapacity: 4_096) else { return nil }
        var error: NSError?
        _ = converter.convert(to: out, error: &error) { _, outStatus in
            outStatus.pointee = .endOfStream
            return nil
        }
        converter.reset()
        return out.frameLength > 0 ? out : nil
    }
}

/// Splits a stream into fixed-size chunks.
public struct SampleChunker<T: Sendable>: Sendable {
    public let size: Int
    private var pending: [T] = []

    public init(size: Int) { self.size = size }

    public mutating func push(_ samples: [T]) -> [[T]] {
        pending.append(contentsOf: samples)
        var out: [[T]] = []
        while pending.count >= size {
            out.append(Array(pending.prefix(size)))
            pending.removeFirst(size)
        }
        return out
    }

    public mutating func reset() { pending.removeAll() }
}
