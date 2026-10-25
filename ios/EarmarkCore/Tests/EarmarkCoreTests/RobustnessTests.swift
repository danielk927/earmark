import Foundation
import simd
import Testing
@testable import EarmarkCore

/// Real-world inputs that used to wedge the engine, each driven through the audio path.
struct RobustnessTests {
    let config: RoomConfig
    init() throws { config = try TestScene.load() }

    /// Calibrates on the first 15.5 s of `blocks`, then runs `after` on each later block.
    func calibrated(_ blocks: [AudioBlock], startTime: Double,
                    after: (EarmarkEngine, AudioBlock, Double) -> AudioBlock? = { _, b, _ in b }) throws -> EarmarkEngine {
        let engine = try EarmarkEngine(config: config)
        engine.startCalibration()
        var done = false
        for original in blocks {
            let t = Double(original.sampleTime) / original.sampleRate - startTime
            guard let block = done ? after(engine, original, t) : original else { continue }
            engine.process(block)
            if !done, t > 15.5 {
                let report = engine.finishCalibration()
                #expect(report.ok, "\(report.problems)")
                done = true
            }
        }
        return engine
    }

    @Test func nanSamplesDoNotStopDetection() throws {
        let synth = AudioSynth(config: config, path: .still(at: config.calibrationPosition, duration: 30))
        var acceptedAtNaN = 0
        let engine = try calibrated(synth.blocks(), startTime: synth.startTime) { engine, block, t in
            guard t > 20, acceptedAtNaN == 0 else { return block }
            acceptedAtNaN = engine.diagnostics.acceptedTotal
            var samples = block.samples
            samples[100] = .nan
            samples[200] = .infinity
            return AudioBlock(samples: samples, sampleRate: block.sampleRate, sampleTime: block.sampleTime, wallClock: block.wallClock)
        }
        #expect(engine.diagnostics.acceptedTotal > acceptedAtNaN + 50)
        #expect(engine.state(at: synth.startTime + 30).status == .tracking)
    }

    @Test func farDivergenceRecovers() throws {
        let synth = AudioSynth(config: config, path: .still(at: config.calibrationPosition, duration: 35))
        var displaced = false
        let engine = try calibrated(synth.blocks(), startTime: synth.startTime) { engine, block, t in
            if t > 20, !displaced { engine.displaceTrack(by: SIMD3(4, 4, 0)); displaced = true }
            return block
        }
        let state = engine.state(at: synth.startTime + 35)
        #expect(state.status == .tracking)
        #expect(simd_distance(state.position, config.calibrationPosition) < 0.1)
        #expect(engine.diagnostics.recoveries >= 1)
    }

    @Test func audioClockGoingBackwardsInvalidates() throws {
        let synth = AudioSynth(config: config, path: .still(at: config.calibrationPosition, duration: 25))
        let blocks = synth.blocks()
        let engine = try calibrated(blocks, startTime: synth.startTime) { _, block, t in
            guard t > 20 else { return block }
            // The audio engine restarted: sample time starts over from 0 while the wall clock goes on.
            return AudioBlock(samples: block.samples, sampleRate: block.sampleRate,
                              sampleTime: block.sampleTime - blocks[0].sampleTime - 20 * 48_000, wallClock: block.wallClock)
        }
        #expect(engine.state(at: 5).status == .notCalibrated)
        #expect(engine.guidance(at: 5, headYaw: 0, destination: "keys").valid == false)
    }

    @Test func sampleRateChangeInvalidates() throws {
        let synth = AudioSynth(config: config, path: .still(at: config.calibrationPosition, duration: 20))
        let engine = try calibrated(synth.blocks(), startTime: synth.startTime)
        #expect(engine.state(at: 0).status == .tracking)
        engine.process(AudioBlock(samples: [Float](repeating: 0, count: 4096), sampleRate: 44_100, sampleTime: 0, wallClock: 1_792_882_400))
        #expect(engine.state(at: 0).status == .notCalibrated)
    }

    @Test func unusableSampleRatesAreIgnored() throws {
        let engine = try EarmarkEngine(config: config)
        for rate in [16_000.0, 24_000, .infinity, .nan, 0] {
            engine.process(AudioBlock(samples: [Float](repeating: 0.1, count: 4096), sampleRate: rate, sampleTime: 0, wallClock: 0))
        }
        #expect(engine.diagnostics.beacons.allSatisfy { $0.detectionsLast5s == 0 })
    }

    @Test func wallClockJumpBackDoesNotStallDetection() {
        let synth = AudioSynth(config: config, path: .still(at: config.calibrationPosition, duration: 12))
        let blocks = synth.blocks().enumerated().map { i, b in
            i < 60 ? b : AudioBlock(samples: b.samples, sampleRate: b.sampleRate, sampleTime: b.sampleTime, wallClock: b.wallClock - 10)
        }
        let jump = Double(blocks[60].sampleTime) / synth.sampleRate
        let after = detectAll(blocks, config: config).filter { $0.arrivalTime > jump + 0.5 && $0.arrivalTime < jump + 4.5 }
        #expect(after.count > 25)   // 4 beacons × 2 per second × 4 s = 32
    }

    @Test func tinyBlocksStillDetect() {
        let synth = AudioSynth(config: config, path: .still(at: config.calibrationPosition, duration: 6))
        let detections = detectAll(synth.blocks(size: 256), config: config)
        #expect(Double(detections.count) > 0.85 * Double(synth.arrivals.count))
        #expect(rms(timingErrors(detections, synth.arrivals)) < 20e-6)
    }
}
