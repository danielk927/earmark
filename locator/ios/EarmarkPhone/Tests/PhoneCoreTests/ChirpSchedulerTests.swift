import AVFoundation
import Foundation
import Testing
@testable import PhoneCore

private let fs = 48000.0
private let period = 24000  // round(0.5 * 48000)

@Suite struct ChirpSchedulerTests {
    @Test func periodIsHalfASecondOfSamples() {
        #expect(ChirpScheduler.period(cycleSeconds: 0.5, sampleRate: fs) == period)
        #expect(ChirpScheduler.period(cycleSeconds: 0.5, sampleRate: 44100) == 22050)
    }

    @Test(arguments: [512, 1024, 4096, 1000, 333])
    func startsAreExactlyOnePeriodApartAcrossBufferBoundaries(bufferSize: Int) {
        let s = ChirpScheduler(period: period, firstStart: 7777, chirpLength: 1920)
        var starts: [Int] = []
        var position = 0
        let total = 3 * 48000
        while position < total {
            let n = min(bufferSize, total - position)
            starts += s.starts(inBufferAt: position, count: n)
            position += n
        }
        #expect(starts.count == 6)
        #expect(starts.first == 7777)
        for (a, b) in zip(starts, starts.dropFirst()) { #expect(b - a == period) }
    }

    @Test(arguments: [512, 1024, 4096, 1000, 333])
    func fillWritesWholeChirpsAcrossBufferBoundaries(bufferSize: Int) {
        let chirp = ChirpSpec(fLo: 12000, fHi: 16000, lengthMs: 40, amplitude: 0.8, direction: "up").samples(sampleRate: fs)
        let s = ChirpScheduler(period: period, firstStart: 3000, chirpLength: chirp.count)
        let total = 3 * 48000
        var out = [Float](repeating: -9, count: total)
        var position = 0
        out.withUnsafeMutableBufferPointer { o in
            chirp.withUnsafeBufferPointer { c in
                while position < total {
                    let n = min(bufferSize, total - position)
                    s.fill(o.baseAddress! + position, count: n, position: position, chirp: c.baseAddress!)
                    position += n
                }
            }
        }
        var expected = [Float](repeating: 0, count: total)
        var start = 3000
        while start + chirp.count <= total {
            for i in 0..<chirp.count { expected[start + i] = chirp[i] }
            start += period
        }
        #expect(out == expected)
        // and the chirps really are 24000 samples apart: cross-check by locating each one
        let found = (0..<(total - chirp.count)).filter { i in out[i + 1] == chirp[1] && out[i + 100] == chirp[100] && out[i + 1000] == chirp[1000] }
        #expect(found == [3000, 27000, 51000, 75000, 99000, 123000])
    }

    @Test func chirpsStartedCountsStartsBeforePosition() {
        let s = ChirpScheduler(period: period, firstStart: 100, chirpLength: 1920)
        #expect(s.chirpsStarted(before: 0) == 0)
        #expect(s.chirpsStarted(before: 100) == 0)
        #expect(s.chirpsStarted(before: 101) == 1)
        #expect(s.chirpsStarted(before: 24100) == 1)
        #expect(s.chirpsStarted(before: 24101) == 2)
    }

    @Test(arguments: [1, 2, 3, 4])
    func firstChirpLandsAtTheBeaconsPhase(beacon: Int) {
        let phase = Double(beacon - 1) * 0.125
        for now in [1_700_000_000.0, 1_700_000_000.3, 1_700_000_000.49, 1_700_000_000.126, 1_761_300_000.999] {
            let t = ChirpScheduler.firstChirpTime(after: now, beaconNumber: beacon, cycleSeconds: 0.5, slotSeconds: 0.125, lead: 0.25)
            let inCycle = t - (t / 0.5).rounded(.down) * 0.5
            #expect(abs(inCycle - phase) < 1e-6 || abs(inCycle - phase - 0.5) < 1e-6, "beacon \(beacon) now \(now) -> \(t) phase \(inCycle)")
            #expect(t >= now + 0.25 - 1e-9)
            #expect(t < now + 0.25 + 0.5 + 1e-9)
        }
    }
}

@Suite struct SelfTimedChirpTests {
    @Test func chirpIs1920SamplesAt48kFor40ms() {
        #expect(ChirpSpec(fLo: 12000, fHi: 16000, lengthMs: 40, amplitude: 0.8, direction: "up").samples(sampleRate: fs).count == 1920)
        #expect(ChirpSpec().lengthMs == 40)  // Swift default now matches chirp.py
        #expect(SelfTimedBeacon(beaconNumber: 1, band: (12000, 16000), amplitude: 0.8).spec.samples(sampleRate: fs).count == 1920)
    }

