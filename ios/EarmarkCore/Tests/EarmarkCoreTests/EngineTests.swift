import Foundation
import simd
import Testing
@testable import EarmarkCore

/// State shared between the test's threads.
final class SharedFlags: @unchecked Sendable {
    struct Values { var finished = false; var calls = 0; var calibrated = false }
    private let lock = NSLock()
    private var values = Values()
    func read<T>(_ body: (Values) -> T) -> T { lock.lock(); defer { lock.unlock() }; return body(values) }
    func write(_ body: (inout Values) -> Void) { lock.lock(); defer { lock.unlock() }; body(&values) }
}

struct EngineTests {
    /// B7: guidance at 1 kHz from another thread while 60 s of audio is processed, with calibration
    /// started and finished from that thread too. Run `swift test --sanitize=thread` to check for races.
    @Test func concurrentCallsAreSafe() throws {
        let config = try TestScene.load()
        let synth = AudioSynth(config: config, path: .still(at: config.calibrationPosition, duration: 60))
        let engine = try EarmarkEngine(config: config)
        let blocks = synth.blocks()
        let done = DispatchSemaphore(value: 0)
        let shared = SharedFlags()

        DispatchQueue.global().async {
            var started = false, calls = 0, report: CalibrationReport?
            while !shared.read({ $0.finished }) {
                let t = synth.startTime + Double(calls) / 1000
                _ = engine.guidance(at: t, headYaw: Double(calls % 360) * .pi / 180, destination: "sugar jar")
                _ = engine.state(at: t)
                if calls % 50 == 0 { _ = engine.diagnostics; _ = engine.calibrationProgress }
                if !started && calls > 1_000 { engine.startCalibration(); started = true }
                if started && report == nil, engine.calibrationProgress.elapsed > 15.5 { report = engine.finishCalibration() }
                calls += 1
                Thread.sleep(forTimeInterval: 0.001)
            }
            shared.write { $0.calls = calls; $0.calibrated = report?.ok == true }
            done.signal()
        }
        for block in blocks {
            engine.process(block)
            Thread.sleep(forTimeInterval: 0.002)   // give the other thread time to interleave
        }
        shared.write { $0.finished = true }
        done.wait()
        let (calls, calibrated) = shared.read { ($0.calls, $0.calibrated) }
        print("concurrency: \(calls) guidance calls during \(blocks.count) blocks; calibration ok: \(calibrated)")
        #expect(calls > 1_000)
        #expect(calibrated)
        #expect(engine.state(at: synth.startTime + 60).status == .tracking)
    }

    @Test func outputCallsAreFast() throws {
        let config = try TestScene.load()
        let engine = try EarmarkEngine(config: config)
        let sim = DetectionSim(config: config, path: .hold(at: config.calibrationPosition, duration: 20, seed: 2))
        engine.startCalibration()
        engine.ingest([], streamTime: sim.options.startTime)
        engine.ingest(sim.detections.filter { $0.arrivalTime < sim.options.startTime + 15.2 }, streamTime: sim.options.startTime + 15.2)
        #expect(engine.finishCalibration().ok)
        let start = DispatchTime.now().uptimeNanoseconds
        for i in 0..<1_000 {
            _ = engine.guidance(at: sim.options.startTime + 15.2 + Double(i) / 1000, headYaw: 0, destination: "keys")
            _ = engine.state(at: sim.options.startTime + 15.2)
            _ = engine.diagnostics
        }
        let each = Double(DispatchTime.now().uptimeNanoseconds - start) / 1e6 / 1_000
        print(String(format: "guidance + state + diagnostics: %.4f ms per call set", each))
        #expect(each < 1)
    }

    @Test func invalidateAndRecalibrate() throws {
        let config = try TestScene.load()
        let synth = AudioSynth(config: config, path: .still(at: config.calibrationPosition, duration: 36))
        let engine = try EarmarkEngine(config: config)
        var reports: [CalibrationReport] = []
        engine.startCalibration()
        for block in synth.blocks() {
            engine.process(block)
            let t = Double(block.sampleTime) / block.sampleRate - synth.startTime
            if reports.isEmpty, t > 15.5 { reports.append(engine.finishCalibration()); engine.invalidateCalibration() }
            if reports.count == 1, t > 18, engine.state(at: 0).status == .notCalibrated { engine.startCalibration() }
            if reports.count == 1, t > 34 { reports.append(engine.finishCalibration()) }
        }
        #expect(reports.count == 2 && reports.allSatisfy(\.ok))
        let state = engine.state(at: synth.startTime + 36)
        #expect(state.status == .tracking)
        #expect(simd_distance(state.position, config.calibrationPosition) < 0.05)
    }

    /// The whole signal path on the spec walk: synthetic audio with clock offsets and drift, room
    /// echoes, body blocking and Doppler, through detection, calibration and tracking.
    func endToEnd(minEchoDelay: Double, seeds: ClosedRange<UInt64>) throws -> (errors: [Double], calibrated: Int, recoveries: Int) {
        let config = try TestScene.load()
        var errors: [Double] = [], recoveries = 0, calibrated = 0
        for seed in seeds {
            let path = ReceiverPath.specWalk(from: config.calibrationPosition, seed: seed, height: config.receiverHeight)
            var options = AudioSynth.Options()
            options.snrDB = 20
            options.echoes = .room(minDelay: minEchoDelay)
            options.bodyBlocking = true
            options.seed = seed
            let synth = AudioSynth(config: config, path: path, options: options)
            let engine = try EarmarkEngine(config: config)
            engine.startCalibration()
            var ok = false
            for block in synth.blocks() {
                engine.process(block)
                let end = Double(block.sampleTime + Int64(block.samples.count)) / block.sampleRate
                if engine.state(at: end).status == .calibrating, engine.calibrationProgress.elapsed >= 15 {
                    ok = engine.finishCalibration().ok
                    calibrated += ok ? 1 : 0
                }
                if ok { errors.append(simd_distance(engine.state(at: end).position, path.position(end - synth.startTime))) }
            }
            recoveries += engine.diagnostics.recoveries
        }
        return (errors, calibrated, recoveries)
    }

    @Test func endToEndWalkOnSyntheticAudio() throws {
        let run = try endToEnd(minEchoDelay: 0.0003, seeds: 1...8)
        print(String(format: "end to end (audio): median %.1f cm, p95 %.1f cm, max %.1f cm, %d recoveries, %d of 8 calibrated",
                     percentile(run.errors, 0.5) * 100, percentile(run.errors, 0.95) * 100, (run.errors.max() ?? .nan) * 100,
                     run.recoveries, run.calibrated))
        #expect(run.calibrated >= 7)
        #expect(percentile(run.errors, 0.5) <= 0.15)
        #expect(percentile(run.errors, 0.95) <= 0.35)
    }
}
