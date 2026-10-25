import Foundation
import simd
@testable import EarmarkCore

/// Renders what the receiver's microphone hears (B2.1): every beacon's chirp with clock offsets and
/// drift, travel time at the true speed of sound, Doppler, echoes, body blocking and white noise.
struct AudioSynth {
    enum Echoes {
        case none
        /// Two reflections per beacon from fixed image sources, 0.3–2.5 ms late at the calibration point
        /// and 0.3–1.2× the unblocked direct level. Their delays change smoothly as the receiver moves.
        case room
        /// One copy per chirp at a fixed delay and level relative to the direct path. A pure delayed
        /// copy has phase 0; nil picks a random carrier phase per chirp (a reflection's phase changes
        /// a full turn for every 53 µs of extra delay, so in a real room it is effectively random).
        case fixed(delay: Double, gainDB: Double, phase: Double?)
    }

    struct Options {
        var sampleRate = 48_000.0
        /// Input SNR: chirp RMS at 2 m from the beacon versus noise RMS, over the full band.
        var snrDB = 30.0
        var chirps = true
        var echoes = Echoes.none
        var bodyBlocking = false
        var doppler = true
        var seed: UInt64 = 1
        var firstSampleTime: Int64 = 1_000_000
    }

    struct Arrival { let beacon: Int; let time: Double }

    let world: BeaconWorld
    let path: ReceiverPath
    let options: Options
    /// True direct-path arrivals (audio-clock seconds of each chirp's first sample).
    private(set) var arrivals: [Arrival] = []
    private(set) var samples: [Float] = []

    private static let amplitudeAt2m = 0.05

    init(config: RoomConfig, path: ReceiverPath, options: Options = Options()) {
        var rng = SeededRandom(seed: options.seed)
        world = BeaconWorld(config: config, rng: &rng)
        self.path = path
        self.options = options
        render(rng: &rng)
    }

    var sampleRate: Double { options.sampleRate }
    /// Audio-clock seconds of samples[0].
    var startTime: Double { Double(options.firstSampleTime) / sampleRate }

    private mutating func render(rng: inout SeededRandom) {
        let fs = sampleRate
        let count = Int(path.duration * fs)
        var buffer = [Double](repeating: 0, count: count)
        let t0 = startTime
        let images = world.config.beacons.indices.map { k in Self.imageSources(beacon: k, world: world, rng: &rng) }
        if options.chirps {
            // The path's clock starts at the first sample.
            for emission in world.emissions(duration: path.duration) {
                let k = emission.beacon
                let arrival = world.arrival(emittedAt: emission.time, beacon: k, path: path)
                arrivals.append(Arrival(beacon: k, time: t0 + arrival))
                let p = path.position(arrival)
                let level = Self.amplitudeAt2m * 2 / max(world.trueDistance(beacon: k, from: p), 0.3)
                let scale = options.doppler ? 1 - world.radialVelocity(beacon: k, at: arrival, path: path) / world.speedOfSound : 1
                let blocked = options.bodyBlocking && world.isBehind(beacon: k, at: arrival, path: path)
                addChirp(to: &buffer, start: arrival, amplitude: blocked ? level * pow(10, -15.0 / 20) : level, scale: scale, phase: 0)
                switch options.echoes {
                case .none:
                    break
                case .room:
                    let direct = world.trueDistance(beacon: k, from: p)
                    for image in images[k] {
                        let delay = (simd_distance(p, image.position) - direct) / world.speedOfSound
                        addChirp(to: &buffer, start: arrival + delay, amplitude: level * image.gain, scale: scale, phase: image.phase)
                    }
                case .fixed(let delay, let gainDB, let phase):
                    addChirp(to: &buffer, start: arrival + delay, amplitude: level * pow(10, gainDB / 20),
                             scale: scale, phase: phase ?? rng.uniform(0...(2 * .pi)))
                }
            }
        }
        let noiseRMS = Self.amplitudeAt2m / 2.squareRoot() / pow(10, options.snrDB / 20)
        samples = buffer.map { Float($0 + noiseRMS * rng.gaussian()) }
    }

    struct ImageSource { let position: SIMD3<Double>; let gain: Double; let phase: Double }

    /// Two mirror-image sources for beacon k, placed so their extra path at the calibration point is
    /// 0.3–2.5 ms of travel.
    static func imageSources(beacon k: Int, world: BeaconWorld, rng: inout SeededRandom) -> [ImageSource] {
        let b = SIMD3(world.config.beacons[k].position), c = world.config.calibrationPosition
        let direct = simd_distance(b, c)
        return (0..<2).map { _ in
            let excess = rng.uniform(0.0003...0.0025) * world.speedOfSound
            let direction = simd_normalize(SIMD3(rng.gaussian(), rng.gaussian(), rng.gaussian()))
            var lo = 0.0, hi = 10.0        // excess path grows with distance along `direction`
            for _ in 0..<60 {
                let mid = 0.5 * (lo + hi)
                if simd_distance(b + direction * mid, c) - direct < excess { lo = mid } else { hi = mid }
            }
            return ImageSource(position: b + direction * lo, gain: rng.uniform(0.3...1.2), phase: rng.chance(0.5) ? 0 : .pi)
        }
    }

    /// Adds one chirp starting at `start` (seconds from the first sample), time-scaled by `scale`.
    private func addChirp(to buffer: inout [Double], start: Double, amplitude: Double, scale: Double, phase: Double) {
        let fs = sampleRate, T = Parameters.chirpDuration, fade = Parameters.fade
        let sweep = (Parameters.f1 - Parameters.f0) / T
        let first = max(Int((start * fs).rounded(.up)), 0)
        let last = min(Int(((start + T / scale) * fs).rounded(.down)), buffer.count - 1)
        guard first <= last else { return }
        for n in first...last {
            let tau = (Double(n) / fs - start) * scale
            guard tau >= 0 && tau < T else { continue }
            let w = tau < fade ? 0.5 - 0.5 * cos(.pi * tau / fade) : tau > T - fade ? 0.5 - 0.5 * cos(.pi * (T - tau) / fade) : 1
            buffer[n] += amplitude * w * cos(2 * .pi * (Parameters.f0 * tau + 0.5 * sweep * tau * tau) + phase)
        }
    }

    /// The rendered audio as 4096-sample blocks. `dropping` lists block numbers to leave out,
    /// as if the capture queue lost those buffers.
    func blocks(size: Int = 4096, dropping: Set<Int> = []) -> [AudioBlock] {
        stride(from: 0, to: samples.count, by: size).enumerated().compactMap { index, offset in
            guard !dropping.contains(index) else { return nil }
            let slice = Array(samples[offset..<min(offset + size, samples.count)])
            return AudioBlock(samples: slice, sampleRate: sampleRate, sampleTime: options.firstSampleTime + Int64(offset),
                              wallClock: world.wallClockAtZero + Double(offset) / sampleRate)
        }
    }
}
