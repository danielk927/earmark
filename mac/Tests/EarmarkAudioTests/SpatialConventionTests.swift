import AVFAudio
import EarmarkAudio
import Foundation
import simd
import Testing

// Coordinate mapping and offline-rendered sign conventions, using the production renderer graph.

@Suite struct CoordinateMappingTests {
    @Test func earmarkToAVAudioMapping() {
        let p = Geometry.avPoint(EarmarkPoint(0.16, 0.58, -0.3))
        #expect(p.x == Float(0.16))
        #expect(p.y == Float(-0.3))     // Earmark +z up -> AV +y up
        #expect(p.z == Float(-0.58))    // Earmark +y forward -> AV -z forward
    }

    @Test func mappingIsAProperRotation() {
        // Columns are the images of the Earmark basis vectors.
        func v(_ p: AVAudio3DPoint) -> SIMD3<Double> { SIMD3(Double(p.x), Double(p.y), Double(p.z)) }
        let m = simd_double3x3(columns: (v(Geometry.avPoint([1, 0, 0])), v(Geometry.avPoint([0, 1, 0])), v(Geometry.avPoint([0, 0, 1]))))
        #expect(abs(m.determinant - 1) < 1e-12)
    }

    @Test func azimuthAndElevation() {
        #expect(Geometry.azimuthDeg([0, 1, 0]) == 0)
        #expect(abs(Geometry.azimuthDeg([1, 0, 0]) - 90) < 1e-9)
        #expect(abs(Geometry.azimuthDeg([-1, 0, 0]) + 90) < 1e-9)
        #expect(abs(abs(Geometry.azimuthDeg([0, -1, 0])) - 180) < 1e-9)
        #expect(abs(Geometry.azimuthDeg([0.16, 0.58, 0]) - 15.42) < 0.05)   // spot 3 "center right"
        #expect(abs(Geometry.elevationDeg([0, 1, -1]) + 45) < 1e-9)
        let p = Geometry.point(azimuthDeg: -45, elevationDeg: 10, distance: 2)
        #expect(abs(Geometry.azimuthDeg(p) + 45) < 1e-9)
        #expect(abs(Geometry.elevationDeg(p) - 10) < 1e-9)
    }

    @Test func listenerRelativeAzimuthAndDistance() {
        let target = EarmarkPoint(0.16, 0.58, 0)            // spot 3
        // From the origin: unchanged.
        #expect(Geometry.azimuthDeg(target, from: .zero) == Geometry.azimuthDeg(target))
        #expect(Geometry.horizontalDistance(target, from: .zero) == Geometry.horizontalDistance(target))
        // From 2 m back, nearly straight ahead and 2.58 m away.
        let back = EarmarkPoint(0, -2, 0)
        #expect(abs(Geometry.azimuthDeg(target, from: back) - atan2(0.16, 2.58) * 180 / .pi) < 1e-9)
        #expect(abs(Geometry.horizontalDistance(target, from: back) - (0.16 * 0.16 + 2.58 * 2.58).squareRoot()) < 1e-12)
        // Standing past the target's right side: it is to the left.
        #expect(abs(Geometry.azimuthDeg(target, from: [1.16, 0.58, 0]) + 90) < 1e-9)
        // Behind: the counter seen from beyond it.
        #expect(abs(abs(Geometry.azimuthDeg([0, 0, 0], from: [0, 1, 0])) - 180) < 1e-9)
        // Height difference does not change the horizontal distance; elevation is relative too.
        #expect(Geometry.horizontalDistance([0, 1, -0.4], from: [0, 0, 0]) == 1)
        #expect(abs(Geometry.elevationDeg([0, 1, -1], from: [0, 0, -1])) < 1e-9)
    }

    @Test func wrapAndClock() {
        #expect(Angles.wrapDeg(190) == -170)
        #expect(Angles.wrapDeg(-180) == 180)
        #expect(Angles.wrapDeg(540) == 180)
        #expect(Angles.wrapDeg(-190) == 170)
        #expect(Geometry.clockHour(azimuthDeg: 0) == 12)
        #expect(Geometry.clockHour(azimuthDeg: 90) == 3)
        #expect(Geometry.clockHour(azimuthDeg: -60) == 10)
        #expect(Geometry.clockHour(azimuthDeg: 180) == 6)
    }

