import Foundation
import simd
import Testing
@testable import EarmarkCore

/// Runs the detector with pre-calibration slot windows over every block.
func detectAll(_ blocks: [AudioBlock], config: RoomConfig) -> [Detection] {
    guard let first = blocks.first else { return [] }
    let detector = ChirpDetector(sampleRate: first.sampleRate)
    var beaconForSlot = [Int?](repeating: nil, count: Parameters.maxBeacons)
    for (k, beacon) in config.beacons.enumerated() { beaconForSlot[beacon.slot] = k }
    var out: [Detection] = []
    for block in blocks {
        detector.ingest(block)
        out += detector.detect(schedule: .slots(beaconForSlot: beaconForSlot), generation: 0)
    }
    return out
}

/// Timing error of each detection against the nearest true direct arrival of the same beacon.
func timingErrors(_ detections: [Detection], _ arrivals: [AudioSynth.Arrival]) -> [Double] {
    detections.map { d in
        arrivals.filter { $0.beacon == d.beacon }.map { d.arrivalTime - $0.time }.min { abs($0) < abs($1) } ?? .infinity
    }
}

func rms(_ values: [Double]) -> Double { (values.reduce(0) { $0 + $1 * $1 } / Double(values.count)).squareRoot() }

struct DetectorTests {
    let config: RoomConfig
    init() throws { config = try TestScene.load() }

    @Test func templateHasUnitEnergyAndSpecLength() {
        let h = ChirpTemplate(sampleRate: 48_000)
        #expect(h.count == 576)
        let energy = zip(h.real, h.imag).reduce(0.0) { $0 + Double($1.0 * $1.0 + $1.1 * $1.1) }
        #expect(abs(energy - 1) < 1e-5)
        #expect(ChirpTemplate(sampleRate: 44_100).count == 529)
    }

