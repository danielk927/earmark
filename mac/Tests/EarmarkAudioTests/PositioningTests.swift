import EarmarkAudio
import EarmarkContracts
import Foundation
import Testing

private func fix(_ x: Double, _ y: Double, age: Double = 0.3, q: ListenerPose.Quality = .ok) -> PositioningFix {
    PositioningFix(position: [x, y, 1.5], quality: q, source: .none, ageS: age)
}

@Suite struct PositioningTextTests {
    @Test func staleness() {
        #expect(!PositioningText.isStale(fix(0, 0, age: 2.0)))
        #expect(PositioningText.isStale(fix(0, 0, age: 2.1)))
        #expect(PositioningText.isStale(fix(0, 0, age: 0.1, q: .lost)))
        #expect(!PositioningText.isStale(fix(0, 0, q: .degraded)))
    }

    @Test func distanceIsHorizontal() throws {
        let d = try #require(PositioningText.distance(fix(0, 0), fix(0.3, 0.4)))
        #expect(abs(d - 0.5) < 1e-9)
    }

    @Test func soundInactiveLine() {
        let p = Positioning(active: .uwb, uwb: fix(1.0, 1.0), sound: fix(1.18, 1.0))
        #expect(PositioningText.inactiveLine(p) == "Sound: 0.18 m from UWB, 0.3 s old")
        #expect(PositioningText.ghost(p) != nil)
    }

    @Test func uwbInactiveLine() {
        let p = Positioning(active: .sound, uwb: fix(0, 0), sound: fix(0, 0.5))
        #expect(PositioningText.inactiveLine(p) == "UWB: 0.50 m from Sound, 0.3 s old")
    }

    @Test func missingAndStale() {
        let none = Positioning(active: .uwb, uwb: fix(0, 0), sound: nil)
        #expect(PositioningText.inactiveLine(none) == "Sound: not heard")
        #expect(PositioningText.ghost(none) == nil)
        let noUwb = Positioning(active: .sound, uwb: nil, sound: fix(0, 0))
        #expect(PositioningText.inactiveLine(noUwb) == "UWB: not tracking")
        let old = Positioning(active: .uwb, uwb: fix(0, 0), sound: fix(1, 1, age: 3.4))
        #expect(PositioningText.inactiveLine(old) == "Sound: stale, 3.4 s old")
        #expect(PositioningText.ghost(old) == nil)
        let lost = Positioning(active: .uwb, uwb: fix(0, 0), sound: fix(1, 1, q: .lost))
        #expect(PositioningText.inactiveLine(lost) == "Sound: lost, 0.3 s old")
        #expect(PositioningText.ghost(nil) == nil)
    }

    @Test func agedAddsTimeToBothFixes() throws {
        let p = Positioning(active: .uwb, uwb: fix(0, 0, age: 0.5), sound: fix(1, 1, age: 0.3))
        let a = PositioningText.aged(p, by: 1.6)
        let u = try #require(a.uwb), s = try #require(a.sound)
        #expect(abs(u.ageS - 2.1) < 1e-9)
        #expect(abs(s.ageS - 1.9) < 1e-9)
        #expect(PositioningText.ghost(a) != nil)
        #expect(PositioningText.ghost(PositioningText.aged(p, by: 1.8)) == nil)  // 2.1 s old
        #expect(PositioningText.aged(p, by: -5) == p)
        let one = Positioning(active: .sound, uwb: nil, sound: fix(0, 0, age: 1))
        #expect(PositioningText.aged(one, by: 3).uwb == nil)
    }

    @Test func staleActiveSkipsDistance() {
        let p = Positioning(active: .uwb, uwb: fix(0, 0, age: 5), sound: fix(1, 1))
        #expect(PositioningText.inactiveLine(p) == "Sound: 0.3 s old")
    }
}

@MainActor
@Suite struct PositioningCoreTests {
    @Test func storesPositioningAndSendsSelect() {
        let bus = RecordingBus()
        let core = EarmarkCore(head: MockHeadTracker(), speech: MockSpeech(), bus: bus, preferredRenderer: .mock,
                               clock: { 0 }, makeRenderer: { _ in MockRenderer() })
        core.busStateChanged(.connected)
        #expect(core.positioning == nil)
        core.handle(.positioning(Positioning(active: .sound, uwb: nil, sound: fix(0, 0))))
        #expect(core.positioning?.active == .sound)
        core.selectPositioning(.uwb)
        let sent = bus.ofType("positioning_select")
        #expect(sent.count == 1)
        if case .positioningSelect(let s)? = sent.first { #expect(s.active == .uwb) } else { Issue.record("no select") }
        #expect(BusClient.subscribeTypes.contains("positioning"))
    }
    @Test func ghostGoesStaleWithTimeSinceArrival() {
        let t = TestClock()
        let core = EarmarkCore(head: MockHeadTracker(), speech: MockSpeech(), bus: RecordingBus(), preferredRenderer: .mock,
                               clock: { t.now }, makeRenderer: { _ in MockRenderer() })
        #expect(core.agedPositioning == nil)
        core.handle(.positioning(Positioning(active: .uwb, uwb: fix(0, 0), sound: fix(1, 1))))
        #expect(core.agedPositioning?.sound?.ageS == 0.3)
        #expect(PositioningText.ghost(core.agedPositioning) != nil)
        // The hub goes quiet: the stored message never changes, but the aged view keeps getting older.
        t.advance(1.5)
        #expect(abs((core.agedPositioning?.sound?.ageS ?? 0) - 1.8) < 1e-9)
        #expect(PositioningText.ghost(core.agedPositioning) != nil)
        t.advance(1.0)
        #expect(abs((core.agedPositioning?.uwb?.ageS ?? 0) - 2.8) < 1e-9)
        #expect(PositioningText.ghost(core.agedPositioning) == nil)
        #expect(PositioningText.inactiveLine(core.agedPositioning!) == "Sound: stale, 2.8 s old")
        #expect(core.positioning?.sound?.ageS == 0.3)
        // A fresh message resets the clock.
        core.handle(.positioning(Positioning(active: .uwb, uwb: fix(0, 0), sound: fix(1, 1))))
        #expect(core.agedPositioning?.sound?.ageS == 0.3)
        #expect(PositioningText.ghost(core.agedPositioning) != nil)
    }

    @Test func tickRedrawsOncePerSecondWhileAPositioningIsHeld() {
        let t = TestClock()
        let core = EarmarkCore(head: MockHeadTracker(), speech: MockSpeech(), bus: RecordingBus(), preferredRenderer: .mock,
                               clock: { t.now }, makeRenderer: { _ in MockRenderer() })
        var redraws = 0
        core.onChange = { redraws += 1 }
        core.tick()
        #expect(redraws == 0)  // nothing held, nothing to age
        core.handle(.positioning(Positioning(active: .uwb, uwb: fix(0, 0), sound: fix(1, 1))))
        let afterArrival = redraws
        for _ in 0..<8 { t.advance(0.25); core.tick() }  // 2 s; quarter seconds are exact in binary, so no rounding drift
        #expect(redraws - afterArrival == 2)
    }
}
