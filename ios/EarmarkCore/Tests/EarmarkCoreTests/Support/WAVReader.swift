import Foundation

/// Minimal RIFF/WAVE reader for fixtures: 16-bit PCM or 32-bit float, first channel only.
struct WAVFile {
    let sampleRate: Double
    let samples: [Float]

    struct FormatError: Error, CustomStringConvertible { let description: String }

    init(url: URL) throws {
        let data = try Data(contentsOf: url)
        func u16(_ o: Int) -> UInt16 { UInt16(data[o]) | UInt16(data[o + 1]) << 8 }
        func u32(_ o: Int) -> UInt32 { UInt32(u16(o)) | UInt32(u16(o + 2)) << 16 }
        func tag(_ o: Int) -> String { String(decoding: data[o..<o + 4], as: UTF8.self) }

        guard data.count >= 12, tag(0) == "RIFF", tag(8) == "WAVE" else { throw FormatError(description: "\(url.lastPathComponent): not a WAVE file") }
        var format: UInt16?, channels = 1, rate = 0.0, bits = 0
        var offset = 12
        while offset + 8 <= data.count {
            let id = tag(offset), size = Int(u32(offset + 4)), body = offset + 8
            if id == "fmt " {
                var code = u16(body)
                channels = Int(u16(body + 2))
                rate = Double(u32(body + 4))
                bits = Int(u16(body + 14))
                if code == 0xFFFE && size >= 26 { code = u16(body + 24) }   // WAVE_FORMAT_EXTENSIBLE sub-format
                format = code
            } else if id == "data", let format {
                guard (format == 1 && bits == 16) || (format == 3 && bits == 32) else {
                    throw FormatError(description: "\(url.lastPathComponent): format \(format), \(bits)-bit is not supported")
                }
                let frameBytes = channels * bits / 8
                let frames = min(size, data.count - body) / frameBytes
                var out = [Float](repeating: 0, count: frames)
                data.withUnsafeBytes { raw in
                    for i in 0..<frames {
                        let o = body + i * frameBytes
                        switch (format, bits) {
                        case (1, 16): out[i] = Float(Int16(bitPattern: raw.loadUnaligned(fromByteOffset: o, as: UInt16.self))) / 32768
                        case (3, 32): out[i] = raw.loadUnaligned(fromByteOffset: o, as: Float.self)
                        default: break
                        }
                    }
                }
                sampleRate = rate
                samples = out
                return
            }
            offset = body + size + (size & 1)
        }
        throw FormatError(description: "\(url.lastPathComponent): no data chunk")
    }
}
