import Foundation

/// The chirp every phone plays. Must match services/ranging/earmark_ranging/chirp.py exactly.
public struct ChirpSpec: Equatable, Sendable {
    public var fLo: Double
    public var fHi: Double
    public var lengthMs: Double
    public var amplitude: Double
    public var direction: String  // "up" or "down"

    public init(fLo: Double = 17000, fHi: Double = 20000, lengthMs: Double = 40, amplitude: Double = 0.8, direction: String = "up") {
        self.fLo = fLo; self.fHi = fHi; self.lengthMs = lengthMs; self.amplitude = amplitude; self.direction = direction
    }

    /// One chirp as samples in -1...1, faded in and out so the speaker does not click.
    public func samples(sampleRate: Double) -> [Float] {
        let n = Int((lengthMs / 1000 * sampleRate).rounded())
        let length = lengthMs / 1000
        let (f0, f1) = direction == "up" ? (fLo, fHi) : (fHi, fLo)
        let k = (f1 - f0) / length
        let alpha = 0.4
        return (0..<n).map { i in
            let t = Double(i) / sampleRate
            let phase = 2 * Double.pi * (f0 * t + 0.5 * k * t * t)
            let x = min(max(t / length, 0), 1)
            let ramp: Double
            if x < alpha / 2 { ramp = 0.5 * (1 + cos(2 * Double.pi / alpha * (x - alpha / 2))) }
            else if x > 1 - alpha / 2 { ramp = 0.5 * (1 + cos(2 * Double.pi / alpha * (x - 1 + alpha / 2))) }
            else { ramp = 1 }
            return Float(amplitude * sin(phase) * ramp)
        }
    }

    /// A slow sweep (default 1 to 20 kHz over 10 s, 2 s of silence either side) for checking what a phone can hear.
    public static func testSweep(sampleRate: Double, fLo: Double = 1000, fHi: Double = 20000, seconds: Double = 10) -> [Float] {
        let pad = [Float](repeating: 0, count: Int(2 * sampleRate))
        let n = Int(seconds * sampleRate)
        let k = (fHi - fLo) / seconds
        let body: [Float] = (0..<n).map { i in
            let t = Double(i) / sampleRate
            let edge = min(1, min(t, seconds - t) / 0.01)
            return Float(0.9 * sin(2 * Double.pi * (fLo * t + 0.5 * k * t * t)) * edge)
        }
        return pad + body + pad
    }
}
