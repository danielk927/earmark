import Foundation
import simd
@testable import EarmarkCore

/// Renders what the receiver's microphone hears (B2.1): every beacon's chirp with clock offsets and
/// drift, travel time at the true speed of sound, Doppler, echoes, body blocking and white noise.
struct AudioSynth {
    enum Echoes {
        case none
        /// Two reflections per beacon from fixed mirror-image sources, `minDelay`–2.5 ms late at the calibration
        /// point (the spec says 0.3 ms) and 0.3–1.2× the unblocked direct level. Their delays and phases
        /// change smoothly as the receiver moves.
        case room(minDelay: Double)
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
        var minDelay = 0.0003
        if case .room(let d) = options.echoes { minDelay = d }
        let images = world.config.beacons.indices.map { k in Self.imageSources(beacon: k, world: world, minDelay: minDelay, rng: &rng) }
        if options.chirps {
            // The path's clock starts at the first sample.
            for emission in world.emissions(duration: path.duration) {
                let k = emission.beacon
                let arrival = world.arrival(emittedAt: emission.time, beacon: k, path: path)
                arrivals.append(Arrival(beacon: k, time: t0 + arrival))
                let p = path.position(arrival)
                let level = Self.amplitudeAt2m * 2 / max(world.trueDistance(beacon: k, from: p), 0.3)
                let scale = options.doppler ? 1 - world.radialVelocity(beacon: k, at: arrival, path: path) / world.speedOfSound : 1
                // The body blocks every path that arrives from behind: the direct one, and echoes whose
                // mirror image lies behind.
                let blockGain = pow(10, -15.0 / 20)
                func blocked(_ source: SIMD3<Double>) -> Bool { options.bodyBlocking && world.isBehind(source: source, at: arrival, path: path) }
                addChirp(to: &buffer, start: arrival, amplitude: blocked(SIMD3(world.config.beacons[k].position)) ? level * blockGain : level,
                         scale: scale, phase: 0)
                switch options.echoes {
                case .none:
                    break
                case .room:
                    let direct = world.trueDistance(beacon: k, from: p)
                    for image in images[k] where image.reaches(p) {
                        let delay = (simd_distance(p, image.position) - direct) / world.speedOfSound
                        addChirp(to: &buffer, start: arrival + delay, amplitude: level * image.gain * (blocked(image.position) ? blockGain : 1),
                                 scale: scale, phase: image.phase)
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

    /// A reflector: the plane through `point` with unit `normal` (pointing into the room), and the
    /// beacon's mirror image across it.
    struct ImageSource {
        let position: SIMD3<Double>
        let point: SIMD3<Double>
        let normal: SIMD3<Double>
        let gain: Double
        let phase: Double

        /// A real reflection only reaches receivers on the room side of the plane.
        func reaches(_ p: SIMD3<Double>) -> Bool { simd_dot(p - point, normal) > 0 }
    }

    /// Two reflecting planes behind or beside beacon k, each placed so its reflection arrives
    /// `minDelay`–2.5 ms after the direct path at the calibration point. Mirror images obey the triangle
    /// inequality, so an echo is never early anywhere in the room.
    static func imageSources(beacon k: Int, world: BeaconWorld, minDelay: Double, rng: inout SeededRandom) -> [ImageSource] {
        let b = SIMD3(world.config.beacons[k].position), c = world.config.calibrationPosition
        let direct = simd_distance(b, c)
        let towardRoom = simd_normalize(c - b)
        var out: [ImageSource] = []
        while out.count < 2 {
            let normal = simd_normalize(SIMD3(rng.gaussian(), rng.gaussian(), rng.gaussian()))
            guard simd_dot(normal, towardRoom) > 0.3 else { continue }    // the plane faces the room
            let excess = rng.uniform(minDelay...0.0025) * world.speedOfSound
            var lo = 0.0, hi = 5.0     // distance from the beacon back to the plane
            for _ in 0..<60 {
                let h = 0.5 * (lo + hi)
                if simd_distance(b - 2 * h * normal, c) - direct < excess { lo = h } else { hi = h }
            }
            guard lo < 4.9 else { continue }
            out.append(ImageSource(position: b - 2 * lo * normal, point: b - lo * normal, normal: normal,
                                   gain: rng.uniform(0.3...1.2), phase: rng.chance(0.5) ? 0 : .pi))
        }
        return out
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
