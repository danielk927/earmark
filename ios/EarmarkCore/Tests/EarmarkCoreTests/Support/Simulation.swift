import Foundation
import simd
@testable import EarmarkCore

/// Deterministic random numbers (SplitMix64) so every test run sees the same data.
struct SeededRandom: RandomNumberGenerator {
    private var state: UInt64
    init(seed: UInt64) { state = seed &+ 0x9E37_79B9_7F4A_7C15 }

    mutating func next() -> UInt64 {
        state &+= 0x9E37_79B9_7F4A_7C15
        var z = state
        z = (z ^ (z >> 30)) &* 0xBF58_476D_1CE4_E5B9
        z = (z ^ (z >> 27)) &* 0x94D0_49BB_1331_11EB
        return z ^ (z >> 31)
    }

    mutating func uniform(_ range: ClosedRange<Double>) -> Double { Double.random(in: range, using: &self) }
    mutating func chance(_ p: Double) -> Bool { uniform(0...1) < p }

    mutating func gaussian() -> Double {
        let u1 = max(uniform(0...1), 1e-300), u2 = uniform(0...1)
        return (-2 * log(u1)).squareRoot() * cos(2 * .pi * u2)
    }
}

/// A receiver path: where the microphone is, and the walking velocity used to decide which
/// beacons the body blocks (hand jiggle excluded).
struct ReceiverPath {
    let position: (Double) -> SIMD3<Double>
    let walkVelocity: (Double) -> SIMD3<Double>
    let duration: Double

    func velocity(at t: Double) -> SIMD3<Double> {
        let h = 1e-4
        return (position(t + h) - position(t - h)) / (2 * h)
    }

    static func still(at p: SIMD3<Double>, duration: Double) -> ReceiverPath {
        ReceiverPath(position: { _ in p }, walkVelocity: { _ in .zero }, duration: duration)
    }

    /// The tracker-test walk from B2: still, walk, search, walk, walk, with hand jiggle throughout.
    static func specWalk(from start: SIMD3<Double>, seed: UInt64, jiggle: Bool = true) -> ReceiverPath {
        let waypoints: [(SIMD3<Double>, Double, Double)] = [   // (target, seconds to get there, seconds to stay)
            (start, 0, 15),
            (SIMD3(1.0, 0.8, 1.1), 6, 6),
            (SIMD3(-1.0, 0.9, 1.3), 8, 0),
            (SIMD3(-1.0, -1.0, 1.2), 8, 0),
        ]
        var legs: [(t0: Double, t1: Double, a: SIMD3<Double>, b: SIMD3<Double>)] = []
        var t = 0.0, here = start
        for (target, move, stay) in waypoints {
            if move > 0 { legs.append((t, t + move, here, target)); t += move; here = target }
            if stay > 0 { legs.append((t, t + stay, here, here)); t += stay }
        }
        let total = t
        var rng = SeededRandom(seed: seed)
        // About 6 cm peak to peak on each axis, at 0.7–1.1 Hz.
        let shake = (0..<3).map { _ in (f: rng.uniform(0.7...1.1), phase: rng.uniform(0...(2 * .pi))) }
        let amplitude = jiggle ? 0.03 : 0

        func walk(_ t: Double) -> SIMD3<Double> {
            guard let leg = legs.first(where: { t < $0.t1 }) ?? legs.last else { return start }
            let u = min(max((t - leg.t0) / (leg.t1 - leg.t0), 0), 1)
            let s = 0.5 - 0.5 * cos(.pi * u)          // smooth start and stop
            return leg.a + (leg.b - leg.a) * s
        }
        return ReceiverPath(
            position: { t in
                let j = SIMD3((0..<3).map { amplitude * sin(2 * .pi * shake[$0].f * t + shake[$0].phase) })
                return walk(t) + j
            },
            walkVelocity: { t in (walk(t + 1e-4) - walk(t - 1e-4)) / 2e-4 },
            duration: total)
    }
}

extension SIMD3 where Scalar == Double {
    init(_ values: [Double]) { self.init(values[0], values[1], values[2]) }
}

/// Beacon clocks and propagation shared by both simulators.
struct BeaconWorld {
    let config: RoomConfig
    let wallClockAtZero: Double
    let offsets: [Double]           // s, each beacon's clock error
    let drifts: [Double]            // fractional (1e-6 = 1 ppm)
    let speedOfSound: Double        // true value, from a temperature off by up to ±1 °C

    init(config: RoomConfig, rng: inout SeededRandom, wallClockAtZero: Double = 1_792_882_334.512) {
        self.config = config
        self.wallClockAtZero = wallClockAtZero
        offsets = config.beacons.map { _ in rng.uniform(-0.030...0.030) }
        drifts = config.beacons.map { _ in rng.uniform(-30e-6...30e-6) }
        speedOfSound = Parameters.speedOfSound(temperatureC: config.temperatureC + rng.uniform(-1...1))
    }

    struct Emission { let beacon: Int; let time: Double }

    /// Every chirp start in audio-clock seconds within [0, duration].
    func emissions(duration: Double) -> [Emission] {
        var out: [Emission] = []
        let firstCycle = Int64((wallClockAtZero / Parameters.cycle).rounded(.down)) - 1
        let lastCycle = Int64(((wallClockAtZero + duration) / Parameters.cycle).rounded(.up))
        for (k, beacon) in config.beacons.enumerated() {
            for m in firstCycle...lastCycle {
                // Wall-clock slot time relative to t = 0 (subtracted first to keep precision).
                let nominal = Double(m - firstCycle) * Parameters.cycle
                    + (Double(firstCycle) * Parameters.cycle - wallClockAtZero) + Double(beacon.slot) * Parameters.slotSpacing
                let t = nominal + offsets[k] + drifts[k] * nominal
                if t >= 0 && t < duration { out.append(Emission(beacon: k, time: t)) }
            }
        }
        return out.sorted { $0.time < $1.time }
    }

    /// Arrival time at a moving receiver for a chirp emitted at `t`.
    func arrival(emittedAt t: Double, beacon k: Int, path: ReceiverPath) -> Double {
        let b = SIMD3(config.beacons[k].position)
        var ta = t + simd_distance(path.position(t), b) / speedOfSound
        for _ in 0..<3 { ta = t + simd_distance(path.position(ta), b) / speedOfSound }
        return ta
    }

    /// Radial velocity away from beacon k.
    func radialVelocity(beacon k: Int, at t: Double, path: ReceiverPath) -> Double {
        let p = path.position(t), b = SIMD3(config.beacons[k].position)
        return simd_dot(simd_normalize(p - b), path.velocity(at: t))
    }

    /// True when the judge walks away from beacon k, so the body is between it and the receiver.
    func isBehind(beacon k: Int, at t: Double, path: ReceiverPath) -> Bool {
        let v = path.walkVelocity(t)
        guard simd_length(v) > 0.05 else { return false }
        return simd_dot(SIMD3(config.beacons[k].position) - path.position(t), v) < 0
    }

    func trueDistance(beacon k: Int, from p: SIMD3<Double>) -> Double {
        simd_distance(p, SIMD3(config.beacons[k].position))
    }
}