    @Test func coreMotionSignChain() {
        // Head turns LEFT -> CoreMotion yaw positive (right-hand rule about +Z up) -> Earmark yaw negative.
        #expect(HeadSigns.earmarkYawDeg(coreMotionYawRad: .pi / 2) == -90)
        #expect(HeadSigns.earmarkPitchDeg(coreMotionPitchRad: .pi / 6) > 29.99)
    }

    @Test func phaseListenerTransform() {
        func forward(_ m: simd_float4x4) -> SIMD3<Float> { let f = m * SIMD4<Float>(0, 0, -1, 0); return SIMD3(f.x, f.y, f.z) }
        let right = forward(PHASECueRenderer.listenerTransform(yawDeg: 90, pitchDeg: 0))
        #expect(abs(right.x - 1) < 1e-5 && abs(right.z) < 1e-5)        // yaw +90 (turned right) faces +x
        let up = forward(PHASECueRenderer.listenerTransform(yawDeg: 0, pitchDeg: 30))
        #expect(abs(up.y - 0.5) < 1e-5)                                  // pitch +30 looks up
        let src = PHASECueRenderer.sourceTransform([0.16, 0.58, 0])
        #expect(src.columns.3 == SIMD4<Float>(0.16, 0, -0.58, 1))
        // Listener position goes in the translation column, mapped like any point; rotation is unchanged.
        let moved = PHASECueRenderer.listenerTransform(yawDeg: 90, pitchDeg: 0, position: [0.5, -2, 0])
        #expect(moved.columns.3 == SIMD4<Float>(0.5, 0, 2, 1))
        let f = forward(moved)
        #expect(abs(f.x - 1) < 1e-5 && abs(f.z) < 1e-5)
    }

    @Test func stereoPanIsExaggeratedAndPointsTheShorterWay() {
        #expect(AVAudioCueRenderer.exaggeratedPan(relativeAzimuthDeg: 0) == 0)
        #expect(AVAudioCueRenderer.exaggeratedPan(relativeAzimuthDeg: 45) == 1)
        #expect(AVAudioCueRenderer.exaggeratedPan(relativeAzimuthDeg: -20) < -0.4)
        #expect(AVAudioCueRenderer.exaggeratedPan(relativeAzimuthDeg: 150) == 1)
        #expect(AVAudioCueRenderer.exaggeratedPan(relativeAzimuthDeg: -150) == -1)
    }
}

/// Renders through the production AVAudioCueRenderer graph offline and returns right-minus-left level in dB.
private func rightMinusLeftDB(kind: RendererKind, target: EarmarkPoint, headYaw: Double, listener: EarmarkPoint = .zero,
                              source: (AVAudioFormat) -> AVAudioPCMBuffer, loops: Bool = true) throws -> Double {
    let stereo = AVAudioFormat(standardFormatWithSampleRate: 48_000, channels: 2)!
    let r = AVAudioCueRenderer(kind: kind, offlineRenderFormat: stereo)
    try r.start()
    r.setTarget(target)
    r.setListener(yawDeg: headYaw, pitchDeg: 0)
    r.setListener(position: listener)
    r.scheduleForTest(source(PCM.monoFloat(48_000)), loops: loops)
    _ = try r.renderOffline(frames: 8_192)               // settle
    let out = try r.renderOffline(frames: 48_000)
    let l = PCM.floatSamples(out, channel: 0).reduce(0.0) { $0 + Double($1 * $1) }
    let rr = PCM.floatSamples(out, channel: 1).reduce(0.0) { $0 + Double($1 * $1) }
    r.stop()
    return 10 * log10(rr / max(l, 1e-12))
}

private func noise(_ f: AVAudioFormat) -> AVAudioPCMBuffer {
    var state: UInt32 = 1
    let samples: [Float] = (0..<48_000).map { _ in
        state = state &* 1_664_525 &+ 1_013_904_223
        return (Float(state >> 8) / Float(1 << 24) - 0.5) * 0.5
    }
    return PCM.floatBuffer(samples, format: f)
}

/// The production cue repeated to fill one second (ping every 100 ms).
private func pingTrain(_ timbre: PingTimbre) -> (AVAudioFormat) -> AVAudioPCMBuffer {
    { f in
        let one = CueSynth.samples(.ping, timbre: timbre, sampleRate: f.sampleRate)
        var s = [Float](repeating: 0, count: 4_800)
        s.replaceSubrange(0..<one.count, with: one)
        return PCM.floatBuffer(s, format: f)
    }
}

