import Foundation
import simd
import Testing
@testable import EarmarkCore

/// A fixture from A (C5): fixtures/<name>.wav plus fixtures/<name>.json.
struct Fixture {
    struct Meta: Decodable {
        struct Truth: Decodable { let type: String; let position: [Double]?; let points: [[Double]]? }
        let sampleRate: Double
        let wallClockAtFirstSample: Double
        let scene: String
        let truth: Truth
        let notes: String?
    }

    let name: String
    let meta: Meta
    let audio: WAVFile
    let config: RoomConfig

    static func names(in directory: URL = TestScene.fixtures) -> [String] {
        let files = (try? FileManager.default.contentsOfDirectory(atPath: directory.path)) ?? []
        return files.filter { $0.hasSuffix(".json") }.map { String($0.dropLast(5)) }
            .filter { FileManager.default.fileExists(atPath: directory.appendingPathComponent($0 + ".wav").path) }
            .sorted()
    }

    static func exists(_ name: String) -> Bool { names().contains(name) }

    /// `root` is the folder the fixture's `scene` path is relative to (the repo root).
    init(_ name: String, directory: URL = TestScene.fixtures, root: URL = TestScene.repoRoot) throws {
        self.name = name
        meta = try JSONDecoder().decode(Meta.self, from: Data(contentsOf: directory.appendingPathComponent(name + ".json")))
        audio = try WAVFile(url: directory.appendingPathComponent(name + ".wav"))
        config = try RoomConfig.load(from: Data(contentsOf: root.appendingPathComponent(meta.scene)))
    }

    var duration: Double { Double(audio.samples.count) / audio.sampleRate }

    func blocks(size: Int = 4096) -> [AudioBlock] {
        stride(from: 0, to: audio.samples.count, by: size).map { offset in
            AudioBlock(samples: Array(audio.samples[offset..<min(offset + size, audio.samples.count)]), sampleRate: audio.sampleRate,
                       sampleTime: Int64(offset), wallClock: meta.wallClockAtFirstSample + Double(offset) / audio.sampleRate)
        }
    }

    /// Distance from `p` to the truth: the static point, or the nearest point on the walked route.
    func truthError(_ p: SIMD3<Double>) -> Double? {
        switch meta.truth.type {
        case "static": return meta.truth.position.map { simd_distance(p, SIMD3($0)) }
        case "route":
            guard let points = meta.truth.points?.map({ SIMD3($0) }), points.count >= 2 else { return nil }
            return zip(points, points.dropFirst()).map { a, b in
                let u = simd_clamp(simd_dot(p - a, b - a) / max(simd_length_squared(b - a), 1e-12), 0, 1)
                return simd_distance(p, a + (b - a) * u)
            }.min()
        default: return nil
        }
    }

    struct Result {
        var detectionRate: [String: Double] = [:]
        var calibration: CalibrationReport?
        var errors: [Double] = []
        var ranges: [[Double]] = []
    }

    /// Detects with slot windows for the per-beacon rate, then calibrates on the first 15 s and tracks the rest.
    func run() throws -> Result {
        var result = Result()
        let detections = detectAll(blocks(), config: config)
        for (k, beacon) in config.beacons.enumerated() {
            result.detectionRate[beacon.id] = Double(detections.filter { $0.beacon == k }.count) / (duration / Parameters.cycle)
        }
        guard meta.truth.type != "none", duration > Parameters.calibrationDuration + 1 else { return result }
        let engine = try EarmarkEngine(config: config)
        engine.startCalibration()
        result.ranges = Array(repeating: [], count: config.beacons.count)
        var seen = [Double?](repeating: nil, count: config.beacons.count)
        for block in blocks() {
            engine.process(block)
            let end = Double(block.sampleTime + Int64(block.samples.count)) / block.sampleRate
            if result.calibration == nil, engine.calibrationProgress.elapsed >= Parameters.calibrationDuration {
                result.calibration = engine.finishCalibration()
            }
            guard result.calibration?.ok == true else { continue }
            if let error = truthError(engine.state(at: end).position) { result.errors.append(error) }
            for (k, b) in engine.diagnostics.beacons.enumerated() where b.lastRangeM != seen[k] {
                seen[k] = b.lastRangeM
                if let r = b.lastRangeM { result.ranges[k].append(r) }
            }
        }
        return result
    }
}

struct FixtureTests {
    /// B8: reports every fixture in fixtures/. Passes when there are none.
    @Test func reportEveryFixture() throws {
        let names = Fixture.names()
        if names.isEmpty { print("fixtures: none in \(TestScene.fixtures.path)") }
        for name in names {
            let fixture = try Fixture(name)
            let result = try fixture.run()
            let rates = fixture.config.beacons.map { String(format: "%@ %.0f%%", $0.id, (result.detectionRate[$0.id] ?? 0) * 100) }
            var line = String(format: "fixture %@ (%.1f s, %@): detections ", name, fixture.duration, fixture.meta.truth.type) + rates.joined(separator: ", ")
            if let report = result.calibration {
                line += report.ok ? "; calibrated" : "; calibration failed: \(report.problems.joined(separator: " "))"
            }
            if !result.errors.isEmpty {
                line += String(format: "; position error median %.1f cm, p95 %.1f cm", percentile(result.errors, 0.5) * 100, percentile(result.errors, 0.95) * 100)
            }
            print(line)
        }
    }

