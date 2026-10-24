import AVFAudio
import EarmarkAudio
import EarmarkContracts
import Foundation
import Testing

@Suite struct SpeakDecodingTests {
    @Test func s16leExampleChunk() throws {
        // contracts/examples/bus/speak/01.json: "AAABAAIAAwA=" = Int16 LE [0, 1, 2, 3]
        var d = SpeakChunkDecoder(format: .pcmS16le)
        let decoded = d.decode(base64: "AAABAAIAAwA=")
        let s = try #require(decoded)
        #expect(s == [0, 1, 2, 3].map { Float($0) / 32_768 })
    }

    @Test func s16leFullScaleAndSign() {
        var d = SpeakChunkDecoder(format: .pcmS16le)
        let samples: [Int16] = [Int16.min, -16_384, 0, 16_384, Int16.max]
        let out = d.decode(PCM.int16LEData(samples))
        #expect(out[0] == -1)
        #expect(out[1] == -0.5)
        #expect(out[3] == 0.5)
        #expect(abs(out[4] - 1) < 1e-4)
    }

    @Test func f32leRoundTrip() throws {
        let src: [Float] = [0, 0.25, -0.5, 0.999, -1]
        var data = Data()
        for v in src { withUnsafeBytes(of: v.bitPattern.littleEndian) { data.append(contentsOf: $0) } }
        var d = SpeakChunkDecoder(format: .pcmF32le)
        let decoded = d.decode(base64: data.base64EncodedString())
        let out = try #require(decoded)
        #expect(out == src)
    }

    @Test func oddChunkBoundariesCarryOver() {
        let samples: [Int16] = (0..<101).map { Int16($0 * 300 - 15_000) }
        let data = PCM.int16LEData(samples)
        var d = SpeakChunkDecoder(format: .pcmS16le)
        var out: [Float] = []
        var i = 0
        for size in [1, 3, 7, 2, 50, 999] where i < data.count {
            let end = min(i + size, data.count)
            out += d.decode(data.subdata(in: i..<end))
            i = end
        }
        #expect(out == samples.map { Float($0) / 32_768 })
    }

    @Test func emptyFinalChunkAndBadBase64() {
        var d = SpeakChunkDecoder(format: .pcmF32le)
        #expect(d.decode(base64: "") == [])
        #expect(d.decode(base64: "not base64!!") == nil)
    }
}

@Suite struct ConversionTests {
    /// 48 kHz Float32 mono -> 16 kHz Int16 mono, as the mic path does, fed in 100 ms buffers.
    @Test func float48kToInt16At16k() throws {
        let src = PCM.monoFloat(48_000)
        let rs = try #require(PCMResampler(from: src, to: PCM.micFormat))
        let hz = 440.0
        var out: [Int16] = []
        for block in 0..<10 {
            let samples: [Float] = (0..<4_800).map { i in
                Float(0.5 * sin(2 * .pi * hz * Double(block * 4_800 + i) / 48_000))
            }
            if let b = rs.convert(PCM.floatBuffer(samples, format: src)) { out += PCM.int16Samples(b) }
        }
        if let tail = rs.flush() { out += PCM.int16Samples(tail) }
        #expect(abs(out.count - 16_000) <= 16)
        let peak = out.map { abs(Int($0)) }.max() ?? 0
        #expect(abs(peak - 16_384) < 400)                       // 0.5 full scale
        // Frequency preserved: ~880 zero crossings per second for 440 Hz.
        let body = Array(out[400..<15_600])
        let crossings = zip(body, body.dropFirst()).filter { ($0 < 0) != ($1 < 0) }.count
        let perSecond = Double(crossings) / (Double(body.count) / 16_000)
        #expect(abs(perSecond - 880) < 10)
    }

    @Test func chunkerMakes100msChunks() {
        var c = SampleChunker<Int16>(size: PCM.micChunkFrames)
        var chunks: [[Int16]] = []
        for _ in 0..<7 { chunks += c.push([Int16](repeating: 1, count: 1_000)) }
        #expect(chunks.count == 4)
        #expect(chunks.allSatisfy { $0.count == 1_600 })
    }

    @Test func rmsLevels() {
        #expect(PCM.rmsDBFS([Int16](repeating: 0, count: 100)) == -120)
        let full = PCM.rmsDBFS([Int16](repeating: 32_767, count: 100))
        #expect(abs(full) < 0.01)
        let tenth = PCM.rmsDBFS([Int16](repeating: 3_277, count: 100))
        #expect(abs(tenth + 20) < 0.05)
    }

    @Test func cuesAreMonoShortAndDistinct() {
        let ping = CueSynth.samples(.ping)
        #expect(Double(ping.count) / CueSynth.sampleRate <= 0.08)       // short for Bluetooth
        #expect(abs(PCM.peak(ping) - 0.5) < 1e-4)
        #expect(ping[0] == 0)                                           // soft attack, no click
        let broadband = CueSynth.samples(.ping, timbre: .broadband)
        #expect(broadband != ping)
        let behind = CueSynth.samples(.behind)
        #expect(behind.count > ping.count)
        // "Behind" is lower: fewer zero crossings per second than the ping.
        func zc(_ x: [Float]) -> Double { Double(zip(x, x.dropFirst()).filter { ($0 < 0) != ($1 < 0) }.count) / Double(x.count) }
        #expect(zc(behind) < zc(ping) / 2)
        #expect(CueSynth.samples(.locked).count > ping.count)
    }
}
