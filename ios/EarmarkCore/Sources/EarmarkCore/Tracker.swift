import Foundation
import simd

/// Constant-velocity extended Kalman filter on ranges, with batch recovery (B5).
struct Tracker {
    private(set) var x = [Double](repeating: 0, count: 6)     // [p; v]
    private(set) var P = [Double](repeating: 0, count: 36)    // row-major 6×6
    private(set) var tLast: Double
    private(set) var status: TrackStatus = .tracking
    private(set) var accepted = 0
    private(set) var rejected = 0
    private(set) var recoveries = 0

    private let beacons: [SIMD3<Double>]
    private let timings: [BeaconTiming]
    private let c: Double
    private let kappa: Double
    private let receiverHeight: Double?
    private var lastAcceptedTime: Double
    private var consecutiveRejections = 0
    private var recoveringSince: Double?
    private var lastGoodPosition: SIMD3<Double>
    private var latestRanges: [(range: Double, time: Double)?]

    init(start: SIMD3<Double>, time: Double, beacons: [SIMD3<Double>], timings: [BeaconTiming],
         speedOfSound: Double, kappa: Double, receiverHeight: Double?) {
        self.beacons = beacons
        self.timings = timings
        self.c = speedOfSound
        self.kappa = kappa
        self.receiverHeight = receiverHeight
        tLast = time
        lastAcceptedTime = time
        lastGoodPosition = start
        latestRanges = Array(repeating: nil, count: beacons.count)
        reset(position: start, positionSigma: Parameters.initialPositionSigma, velocitySigma: Parameters.initialVelocitySigma)
    }

    var position: SIMD3<Double> { SIMD3(x[0], x[1], x[2]) }
    var velocity: SIMD3<Double> { SIMD3(x[3], x[4], x[5]) }
    var uncertainty: Double { (P[0] + P[7] + P[14]).squareRoot() }

    /// p + v·(t − t_last), without changing the filter. Extrapolation is capped at the no-update
    /// timeout so a stale velocity can't carry the position across the room.
    func state(at t: Double) -> TrackState {
        let dt = min(t - tLast, Parameters.noUpdateTimeout)
        return TrackState(time: t, position: position + velocity * dt, velocity: velocity, uncertainty: uncertainty, status: status)
    }

    /// Measured range for a detection (B5), or nil for an unknown beacon.
    func measuredRange(_ detection: Detection) -> Double {
        timings[detection.beacon].range(arrival: detection.arrivalTime, speedOfSound: c)
    }

    /// Feeds one detection. Returns its measured range and whether the filter accepted it.
    @discardableResult
    mutating func update(_ detection: Detection) -> (range: Double, accepted: Bool) {
        let k = detection.beacon, t = detection.arrivalTime
        let r = measuredRange(detection)
        latestRanges[k] = (r, t)
        predict(to: t)

        let b = beacons[k]
        let p = position, v = velocity
        let rho = max(simd_distance(p, b), 1e-6)
        let u = (p - b) / rho
        let rdot = simd_dot(u, v)
        let hPos = u + kappa * (v - rdot * u) / rho
        let hVel = kappa * u
        let H = [hPos.x, hPos.y, hPos.z, hVel.x, hVel.y, hVel.z]
        let noise = c * timings[k].sigma
        let R = noise * noise + Parameters.rangeFloor * Parameters.rangeFloor
        let y = r - (rho + kappa * rdot)

        let gated = status == .tracking
        let S = quadratic(H) + R
        let accept = !gated || !(y * y / S > Parameters.gateChiSquare && abs(y) > Parameters.gateMinInnovation)
        if accept {
            scalarUpdate(H: H, innovation: y, R: R)
            if let height = receiverHeight {
                scalarUpdate(H: [0, 0, 1, 0, 0, 0], innovation: height - x[2], R: Parameters.heightSigma * Parameters.heightSigma)
            }
            accepted += 1
            consecutiveRejections = 0
            lastAcceptedTime = t
            if status == .tracking { lastGoodPosition = position }
        } else {
            rejected += 1
            consecutiveRejections += 1
        }
        tick(now: t)
        if status != .tracking { attemptRecovery(now: t) }
        return (r, accept)
    }

    /// Time-based checks: recovery triggers and the lost timer.
    mutating func tick(now: Double) {
        if status == .tracking,
           now - lastAcceptedTime > Parameters.noUpdateTimeout
            || consecutiveRejections >= Parameters.rejectionsBeforeRecovery
            || uncertainty > Parameters.uncertaintyLimit {
            status = .recovering
            recoveringSince = now
        }
        if status == .recovering, let since = recoveringSince, now - since > Parameters.lostAfter {
            status = .lost
        }
    }

    /// Test hook: moves the filter's position without telling it.
    mutating func displace(by offset: SIMD3<Double>) {
        x[0] += offset.x; x[1] += offset.y; x[2] += offset.z
    }

    // MARK: Filter steps

    private mutating func reset(position p: SIMD3<Double>, positionSigma: Double, velocitySigma: Double) {
        x = [p.x, p.y, p.z, 0, 0, 0]
        P = [Double](repeating: 0, count: 36)
        for i in 0..<3 {
            P[i * 7] = positionSigma * positionSigma
            P[(i + 3) * 7] = velocitySigma * velocitySigma
        }
    }

