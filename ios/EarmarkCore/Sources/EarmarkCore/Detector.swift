import Accelerate
import Foundation

/// One chirp detection (B3). Internal: not part of the public API.
struct Detection {
    let beacon: Int             // index into config.beacons
    let arrivalTime: Double     // audio-clock seconds of the chirp's first sample
    let snrDB: Double
    let ambiguous: Bool
    let wallClock: Double       // Unix seconds at arrivalTime
}

/// Where the detector looks for each beacon's chirp.
enum WindowSchedule {
    /// Before calibration: wall-clock slots. `beaconForSlot[k]` is the beacon index in slot k, if any.
    case slots(beaconForSlot: [Int?])
    /// After calibration: around the predicted arrival. `range(k, t)` is |p̂(t) − B_k|.
    case predicted(calibration: Calibration, speedOfSound: Double, range: (Int, Double) -> Double)
}

/// Matched filter, noise estimate, search windows and peak choice from B3.
final class ChirpDetector {
    let sampleRate: Double
    private let correlator: StreamingCorrelator
    private var history: EnvelopeHistory
    private(set) var wallOffset: Double?        // wall clock minus audio-clock seconds, from the latest block

    private var noiseMeanSquare = 0.0
    private var noiseSamples = 0
    private var noiseCursor: Int64 = 0          // samples before this are already classified
    private var nextSlot: Int64?                // pre-calibration: next global slot number (wall / 0.125)
    private var nextCycle: [Int64?] = []        // post-calibration: next cycle number per beacon
    private var scheduleGeneration = -1

    init(sampleRate: Double) {
        self.sampleRate = sampleRate
        correlator = StreamingCorrelator(template: ChirpTemplate(sampleRate: sampleRate))
        history = EnvelopeHistory(capacity: 1 << 18)
    }

    /// Correlates one block. Touches only detector-private state, so it needs no lock.
    func ingest(_ block: AudioBlock) {
        let out = correlator.push(samples: block.samples, sampleTime: block.sampleTime)
        if out.restarted || history.end != out.start {
            history.restart(at: out.start)
            noiseCursor = out.start
        }
        history.append(out.envelope)
        wallOffset = block.wallClock - Double(block.sampleTime) / sampleRate
    }

    /// Envelope samples with complete data, as audio-clock seconds.
    var streamTime: Double { Double(history.end) / sampleRate }

    /// Evaluates every search window whose samples are all in. `generation` changes whenever the
    /// schedule changes (calibration done or invalidated), which restarts window numbering.
    func detect(schedule: WindowSchedule, generation: Int) -> [Detection] {
        guard let wallOffset else { return [] }
        if generation != scheduleGeneration {
            scheduleGeneration = generation
            nextSlot = nil
            nextCycle = []
        }
        var detections: [Detection] = []
        while let window = nextWindow(schedule, wallOffset: wallOffset) {
            if window.start < noiseCursor {         // before the stream started, in a gap, or already searched
                advance(past: window)
                continue
            }
            if window.end + 1 >= history.end { break }  // wait for the rest of the window
            updateNoise(until: window.start)
            if let peak = choosePeak(window.start, window.end) {
                let arrival = peak.position / sampleRate
                detections.append(Detection(beacon: window.beacon, arrivalTime: arrival, snrDB: peak.snrDB,
                                            ambiguous: peak.ambiguous, wallClock: arrival + wallOffset))
            }
            noiseCursor = window.end + 1
            advance(past: window)
        }
        return detections
    }

    // MARK: Windows

    private struct Window {
        let beacon: Int
        let key: Int64          // global slot (pre-calibration) or cycle number (post-calibration)
        let start: Int64        // first sample, inclusive
        let end: Int64          // last sample, inclusive
    }

    private func samples(from t0: Double, to t1: Double) -> (Int64, Int64) {
        (Int64((t0 * sampleRate).rounded(.up)), Int64((t1 * sampleRate).rounded(.down)))
    }

