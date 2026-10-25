import EarmarkAudio
import EarmarkContracts
import Foundation
import Testing

/// Bus message handling with a mock renderer and mock head tracker.
/// @MainActor because the core runs on the main thread in the app.
@MainActor
@Suite struct CoreBusTests {
    let busSink = RecordingBus()
    let speech = MockSpeech()
    let head = MockHeadTracker()
    let clock = TestClock()
    let transcriber = MockTranscriber()
    var renderers: [MockRenderer] = []
    let core: EarmarkCore
    let renderer: MockRenderer

    init() {
        let r = MockRenderer()
        renderer = r
        let c = clock
        core = EarmarkCore(head: head, speech: speech, bus: busSink, preferredRenderer: .mock,
                           clock: { c.now }, makeRenderer: { _ in r })
        core.apple = transcriber
        head.start()
        core.startAudio()
        core.busStateChanged(.connected)
    }

    /// Ticks at 50 Hz for `seconds`, optionally moving the head.
    func run(_ seconds: Double, yaw: ((Double) -> Double)? = nil) {
        let steps = Int(seconds * 50)
        for i in 0..<steps {
            clock.advance(0.02)
            if let yaw { head.setRawPose(yawDeg: yaw(Double(i) * 0.02)) }
            core.tick()
        }
    }

    @Test func guideStartSetsTargetAndStartsPings() throws {
        core.handle(example("guide_start", "01"))   // sugar at spot 3 (0.16, 0.58, 0)
        let t = try #require(renderer.target)
        #expect(t == EarmarkPoint(0.16, 0.58, 0))
        let interval = try #require(renderer.pingInterval)
        #expect(interval > 0.15 && interval < 0.3)    // ~15 deg off-axis
        #expect(renderer.repeatingCue == .ping)
        #expect(core.guide?.objectId == "sugar")
        #expect(core.guidanceMode == .spatialTracked)
    }

    @Test func guideStopStops() {
        core.handle(example("guide_start", "01"))
        core.handle(example("guide_stop", "01"))
        #expect(renderer.pingInterval == nil)
        #expect(renderer.target == nil)
        #expect(core.guide == nil)
        run(0.5)
        #expect(renderer.pingInterval == nil)          // ticks do not restart pings
    }

