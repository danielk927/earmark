import Foundation
#if canImport(Accelerate)
import Accelerate
#endif

public enum Chirp {
    public static func edges(config: ChirpConfig, falling: Bool) -> [Double] {
        let start = falling ? config.f_hi : config.f_lo
        let end = falling ? config.f_lo : config.f_hi
        let slope = (end - start) / config.duration
        let halfCycles = Int(floor((start + end) * config.duration + 1e-9))
        return (1...max(1, halfCycles)).compactMap { k in
            let time = Double(k) / (start + sqrt(start * start + slope * Double(k)))
            guard time < config.duration - 1e-12 else { return nil }
            return floor(time / 1e-7 + 0.5) * 1e-7
        }
    }
    public static func samples(config: ChirpConfig, fs: Double, falling: Bool) -> [Double] {
        let transitions = edges(config: config, falling: falling)
        var edge = 0
        // Python evaluates each sample at its center, not its leading edge.
        return (0..<Int((config.duration * fs).rounded(.toNearestOrEven))).map { i in
            while edge < transitions.count && transitions[edge] <= (Double(i) + 0.5) / fs { edge += 1 }
            return edge.isMultiple(of: 2) ? 1 : -1
        }
    }
}

struct Spectrum {
    var real: [Double]
    var imaginary: [Double]
}

public enum DSP {
    static func transform(_ input: Spectrum, inverse: Bool = false, portable: Bool = false) -> Spectrum {
        var output = input
        let count = output.real.count
        precondition(count > 0 && count.nonzeroBitCount == 1 && count == output.imaginary.count)
        #if canImport(Accelerate) && !FORCE_PORTABLE_DSP
        if !portable, let setup = vDSP_create_fftsetupD(vDSP_Length(count.trailingZeroBitCount), FFTRadix(kFFTRadix2)) {
            defer { vDSP_destroy_fftsetupD(setup) }
            output.real.withUnsafeMutableBufferPointer { real in
                output.imaginary.withUnsafeMutableBufferPointer { imaginary in
                    var split = DSPDoubleSplitComplex(realp: real.baseAddress!, imagp: imaginary.baseAddress!)
                    vDSP_fft_zipD(setup, &split, 1, vDSP_Length(count.trailingZeroBitCount), FFTDirection(inverse ? FFT_INVERSE : FFT_FORWARD))
                }
            }
        } else {
            portableTransform(&output, inverse: inverse)
        }
        #else
        portableTransform(&output, inverse: inverse)
        #endif
        if inverse {
            output.real = output.real.map { $0 / Double(count) }
            output.imaginary = output.imaginary.map { $0 / Double(count) }
        }
        return output
    }
    private static func portableTransform(_ s: inout Spectrum, inverse: Bool) {
        let n = s.real.count
        var j = 0
        for i in 1..<n {
            var bit = n >> 1
            while j & bit != 0 { j ^= bit; bit >>= 1 }
            j ^= bit
            if i < j { s.real.swapAt(i, j); s.imaginary.swapAt(i, j) }
        }
        var width = 2
        while width <= n {
            butterfly(&s, width: width, inverse: inverse)
            width *= 2
        }
    }
    private static func butterfly(_ s: inout Spectrum, width: Int, inverse: Bool) {
        let angle = (inverse ? 2.0 : -2.0) * Double.pi / Double(width)
        for start in stride(from: 0, to: s.real.count, by: width) {
            for k in 0..<(width / 2) {
                let a = start + k, b = a + width / 2
                let wr = cos(angle * Double(k)), wi = sin(angle * Double(k))
                let re = s.real[b] * wr - s.imaginary[b] * wi
                let im = s.real[b] * wi + s.imaginary[b] * wr
                s.real[b] = s.real[a] - re; s.imaginary[b] = s.imaginary[a] - im
                s.real[a] += re; s.imaginary[a] += im
            }
        }
    }
    public static func dot(_ a: [Double], _ b: [Double]) -> Double {
        precondition(a.count == b.count)
        #if canImport(Accelerate) && !FORCE_PORTABLE_DSP
        var result = 0.0
        vDSP_dotprD(a, 1, b, 1, &result, vDSP_Length(a.count))
        return result
        #else
        return zip(a, b).reduce(0) { $0 + $1.0 * $1.1 }
        #endif
    }
    public static func envelope(signal: [Double], template: [Double], fs: Double, low: Double, high: Double) -> [Double] {
        guard signal.count >= template.count, !template.isEmpty else { return [] }
        var n = 1
        while n < signal.count + template.count - 1 { n *= 2 }
        let zeros = [Double](repeating: 0, count: n)
        let s = transform(Spectrum(real: signal + Array(repeating: 0, count: n - signal.count), imaginary: zeros))
        let t = transform(Spectrum(real: template + Array(repeating: 0, count: n - template.count), imaginary: zeros))
        var product = Spectrum(real: zeros, imaginary: zeros)
        // Applying the band mask here is identical to filtering the signal before correlation.
        for k in 0...n / 2 {
            let frequency = Double(k) * fs / Double(n)
            guard frequency >= low && frequency <= high else { continue }
            let scale = k == 0 || k == n / 2 ? 1.0 : 2.0
            product.real[k] = scale * (s.real[k] * t.real[k] + s.imaginary[k] * t.imaginary[k])
            product.imaginary[k] = scale * (s.imaginary[k] * t.real[k] - s.real[k] * t.imaginary[k])
        }
        let correlation = transform(product, inverse: true)
        return (0...(signal.count - template.count)).map { hypot(correlation.real[$0], correlation.imaginary[$0]) }
    }
}

public struct Peak: Equatable, Sendable {
    public let sample: Double
    public let snr: Double
}

public enum Detection {
    static func markerCandidate(envelope: [Double], gate: Int, lookback: Int, minimumSNR: Double) -> Peak? {
        guard gate > 0, envelope.count >= 2 * gate + 3 else { return nil }
        let search = envelope[gate..<(envelope.count - gate)]
        guard let maximum = search.max(), let peak = search.firstIndex(of: maximum) else { return nil }
        return firstArrival(envelope: envelope, range: (peak - gate)..<(peak + gate + 1),
                            lookback: lookback, minimumSNR: minimumSNR)
    }
    public static func firstArrival(envelope: [Double], range: Range<Int>, lookback: Int, minimumSNR: Double) -> Peak? {
        let lower = max(1, range.lowerBound), upper = min(envelope.count - 1, range.upperBound)
        guard upper > lower else { return nil }
        let search = Array(envelope[lower..<upper])
        guard let maximum = search.max(), maximum > Double.ulpOfOne,
              let offset = search.firstIndex(of: maximum) else { return nil }
        let ordered = search.sorted()
        let mid = ordered.count / 2
        let median = ordered.count.isMultiple(of: 2) ? (ordered[mid - 1] + ordered[mid]) / 2 : ordered[mid]
        let snr = maximum / max(median, Double.ulpOfOne)
        guard snr >= minimumSNR else { return nil }
        let biggest = lower + offset
        guard let first = (max(lower, biggest - lookback)...biggest).first(where: { i in
            envelope[i] >= 0.5 * maximum && envelope[i] > envelope[i - 1] && envelope[i] >= envelope[i + 1]
        }) else { return nil }
        let a = envelope[first - 1], b = envelope[first], c = envelope[first + 1]
        let denominator = a - 2 * b + c
        let delta = denominator != 0 ? max(-0.5, min(0.5, 0.5 * (a - c) / denominator)) : 0
        return Peak(sample: Double(first) + delta, snr: snr)
    }
}
