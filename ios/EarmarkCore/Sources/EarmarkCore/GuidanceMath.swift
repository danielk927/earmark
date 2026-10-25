import Foundation
import simd

/// Exponential smoothing of the room-frame head-to-target vector (B6 step 2).
struct GuidanceSmoother {
    private var destination: String?
    private var vector = SIMD3<Double>(0, 0, 0)
    private var time = 0.0

    /// Starts over on the first call and whenever the destination changes or the caller says so.
    mutating func smooth(_ raw: SIMD3<Double>, at t: Double, destination: String, restart: Bool) -> SIMD3<Double> {
        if restart || destination != self.destination {
            self.destination = destination
            vector = raw
            time = t
            return vector
        }
        let dt = t - time
        if dt > 0 {
            vector += (1 - exp(-dt / Parameters.guidanceTau)) * (raw - vector)
            time = t
        }
        return vector
    }
}

enum GuidanceMath {
    /// Rotates a smoothed room-frame vector into the head frame with the current yaw ψ and fills in
    /// angles, mode and height hint (B6, C6).
    static func guidance(destination: String, delta: SIMD3<Double>, headYaw psi: Double,
                         targetHeight: Double, earHeight: Double, valid: Bool) -> Guidance {
        let forward = delta.x * sin(psi) + delta.y * cos(psi)
        let right = delta.x * cos(psi) - delta.y * sin(psi)
        let up = delta.z
        let horizontal = (delta.x * delta.x + delta.y * delta.y).squareRoot()
        let mode: GuidanceMode = horizontal > Parameters.farBeyond ? .far : horizontal < Parameters.foundWithin ? .found : .near
        let hint: HeightHint = targetHeight > earHeight - Parameters.highAboveEarMinus ? .high
            : targetHeight < earHeight - Parameters.lowBelowEarMinus ? .low : .chest
        return Guidance(destination: destination, distance: simd_length(delta), horizontalDistance: horizontal,
                        headRelative: SIMD3(right, forward, up),
                        azimuthDeg: atan2(right, forward) * 180 / .pi,
                        elevationDeg: atan2(up, horizontal) * 180 / .pi,
                        mode: mode, heightHint: hint, valid: valid)
    }
}
