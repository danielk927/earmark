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

    @Test func pushToTalkIsCappedAndNeedsReleaseToReopen() {
        var cfg = VoiceGateConfig()
        cfg.maxPushToTalkChunks = 20
        var g = VoiceGate(mode: .pushToTalk, config: cfg)
        g.setPushToTalk(held: true)
        let out = run(&g, Array(repeating: quiet, count: 40))   // key never released
        #expect(out.filter { $0 == .began }.count == 1)
        #expect(out.filter { $0 == .ended }.count == 1)
        #expect(audioCount(out) == 20)
        #expect(!g.isOpen)
        g.setPushToTalk(held: false)
        g.setPushToTalk(held: true)
        #expect(run(&g, [quiet, quiet]).first == .began)         // a fresh press works again
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

    @Test func squeezeOpensAtOnceAndEndsOnAPauseAfterSpeech() {
        var g = VoiceGate(mode: .pushToTalk)
        _ = run(&g, Array(repeating: quiet, count: 20))
        let started = g.startHandsFree()
        #expect(started)
        var out = run(&g, [quiet])
        #expect(out == [.began, .audio(quiet), .audio(quiet), .audio(quiet)])   // open before any speech, with pre-roll
        out = run(&g, Array(repeating: speech, count: 5) + Array(repeating: quiet, count: 20))
        // 5 speech chunks, then 1.5 s of quiet ends it; the quiet is already sent, so no extra trailing audio.
        #expect(audioCount(out) == 5 + 15)
        #expect(out.filter { $0 == .ended }.count == 1)
        #expect(!g.isOpen && !g.handsFree)
    }

    @Test func squeezeWithNoSpeechClosesAfterFiveSeconds() {
        var g = VoiceGate(mode: .pushToTalk)
        _ = run(&g, Array(repeating: quiet, count: 20))
        g.startHandsFree()
        // One click is not speech, so the 1.5 s end-of-speech rule never starts; only the 5 s rule ends it.
        let out = run(&g, Array(repeating: quiet, count: 6) + [speech] + Array(repeating: quiet, count: 60))
        #expect(audioCount(out) == 3 + 50)
        #expect(out.last == .ended)
        #expect(!g.handsFree)
    }

    @Test func listeningEarconIsNotSpeech() {
        var g = VoiceGate(mode: .pushToTalk)
        _ = run(&g, Array(repeating: quiet, count: 20))
        g.startHandsFree()
        // The earcon through the Mac speakers: two loud chunks right after the squeeze. Counted as speech, they
        // would end the utterance 1.5 s later, before the user has said anything.
        let out = run(&g, [quiet, speech, speech] + Array(repeating: quiet, count: 20))
        #expect(!out.contains(.ended))
        #expect(g.handsFree)
    }

    @Test func secondSqueezeStopsWithTrailingAudio() {
        var g = VoiceGate(mode: .pushToTalk)
        _ = run(&g, Array(repeating: quiet, count: 20))
        g.startHandsFree()
        _ = run(&g, [quiet] + Array(repeating: speech, count: 10))
        g.stopHandsFree()
        let out = run(&g, Array(repeating: speech, count: 15))
        #expect(audioCount(out) == 10)                                    // 1 s trailing, like a key release
        #expect(out.last == .ended)
    }

    @Test func squeezeIsCapped() {
        var cfg = VoiceGateConfig()
        cfg.maxHandsFreeChunks = 20
        var g = VoiceGate(mode: .pushToTalk, config: cfg)
        _ = run(&g, Array(repeating: quiet, count: 20))
        g.startHandsFree()
        let out = run(&g, Array(repeating: speech, count: 40))          // never pauses
        #expect(out.filter { $0 == .began }.count == 1)
        #expect(out.filter { $0 == .ended }.count == 1)
        #expect(audioCount(out) == 3 + 20)
    }

    @Test func heldKeyOutlastsASqueeze() {
        var g = VoiceGate(mode: .pushToTalk)
        _ = run(&g, Array(repeating: quiet, count: 20))
        g.startHandsFree()
        g.setPushToTalk(held: true)
        #expect(!run(&g, Array(repeating: quiet, count: 60)).contains(.ended))   // squeeze timed out, key still held
        #expect(!g.handsFree && g.isOpen)
        g.setPushToTalk(held: false)
        #expect(run(&g, Array(repeating: quiet, count: 10)).last == .ended)
    }

    @Test func squeezeDoesNothingInAlwaysListening() {
        var g = VoiceGate(mode: .alwaysListening)
        let started = g.startHandsFree()
        #expect(!started)
        #expect(run(&g, Array(repeating: quiet, count: 20)).isEmpty)
        var p = VoiceGate(mode: .pushToTalk)
        p.startHandsFree()
        p.mode = .alwaysListening                                          // switching modes ends a squeeze
        #expect(!p.handsFree)
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
