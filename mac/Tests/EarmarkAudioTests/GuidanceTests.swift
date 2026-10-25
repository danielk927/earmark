import EarmarkAudio
import simd
import Testing

@Suite struct GuidanceCurveTests {
    @Test func endpoints() {
        #expect(Guidance.pingInterval(errorDeg: 0) == 0.15)
        #expect(Guidance.pingInterval(errorDeg: 9.9) == 0.15)
        #expect(Guidance.pingInterval(errorDeg: -5) == 0.15)
        #expect(Guidance.pingInterval(errorDeg: 90) == 0.9)
        #expect(Guidance.pingInterval(errorDeg: -135) == 0.9)
        #expect(Guidance.pingInterval(errorDeg: 180) == 0.9)
    }

    @Test func monotonicAndSmooth() {
        var prev = Guidance.pingInterval(errorDeg: 0)
        var maxStep = 0.0
        for tenth in 1...1_800 {
            let v = Guidance.pingInterval(errorDeg: Double(tenth) / 10)
            #expect(v >= prev)
            maxStep = max(maxStep, v - prev)
            prev = v
        }
        #expect(maxStep < 0.003)  // no jumps: at most ~3 ms per 0.1 deg
        let mid = Guidance.pingInterval(errorDeg: 50)
        #expect(abs(mid - 0.525) < 1e-9)  // smoothstep midpoint
    }

    @Test func symmetricInSign() {
        for e in stride(from: 0.0, through: 180, by: 7.5) {
            #expect(Guidance.pingInterval(errorDeg: e) == Guidance.pingInterval(errorDeg: -e))
        }
    }
}

@Suite struct GuidanceStateTests {
    /// Target straight ahead at 1 m, at ear level.
    let front = EarmarkPoint(0, 1, 0)

    @Test func errorIsTargetMinusHeadAndWraps() {
        #expect(Guidance.signedErrorDeg(targetAzimuthDeg: 30, headYawDeg: 0) == 30)
        #expect(Guidance.signedErrorDeg(targetAzimuthDeg: 0, headYawDeg: 30) == -30)
        #expect(Guidance.signedErrorDeg(targetAzimuthDeg: 170, headYawDeg: -170) == -20)   // across +-180
        #expect(Guidance.signedErrorDeg(targetAzimuthDeg: -170, headYawDeg: 170) == 20)
        #expect(Guidance.signedErrorDeg(targetAzimuthDeg: 0, headYawDeg: 180) == 180)
    }

    @Test func elevationDoesNotAffectError() {
        // Spot 3 sits 40 cm below ear level; facing it with a level head must still lock.
        var g = Guidance(target: EarmarkPoint(0.16, 0.58, -0.40))
        let az = g.targetAzimuthDeg
        #expect(g.targetElevationDeg < -30)
        var locked = false
        for i in 0...30 {
            let r = g.update(headYawDeg: az, now: Double(i) * 0.02)
            #expect(abs(r.state.errorDeg) < 1e-9)
            if r.events.contains(where: { if case .locked = $0 { return true } else { return false } }) { locked = true }
        }
        #expect(locked)
    }

    @Test func lockNeedsMoreThan300msUnder8Degrees() {
        var g = Guidance(target: front)
        var lockedAt: Double?
        for i in 0..<40 {
            let t = Double(i) * 0.02
            let r = g.update(headYawDeg: 5, now: t)
            if r.events.contains(.locked(errorDeg: -5)) { lockedAt = t }
        }
        let t = try! #require(lockedAt)
        #expect(t > 0.3 && t < 0.35)
    }

    @Test func lockIsResetIfErrorLeavesBeforeDwell() {
        var g = Guidance(target: front)
        _ = g.update(headYawDeg: 0, now: 0)
        _ = g.update(headYawDeg: 0, now: 0.2)
        _ = g.update(headYawDeg: 9, now: 0.25)        // leaves the 8 deg window
        let r = g.update(headYawDeg: 0, now: 0.4)    // back in, dwell restarts
        #expect(!r.state.locked)
        #expect(!g.update(headYawDeg: 0, now: 0.65).state.locked)
        #expect(g.update(headYawDeg: 0, now: 0.75).state.locked)
    }

    @Test func lockHysteresis() {
        var g = Guidance(target: front)
        for i in 0...20 { _ = g.update(headYawDeg: 0, now: Double(i) * 0.02) }
        #expect(g.locked)
        // Between 8 and 12 degrees: stays locked, no event.
        let r1 = g.update(headYawDeg: 11, now: 0.5)
        #expect(r1.state.locked && r1.events.isEmpty)
        // Beyond 12: unlocks exactly once.
        let r2 = g.update(headYawDeg: 12.5, now: 0.52)
        #expect(!r2.state.locked)
        #expect(r2.events == [.unlocked(errorDeg: -12.5)])
        #expect(g.update(headYawDeg: 20, now: 0.54).events.isEmpty)
    }

    @Test func behindDetectionWithShorterTurn() {
        // Target at 150 deg (behind, to the right): turn right.
        var g = Guidance(target: Geometry.point(azimuthDeg: 150))
        let r = g.update(headYawDeg: 0, now: 0)
        #expect(r.state.zone == .behind)
        #expect(r.events.count == 1)
        guard case .behind(let turn, let e)? = r.events.first else { Issue.record("no behind event"); return }
        #expect(turn == .right)
        #expect(abs(e - 150) < 1e-9)

        var g2 = Guidance(target: Geometry.point(azimuthDeg: -120))
        guard case .behind(let turn2, _)? = g2.update(headYawDeg: 0, now: 0).events.first else { Issue.record("no behind event"); return }
        #expect(turn2 == .left)

        // Head turned to 100 deg, target at -100: error is -200 -> wraps to +160, so turn right.
        var g3 = Guidance(target: Geometry.point(azimuthDeg: -100))
        guard case .behind(let turn3, let e3)? = g3.update(headYawDeg: 100, now: 0).events.first else { Issue.record("no behind event"); return }
        #expect(turn3 == .right)
        #expect(abs(e3 - 160) < 1e-9)
    }