    private func nextWindow(_ schedule: WindowSchedule, wallOffset: Double) -> Window? {
        let cursorTime = Double(noiseCursor) / sampleRate
        switch schedule {
        case .slots(let beaconForSlot):
            guard beaconForSlot.contains(where: { $0 != nil }) else { return nil }
            let slotsPerCycle = Int64((Parameters.cycle / Parameters.slotSpacing).rounded())
            let cursorSlot = Int64(((cursorTime + wallOffset + Parameters.preCalWindowBefore) / Parameters.slotSpacing).rounded(.down))
            // Start fresh, or resynchronize after the wall clock jumped ahead.
            if nextSlot == nil || nextSlot! < cursorSlot - slotsPerCycle { nextSlot = cursorSlot }
            var g = nextSlot!
            while true {
                let slot = Int(((g % slotsPerCycle) + slotsPerCycle) % slotsPerCycle)
                if slot < beaconForSlot.count, let beacon = beaconForSlot[slot] {
                    let center = Double(g) * Parameters.slotSpacing - wallOffset
                    let (s, e) = samples(from: center - Parameters.preCalWindowBefore, to: center + Parameters.preCalWindowAfter)
                    return Window(beacon: beacon, key: g, start: s, end: e)
                }
                g += 1
            }

        case .predicted(let calibration, let c, let range):
            if nextCycle.count != calibration.beacons.count {
                nextCycle = Array(repeating: nil, count: calibration.beacons.count)
            }
            var best: Window?
            for (k, timing) in calibration.beacons.enumerated() {
                let cursorCycle = Int64(((cursorTime - timing.a) / timing.b).rounded(.down))
                if nextCycle[k] == nil || nextCycle[k]! < cursorCycle - 1 { nextCycle[k] = cursorCycle }
                let n = nextCycle[k]!
                let nominal = timing.a + timing.b * Double(n)
                let predicted = nominal + (range(k, nominal) - timing.d) / c
                let half = Parameters.postCalWindowHalfWidth
                let (s, e) = samples(from: predicted - half, to: predicted + half)
                if best == nil || s < best!.start { best = Window(beacon: k, key: n, start: s, end: e) }
            }
            return best
        }
    }

    private func advance(past window: Window) {
        if nextCycle.isEmpty { nextSlot = window.key + 1 } else { nextCycle[window.beacon] = window.key + 1 }
    }

    // MARK: Noise and peaks

    private func updateNoise(until stop: Int64) {
        let alphaFloor = 1 / (Parameters.noiseTimeConstant * sampleRate)
        let first = max(noiseCursor, history.oldest), last = min(stop, history.end) - 1
        guard first <= last else { return }
        let values = history.values(first, last)
        var meanSquare = noiseMeanSquare, count = noiseSamples
        values.withUnsafeBufferPointer { e in
            for v in e {
                count += 1
                // Warm start: a plain mean until the exponential average has enough history.
                meanSquare += max(1 / Double(count), alphaFloor) * (Double(v * v) - meanSquare)
            }
        }
        noiseMeanSquare = meanSquare
        noiseSamples = count
    }

    private func choosePeak(_ start: Int64, _ end: Int64) -> (position: Double, snrDB: Double, ambiguous: Bool)? {
        guard Double(noiseSamples) >= Parameters.noiseWarmup * sampleRate, noiseMeanSquare > 0 else { return nil }
        let noiseRMS = noiseMeanSquare.squareRoot()
        let first = max(start, history.oldest)
        guard first <= end else { return nil }

        // e[i] is sample first − 1 + i: one sample of context on each side of the window.
        let hasBefore = history.contains(first - 1)
        var e = history.values(hasBefore ? first - 1 : first, end + 1)
        if !hasBefore { e.insert(0, at: 0) }
        let count = e.count - 2

        var emax: Float = 0
        var imax: vDSP_Length = 0
        e.withUnsafeBufferPointer { b in vDSP_maxvi(b.baseAddress! + 1, 1, &emax, &imax, vDSP_Length(count)) }
        let minPeak = Float(noiseRMS * pow(10, Parameters.minSNRdB / 20))
        guard emax >= minPeak else { return nil }

        // Echo defense: the earliest local maximum that is at least half the window maximum.
        let threshold = max(Float(Parameters.leadingEdgeRatio) * emax, minPeak)
        let chosen: Int? = e.withUnsafeBufferPointer { b in
            for i in 1...count where b[i] >= threshold && b[i] >= b[i - 1] && b[i] > b[i + 1] { return i }
            return nil
        }
        guard let i = chosen else { return nil }

        let em = Double(e[i - 1]), e0 = Double(e[i]), ep = Double(e[i + 1])
        let denominator = em - 2 * e0 + ep
        var delta = denominator != 0 ? 0.5 * (em - ep) / denominator : 0
        if abs(delta) >= 0.5 { delta = 0 }
        let ambiguous = Double(abs(Int(imax) + 1 - i)) > Parameters.ambiguityGap * sampleRate
        return (Double(first - 1 + Int64(i)) + delta, 20 * log10(e0 / noiseRMS), ambiguous)
    }
}
