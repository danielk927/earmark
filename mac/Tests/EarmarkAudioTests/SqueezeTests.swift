import EarmarkAudio
import Foundation
import Testing

private let quiet = [Int16](repeating: 0, count: 1_600)

private func feed(_ p: MicPipeline, _ n: Int) {
    for _ in 0..<n { p.process(quiet) }
}

@Suite struct SqueezeTests {
    @Test func firstSqueezeInterruptsEarmarkAndListens() {
        let pipeline = MicPipeline(mode: .pushToTalk), speech = MockSpeech()
        let s = SqueezeToTalk(pipeline: pipeline, speech: speech)
        feed(pipeline, 20)
        s.squeeze()
        #expect(s.listening && pipeline.handsFreeActive)
        #expect(speech.calls == ["stopAll", "earcon listening"])
        #expect(!s.poll())
    }

    @Test func secondSqueezeStopsAndPlaysDone() {
        let pipeline = MicPipeline(mode: .pushToTalk), speech = MockSpeech()
        let s = SqueezeToTalk(pipeline: pipeline, speech: speech)
        feed(pipeline, 20)
        s.squeeze()
        feed(pipeline, 3)
        s.squeeze()
        #expect(s.poll())
        #expect(!s.listening)
        #expect(speech.calls.last == "earcon done")
        #expect(!s.poll())                                     // the done sound plays once
    }

    @Test func silenceEndsItWithoutASecondSqueeze() {
        let pipeline = MicPipeline(mode: .pushToTalk), speech = MockSpeech(), clock = TestClock()
        let s = SqueezeToTalk(pipeline: pipeline, speech: speech, clock: { clock.now })
        feed(pipeline, 20)
        s.squeeze()
        feed(pipeline, 30)
        #expect(!s.poll())
        feed(pipeline, 30)                                     // past the 5 s no-speech limit
        #expect(s.poll())
        #expect(speech.calls.last == "earcon done")
        clock.advance(2)
        s.squeeze()                                            // and a later squeeze starts a fresh one
        #expect(s.listening)
    }

    @Test func squeezeJustAfterItEndedByItselfIsTheStop() {
        let pipeline = MicPipeline(mode: .pushToTalk), speech = MockSpeech(), clock = TestClock()
        let s = SqueezeToTalk(pipeline: pipeline, speech: speech, clock: { clock.now })
        feed(pipeline, 20)
        s.squeeze()
        feed(pipeline, 60)                                     // the gate ends it; the app tick has not polled yet
        s.squeeze()                                            // the user's "stop" arrives a moment late
        #expect(!s.listening)
        #expect(speech.calls.filter { $0 == "earcon done" }.count == 1)
        clock.advance(0.5)
        s.squeeze()
        #expect(!s.listening)                                  // still inside the late-stop window
        clock.advance(1)
        s.squeeze()
        #expect(s.listening)
    }

    @Test func squeezeRightAfterAStopSqueezeStartsAgain() {
        let pipeline = MicPipeline(mode: .pushToTalk), speech = MockSpeech(), clock = TestClock()
        let s = SqueezeToTalk(pipeline: pipeline, speech: speech, clock: { clock.now })
        feed(pipeline, 20)
        s.squeeze()
        s.squeeze()
        #expect(s.poll())
        clock.advance(0.5)
        s.squeeze()                                            // the user stopped it, so no late-stop window
        #expect(s.listening)
    }

    @Test func alwaysListeningIgnoresSqueezes() {
        let pipeline = MicPipeline(mode: .alwaysListening), speech = MockSpeech()
        let s = SqueezeToTalk(pipeline: pipeline, speech: speech)
        s.squeeze()
        #expect(!s.listening)
        #expect(speech.calls.isEmpty)
    }

    @Test func debounceCountsCloseCommandsOnce() {
        var d = SqueezeDebounce(window: 0.4)
        let accepted = [10, 10.2, 10.5].map { d.accept(now: $0) }
        #expect(accepted == [true, false, true])
    }

    @Test func earconsRiseAndFall() {
        let up = CueSynth.samples(Earcon.listening), down = CueSynth.samples(Earcon.done)
        #expect(up.count == down.count && up.count > 0)
        #expect(up != down)
        #expect(abs(up.map { abs($0) }.max()! - 0.35) < 0.001)
    }
}
