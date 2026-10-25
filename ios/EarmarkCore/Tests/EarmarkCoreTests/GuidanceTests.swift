import Foundation
import simd
import Testing
@testable import EarmarkCore

struct GuidanceTests {
    func guide(_ delta: SIMD3<Double>, yaw: Double) -> Guidance {
        GuidanceMath.guidance(destination: "x", delta: delta, headYaw: yaw, targetHeight: 1.2, earHeight: 1.62, valid: true)
    }

    @Test func straightAheadIsZeroAzimuth() {
        let g = guide(SIMD3(0, 2, 0), yaw: 0)
        #expect(abs(g.azimuthDeg) < 1e-9)
        #expect(abs(g.headRelative.y - 2) < 1e-12)
    }

    @Test func turningRightPutsTargetOnTheLeft() {
        let g = guide(SIMD3(0, 2, 0), yaw: .pi / 2)
        #expect(abs(g.azimuthDeg + 90) < 1e-9)
        #expect(abs(g.headRelative.x + 2) < 1e-12)   // x is right, so −2 m is to the left
    }

    @Test func targetToTheRightAndBehind() {
        #expect(abs(guide(SIMD3(1, 0, 0), yaw: 0).azimuthDeg - 90) < 1e-9)
        #expect(abs(abs(guide(SIMD3(0, -1, 0), yaw: 0).azimuthDeg) - 180) < 1e-9)
    }

    @Test func elevationModesAndHints() {
        let below = guide(SIMD3(0, 1, -1), yaw: 0)
        #expect(abs(below.elevationDeg + 45) < 1e-9)
        #expect(guide(SIMD3(0, 1.0, 0), yaw: 0).mode == .far)
        #expect(guide(SIMD3(0, 0.6, 0), yaw: 0).mode == .near)
        #expect(guide(SIMD3(0.3, 0.2, -1), yaw: 0).mode == .found)        // horizontal distance decides
        func hint(_ z: Double) -> HeightHint {
            GuidanceMath.guidance(destination: "x", delta: .zero, headYaw: 0, targetHeight: z, earHeight: 1.62, valid: true).heightHint
        }
        #expect(hint(1.60) == .high)
        #expect(hint(1.30) == .chest)
        #expect(hint(0.90) == .low)
    }

    @Test func positionIsSmoothedButYawIsImmediate() {
        var smoother = GuidanceSmoother()
        _ = smoother.smooth(SIMD3(0, 2, 0), at: 10, destination: "x", restart: false)
        // The judge's position jumps 1 m to the left (−x), so the target moves 1 m to the right (+x).
        var delta = SIMD3<Double>(0, 0, 0)
        for step in 1...25 { delta = smoother.smooth(SIMD3(1, 2, 0), at: 10 + Double(step) * 0.01, destination: "x", restart: false) }
        #expect(abs(delta.x - (1 - exp(-1))) < 1e-9)    // 63% of the way after 0.25 s
        let before = guide(delta, yaw: 0), turned = guide(delta, yaw: .pi / 2)
        #expect(abs((before.azimuthDeg - turned.azimuthDeg) - 90) < 1e-9)   // a head turn applies in full at once
    }

    @Test func engineGuidanceWhileTracking() throws {
        let config = try TestScene.load()
        let engine = try EarmarkEngine(config: config)
        #expect(engine.guidance(at: 0, headYaw: 0, destination: "keys").valid == false)
        let sim = DetectionSim(config: config, path: .hold(at: config.calibrationPosition, duration: 20, seed: 5))
        engine.startCalibration()
        engine.ingest([], streamTime: sim.options.startTime)
        engine.ingest(sim.detections.filter { $0.arrivalTime < sim.options.startTime + 15.2 }, streamTime: sim.options.startTime + 15.2)
        let report = engine.finishCalibration()
        #expect(report.ok, "\(report.problems)")
        engine.ingest(sim.detections.filter { $0.arrivalTime >= sim.options.startTime + 15.2 }, streamTime: sim.options.startTime + 20)

        let t = sim.options.startTime + 20
        let g = engine.guidance(at: t, headYaw: 0, destination: "keys")       // keys at (−1.10, 0.90, 1.30)
        #expect(g.valid)
        #expect(g.azimuthDeg < -40 && g.azimuthDeg > -60)                   // ahead and to the left
        #expect(g.heightHint == .chest)
        #expect(abs(g.horizontalDistance - 1.42) < 0.1)
        #expect(engine.guidance(at: t, headYaw: 0, destination: "nowhere").valid == false)
        let d = engine.diagnostics
        #expect(d.beacons.allSatisfy { $0.detectionsLast5s > 0 && $0.lastRangeM != nil })
        #expect(d.acceptedTotal > 20)
    }
}