    private mutating func predict(to t: Double) {
        let dt = max(0, t - tLast)
        tLast = max(tLast, t)
        guard dt > 0 else { return }
        for i in 0..<3 { x[i] += dt * x[i + 3] }
        // P ← F·P·Fᵀ, with F = [[I, dt·I], [0, I]]: add dt × velocity rows, then dt × velocity columns.
        for i in 0..<3 { for j in 0..<6 { P[i * 6 + j] += dt * P[(i + 3) * 6 + j] } }
        for i in 0..<6 { for j in 0..<3 { P[i * 6 + j] += dt * P[i * 6 + j + 3] } }
        let q = Parameters.accelerationSigma * Parameters.accelerationSigma
        let dt2 = dt * dt
        for i in 0..<3 {
            P[i * 6 + i] += dt2 * dt2 / 4 * q
            P[i * 6 + i + 3] += dt2 * dt / 2 * q
            P[(i + 3) * 6 + i] += dt2 * dt / 2 * q
            P[(i + 3) * 6 + i + 3] += dt2 * q
        }
    }

    private func quadratic(_ H: [Double]) -> Double {
        var s = 0.0
        for i in 0..<6 { for j in 0..<6 { s += H[i] * P[i * 6 + j] * H[j] } }
        return s
    }

    private mutating func scalarUpdate(H: [Double], innovation y: Double, R: Double) {
        var PH = [Double](repeating: 0, count: 6)
        for i in 0..<6 { for j in 0..<6 { PH[i] += P[i * 6 + j] * H[j] } }
        let S = zip(H, PH).reduce(0) { $0 + $1.0 * $1.1 } + R
        let K = PH.map { $0 / S }
        for i in 0..<6 { x[i] += K[i] * y }
        // P ← (I − K·H)·P = P − K·(Hᵀ·P), and Hᵀ·P = (P·H)ᵀ because P is symmetric.
        for i in 0..<6 { for j in 0..<6 { P[i * 6 + j] -= K[i] * PH[j] } }
        for i in 0..<6 {
            for j in (i + 1)..<6 {
                let m = 0.5 * (P[i * 6 + j] + P[j * 6 + i])
                P[i * 6 + j] = m
                P[j * 6 + i] = m
            }
        }
    }

    // MARK: Recovery

    private mutating func attemptRecovery(now: Double) {
        guard let solution = batchSolve(now: now), solution.rms < Parameters.recoveryAcceptRMS else { return }
        reset(position: solution.position, positionSigma: Parameters.recoveryPositionSigma, velocitySigma: Parameters.recoveryVelocitySigma)
        status = .tracking
        recoveringSince = nil
        recoveries += 1
        consecutiveRejections = 0
        lastAcceptedTime = now
        lastGoodPosition = solution.position
    }

    /// Least-squares position from the latest fresh range per beacon, trying every 3-beacon subset too
    /// when 4 ranges are fresh. A subset is only tried if it has more ranges than unknowns; an exactly
    /// determined subset always fits with zero residual and would win regardless of its quality.
    func batchSolve(now: Double) -> (position: SIMD3<Double>, rms: Double)? {
        let fresh = latestRanges.indices.filter { k in
            guard let entry = latestRanges[k] else { return false }
            return now - entry.time <= Parameters.recoveryRangeAge
        }
        let unknowns = receiverHeight == nil ? 3 : 2
        var sets: [[Int]] = []
        if fresh.count > unknowns { sets.append(fresh) }
        if fresh.count == 4 && 3 > unknowns {
            for skip in fresh { sets.append(fresh.filter { $0 != skip }) }
        }
        var best: (position: SIMD3<Double>, rms: Double)?
        for set in sets {
            guard let solution = gaussNewton(set) else { continue }
            if best == nil || solution.rms < best!.rms { best = solution }
        }
        return best
    }

    private func gaussNewton(_ set: [Int]) -> (position: SIMD3<Double>, rms: Double)? {
        var p = lastGoodPosition
        if let height = receiverHeight { p.z = height }
        func residual(_ k: Int, _ p: SIMD3<Double>) -> Double { simd_distance(p, beacons[k]) - latestRanges[k]!.range }
        for _ in 0..<Parameters.recoveryIterations {
            var JtJ = simd_double3x3(0), Jtr = SIMD3<Double>(0, 0, 0)
            for k in set {
                let rho = max(simd_distance(p, beacons[k]), 1e-6)
                var u = (p - beacons[k]) / rho
                if receiverHeight != nil { u.z = 0 }
                JtJ += simd_double3x3(rows: [u * u.x, u * u.y, u * u.z])
                Jtr += u * residual(k, p)
            }
            if receiverHeight != nil { JtJ[2, 2] = 1 }   // z is held, so solve only x and y
            guard abs(JtJ.determinant) > 1e-12 else { return nil }
            p -= JtJ.inverse * Jtr
        }
        let sumSquares = set.reduce(0) { $0 + pow(residual($1, p), 2) }
        let rms = (sumSquares / Double(set.count)).squareRoot()
        return rms.isFinite ? (p, rms) : nil
    }
}
