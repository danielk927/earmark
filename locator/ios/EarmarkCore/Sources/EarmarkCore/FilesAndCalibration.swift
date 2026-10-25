import Foundation

public struct WaveFile {
    public let sampleRate: Double
    public let samples: [Double]
    public init(data: Data) throws {
        let bytes = Array(data)
        guard bytes.count >= 44, String(bytes: bytes[0..<4], encoding: .ascii) == "RIFF",
              String(bytes: bytes[8..<12], encoding: .ascii) == "WAVE" else { throw LocatorError.invalid("Expected RIFF WAV") }
        var rate: Int?, channels: Int?, bits: Int?, format: Int?, payload: Range<Int>?
        var offset = 12
        while offset + 8 <= bytes.count {
            let tag = String(bytes: bytes[offset..<(offset + 4)], encoding: .ascii)
            let length = Self.integer(bytes, offset + 4, 4)
            let start = offset + 8
            guard length <= bytes.count - start else { throw LocatorError.invalid("Truncated WAV chunk") }
            if tag == "fmt ", length >= 16 {
                format = Self.integer(bytes, start, 2); channels = Self.integer(bytes, start + 2, 2)
                rate = Self.integer(bytes, start + 4, 4); bits = Self.integer(bytes, start + 14, 2)
            }
            if tag == "data" { payload = start..<(start + length) }
            offset = start + length + length % 2
        }
        guard let rate, let payload, channels == 1, format == 1, bits == 16, (8000...192000).contains(rate), payload.count.isMultiple(of: 2) else {
            throw LocatorError.invalid("Use mono 16-bit PCM WAV at 8–192 kHz")
        }
        sampleRate = Double(rate)
        samples = stride(from: payload.lowerBound, to: payload.upperBound, by: 2).map {
            Double(Int16(bitPattern: UInt16(Self.integer(bytes, $0, 2)))) / 32768
        }
    }
    private static func integer(_ bytes: [UInt8], _ start: Int, _ count: Int) -> Int {
        (0..<count).reduce(0) { $0 | (Int(bytes[start + $1]) << (8 * $1)) }
    }
    public static func header(sampleRate: Int, sampleCount: Int) -> Data {
        var data = Data("RIFF".utf8)
        func append(_ value: Int, bytes: Int) { for index in 0..<bytes { data.append(UInt8((value >> (8 * index)) & 255)) } }
        append(36 + sampleCount * 2, bytes: 4); data.append(Data("WAVEfmt ".utf8))
        append(16, bytes: 4); append(1, bytes: 2); append(1, bytes: 2)
        append(sampleRate, bytes: 4); append(sampleRate * 2, bytes: 4)
        append(2, bytes: 2); append(16, bytes: 2); data.append(Data("data".utf8))
        append(sampleCount * 2, bytes: 4)
        return data
    }
}

public final class JSONLinesWriter {
    private let handle: FileHandle
    private let encoder = JSONEncoder()
    public init(url: URL) throws {
        try Data().write(to: url)
        handle = try FileHandle(forWritingTo: url)
        encoder.outputFormatting = [.sortedKeys]
    }
    public func append<T: Encodable>(_ record: T) throws {
        var data = try encoder.encode(record); data.append(10)
        try handle.write(contentsOf: data)
    }
    public func close() throws { try handle.close() }
}

public struct CapturedTemplate: Codable, Sendable {
    public let beacon: String
    public let fs: Double
    public let chirp: ChirpConfig
    public let samples: [Double]
    public let snr: Double
    public let copies: Int
}

public enum Calibration {
    public static func template(samples: [Double], beacon: String, config: LocatorConfig) throws -> CapturedTemplate {
        guard config.beacons.contains(where: { $0.id == beacon }) else { throw LocatorError.invalid("Unknown beacon") }
        let synthesized = Chirp.samples(config: config.chirp, fs: config.fs, falling: beacon == "B1")
        let env = DSP.envelope(signal: samples, template: synthesized, fs: config.fs, low: config.chirp.f_lo - 300, high: config.chirp.f_hi + 300)
        let cycle = config.chirp.cycle * config.fs
        // B1 establishes the slot origin even when capturing an upward-sweeping beacon.
        let marker = DSP.envelope(signal: samples, template: Chirp.samples(config: config.chirp, fs: config.fs, falling: true),
                                  fs: config.fs, low: config.chirp.f_lo - 300, high: config.chirp.f_hi + 300)
        guard let phase = Detection.firstArrival(envelope: marker, range: 1..<min(marker.count - 1, Int(cycle)),
                                                lookback: Int(config.lookback_ms * config.fs / 1000), minimumSNR: config.snr_acquire),
              let slot = config.beacons.first(where: { $0.id == beacon })?.slot else {
            throw LocatorError.invalid("Could not lock B1. Run all five beacons; keep B1 audible during capture.")
        }
        var aligned: [[Double]] = [], snrs: [Double] = []
        for index in 0..<10 {
            let predicted = phase.sample + Double(slot) * config.chirp.slot * config.fs + Double(index) * cycle
            let gate = Int(config.fs * 0.015)
            guard let peak = Detection.firstArrival(envelope: env, range: (Int(predicted) - gate)..<(Int(predicted) + gate),
                                                   lookback: Int(config.lookback_ms * config.fs / 1000), minimumSNR: 20),
                  Int(peak.sample) >= 0, Int(peak.sample) + synthesized.count + 1 < samples.count else { continue }
            aligned.append(interpolated(samples, start: peak.sample, count: synthesized.count)); snrs.append(peak.snr)
        }
        guard aligned.count >= 8 else { throw LocatorError.invalid("Template failed: \(aligned.count)/10 copies; need ≥8 with SNR ≥20. Move closer and retry.") }
        let average = (0..<synthesized.count).map { i in aligned.reduce(0) { $0 + $1[i] } / Double(aligned.count) }
        return CapturedTemplate(beacon: beacon, fs: config.fs, chirp: config.chirp, samples: average,
                                snr: snrs.reduce(0, +) / Double(snrs.count), copies: aligned.count)
    }
    private static func interpolated(_ samples: [Double], start: Double, count: Int) -> [Double] {
        (0..<count).map { offset in
            let time = start + Double(offset), i = Int(time), fraction = time - Double(i)
            return samples[i] * (1 - fraction) + samples[i + 1] * fraction
        }
    }
    public static func savePoint(_ fixes: [Fix], label: String, now: Double) throws -> SavedPoint {
        guard let first = fixes.first, let last = fixes.last, last.t - first.t >= 2, fixes.count >= 6,
              now.isFinite, now >= last.t, now - last.t <= 0.7,
              fixes.allSatisfy({ $0.quality != .lost && $0.t.isFinite }),
              !label.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty,
              zip(fixes, fixes.dropFirst()).allSatisfy({ $1.t > $0.t && $1.t - $0.t <= 0.7 }) else {
            throw LocatorError.invalid("Hold still for two continuous seconds of current valid fixes and enter a label")
        }
        let mean = fixes.reduce(Vector3.zero) { $0 + $1.mic_position } * (1 / Double(fixes.count))
        let deviation = sqrt(fixes.reduce(0) { $0 + pow(($1.mic_position - mean).norm, 2) } / Double(fixes.count))
        guard deviation < 0.02 else { throw LocatorError.invalid(String(format: "Unsteady: %.1f cm standard deviation; require <2 cm", deviation * 100)) }
        return SavedPoint(label: label, position: mean)
    }
}
public struct SavedPoint: Codable, Sendable {
    public let label: String
    public let position: Vector3
}