    /// B3 and B4 on the real static recording: all four beacons found, and after calibrating on the
    /// first 15 s every later range matches the true distance within 1 cm.
    @Test(.enabled(if: Fixture.exists("cal-static-20s"))) func calStatic20s() throws {
        try checkCalStatic(Fixture("cal-static-20s"))
    }

    /// The same checks on a synthetic recording written in the fixture format, so the fixture path
    /// (WAV reader, JSON, wall clock, scene lookup) is exercised before A's recordings exist.
    @Test func syntheticCalStaticFixture() throws {
        let dir = FileManager.default.temporaryDirectory.appendingPathComponent("earmark-fixture-\(UUID().uuidString)")
        try FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)
        defer { try? FileManager.default.removeItem(at: dir) }
        let config = try TestScene.load()
        var options = AudioSynth.Options()
        options.snrDB = 15
        options.echoes = .room(minDelay: 0.0003)
        let synth = AudioSynth(config: config, path: .still(at: config.calibrationPosition, duration: 20), options: options)
        try WAVReaderTests().write(synth.samples, format: 1, to: dir.appendingPathComponent("cal-static-20s.wav"))
        let p = config.calibrationPoint
        let meta = """
        { "version": 1, "sampleRate": 48000, "wallClockAtFirstSample": \(synth.world.wallClockAtZero), "recorder": "other",
          "scene": "scene.json", "truth": { "type": "static", "position": [\(p[0]), \(p[1]), \(p[2])] }, "notes": "synthetic" }
        """
        try Data(meta.utf8).write(to: dir.appendingPathComponent("cal-static-20s.json"))
        let sceneData = (try? Data(contentsOf: TestScene.repoRoot.appendingPathComponent("scene.json"))) ?? Data(TestScene.c4Example.utf8)
        try sceneData.write(to: dir.appendingPathComponent("scene.json"))
        #expect(Fixture.names(in: dir) == ["cal-static-20s"])
        try checkCalStatic(Fixture("cal-static-20s", directory: dir, root: dir))
    }

    func checkCalStatic(_ fixture: Fixture) throws {
        let result = try fixture.run()
        for beacon in fixture.config.beacons {
            #expect((result.detectionRate[beacon.id] ?? 0) > 0.5, "\(beacon.id) found in \((result.detectionRate[beacon.id] ?? 0) * 100)% of cycles")
        }
        let report = try #require(result.calibration)
        #expect(report.ok, "\(report.problems)")
        let truth = try #require(fixture.meta.truth.position.map { SIMD3($0) })
        for (k, beacon) in fixture.config.beacons.enumerated() {
            let distance = simd_distance(truth, fixture.config.beaconPositions[k])
            let errors = result.ranges[k].map { abs($0 - distance) }
            #expect(!errors.isEmpty && errors.allSatisfy { $0 < 0.01 },
                    "\(beacon.id): \(errors.count) ranges, worst error \((errors.max() ?? .nan) * 100) cm")
        }
    }
}

/// The WAV reader on files written here, since no fixtures may exist yet.
struct WAVReaderTests {
    func write(_ samples: [Float], format: UInt16, to url: URL) throws {
        var data = Data()
        func put<T: FixedWidthInteger>(_ v: T) { withUnsafeBytes(of: v.littleEndian) { data.append(contentsOf: $0) } }
        let bits: UInt16 = format == 1 ? 16 : 32
        let bytes = samples.count * Int(bits) / 8
        data.append(contentsOf: Array("RIFF".utf8)); put(UInt32(36 + bytes)); data.append(contentsOf: Array("WAVE".utf8))
        data.append(contentsOf: Array("fmt ".utf8)); put(UInt32(16)); put(format); put(UInt16(1)); put(UInt32(48_000))
        put(UInt32(48_000 * Int(bits) / 8)); put(UInt16(bits / 8)); put(bits)
        data.append(contentsOf: Array("data".utf8)); put(UInt32(bytes))
        for s in samples {
            if format == 1 { put(Int16(max(-1, min(1, s)) * 32767)) } else { put(s.bitPattern) }
        }
        try data.write(to: url)
    }

    @Test(arguments: [UInt16(1), 3]) func readsPCM16AndFloat32(format: UInt16) throws {
        let url = FileManager.default.temporaryDirectory.appendingPathComponent("earmark-wav-\(format)-\(UUID().uuidString).wav")
        defer { try? FileManager.default.removeItem(at: url) }
        let samples: [Float] = [0, 0.5, -0.5, 0.25, -1]
        try write(samples, format: format, to: url)
        let wav = try WAVFile(url: url)
        #expect(wav.sampleRate == 48_000)
        #expect(wav.samples.count == samples.count)
        for (a, b) in zip(wav.samples, samples) { #expect(abs(a - b) < 1e-4) }
    }
}