    @Test func resetStopsGuidanceSpeechAndRestoresCartesia() {
        core.handle(example("guide_start", "01"))
        core.handle(example("stt_mode", "01"))         // apple
        core.handle(example("speak_text", "01"))
        core.handle(bus(#"{"type":"reset","t":1}"#))
        #expect(core.guide == nil)
        #expect(renderer.pingInterval == nil)
        #expect(speech.calls.contains("stopAll"))
        #expect(core.sttEngine == .cartesia)
        #expect(transcriber.log.contains("cancel"))
    }

    @Test func sttModeSwitchesEngines() {
        let chunk = [Int16](repeating: 100, count: 1_600)
        func utterance() { core.ingestGate(.began); core.ingestGate(.audio(chunk)); core.ingestGate(.audio(chunk)); core.ingestGate(.ended) }

        utterance()
        #expect(busSink.ofType("mic_audio").count == 2)
        #expect(transcriber.appended == 0)
        if case .micAudio(let m)? = busSink.ofType("mic_audio").last {
            #expect(m.sampleRate == 16_000 && m.encoding == "pcm_s16le" && m.seq == 1)
            #expect(Data(base64Encoded: m.chunkB64)?.count == 3_200)
        }

        core.handle(example("stt_mode", "01"))          // engine apple
        #expect(core.micRoute == .apple)
        utterance()
        #expect(busSink.ofType("mic_audio").count == 2)  // nothing more streamed to Cartesia
        #expect(transcriber.appended == 2)
        #expect(transcriber.log == ["begin", "end"])

        core.handle(example("stt_mode", "02"))          // back to cartesia
        utterance()
        #expect(busSink.ofType("mic_audio").count == 4)

        core.appleTranscript("where's the sugar", final: true)
        guard case .transcript(let tr)? = busSink.ofType("transcript").last else { Issue.record("no transcript"); return }
        #expect(tr.source == .apple && tr.isFinal && tr.text == "where's the sugar")
    }

    @Test func busDownRoutesMicToAppleSpeech() {
        core.busStateChanged(.disconnected("test"))
        #expect(core.micRoute == .apple)
        #expect(core.effectiveSttEngine == "apple")
        core.busStateChanged(.connected)
        #expect(core.micRoute == .cartesia)
    }

    @Test func behindTransitionEmitsExactlyOneGuideFeedback() {
        core.handle(example("guide_start", "01"))       // target ~15 deg right
        run(0.2)
        busSink.clear()
        // Turn the head left until the error is ~101 deg, then jitter +-4 deg so the error crosses
        // 100 deg repeatedly (but never drops under the 95 deg exit threshold).
        run(1.0) { t in -60 - 26 * min(t / 0.5, 1) + (t > 0.5 ? 4 * sin(t * 40) : 0) }
        let fb = busSink.feedback
        #expect(fb.filter { $0.event == .behind }.count == 1)
        #expect(fb.first?.event == .behind)
        #expect(fb.first?.turn == .right)                // shorter way back to the target is right
        #expect(renderer.repeatingCue == .behind)
        // Turning back emits exactly one "front".
        busSink.clear()
        run(0.6) { _ in 0 }
        #expect(busSink.feedback.filter { $0.event == .front }.count == 1)
        #expect(renderer.repeatingCue == .ping)
    }

    @Test func behindAtStartIsReportedImmediately() {
        core.handle(bus(#"{"type":"guide_start","object_id":"keys","name":"keys","target_position":[0.2,-0.8,0],"precision":"exact","utterance_id":"u1","t":1}"#))
        let fb = busSink.feedback
        #expect(fb.count == 1)
        #expect(fb.first?.event == .behind && fb.first?.turn == .right && fb.first?.objectId == "keys")
    }

    @Test func lockPlaysTheLockedToneOnce() {
        core.handle(example("guide_start", "01"))
        let az = Geometry.azimuthDeg([0.16, 0.58, 0])
        run(1.0) { _ in az + 2 }
        #expect(renderer.played.filter { $0 == .locked }.count == 1)
        #expect(busSink.feedback.filter { $0.event == .locked }.count == 1)
        #expect(renderer.pingInterval == 0.15)
    }

    @Test func headPoseIsRateLimitedTo10Hz() {
        run(1.0) { t in 30 * sin(t * 6) }
        let n = busSink.ofType("head_pose").count
        #expect(n >= 9 && n <= 11)
    }

    @Test func statusCarriesTheRequiredInfoKeys() throws {
        run(0.1)
        guard case .status(let s)? = busSink.ofType("status").last else { Issue.record("no status"); return }
        #expect(s.component == .macApp)
        let info = try #require(s.info)
        for key in ["renderer", "head_tracking", "guidance_mode", "input_device", "output_device", "output_sample_rate", "stt_engine"] {
            #expect(info[key] != nil, "missing \(key)")
        }
        #expect(info["guidance_mode"] == .string("spatial_tracked"))
        #expect(info["head_tracking"] == .string("mock"))
        // Unchanged status is not re-sent every tick (heartbeat only).
        let before = busSink.ofType("status").count
        run(2)
        #expect(busSink.ofType("status").count == before)
    }

    @Test func speechDucksTheCueLayerAndReportsPlayback() {
        speech.emit("u-1", .started)
        #expect(renderer.ducked)
        speech.emit("u-1", .finished)
        #expect(!renderer.ducked)
        let events = busSink.ofType("playback").compactMap { if case .playback(let p) = $0 { p.event } else { nil } }
        #expect(events == [.started, .finished])
    }

    @Test func speechMessagesReachTheSpeechLayerWithCaptions() {
        core.handle(example("speak", "01"))
        core.handle(example("speak_cached", "01"))
        core.handle(example("speak_text", "02"))
        #expect(speech.calls.suffix(3) == ["speak u-17 0", "cached behind_turn_right", "text u-22"])
        #expect(core.captions.filter { $0.speaker == .earmark }.count == 3)
    }

    @Test func snapshotAndStateUpdatesFeedTheMap() {
        core.handle(example("snapshot", "01"))
        #expect(core.space?.spots.count == 4)
        #expect(core.objects.contains { $0.objectId == "sugar" })
        core.handle(example("state_update", "03"))
        #expect(core.states["salt"]?.status == .held)
    }

    // MARK: Locator (listener_pose)

    func pose(_ x: Double, _ y: Double, quality: String = "ok") {
        core.handle(bus("""
        {"type":"listener_pose","position":[\(x),\(y),0],"quality":"\(quality)","beacons_heard":5,"source":"beacons","t":1}
        """))
    }

    func guideKeys() {
        core.handle(bus("""
        {"type":"guide_start","object_id":"keys","name":"keys","target_position":[0,3,1],"precision":"exact","utterance_id":"u1","t":1}
        """))
    }

    @Test func targetIsRelativeToWhereTheUserStands() throws {
        guideKeys()
        #expect(renderer.target == EarmarkPoint(0, 3, 1))   // no fix: the user is on the mat
        pose(0, 1)
        #expect(renderer.target == EarmarkPoint(0, 2, 1))
        pose(0, 1.5, quality: "lost")                        // a lost fix changes nothing
        #expect(renderer.target == EarmarkPoint(0, 2, 1))
    }

    @Test func pingsGetFasterAndLouderOnTheWayAndStopOnArrival() throws {
        guideKeys()
        pose(0, 1); run(0.1)
        let farInterval = try #require(renderer.pingInterval), farGain = renderer.proximityGain
        pose(0, 2); run(0.1)
        #expect(try #require(renderer.pingInterval) < farInterval)
        #expect(renderer.proximityGain > farGain)
        #expect(core.guide != nil)
        pose(0, 2.8); run(0.1)                               // 0.2 m away: arrived
        #expect(core.guide == nil)
        #expect(busSink.feedback.contains { $0.event == .arrived && $0.objectId == "keys" })
        #expect(renderer.played.contains(.locked))
    }

    @Test func noFixForFiveSecondsMeansBackOnTheMat() throws {
        pose(0, 1)
        guideKeys()
        run(5.5)
        #expect(renderer.target == EarmarkPoint(0, 3, 1))
    }
}

@MainActor
@Suite struct FallbackLadderTests {
    @Test func failingSpatialRendererFallsBackToStereoThenSpeechOnly() {
        let head = MockHeadTracker()
        head.start()
        var made: [RendererKind] = []
        let core = EarmarkCore(head: head, speech: MockSpeech(), bus: RecordingBus(), preferredRenderer: .avaudioHRTFHQ,
                               makeRenderer: { kind in
                                   made.append(kind)
                                   let r = MockRenderer(); r.failOnStart = true; return r
                               })
        core.startAudio()
        #expect(made == [.avaudioHRTFHQ, .stereoPan])
        #expect(core.renderer == nil)
        #expect(core.guidanceMode == .speechOnly)
        #expect(core.rendererFailures.count == 2)
    }

    @Test func lostHeadTrackingFixesYawAtZero() {
        let head = MockHeadTracker()
        head.start()
        let r = MockRenderer()
        let core = EarmarkCore(head: head, speech: MockSpeech(), bus: RecordingBus(), preferredRenderer: .mock, makeRenderer: { _ in r })
        core.startAudio()
        head.setRawPose(yawDeg: 40)
        #expect(r.yawDeg == 40)
        head.stop()                                        // tracking lost
        #expect(core.guidanceMode == .spatialUntracked)
        #expect(r.yawDeg == 0)
        head.setRawPose(yawDeg: 70)                        // samples no longer move the listener
        #expect(r.yawDeg == 0)
    }

    @Test func modeResolution() {
        #expect(GuidanceMode.resolve(renderer: .avaudioAuto, headTracking: true) == .spatialTracked)
        #expect(GuidanceMode.resolve(renderer: .phaseManual, headTracking: false) == .spatialUntracked)
        #expect(GuidanceMode.resolve(renderer: .stereoPan, headTracking: true) == .stereoPan)
        #expect(GuidanceMode.resolve(renderer: nil, headTracking: true) == .speechOnly)
    }
}
