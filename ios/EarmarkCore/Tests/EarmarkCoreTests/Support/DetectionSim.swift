import Foundation
import simd
@testable import EarmarkCore

/// Simulated detector output for tracker tests without signal processing (B2.2).
struct DetectionSim {
    struct Options {
        var timingNoiseAt2m = 20e-6        // s, scales with distance / 2 m
        var dropRate = 0.12
        var echoRate = 0.06
        var behindDropRate = 0.5
        var behindEchoRate = 0.3
        var echoDelay = 0.0003...0.0025    // s
        var kappa = Parameters.kappa       // Doppler bias in the simulated arrivals
        var seed: UInt64 = 1
        var startTime = 20.0               // audio-clock seconds at path time 0
    }

    let world: BeaconWorld
    let path: ReceiverPath
    let options: Options
    private(set) var detections: [Detection] = []

    init(config: RoomConfig, path: ReceiverPath, options: Options = Options()) {
        var rng = SeededRandom(seed: options.seed)
        world = BeaconWorld(config: config, rng: &rng)
        self.path = path
        self.options = options
        let c = world.speedOfSound
        for emission in world.emissions(duration: path.duration) {
            let k = emission.beacon
            var t = world.arrival(emittedAt: emission.time, beacon: k, path: path)
            let behind = world.isBehind(beacon: k, at: t, path: path)
            guard !rng.chance(behind ? options.behindDropRate : options.dropRate) else { continue }
            let distance = world.trueDistance(beacon: k, from: path.position(t))
            t += options.kappa * world.radialVelocity(beacon: k, at: t, path: path) / c
            t += options.timingNoiseAt2m * distance / 2 * rng.gaussian()
            let echo = rng.chance(behind ? options.behindEchoRate : options.echoRate)
            if echo { t += rng.uniform(options.echoDelay) }
            let audio = options.startTime + t
            detections.append(Detection(beacon: k, arrivalTime: audio, snrDB: echo ? 18 : 25, ambiguous: echo,
                                        wallClock: world.wallClockAtZero + t))
        }
        detections.sort { $0.arrivalTime < $1.arrivalTime }
    }

    /// True receiver position at an audio-clock time.
    func truth(at audioTime: Double) -> SIMD3<Double> { path.position(audioTime - options.startTime) }
}
