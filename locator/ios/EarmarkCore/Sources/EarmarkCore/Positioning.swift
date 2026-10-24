import Foundation

public enum Quality: String, Codable, Sendable { case ok, degraded, lost }
public enum PoseSource: String, Codable, Sendable { case beacons, sim, manual, steps }

public struct Arrival: Codable, Equatable, Sendable {
    public let beacon: String
    public let arrival: Double
    public let snr: Double
    public init(beacon: String, arrival: Double, snr: Double) { self.beacon = beacon; self.arrival = arrival; self.snr = snr }
}

public struct Solution: Sendable {
    public let position: Vector3
    public let tau: Double
    public let residuals: [Double]
    public let used: [Arrival]
    public let quality: Quality
    public var rmsMilliseconds: Double { sqrt(residuals.reduce(0) { $0 + $1 * $1 } / Double(residuals.count)) * 1000 }
}

enum LinearAlgebra {
    static func solve(_ matrix: [[Double]], _ rhs: [Double]) -> [Double]? {
        let n = rhs.count
        var a = zip(matrix, rhs).map { $0 + [$1] }
        for k in 0..<n {
            guard let pivot = (k..<n).max(by: { abs(a[$0][k]) < abs(a[$1][k]) }), abs(a[pivot][k]) > 1e-12 else { return nil }
            a.swapAt(k, pivot)
            let divisor = a[k][k]
            for j in k...n { a[k][j] /= divisor }
            for i in 0..<n where i != k {
                let factor = a[i][k]
                for j in k...n { a[i][j] -= factor * a[k][j] }
            }
        }
        let result = a.map { $0[n] }
        return result.allSatisfy(\.isFinite) ? result : nil
    }
}

public enum PositionSolver {
    public static func solve(arrivals: [Arrival], config: LocatorConfig, initial: Vector3? = nil) -> Solution? {
        guard arrivals.count >= 3, arrivals.count <= 5,
              Set(arrivals.map(\.beacon)).count == arrivals.count,
              arrivals.allSatisfy({ arrival in arrival.arrival.isFinite && config.beacons.contains(where: { $0.id == arrival.beacon }) }) else { return nil }
        guard let result = fit(arrivals, config: config, initial: initial) else { return nil }
        if arrivals.count == 5, let worst = result.residuals.indices.max(by: { abs(result.residuals[$0]) < abs(result.residuals[$1]) }),
           abs(result.residuals[worst]) * 1000 > config.resid_max_ms {
            return accepted(fit(arrivals.enumerated().filter { $0.offset != worst }.map(\.element), config: config, initial: initial), config: config)
        }
        return accepted(result, config: config)
    }
    private static func accepted(_ result: Solution?, config: LocatorConfig) -> Solution? {
        guard let result, result.rmsMilliseconds <= config.resid_max_ms else { return nil }
        return result
    }
    private static func fit(_ arrivals: [Arrival], config: LocatorConfig, initial: Vector3?) -> Solution? {
        let beacons = arrivals.compactMap { arrival in config.beacons.first { $0.id == arrival.beacon } }
        guard beacons.count == arrivals.count else { return nil }
        var p = initial ?? Vector3(0, 0, config.height.mean)
        let c = config.speedOfSound
        let epoch = arrivals[0].arrival
        let adjusted = zip(arrivals, beacons).map { ($0.arrival - epoch - Double($1.slot) * config.chirp.slot) * c }
        var bias = zip(adjusted, beacons).map { $0 - (p - $1.position).norm }.reduce(0, +) / Double(arrivals.count)
        for _ in 0..<10 {
            guard let step = iteration(p: p, bias: bias, adjusted: adjusted, beacons: beacons, config: config) else { return nil }
            let delta = Vector3(step[0], step[1], step[2])
            p = p + delta; bias += step[3]
            if delta.norm < 0.001 { break }
        }
        guard p.values.allSatisfy(\.isFinite) else { return nil }
        let residuals = zip(adjusted, beacons).map { ($0 - bias - (p - $1.position).norm) / c }
        let rms = sqrt(residuals.reduce(0) { $0 + $1 * $1 } / Double(arrivals.count)) * 1000
        let quality: Quality = arrivals.count >= 4 && rms <= config.resid_ok_ms ? .ok : .degraded
        return Solution(position: p, tau: epoch + bias / c, residuals: residuals, used: arrivals, quality: quality)
    }
    private static func iteration(p: Vector3, bias: Double, adjusted: [Double], beacons: [Beacon], config: LocatorConfig) -> [Double]? {
        var normal = Array(repeating: Array(repeating: 0.0, count: 4), count: 4)
        var rhs = Array(repeating: 0.0, count: 4)
        for (measurement, beacon) in zip(adjusted, beacons) {
            let d = p - beacon.position, range = max(d.norm, 1e-9)
            let row = [d.x / range, d.y / range, d.z / range, 1]
            accumulate(row, residual: measurement - bias - range, weight: 1, matrix: &normal, rhs: &rhs)
        }
        // Both acoustic residuals and the height pseudo-measurement are in meters.
        let relativeWeight = pow(config.kalman_measurement_sigma_ok / config.height.sigma, 2)
        accumulate([0, 0, 1, 0], residual: config.height.mean - p.z, weight: relativeWeight, matrix: &normal, rhs: &rhs)
        return LinearAlgebra.solve(normal, rhs)
    }
    private static func accumulate(_ row: [Double], residual: Double, weight: Double, matrix: inout [[Double]], rhs: inout [Double]) {
        for i in 0..<4 {
            rhs[i] += weight * row[i] * residual
            for j in 0..<4 { matrix[i][j] += weight * row[i] * row[j] }
        }
    }
}