@Suite struct OfflineRenderConventionTests {
    static let spatialKinds: [RendererKind] = [.avaudioHRTFHQ, .avaudioAuto]

    @Test(arguments: spatialKinds)
    func plusXTargetIsLouderInTheRightEar(kind: RendererKind) throws {
        #expect(try rightMinusLeftDB(kind: kind, target: [1, 0, 0], headYaw: 0, source: noise) > 6)
        #expect(try rightMinusLeftDB(kind: kind, target: [-1, 0, 0], headYaw: 0, source: noise) < -6)
    }

    @Test(arguments: spatialKinds)
    func headTurnedLeftPutsAFrontTargetInTheRightEar(kind: RendererKind) throws {
        #expect(try rightMinusLeftDB(kind: kind, target: [0, 1, 0], headYaw: -90, source: noise) > 6)
    }

    @Test(arguments: spatialKinds)
    func headTurnedRightPutsAFrontTargetInTheLeftEar(kind: RendererKind) throws {
        #expect(try rightMinusLeftDB(kind: kind, target: [0, 1, 0], headYaw: 90, source: noise) < -6)
    }

    @Test(arguments: spatialKinds)
    func frontTargetIsCentered(kind: RendererKind) throws {
        #expect(abs(try rightMinusLeftDB(kind: kind, target: [0, 1, 0], headYaw: 0, source: noise)) < 2)
    }

    @Test(arguments: spatialKinds, PingTimbre.allCases)
    func productionPingIsLateralized(kind: RendererKind, timbre: PingTimbre) throws {
        #expect(try rightMinusLeftDB(kind: kind, target: [0.6, 0.2, -0.3], headYaw: 0, source: pingTrain(timbre)) > 3)
        #expect(try rightMinusLeftDB(kind: kind, target: [0, 0.6, -0.3], headYaw: 60, source: pingTrain(timbre)) < -3)
    }

    /// UWB: the listener moves, the target stays put. A front target seen from 1 m to its left is on the right.
    @Test(arguments: spatialKinds)
    func listenerPositionMovesTheScene(kind: RendererKind) throws {
        #expect(try rightMinusLeftDB(kind: kind, target: [0, 1, 0], headYaw: 0, listener: [-1, 1, 0], source: noise) > 6)
        #expect(try rightMinusLeftDB(kind: kind, target: [0, 1, 0], headYaw: 0, listener: [1, 1, 0], source: noise) < -6)
        #expect(abs(try rightMinusLeftDB(kind: kind, target: [1, 1, 0], headYaw: 0, listener: [1, -1, 0], source: noise)) < 2)
    }

    @Test func stereoPanIsListenerRelative() throws {
        #expect(try rightMinusLeftDB(kind: .stereoPan, target: [1, 1, 0], headYaw: 0, source: noise) > 20)   // 45 deg right of the origin
        #expect(abs(try rightMinusLeftDB(kind: .stereoPan, target: [1, 1, 0], headYaw: 0, listener: [1, 0, 0], source: noise)) < 1)
    }

    @Test func stereoPanFallbackFollowsTheHead() throws {
        #expect(try rightMinusLeftDB(kind: .stereoPan, target: [1, 0, 0], headYaw: 0, source: noise) > 20)
        #expect(try rightMinusLeftDB(kind: .stereoPan, target: [0, 1, 0], headYaw: -90, source: noise) > 20)
        #expect(try rightMinusLeftDB(kind: .stereoPan, target: [0, 1, 0], headYaw: 90, source: noise) < -20)
    }

    @Test func duckingLowersTheCueLayer() throws {
        let stereo = AVAudioFormat(standardFormatWithSampleRate: 48_000, channels: 2)!
        func level(ducked: Bool) throws -> Double {
            let r = AVAudioCueRenderer(kind: .avaudioHRTFHQ, offlineRenderFormat: stereo)
            try r.start()
            r.setTarget([0, 1, 0])
            r.setDucked(ducked)
            r.scheduleForTest(noise(PCM.monoFloat(48_000)), loops: true)
            let out = try r.renderOffline(frames: 24_000)
            return PCM.floatSamples(out, channel: 0).reduce(0.0) { $0 + Double($1 * $1) }
        }
        let ratio = 10 * log10(try level(ducked: true) / level(ducked: false))
        #expect(ratio < -10 && ratio > -14)
    }
}
