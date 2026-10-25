import XCTest
@testable import EarmarkCore

final class StreamingTests: XCTestCase {
    func signal(seconds: Double, silentCycles: Set<Int> = []) -> [Double] {
        let config = LocatorConfig(), fs = 48000.0
        let p = Vector3(0, 0, 1.25)
        var samples = (0..<Int(seconds * fs)).map { 0.00001 * sin(Double($0) * 0.37) }
        for cycle in 0..<Int(seconds / config.chirp.cycle) where !silentCycles.contains(cycle) {
            for beacon in config.beacons {
                let start = 0.04 + Double(cycle) * config.chirp.cycle + Double(beacon.slot) * config.chirp.slot + (p - beacon.position).norm / config.speedOfSound
                let chirp = Chirp.samples(config: config.chirp, fs: fs, falling: beacon.id == "B1")
                let offset = Int((start * fs).rounded())
                for i in chirp.indices where offset + i < samples.count { samples[offset + i] += chirp[i] * 0.2 }
            }
        }
        return samples
    }
    func run(_ signal: [Double], pipeline: LocatorPipeline) -> [Fix] {
        var fixes: [Fix] = []
        for start in stride(from: 0, to: signal.count, by: 2400) {
            let end = min(signal.count, start + 2400)
            fixes += pipeline.append(Array(signal[start..<end]), anchor: SampleAnchor(sample: Int64(start), unix: 1000 + Double(start) / 48000, fs: 48000))
        }
        return fixes
    }
    func testPipelineAcquisitionTrackingAndFixRate() throws {
        let pipeline = try LocatorPipeline(config: LocatorConfig())
        let fixes = run(signal(seconds: 4), pipeline: pipeline)
        XCTAssertGreaterThanOrEqual(fixes.count, 10)
        XCTAssertEqual(pipeline.state, .locked)
        for fix in fixes { XCTAssertLessThan((fix.mic_position - Vector3(0, 0, 1.25)).norm, 0.05) }
        let steady = fixes.filter { $0.t > 1001 }
        if let first = steady.first, let last = steady.last {
            XCTAssertGreaterThanOrEqual(Double(steady.count - 1) / (last.t - first.t), 3.2)
        }
    }
    func testLargeBufferMatchesReferenceSizedBlocks() throws {
        let samples = signal(seconds: 1.5)
        let blocks = run(samples, pipeline: try LocatorPipeline(config: LocatorConfig()))
        let whole = try LocatorPipeline(config: LocatorConfig()).append(samples,
            anchor: SampleAnchor(sample: 0, unix: 1000, fs: 48000))
        XCTAssertGreaterThanOrEqual(blocks.count, 3)
        XCTAssertEqual(whole.count, blocks.count)
        for (a, b) in zip(whole, blocks) {
            XCTAssertEqual(a.sample_index, b.sample_index, accuracy: 1e-6)
            XCTAssertLessThan((a.mic_position - b.mic_position).norm, 1e-9)
            XCTAssertEqual(a.quality, b.quality)
        }
    }
    func testMissingMarkersReacquireAndDiscontinuityResets() throws {
        let pipeline = try LocatorPipeline(config: LocatorConfig())
        let fixes = run(signal(seconds: 5, silentCycles: [4, 5, 6, 7]), pipeline: pipeline)
        XCTAssertTrue(fixes.contains { $0.t < 1001.2 })
        XCTAssertTrue(fixes.contains { $0.t > 1003.3 })
        _ = pipeline.append(Array(repeating: 0, count: 2400), anchor: SampleAnchor(sample: 900000, unix: 1020, fs: 48000))
        XCTAssertEqual(pipeline.droppedBuffers, 1)
        XCTAssertEqual(pipeline.state, .acquiring)
    }
    func testTemplateCaptureAndQuietFailure() throws {
        let template = try Calibration.template(samples: signal(seconds: 3.2), beacon: "B1", config: LocatorConfig())
        XCTAssertGreaterThanOrEqual(template.copies, 8)
        XCTAssertGreaterThanOrEqual(template.snr, 20)
        XCTAssertEqual(template.samples.count, 576)
        XCTAssertThrowsError(try Calibration.template(samples: Array(repeating: 0, count: 144000), beacon: "B1", config: LocatorConfig()))
    }
    func testSavePointRequiresDurationAndStability() throws {
        let fixes = (0..<9).map { i in
            Fix(t: Double(i) * 0.3, sampleIndex: Double(i) * 14400, mic: Vector3(1, 2, 1.25), ear: Vector3(1, 2, 1.60), quality: .ok,
                used: ["B1", "B2", "B3", "B4"], detections: [], residual: 0)
        }
        let point = try Calibration.savePoint(fixes, label: "salt", now: 2.5)
        XCTAssertEqual(point.position, Vector3(1, 2, 1.25))
        XCTAssertThrowsError(try Calibration.savePoint(Array(fixes.prefix(3)), label: "salt", now: 2.5))
        XCTAssertThrowsError(try Calibration.savePoint(fixes, label: "", now: 2.5))
        XCTAssertThrowsError(try Calibration.savePoint(fixes, label: "salt", now: 10))
        XCTAssertThrowsError(try Calibration.savePoint(fixes, label: "salt", now: 1))
        var reversed = fixes
        reversed.swapAt(2, 3)
        XCTAssertThrowsError(try Calibration.savePoint(reversed, label: "salt", now: 2.5))
        var duplicate = fixes
        duplicate[2] = duplicate[1]
        XCTAssertThrowsError(try Calibration.savePoint(duplicate, label: "salt", now: 2.5))
    }
    func testSpeechNonIntegerRateAndChunkBoundaries() {
        var stream = SpeechStream(inputRate: 44100, outputRate: 16000)
        stream.start()
        var chunks: [MicAudio] = []
        for i in 0..<10 { chunks += stream.append((0..<441).map { 0.01 * sin(Double(i * 441 + $0) * 0.1) }) }
        chunks += stream.stop()
        let totalBytes = chunks.compactMap { Data(base64Encoded: $0.chunk_b64)?.count }.reduce(0, +)
        XCTAssertEqual(totalBytes, 3200)
        XCTAssertEqual(chunks.map(\.seq), [0, 1, 2])
    }
}