    @Test func timingErrorUnder20MicrosecondsAt20dB() {
        var options = AudioSynth.Options()
        options.snrDB = 20
        let synth = AudioSynth(config: config, path: .still(at: config.calibrationPosition, duration: 20), options: options)
        let detections = detectAll(synth.blocks(), config: config)
        let errors = timingErrors(detections, synth.arrivals)
        let usable = synth.arrivals.filter { $0.time > synth.startTime + 0.5 }.count
        print(String(format: "timing @20 dB: %d of %d chirps, RMS error %.2f µs", detections.count, usable, rms(errors) * 1e6))
        #expect(Double(detections.count) >= 0.95 * Double(usable))
        #expect(rms(errors) < 20e-6)
        for k in config.beacons.indices { #expect(detections.contains { $0.beacon == k }) }
    }

    /// The spec case: a pure delayed copy. `EchoSweepReport` shows other reflection phases.
    @Test func picksDirectPathOverStrongerEcho() {
        let phase: Double? = 0
        var options = AudioSynth.Options()
        options.snrDB = 20
        options.echoes = .fixed(delay: 0.0006, gainDB: 3, phase: phase)
        let synth = AudioSynth(config: config, path: .still(at: config.calibrationPosition, duration: 30), options: options)
        let detections = detectAll(synth.blocks(), config: config)
        let direct = timingErrors(detections, synth.arrivals).filter { abs($0) < 0.0001 }.count
        let rate = Double(direct) / Double(detections.count)
        print(String(format: "echo +3 dB @0.6 ms, phase \(phase.map { "\($0)" } ?? "random"): direct path in %d of %d (%.1f%%), %d ambiguous",
                     direct, detections.count, rate * 100, detections.filter(\.ambiguous).count))
        #expect(detections.count > 200)
        #expect(rate >= 0.95)
    }

    @Test func noiseOnlyGivesNoDetections() {
        var options = AudioSynth.Options()
        options.chirps = false
        let synth = AudioSynth(config: config, path: .still(at: config.calibrationPosition, duration: 60), options: options)
        let detections = detectAll(synth.blocks(), config: config)
        #expect(detections.isEmpty, "\(detections.count) false detections, max SNR \(detections.map(\.snrDB).max() ?? 0) dB")
    }

    @Test func restartsCleanlyAfterDroppedBuffers() {
        let synth = AudioSynth(config: config, path: .still(at: config.calibrationPosition, duration: 12))
        let blocks = synth.blocks(dropping: [40, 41, 90])
        let detections = detectAll(blocks, config: config)
        let errors = timingErrors(detections, synth.arrivals)
        #expect(errors.allSatisfy { abs($0) < 50e-6 })
        let gapEnd = Double(blocks[40].sampleTime) / synth.sampleRate
        #expect(detections.contains { $0.arrivalTime > gapEnd + 1 })
        #expect(Double(detections.count) > 0.85 * Double(synth.arrivals.count))
    }

    @Test func worksAt44100Hz() {
        var options = AudioSynth.Options()
        options.sampleRate = 44_100
        let synth = AudioSynth(config: config, path: .still(at: config.calibrationPosition, duration: 10), options: options)
        let detections = detectAll(synth.blocks(), config: config)
        #expect(Double(detections.count) > 0.9 * Double(synth.arrivals.count))
        #expect(rms(timingErrors(detections, synth.arrivals)) < 20e-6)
    }

    @Test func processesABlockInUnder3Milliseconds() throws {
        let synth = AudioSynth(config: config, path: .still(at: config.calibrationPosition, duration: 20))
        let engine = try EarmarkEngine(config: config)
        var times: [Double] = []
        for block in synth.blocks() {
            let start = DispatchTime.now().uptimeNanoseconds
            engine.process(block)
            times.append(Double(DispatchTime.now().uptimeNanoseconds - start) / 1e6)
        }
        let mean = times.reduce(0, +) / Double(times.count)
        print(String(format: "process: mean %.3f ms, max %.3f ms per 4096-sample block", mean, times.max()!))
        #expect(mean < 3)
    }

    /// Not a pass/fail target: shows how timing error grows as the detector's own SNR falls.
    @Test func reportTimingVersusSNR() {
        for snr in [20.0, 0, -5, -10] {
            var options = AudioSynth.Options()
            options.snrDB = snr
            options.seed = 7
            let synth = AudioSynth(config: config, path: .still(at: config.calibrationPosition, duration: 10), options: options)
            let detections = detectAll(synth.blocks(), config: config)
            guard !detections.isEmpty else { continue }
            let detectionSNR = detections.map(\.snrDB).sorted()[detections.count / 2]
            print(String(format: "input SNR %5.1f dB → detector SNR %4.1f dB, %3d of %3d chirps, RMS error %6.2f µs",
                         snr, detectionSNR, detections.count, synth.arrivals.count, rms(timingErrors(detections, synth.arrivals)) * 1e6))
        }
    }
}

/// Not a pass/fail target. An echo's carrier phase depends on its exact delay, so in a room it is
/// effectively random. Near the 0.5 ms resolution limit (1 / 2 kHz) some phases merge the direct and
/// echo peaks into one lobe, and the earliest-local-maximum rule then picks the echo.
struct EchoSweepReport {
    @Test func reportEchoPhaseSweep() throws {
        let config = try TestScene.load()
        for delay in [0.0006, 0.0008, 0.001] {
            var line = String(format: "delay %.1f ms:", delay * 1000)
            for step in 0..<8 {
                let phase = Double(step) * .pi / 4
                var options = AudioSynth.Options()
                options.snrDB = 20
                options.echoes = .fixed(delay: delay, gainDB: 3, phase: phase)
                let synth = AudioSynth(config: config, path: .still(at: config.calibrationPosition, duration: 6), options: options)
                let detections = detectAll(synth.blocks(), config: config)
                let direct = timingErrors(detections, synth.arrivals).filter { abs($0) < 0.0001 }.count
                line += String(format: " %3.0f%%", 100 * Double(direct) / Double(max(detections.count, 1)))
            }
            print(line)
        }
    }
}