private struct AxisFilter {
    var position: Double
    var velocity = 0.0
    var pp = 1.0, pv = 0.0, vv = 1.0
    mutating func update(_ measurement: Double, dt: Double, acceleration: Double, sigma: Double) -> Double {
        position += velocity * dt
        let q = acceleration * acceleration
        let predictedPP = pp + 2 * dt * pv + dt * dt * vv + q * pow(dt, 4) / 4
        let predictedPV = pv + dt * vv + q * pow(dt, 3) / 2
        let predictedVV = vv + q * dt * dt
        let denominator = predictedPP + sigma * sigma
        let kp = predictedPP / denominator, kv = predictedPV / denominator
        let innovation = measurement - position
        position += kp * innovation; velocity += kv * innovation
        pp = (1 - kp) * predictedPP
        pv = (1 - kp) * predictedPV
        vv = predictedVV - kv * predictedPV
        return position
    }
}

public struct PositionFilter {
    private var axes: [AxisFilter] = []
    private var lastTime: Double?
    public init() {}
    public mutating func update(_ position: Vector3, time: Double, quality: Quality, config: LocatorConfig) -> Vector3 {
        guard let previous = lastTime, time > previous else {
            axes = position.values.map { AxisFilter(position: $0) }; lastTime = time
            return position
        }
        lastTime = time
        let sigma = quality == .ok ? config.kalman_measurement_sigma_ok : config.kalman_measurement_sigma_degraded
        let values = (0..<3).map { axes[$0].update(position.values[$0], dt: time - previous, acceleration: config.kalman_acceleration_sigma, sigma: sigma) }
        return Vector3(values[0], values[1], values[2])
    }
}

public struct Fix: Codable, Sendable {
    public let t: Double
    public let sample_index: Double
    public let mic_position: Vector3
    public let ear_position: Vector3
    public let quality: Quality
    public let beacons_used: [String]
    public let detections: [Arrival]
    public let residual_rms_ms: Double
    public init(t: Double, sampleIndex: Double, mic: Vector3, ear: Vector3, quality: Quality, used: [String], detections: [Arrival], residual: Double) {
        self.t = t; sample_index = sampleIndex; mic_position = mic; ear_position = ear
        self.quality = quality; beacons_used = used; self.detections = detections; residual_rms_ms = residual
    }
}