    @Test func oddBeaconsSweepUpEvenBeaconsSweepDown() {
        #expect(SelfTimedBeacon.direction(forBeacon: 1) == "up")
        #expect(SelfTimedBeacon.direction(forBeacon: 2) == "down")
        #expect(SelfTimedBeacon.direction(forBeacon: 3) == "up")
        #expect(SelfTimedBeacon.direction(forBeacon: 4) == "down")
        // The sweep direction shows in the samples: an up chirp has a lower instantaneous frequency at the start than at the end.
        func zeroCrossings(_ x: ArraySlice<Float>) -> Int { zip(x, x.dropFirst()).filter { ($0 < 0) != ($1 < 0) }.count }
        let up = SelfTimedBeacon(beaconNumber: 1, band: (12000, 16000), amplitude: 0.8).spec.samples(sampleRate: fs)
        let down = SelfTimedBeacon(beaconNumber: 2, band: (12000, 16000), amplitude: 0.8).spec.samples(sampleRate: fs)
        #expect(zeroCrossings(up[400..<800]) < zeroCrossings(up[1100..<1500]))
        #expect(zeroCrossings(down[400..<800]) > zeroCrossings(down[1100..<1500]))
    }

    @Test func phaseFollowsBeaconNumber() {
        for n in 1...4 {
            #expect(SelfTimedBeacon(beaconNumber: n, band: (12000, 16000), amplitude: 0.8).phaseSeconds == Double(n - 1) * 0.125)
        }
    }

    /// Renders the real audio graph (source node -> mixer -> output) offline for 3 s with odd buffer sizes and checks
    /// the chirps come out exactly 24000 samples apart.
    @Test func offlineRenderOfTheRealGraphIsExactlyPeriodic() throws {
        let beacon = SelfTimedBeacon(beaconNumber: 1, band: (12000, 16000), amplitude: 0.8)
        let chirp = beacon.spec.samples(sampleRate: fs)
        let firstStart = 5000
        let format = AVAudioFormat(commonFormat: .pcmFormatFloat32, sampleRate: fs, channels: 1, interleaved: false)!
        let engine = AVAudioEngine()
        let node = beacon.makeOfflineSourceNode(firstStart: firstStart)
        engine.attach(node)
        engine.connect(node, to: engine.mainMixerNode, format: format)
        engine.connect(engine.mainMixerNode, to: engine.outputNode, format: format)
        try engine.enableManualRenderingMode(.offline, format: format, maximumFrameCount: 4096)
        try engine.start()
        let total = 3 * 48000
        var out: [Float] = []
        out.reserveCapacity(total)
        let sizes = [1024, 4096, 512, 333]
        var i = 0
        let buffer = AVAudioPCMBuffer(pcmFormat: format, frameCapacity: 4096)!
        while out.count < total {
            let n = AVAudioFrameCount(min(sizes[i % sizes.count], total - out.count))
            i += 1
            let status = try engine.renderOffline(n, to: buffer)
            #expect(status == .success)
            out += Array(UnsafeBufferPointer(start: buffer.floatChannelData![0], count: Int(buffer.frameLength)))
        }
        engine.stop()
        // Locate each chirp by matching three samples exactly (the mixer passes float32 through unchanged).
        let starts = (0..<(total - chirp.count)).filter { out[$0 + 1] == chirp[1] && out[$0 + 100] == chirp[100] && out[$0 + 1000] == chirp[1000] }
        #expect(starts == [5000, 29000, 53000, 77000, 101000, 125000])
        // Nothing else but silence between chirps.
        let expected: [Float] = {
            var e = [Float](repeating: 0, count: total)
            var s = firstStart
            while s + chirp.count <= total { for k in 0..<chirp.count { e[s + k] = chirp[k] }; s += 24000 }
            return e
        }()
        let maxErr = zip(out, expected).map { abs($0 - $1) }.max() ?? 1
        #expect(maxErr < 1e-5)
    }
}
