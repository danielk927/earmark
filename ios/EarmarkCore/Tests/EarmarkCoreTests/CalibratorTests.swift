import Foundation
import simd
import Testing
@testable import EarmarkCore

struct CalibratorTests {
    let config: RoomConfig
    init() throws { config = try TestScene.load() }

    /// Calibrates on 15 s of synthetic audio at the calibration point, keeps listening for 15 s more,
    /// and checks every beacon's measured range against its true distance.
    @Test func syntheticRangesMatchTrueDistance() throws {
        var options = AudioSynth.Options()
        options.snrDB = 20
        options.echoes = .room(minDelay: 0.0003)
        options.seed = 3
        let synth = AudioSynth(config: config, path: .still(at: config.calibrationPosition, duration: 32), options: options)
        let engine = try EarmarkEngine(config: config)
        var report: CalibrationReport?
        var ranges = [[Double]](repeating: [], count: config.beacons.count)
        var seen = [Double?](repeating: nil, count: config.beacons.count)
        for block in synth.blocks() {
            engine.process(block)
            let t = Double(block.sampleTime) / block.sampleRate - synth.startTime
            if t >= 1, engine.state(at: 0).status == .notCalibrated, report == nil { engine.startCalibration() }
            if t >= 16.2, report == nil { report = engine.finishCalibration() }
            guard report?.ok == true else { continue }
            for (k, beacon) in engine.diagnostics.beacons.enumerated() {
                if let range = beacon.lastRangeM, range != seen[k] { ranges[k].append(range); seen[k] = range }
            }
        }
        let calibration = try #require(report)
        #expect(calibration.ok, "\(calibration.problems)")
        for (k, beacon) in calibration.beacons.enumerated() {
            let truth = simd_distance(config.calibrationPosition, config.beaconPositions[k])
            let errors = ranges[k].map { abs($0 - truth) }
            print(String(format: "%@: %d kept, residual %.2f cm, phase %.3f s; %d ranges after, worst error %.2f cm",
                         beacon.id, beacon.detections, beacon.residualCm, beacon.phaseSeconds, errors.count, (errors.max() ?? 0) * 100))
            #expect(errors.count > 20)
            #expect(errors.allSatisfy { $0 < 0.01 })
        }
    }

    @Test func tooShortCalibrationFails() throws {
        let synth = AudioSynth(config: config, path: .still(at: config.calibrationPosition, duration: 8))
        let engine = try EarmarkEngine(config: config)
        engine.startCalibration()
        for block in synth.blocks() { engine.process(block) }
        #expect(engine.calibrationProgress.detections.values.allSatisfy { $0 > 10 })
        let report = engine.finishCalibration()
        #expect(!report.ok)
        #expect(report.problems.contains { $0.contains("needs 15 s") })
        #expect(engine.state(at: 0).status == .notCalibrated)
    }

    /// Detections laid out by hand: beacon k arrives at phase `phases[k]` every 0.5 s.
    private func detections(phases: [Double], jitter: Double = 10e-6, outliers: Int = 0) -> [Detection] {
        var rng = SeededRandom(seed: 11)
        var out: [Detection] = []
        for (k, phase) in phases.enumerated() {
            for n in 0..<32 {
                var t = 100 + phase + Double(n) * 0.500_01 + jitter * rng.gaussian()
                if n < outliers { t += 0.002 }      // a clump of echoes at the start
                out.append(Detection(beacon: k, arrivalTime: t, snrDB: 25, ambiguous: false, wallClock: t + 1_792_882_000))
            }
        }
        return out
    }

    @Test func robustFitIgnoresEchoOutliers() {
        let report = Calibrator.fit(config: config, detections: detections(phases: [0.01, 0.135, 0.26, 0.385], outliers: 5), elapsed: 16).0
        #expect(report.ok, "\(report.problems)")
        #expect(report.beacons.allSatisfy { $0.detections == 27 })
    }

    @Test func fitMeasuresDrift() throws {
        let times = (0..<30).map { 5 + Double($0) * 0.500_015 }
        let fit = try #require(Calibrator.robustFit(times))
        #expect(abs(fit.b - 0.500_015) < 1e-9)
        #expect(fit.sigma == Parameters.timingNoiseFloor)
    }

    @Test func beaconsTooCloseInPhaseAreNamed() {
        let report = Calibrator.fit(config: config, detections: detections(phases: [0.01, 0.135, 0.16, 0.385]), elapsed: 16).0
        #expect(!report.ok)
        #expect(report.problems.contains { $0.contains("B2") && $0.contains("B3") && $0.contains("25 ms") })
    }

    @Test func noisyOrMissingBeaconFails() {
        var list = detections(phases: [0.01, 0.135, 0.26, 0.385])
        list.removeAll { $0.beacon == 3 && Int($0.arrivalTime) % 2 == 0 }  // B4 loses about half
        let noisy = detections(phases: [0.01], jitter: 150e-6)               // B1 is 5 cm noisy
        list.removeAll { $0.beacon == 0 }
        list += noisy
        let report = Calibrator.fit(config: config, detections: list, elapsed: 16).0
        #expect(!report.ok)
        #expect(report.problems.contains { $0.hasPrefix("B1: timing noise") })
        #expect(report.problems.contains { $0.hasPrefix("B4: only") })
    }
}
