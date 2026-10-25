import Accelerate
import Foundation

/// The unit-energy complex chirp template h(n) from B3.
struct ChirpTemplate {
    let real: [Float]
    let imag: [Float]

    init(sampleRate fs: Double) {
        let m = Int((Parameters.chirpDuration * fs).rounded())
        let r = Int((Parameters.fade * fs).rounded())
        let sweepRate = (Parameters.f1 - Parameters.f0) / Parameters.chirpDuration
        var w = [Double](repeating: 1, count: m)
        for n in 0..<m {
            if n < r { w[n] = 0.5 - 0.5 * cos(Double.pi * Double(n) / Double(r)) }
            else if n > m - 1 - r { w[n] = 0.5 - 0.5 * cos(Double.pi * Double(m - 1 - n) / Double(r)) }
        }
        let norm = sqrt(w.reduce(0) { $0 + $1 * $1 })
        var re = [Float](repeating: 0, count: m), im = [Float](repeating: 0, count: m)
        for n in 0..<m {
            let t = Double(n) / fs
            let phase = 2 * Double.pi * (Parameters.f0 * t + 0.5 * sweepRate * t * t)
            re[n] = Float(w[n] * cos(phase) / norm)
            im[n] = Float(w[n] * sin(phase) / norm)
        }
        real = re
        imag = im
    }

    var count: Int { real.count }
}

/// Streaming matched filter: overlap-save FFT correlation of the input with the chirp template.
/// It outputs the envelope e(p) = |c(p)| for every chirp start sample p on the sampleTime scale.
final class StreamingCorrelator {
    let templateLength: Int
    private let n = Parameters.fftSize
    private let forward: vDSP.DiscreteFourierTransform<Float>
    private let inverse: vDSP.DiscreteFourierTransform<Float>
    private let kernelReal: [Float], kernelImag: [Float]
    private var pending: [Float] = []
    private var pendingStart: Int64 = 0
    private var expectedNext: Int64?
    private var segReal: [Float], segImag: [Float], specReal: [Float], specImag: [Float], outReal: [Float], outImag: [Float]

    init(template: ChirpTemplate) {
        templateLength = template.count
        forward = try! vDSP.DiscreteFourierTransform(count: n, direction: .forward, transformType: .complexComplex, ofType: Float.self)
        inverse = try! vDSP.DiscreteFourierTransform(count: n, direction: .inverse, transformType: .complexComplex, ofType: Float.self)
        // g(k) = conj(h(M-1-k)), zero-padded to N.
        var gr = [Float](repeating: 0, count: n), gi = [Float](repeating: 0, count: n)
        let m = template.count
        for k in 0..<m {
            gr[k] = template.real[m - 1 - k]
            gi[k] = -template.imag[m - 1 - k]
        }
        var kr = [Float](repeating: 0, count: n), ki = [Float](repeating: 0, count: n)
        forward.transform(inputReal: gr, inputImaginary: gi, outputReal: &kr, outputImaginary: &ki)
        // Fold the inverse transform's 1/N scale into the kernel.
        let scale = 1 / Float(n)
        kernelReal = vDSP.multiply(scale, kr)
        kernelImag = vDSP.multiply(scale, ki)
        segReal = [Float](repeating: 0, count: n)
        segImag = [Float](repeating: 0, count: n)
        specReal = segReal; specImag = segReal; outReal = segReal; outImag = segReal
    }

    /// Feeds one block. Returns the first sample index of the new envelope values, whether the
    /// stream restarted (dropped buffers), and the values themselves.
    func push(samples: [Float], sampleTime: Int64) -> (start: Int64, restarted: Bool, envelope: [Float]) {
        var restarted = false
        if expectedNext != sampleTime {
            pending.removeAll(keepingCapacity: true)
            pendingStart = sampleTime
            restarted = expectedNext != nil
        }
        expectedNext = sampleTime + Int64(samples.count)
        pending.append(contentsOf: samples)

        let start = pendingStart
        var envelope: [Float] = []
        let m = templateLength
        while pending.count >= m {
            // Segments shorter than N are zero-padded at the end; outputs j = M-1 ..< count stay exact.
            let available = min(n, pending.count)
            pending.withUnsafeBufferPointer { src in
                segReal.withUnsafeMutableBufferPointer { dst in
                    dst.baseAddress!.update(from: src.baseAddress!, count: available)
                    if available < n { dst.baseAddress!.advanced(by: available).update(repeating: 0, count: n - available) }
                }
            }
            forward.transform(inputReal: segReal, inputImaginary: segImag, outputReal: &specReal, outputImaginary: &specImag)
            multiplyByKernel()
            inverse.transform(inputReal: specReal, inputImaginary: specImag, outputReal: &outReal, outputImaginary: &outImag)
            let produced = available - m + 1
            var magnitudes = [Float](repeating: 0, count: produced)
            outReal.withUnsafeMutableBufferPointer { re in
                outImag.withUnsafeMutableBufferPointer { im in
                    var tail = DSPSplitComplex(realp: re.baseAddress! + (m - 1), imagp: im.baseAddress! + (m - 1))
                    vDSP_zvabs(&tail, 1, &magnitudes, 1, vDSP_Length(produced))
                }
            }
            envelope.append(contentsOf: magnitudes)
            pending.removeFirst(produced)
            pendingStart += Int64(produced)
        }
        return (start, restarted, envelope)
    }

    private func multiplyByKernel() {
        specReal.withUnsafeMutableBufferPointer { sr in
            specImag.withUnsafeMutableBufferPointer { si in
                kernelReal.withUnsafeBufferPointer { kr in
                    kernelImag.withUnsafeBufferPointer { ki in
                        var a = DSPSplitComplex(realp: sr.baseAddress!, imagp: si.baseAddress!)
                        var b = DSPSplitComplex(realp: UnsafeMutablePointer(mutating: kr.baseAddress!),
                                                imagp: UnsafeMutablePointer(mutating: ki.baseAddress!))
                        vDSP_zvmul(&a, 1, &b, 1, &a, 1, vDSP_Length(n), 1)
                    }
                }
            }
        }
    }
}

/// The last few seconds of envelope values, indexed by absolute sample number.
struct EnvelopeHistory {
    private var ring: [Float]
    private(set) var validStart: Int64 = 0   // first sample of the current stream
    private(set) var end: Int64 = 0          // one past the newest sample

    init(capacity: Int) { ring = [Float](repeating: 0, count: capacity) }

    var oldest: Int64 { max(validStart, end - Int64(ring.count)) }

    mutating func restart(at sample: Int64) {
        validStart = sample
        end = sample
    }

    mutating func append(_ values: [Float]) {
        var rest = values[...]
        while !rest.isEmpty {
            let at = slot(end)
            let n = min(rest.count, ring.count - at)
            ring.replaceSubrange(at..<at + n, with: rest.prefix(n))
            rest = rest.dropFirst(n)
            end += Int64(n)
        }
    }

    /// The values for samples first...last, which must all be held.
    func values(_ first: Int64, _ last: Int64) -> [Float] {
        var out: [Float] = []
        out.reserveCapacity(Int(last - first + 1))
        var p = first
        while p <= last {
            let at = slot(p)
            let n = min(Int(last - p + 1), ring.count - at)
            out.append(contentsOf: ring[at..<at + n])
            p += Int64(n)
        }
        return out
    }

    func contains(_ p: Int64) -> Bool { p >= oldest && p < end }
    subscript(p: Int64) -> Float { ring[slot(p)] }

    private func slot(_ p: Int64) -> Int {
        let c = Int64(ring.count)
        return Int(((p % c) + c) % c)
    }
}
