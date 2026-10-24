import AVFAudio
import Foundation

/// The cues a renderer can play. All are mono and spatialized at the target position.
public enum Cue: String, CaseIterable, Sendable {
    /// Short bright blip; repeats at the guidance interval.
    case ping
    /// Lower, muffled sound used instead of the ping while the target is behind the listener.
    case behind
    /// Distinct two-note rising chime, played once when the head locks onto the target.
    case locked
}

/// Ping timbre. Pure tones localize poorly front/back because HRTF spectral cues need broadband
/// energy (docs/vendor-notes/apple-spatial-audio.md section 3), so the spike makes this switchable.
public enum PingTimbre: String, CaseIterable, Sendable, Identifiable {
    case tone
    case broadband
    public var id: String { rawValue }
    public var displayName: String {
        switch self {
        case .tone: "Tone"
        case .broadband: "Broadband"
        }
    }
}

/// Procedural cue synthesis. Deterministic (seeded noise), mono Float32 samples.
public enum CueSynth {
    public static let sampleRate: Double = 48_000

    public static func samples(_ cue: Cue, timbre: PingTimbre = .tone, sampleRate sr: Double = sampleRate) -> [Float] {
        switch cue {
        case .ping: timbre == .tone ? toneBlip(sr: sr) : broadbandBlip(sr: sr)
        case .behind: behindThud(sr: sr)
        case .locked: lockedChime(sr: sr)
        }
    }

    public static func buffer(_ cue: Cue, timbre: PingTimbre = .tone, format: AVAudioFormat) -> AVAudioPCMBuffer {
        PCM.floatBuffer(samples(cue, timbre: timbre, sampleRate: format.sampleRate), format: format)
    }

    /// 1 kHz sine with 2nd and 3rd harmonics, 4 ms raised-cosine attack, ~18 ms exponential decay, 70 ms total.
    /// Short so Bluetooth latency does not smear it.
    static func toneBlip(sr: Double, hz: Double = 1_000, ms: Double = 70) -> [Float] {
        let n = Int(sr * ms / 1000), attack = 0.004 * sr
        var out = [Float](repeating: 0, count: n)
        for i in 0..<n {
            let t = Double(i) / sr
            let env = Double(i) < attack ? 0.5 - 0.5 * cos(.pi * Double(i) / attack) : exp(-(t - 0.004) / 0.018)
            let w = 2 * Double.pi * hz * t
            out[i] = Float(env * (sin(w) + 0.3 * sin(2 * w) + 0.12 * sin(3 * w)))
        }
        return normalized(out, peak: 0.5)
    }

    /// The tone blip plus a high-passed noise burst (energy from ~500 Hz to 16 kHz) for front/back spectral cues.
    static func broadbandBlip(sr: Double, ms: Double = 70) -> [Float] {
        let tone = toneBlip(sr: sr, ms: ms)
        let n = tone.count, attack = 0.002 * sr
        var rng = SeededNoise(seed: 0xEA12)
        var out = [Float](repeating: 0, count: n)
        var prevIn: Double = 0, prevOut: Double = 0
        let rc = 1 / (2 * Double.pi * 500), dt = 1 / sr, k = rc / (rc + dt)  // one-pole high-pass at 500 Hz
        for i in 0..<n {
            let t = Double(i) / sr
            let env = Double(i) < attack ? Double(i) / attack : exp(-(t - 0.002) / 0.014)
            let x = rng.next()
            let hp = k * (prevOut + x - prevIn)
            prevIn = x; prevOut = hp
            out[i] = Float(0.55 * Double(tone[i]) / 0.5 + 0.9 * env * hp)
        }
        return normalized(out, peak: 0.5)
    }

    /// Two rising notes (E6 then A6), 90 ms each with a 10 ms gap.
    static func lockedChime(sr: Double) -> [Float] {
        func note(_ hz: Double, ms: Double) -> [Float] {
            let n = Int(sr * ms / 1000), attack = 0.006 * sr
            return (0..<n).map { i in
                let t = Double(i) / sr
                let env = Double(i) < attack ? 0.5 - 0.5 * cos(.pi * Double(i) / attack) : exp(-(t - 0.006) / 0.045)
                return Float(env * (sin(2 * .pi * hz * t) + 0.2 * sin(4 * .pi * hz * t)))
            }
        }
        let gap = [Float](repeating: 0, count: Int(sr * 0.010))
        return normalized(note(1_318.5, ms: 90) + gap + note(1_760, ms: 130), peak: 0.45)
    }

    /// Low, muffled thud: 300 -> 220 Hz glide, soft 15 ms attack, 150 ms decay, low-passed.
    static func behindThud(sr: Double, ms: Double = 190) -> [Float] {
        let n = Int(sr * ms / 1000), attack = 0.015 * sr
        var out = [Float](repeating: 0, count: n)
        var phase = 0.0, lp = 0.0
        let alpha = 1 - exp(-2 * Double.pi * 900 / sr)  // one-pole low-pass at 900 Hz
        for i in 0..<n {
            let t = Double(i) / sr
            let hz = 300 - 80 * min(t / (ms / 1000), 1)
            phase += 2 * .pi * hz / sr
            let env = Double(i) < attack ? 0.5 - 0.5 * cos(.pi * Double(i) / attack) : exp(-(t - 0.015) / 0.06)
            let raw = sin(phase) + 0.45 * sin(2 * phase) + 0.2 * sin(3 * phase)
            lp += alpha * (raw - lp)
            out[i] = Float(env * lp)
        }
        return normalized(out, peak: 0.6)
    }

    static func normalized(_ x: [Float], peak: Float) -> [Float] {
        let m = x.reduce(Float(0)) { max($0, abs($1)) }
        guard m > 0 else { return x }
        let g = peak / m
        return x.map { $0 * g }
    }
}

/// Small deterministic uniform noise source in [-1, 1).
struct SeededNoise {
    var state: UInt32
    init(seed: UInt32) { state = seed }
    mutating func next() -> Double {
        state = state &* 1_664_525 &+ 1_013_904_223
        return Double(state >> 8) / Double(1 << 23) - 1
    }
}
