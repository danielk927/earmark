import XCTest
@testable import EarmarkCore

final class CoreTests: XCTestCase {
    func arrivals(_ point: Vector3, config: LocatorConfig = LocatorConfig()) -> [Arrival] {
        config.beacons.map { Arrival(beacon: $0.id, arrival: 10 + Double($0.slot) * config.chirp.slot + (point - $0.position).norm / config.speedOfSound, snr: 30) }
    }
    func testConfigRoundtripAndSpaceImport() throws {
        let config = LocatorConfig()
        XCTAssertEqual(try LocatorConfig.importing(config.exported()), config)
        let data = try JSONEncoder().encode(config.beacons)
        let space = Data("{\"spots\":[],\"beacons\":".utf8) + data + Data("}".utf8)
        XCTAssertEqual(try Beacon.importing(space), config.beacons)
        XCTAssertThrowsError(try Beacon.importing(Data("{\"beacons\":[]}".utf8)))
        XCTAssertThrowsError(try JSONDecoder().decode(Vector3.self, from: Data("[1,2]".utf8)))
        var bad = config; bad.chirp.f_hi = 2500
        XCTAssertThrowsError(try bad.validate())
    }
    func testQuantizedChirpEdges() {
        let config = ChirpConfig()
        for falling in [true, false] {
            let start = falling ? config.f_hi : config.f_lo
            let end = falling ? config.f_lo : config.f_hi
            for (i, t) in Chirp.edges(config: config, falling: falling).enumerated() {
                let phase = 2 * (start * t + (end - start) * t * t / (2 * config.duration))
                XCTAssertEqual(phase, Double(i + 1), accuracy: 0.0005)
                XCTAssertEqual(t * 1e7, (t * 1e7).rounded(), accuracy: 1e-7)
            }
        }
        XCTAssertEqual(Chirp.samples(config: config, fs: 48000, falling: false).count, 576)
    }
    func testChirpSamplesMatchPythonReference() {
        // Full transition indices from square_wave_samples at Python commit 9050384.
        let falling = [5, 11, 16, 22, 27, 33, 38, 44, 49, 55, 60, 66, 72, 78, 83, 89, 95, 101, 107, 113, 119, 125, 131, 137, 143, 149, 156, 162, 168, 175, 181, 188, 194, 201, 207, 214, 221, 228, 235, 241, 248, 255, 263, 270, 277, 284, 292, 299, 307, 314, 322, 330, 338, 346, 354, 362, 370, 378, 387, 395, 404, 413, 422, 431, 440, 449, 459, 469, 478, 488, 499, 509, 519, 530, 541, 553, 564]
        let rising = [12, 23, 35, 46, 57, 67, 77, 88, 98, 107, 117, 127, 136, 145, 154, 163, 172, 181, 189, 198, 206, 214, 222, 230, 238, 246, 254, 262, 269, 277, 284, 292, 299, 306, 313, 321, 328, 335, 341, 348, 355, 362, 369, 375, 382, 388, 395, 401, 408, 414, 420, 427, 433, 439, 445, 451, 457, 463, 469, 475, 481, 487, 493, 498, 504, 510, 516, 521, 527, 532, 538, 543, 549, 554, 560, 565, 571]
        for (isFalling, expected) in [(true, falling), (false, rising)] {
            let samples = Chirp.samples(config: ChirpConfig(), fs: 48000, falling: isFalling)
            XCTAssertEqual(samples.count, 576)
            XCTAssertEqual(samples.first, 1)
            XCTAssertTrue(samples.allSatisfy { $0 == 1 || $0 == -1 })
            XCTAssertEqual((1..<samples.count).filter { samples[$0] != samples[$0 - 1] }, expected)
        }
        var short = ChirpConfig(); short.length_ms = 5
        XCTAssertEqual(Chirp.samples(config: short, fs: 44100, falling: false).count, 220)
    }
    func testExactAndNoisySolver() throws {
        let p = Vector3(0.3, -0.2, 1.25)
        let exact = try XCTUnwrap(PositionSolver.solve(arrivals: arrivals(p), config: LocatorConfig()))
        XCTAssertLessThan((exact.position - p).norm, 0.001)
        XCTAssertEqual(exact.quality, .ok)
        let noise = [0.00001, -0.00001, 0.00002, -0.00002, 0.00001]
        let noisy = zip(arrivals(p), noise).map { Arrival(beacon: $0.beacon, arrival: $0.arrival + $1, snr: 30) }
        let estimate = try XCTUnwrap(PositionSolver.solve(arrivals: noisy, config: LocatorConfig()))
        XCTAssertLessThan((estimate.position - p).norm, 0.03)
    }
    func testThreeBeaconsAndInvalidDetections() throws {
        let p = Vector3(0.1, 0.2, 1.25)
        let solution = try XCTUnwrap(PositionSolver.solve(arrivals: Array(arrivals(p).prefix(3)), config: LocatorConfig()))
        XCTAssertEqual(solution.quality, .degraded)
        XCTAssertLessThan((solution.position - p).norm, 0.001)
        XCTAssertNil(PositionSolver.solve(arrivals: Array(arrivals(p).prefix(2)), config: LocatorConfig()))
        XCTAssertNil(PositionSolver.solve(arrivals: Array(repeating: arrivals(p)[0], count: 5), config: LocatorConfig()))
    }
    func testOutlierRejection() throws {
        let p = Vector3(0, 0, 1.25)
        var measurements = arrivals(p)
        measurements[4] = Arrival(beacon: "B5", arrival: measurements[4].arrival + 0.002, snr: 30)
        let result = try XCTUnwrap(PositionSolver.solve(arrivals: measurements, config: LocatorConfig(), initial: p))
        XCTAssertEqual(result.used.count, 4)
        XCTAssertFalse(result.used.contains { $0.beacon == "B5" })
        XCTAssertLessThan((result.position - p).norm, 0.01)
    }
    func testFirstArrivalBeforeStrongerEcho() throws {
        var envelope = Array(repeating: 1.0, count: 300)
        envelope[99] = 30; envelope[100] = 60; envelope[101] = 30
        envelope[149] = 50; envelope[150] = 100; envelope[151] = 50
        let peak = try XCTUnwrap(Detection.firstArrival(envelope: envelope, range: 1..<299, lookback: 96, minimumSNR: 8))
        XCTAssertEqual(peak.sample, 100, accuracy: 0.001)
    }
    func testAcquisitionScoresOnlyTheCandidateGate() throws {
        var envelope = Array(repeating: 1.0, count: 1001)
        for i in 360..<641 { envelope[i] = 20 }
        envelope[499] = 50; envelope[500] = 100; envelope[501] = 50
        XCTAssertNotNil(Detection.firstArrival(envelope: envelope, range: 1..<1000, lookback: 96, minimumSNR: 10))
        XCTAssertNil(Detection.markerCandidate(envelope: envelope, gate: 144, lookback: 96, minimumSNR: 10))
        for i in 360..<641 { envelope[i] = 1 }
        envelope[499] = 50; envelope[500] = 100; envelope[501] = 50
        envelope[10] = 10000
        let candidate = try XCTUnwrap(Detection.markerCandidate(envelope: envelope, gate: 144, lookback: 96, minimumSNR: 10))
        XCTAssertEqual(candidate.sample, 500)
        XCTAssertEqual(candidate.snr, 100)
        XCTAssertNil(Detection.markerCandidate(envelope: [1, 2, 1], gate: 144, lookback: 96, minimumSNR: 10))
    }
    func testFirstArrivalRequiresLocalMaximum() {
        let rising = (0..<300).map(Double.init)
        XCTAssertNil(Detection.firstArrival(envelope: rising, range: 1..<200, lookback: 96, minimumSNR: 0))
    }
    func testMarkerConfirmationMissesAndClockReset() throws {
        var tracker = MarkerTracker(cycle: 0.3)
        XCTAssertFalse(tracker.observe(0.04))
        XCTAssertEqual(tracker.state, .confirming)
        XCTAssertFalse(tracker.observe(0.342))
        XCTAssertEqual(tracker.misses, 1)
        XCTAssertEqual(try XCTUnwrap(tracker.expected), 0.64, accuracy: 1e-12)
        XCTAssertTrue(tracker.observe(0.64))
        XCTAssertEqual(tracker.state, .locked)
        XCTAssertTrue(tracker.observe(0.942))
        XCTAssertGreaterThan(tracker.period, 0.3)
        XCTAssertFalse(tracker.observe(nil))
        XCTAssertFalse(tracker.observe(nil))
        XCTAssertFalse(tracker.observe(nil))
        XCTAssertEqual(tracker.state, .acquiring)
        XCTAssertNil(tracker.expected)
        XCTAssertEqual(tracker.period, 0.3)
    }
    func testFFTAgreementAndRoundtrip() {
        let original = Spectrum(real: (0..<64).map { sin(Double($0) * 0.4) }, imaginary: Array(repeating: 0, count: 64))
        let portable = DSP.transform(original, portable: true)
        let accelerated = DSP.transform(original)
        for i in 0..<64 {
            XCTAssertEqual(portable.real[i], accelerated.real[i], accuracy: 1e-9)
            XCTAssertEqual(portable.imaginary[i], accelerated.imaginary[i], accuracy: 1e-9)
        }
        let recovered = DSP.transform(accelerated, inverse: true)
        for i in 0..<64 { XCTAssertEqual(recovered.real[i], original.real[i], accuracy: 1e-10) }
    }
    func testLostSentOnceAndMeasurementTimestampRetained() {
        var publisher = PosePublisher()
        let fix = Fix(t: 100, sampleIndex: 0, mic: .zero, ear: Vector3(0, 0, 0.35), quality: .ok, used: ["B1", "B2", "B3", "B4"], detections: [], residual: 0)
        _ = publisher.accept(fix, source: .beacons)
        XCTAssertNil(publisher.timeout(now: 101.4, seconds: 1.5))
        let lost = publisher.timeout(now: 101.5, seconds: 1.5)
        XCTAssertEqual(lost?.quality, .lost); XCTAssertEqual(lost?.t, 100)
        XCTAssertNil(publisher.timeout(now: 110, seconds: 1.5))
        _ = publisher.accept(fix, source: .sim)
        XCTAssertNotNil(publisher.timeout(now: 110, seconds: 1.5))
    }
    func testSpeechChunksResetAndFlush() {
        var speech = SpeechStream(inputRate: 48000, outputRate: 16000)
        XCTAssertTrue(speech.append([1, 2]).isEmpty)
        speech.start()
        let input = (0..<4800).map { 0.01 * sin(2 * Double.pi * 400 * Double($0) / 48000) }
        let chunks = speech.append(input) + speech.stop()
        XCTAssertEqual(chunks.map(\.seq), [0, 1, 2])
        XCTAssertEqual(chunks.compactMap { Data(base64Encoded: $0.chunk_b64)?.count }, [1280, 1280, 640])
        speech.start()
        XCTAssertEqual((speech.append(input) + speech.stop()).first?.seq, 0)
    }
    func testWAVAndExactWireFields() throws {
        let data = WaveFile.header(sampleRate: 48000, sampleCount: 3) + PCM.encode([-1, 0, 0.5])
        XCTAssertEqual(try WaveFile(data: data).samples, [-1, 0, 0.5])
        let pose = ListenerPose(position: .zero, quality: .ok, beacons: 5, source: .beacons, t: 123)
        let object = try XCTUnwrap(JSONSerialization.jsonObject(with: JSONEncoder().encode(pose)) as? [String: Any])
        XCTAssertEqual(Set(object.keys), Set(["type", "position", "quality", "beacons_heard", "source", "t"]))
        let native = try XCTUnwrap(JSONSerialization.jsonObject(with: JSONEncoder().encode(NativePose(position: .zero))) as? [String: Any])
        XCTAssertEqual(Set(native.keys), Set(["type", "pos", "source"]))
        XCTAssertNil(try PTTMessage.parse(Data("{\"type\":\"other\"}".utf8)))
    }
}