    @Test func frontOnlyAfterBehindAndHysteresis() {
        var g = Guidance(target: front)
        #expect(g.update(headYawDeg: 0, now: 0).events.isEmpty)          // starts in front: no event
        let toBehind = g.update(headYawDeg: 101, now: 0.1).events
        #expect(toBehind == [.behind(turn: .left, errorDeg: -101)])
        // Jitter around 100 deg emits nothing more.
        for (i, y) in [99.0, 101, 98, 100.5, 96].enumerated() {
            #expect(g.update(headYawDeg: y, now: 0.2 + Double(i) * 0.02).events.isEmpty)
        }
        #expect(g.update(headYawDeg: 94, now: 0.5).events == [.front(errorDeg: -94)])
    }

    @Test func wrapAroundAt180() {
        // Target almost straight behind, head swings across the +-180 seam.
        var g = Guidance(target: Geometry.point(azimuthDeg: 179))
        _ = g.update(headYawDeg: 0, now: 0)
        let r = g.update(headYawDeg: -178, now: 0.02)    // head now faces just past 180 the other way
        #expect(abs(r.state.errorDeg - (-3)) < 1e-9)
        #expect(r.state.zone == .front)
        #expect(r.events == [.front(errorDeg: r.state.errorDeg)])
        #expect(Guidance.turn(forErrorDeg: 180) == .right)
        #expect(Guidance.turn(forErrorDeg: -180) == .right)   // -180 wraps to +180
    }
}

@Suite struct WalkingGuidanceTests {
    // The app keeps the listener at the origin and passes guidance the target relative to the user (`retarget`).

    @Test func relativeTargetGivesAzimuthDistanceAndProximityPing() {
        // User stands 2 m to the left of the counter mark; the jar is at (0.16, 0.58): relative target (2.16, 0).
        var g = Guidance(target: [2.16, 0, 0])
        let s = g.update(headYawDeg: 0, now: 0).state
        #expect(abs(s.targetAzimuthDeg - 90) < 1e-9)
        #expect(abs(s.errorDeg - 90) < 1e-9)
        #expect(s.turn == .right)
        #expect(abs(s.distanceM - 2.16) < 1e-9)
        #expect(s.pingIntervalSec == 0.9)                      // no locator distance: angle curve only
        var h = Guidance(target: [2.16, 0, 0])
        let near = h.update(headYawDeg: 0, now: 0, distanceM: 2.16).state
        #expect(abs(near.pingIntervalSec - 0.9 * Guidance.proximityScale(distanceM: 2.16)) < 1e-12)
        #expect(near.pingIntervalSec < 0.9)
    }

    @Test func behindAndLockComeFromTheRetargetedVector() {
        // Walked past the counter (listener beyond the jar): the jar is behind. Relative target = (0, 0.58, 0) - (0.3, 1.5, 0).
        var g = Guidance(target: [-0.3, -0.92, 0])
        let r = g.update(headYawDeg: 0, now: 0)
        #expect(r.state.zone == .behind)
        guard case .behind(let turn, _)? = r.events.first else { Issue.record("no behind event"); return }
        #expect(turn == .left)   // target at about -162 deg: the shorter turn is left

        // 3 m back, facing the jar exactly: locks after the dwell, just like seated.
        let rel = EarmarkPoint(0.16, 0.58 + 2.42, 0)
        var h = Guidance(target: rel)
        let az = Geometry.azimuthDeg(rel)
        var locked = false
        for i in 0...25 {
            let r = h.update(headYawDeg: az, now: Double(i) * 0.02)
            if r.events.contains(.locked(errorDeg: 0)) { locked = true }
        }
        #expect(locked)
    }

    @Test func retargetingMidWalkChangesTheVectorButKeepsZone() {
        var g = Guidance(target: [0, 2, 0])
        _ = g.update(headYawDeg: 0, now: 0)
        g.retarget([0, -1, 0])                                  // user walked past the target
        let r = g.update(headYawDeg: 0, now: 0.02)
        #expect(r.state.zone == .behind)
        #expect(abs(r.state.distanceM - 1) < 1e-9)
    }
}

@Suite struct GuidanceProximityTests {
    @Test func louderAndFasterAsTheUserWalksCloser() {
        #expect(Guidance.proximityGain(distanceM: nil) == 1)
        #expect(Guidance.proximityGain(distanceM: 0.3) == 1)
        #expect(abs(Guidance.proximityGain(distanceM: 4) - 0.25) < 1e-6)
        #expect(Guidance.proximityGain(distanceM: 1) > Guidance.proximityGain(distanceM: 2))
        #expect(Guidance.proximityScale(distanceM: nil) == 1)
        #expect(abs(Guidance.proximityScale(distanceM: 0) - 0.4) < 1e-9)
        #expect(Guidance.proximityScale(distanceM: 3) == 1)
        #expect(Guidance.proximityScale(distanceM: 9) == 1)
    }

    @Test func retargetKeepsTheLock() {
        var g = Guidance(target: EarmarkPoint(0, 2, 0))
        _ = g.update(headYawDeg: 0, now: 0)
        _ = g.update(headYawDeg: 0, now: 0.5)
        #expect(g.locked)
        g.retarget(EarmarkPoint(0, 1, 0))
        #expect(g.locked)
        #expect(g.target == EarmarkPoint(0, 1, 0))
    }
}
