import EarmarkAudio
import Foundation
import Testing

@Suite struct GateLogTests {
    @Test func errorWrapsAndConfusionIsMirrorAcrossTheEars() {
        #expect(GateMath.signedError(targetDeg: 170, responseDeg: -170) == 20)
        #expect(GateMath.signedError(targetDeg: -30, responseDeg: -45) == -15)
        #expect(GateMath.isFrontBackConfusion(targetDeg: 30, responseDeg: 150))     // classic mirror
        #expect(GateMath.isFrontBackConfusion(targetDeg: 170, responseDeg: 15))
        #expect(GateMath.isFrontBackConfusion(targetDeg: -20, responseDeg: -165))
        #expect(!GateMath.isFrontBackConfusion(targetDeg: 30, responseDeg: 40))      // ordinary error
        #expect(!GateMath.isFrontBackConfusion(targetDeg: 90, responseDeg: 100))     // lateral: never counts
        #expect(!GateMath.isFrontBackConfusion(targetDeg: 30, responseDeg: -80))     // wrong side, same hemisphere
    }

    @Test func randomAnglesStayInTheirSetAndAvoidRepeats() {
        var g = SystemRandomNumberGenerator()
        var prev: Double?
        for _ in 0..<200 {
            let a = GateMath.randomAngle(.front, previous: prev, using: &g)
            #expect(a >= -90 && a <= 90)
            if let p = prev { #expect(abs(a - p) >= 15) }
            prev = a
            let b = GateMath.randomAngle(.behind, previous: nil, using: &g)
            #expect(abs(b) >= 100 && abs(b) <= 180)
        }
    }

    @Test func tallyVerdictAndLoggerRoundTrip() throws {
        let url = FileManager.default.temporaryDirectory.appendingPathComponent("gate-\(UUID().uuidString)/spatial_gate.jsonl")
        let log = GateLogger(url: url)
        let errors: [Double] = [5, -10, 15, 25, 0, -19, 30, 2, 8, -4]   // 8 of 10 within 20
        for (i, e) in errors.enumerated() {
            try log.append(GateTrial(sessionId: "s1", trial: i + 1, set: .front, renderer: "avaudio_hrtfhq", timbre: "tone",
                                     targetDeg: 10, responseDeg: 10 + e, headTracking: "connected", yawAtResponseDeg: 0,
                                     outputDevice: "AirPods Pro", outputSampleRate: 48_000, mockHead: false, tester: "T1"))
        }
        try log.append(GateTrial(sessionId: "s1", trial: 11, set: .behind, renderer: "avaudio_hrtfhq", timbre: "tone",
                                 targetDeg: 160, responseDeg: 25, headTracking: "connected", yawAtResponseDeg: 0,
                                 outputDevice: "AirPods Pro", outputSampleRate: 48_000, mockHead: false, tester: "T1"))
        let back = log.load()
        #expect(back.count == 11)
        let tally = GateTally(trials: back)
        #expect(tally.passed == true)
        #expect(tally.frontHitsLast10 == 8)
        #expect(tally.confusions == 1)
        #expect(tally.verdict.hasPrefix("PASS"))
        // Keys are snake_case on disk.
        let text = try String(contentsOf: url, encoding: .utf8)
        #expect(text.contains("\"front_back_confusion\":true"))
        #expect(text.contains("\"target_deg\":10"))
        #expect(GateTally(trials: Array(back.prefix(9))).passed == nil)
    }
}

@Suite struct LaunchArgsTests {
    @Test func switchesAndSingleTokenValues() {
        let a = LaunchArgs(["app", "--mock-head", "--no-mic", "--bus-url=ws://127.0.0.1:8799", "--renderer=phase_manual", "stray"])
        #expect(a.has("mock-head") && a.has("no-mic") && !a.has("silent"))
        #expect(a.value("bus-url") == "ws://127.0.0.1:8799")
        #expect(a.value("renderer") == "phase_manual")
    }
}
