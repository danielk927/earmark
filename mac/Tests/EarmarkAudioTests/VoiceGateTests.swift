import EarmarkAudio
import Foundation
import Testing

private func chunk(db: Double) -> [Int16] {
    // A 300 Hz sine at the requested RMS level (dBFS); amplitude = rms * sqrt(2).
    let amp = pow(10, db / 20) * 2.0.squareRoot() * 32_767
    return (0..<1_600).map { i in Int16(max(-32_767, min(32_767, amp * sin(2 * .pi * 300 * Double(i) / 16_000)))) }
}

private let quiet = chunk(db: -65)
private let speech = chunk(db: -25)

private func run(_ gate: inout VoiceGate, _ chunks: [[Int16]]) -> [GateOutput] {
    chunks.flatMap { gate.process($0) }
}

private func audioCount(_ out: [GateOutput]) -> Int { out.filter { if case .audio = $0 { true } else { false } }.count }

@Suite struct VoiceGateTests {
    @Test func silenceSendsNothing() {
        var g = VoiceGate(mode: .alwaysListening)
        #expect(run(&g, Array(repeating: quiet, count: 50)).isEmpty)
    }

    @Test func speechGetsPreRollAndOneSecondOfTrailingAudio() {
        var g = VoiceGate(mode: .alwaysListening)
        var out = run(&g, Array(repeating: quiet, count: 20))
        #expect(out.isEmpty)
        out = run(&g, Array(repeating: speech, count: 5) + Array(repeating: quiet, count: 15))
        #expect(out.first == .began)
        #expect(out.filter { $0 == .ended }.count == 1)
        // Opens on the 2nd speech chunk with 3 chunks of pre-roll (quiet, speech, speech),
        // then 3 more speech chunks, then exactly 10 trailing chunks (1 s) before closing.
        #expect(audioCount(out) == 3 + 3 + 10)
        guard case .audio(let first)? = out.dropFirst().first else { Issue.record("no audio"); return }
        #expect(first == quiet)   // pre-roll reaches back before speech onset
        #expect(!g.isOpen)
    }

    @Test func singleClickDoesNotOpen() {
        var g = VoiceGate(mode: .alwaysListening)
        _ = run(&g, Array(repeating: quiet, count: 20))
        #expect(run(&g, [speech] + Array(repeating: quiet, count: 10)).isEmpty)
    }

    @Test func pausesShorterThanOneSecondKeepTheUtterance() {
        var g = VoiceGate(mode: .alwaysListening)
        _ = run(&g, Array(repeating: quiet, count: 20))
        let out = run(&g, Array(repeating: speech, count: 4) + Array(repeating: quiet, count: 6)
                      + Array(repeating: speech, count: 3) + Array(repeating: quiet, count: 12))
        #expect(out.filter { $0 == .began }.count == 1)
        #expect(out.filter { $0 == .ended }.count == 1)
    }

    @Test func pushToTalkHoldAndRelease() {
        var g = VoiceGate(mode: .pushToTalk)
        #expect(run(&g, Array(repeating: speech, count: 10)).isEmpty)   // loud but key not held
        g.setPushToTalk(held: true)
        var out = run(&g, Array(repeating: quiet, count: 5))
        #expect(out.first == .began)
        #expect(audioCount(out) == 3 + 4)                                 // pre-roll includes the press chunk
        g.setPushToTalk(held: false)
        out = run(&g, Array(repeating: quiet, count: 15))
        #expect(audioCount(out) == 10)                                    // 1 s trailing after release
        #expect(out.last == .ended)
        #expect(run(&g, Array(repeating: quiet, count: 5)).isEmpty)
    }

    @Test func switchingModeClosesAnOpenUtterance() {
        var g = VoiceGate(mode: .pushToTalk)
        g.setPushToTalk(held: true)
        _ = run(&g, [quiet, quiet])
        #expect(g.isOpen)
        g.mode = .alwaysListening
        let out = g.process(quiet)
        #expect(out.first == .ended)
        #expect(!g.isOpen)
    }

    @Test func noiseFloorAdapts() {
        // Steady room noise at -45 dBFS: the floor rises, so -42 dBFS noise no longer opens the gate,
        // while real speech still does.
        var g = VoiceGate(mode: .alwaysListening)
        _ = run(&g, Array(repeating: chunk(db: -45), count: 100))
        #expect(g.noiseFloorDb > -50)
        #expect(run(&g, Array(repeating: chunk(db: -42), count: 20)).isEmpty)
        #expect(run(&g, Array(repeating: chunk(db: -20), count: 3)).first == .began)
    }
}
