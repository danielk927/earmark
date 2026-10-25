import Foundation

public struct SampleAnchor: Codable, Sendable {
    public let sample: Int64
    public let unix: Double
    public let fs: Double
    public init(sample: Int64, unix: Double, fs: Double) { self.sample = sample; self.unix = unix; self.fs = fs }
    public func time(at sampleIndex: Double) -> Double { unix + (sampleIndex - Double(sample)) / fs }
}

public enum CycleState: String, Sendable { case acquiring, confirming, locked }

struct MarkerTracker {
    let cycle: Double
    private(set) var period: Double
    private(set) var last: Double?
    private(set) var locked = false
    private(set) var misses = 0

    init(cycle: Double) { self.cycle = cycle; period = cycle }
    var expected: Double? { last.map { $0 + period * Double(misses + 1) } }
    var state: CycleState { locked ? .locked : (last == nil ? .acquiring : .confirming) }
    mutating func observe(_ marker: Double?) -> Bool {
        guard let marker else { miss(); return false }
        guard let expected, let last else { self.last = marker; misses = 0; return false }
        guard locked || abs(marker - expected) <= 0.001 else { miss(); return false }
        if misses == 0 {
            let ratio = min(1.0001, max(0.9999, (marker - last) / cycle))
            period = 0.95 * period + 0.05 * ratio * cycle
        }
        self.last = marker; locked = true; misses = 0
        return true
    }
    private mutating func miss() {
        misses += 1
        if misses >= 3 { self = MarkerTracker(cycle: cycle) }
    }
}

public final class LocatorPipeline {
    public let config: LocatorConfig
    public var state: CycleState { tracker.state }
    public private(set) var droppedBuffers = 0
    public private(set) var latestDetections: [Arrival] = []
    public private(set) var lastMic: Vector3?
    private var samples: [Double] = []
    private var firstSample: Int64 = 0
    private var expectedSample: Int64?
    private var tracker: MarkerTracker
    private var pending: [Double] = []
    private var filter = PositionFilter()
    private var templates: [String: [Double]]

    public init(config: LocatorConfig, templates: [String: [Double]] = [:]) throws {
        try config.validate()
        self.config = config
        self.templates = templates
        tracker = MarkerTracker(cycle: config.chirp.cycle)
    }
    public func reset() {
        samples.removeAll(keepingCapacity: true); expectedSample = nil
        tracker = MarkerTracker(cycle: config.chirp.cycle); pending.removeAll(keepingCapacity: true)
        filter = PositionFilter(); lastMic = nil; latestDetections = []
    }
    public func setTemplate(beacon: String, samples: [Double]) throws {
        guard config.beacons.contains(where: { $0.id == beacon }), !samples.isEmpty, samples.allSatisfy(\.isFinite) else {
            throw LocatorError.invalid("Invalid captured template")
        }
        templates[beacon] = samples
    }
    public func append(_ incoming: [Double], anchor: SampleAnchor) -> [Fix] {
        guard !incoming.isEmpty, incoming.allSatisfy(\.isFinite), anchor.fs == config.fs else { return [] }
        if let expectedSample, expectedSample != anchor.sample { reset(); droppedBuffers += 1 }
        if samples.isEmpty { firstSample = anchor.sample }
        expectedSample = anchor.sample + Int64(incoming.count)
        let block = max(1, Int((0.05 * config.fs).rounded(.toNearestOrEven)))
        return stride(from: 0, to: incoming.count, by: block).flatMap { offset in
            appendBlock(Array(incoming[offset..<min(incoming.count, offset + block)]), anchor: anchor)
        }
    }
    private func appendBlock(_ incoming: [Double], anchor: SampleAnchor) -> [Fix] {
        samples += incoming
        let now = Double(firstSample + Int64(samples.count)) / config.fs
        updateMarkers(now: now)
        var fixes: [Fix] = []
        let tail = Double((config.beacons.map(\.slot).max() ?? 4) + 1) * config.chirp.slot
        while let marker = pending.first, now >= marker + tail {
            pending.removeFirst()
            if let fix = processCycle(marker: marker, anchor: anchor) { fixes.append(fix) }
        }
        let capacity = Int((max(1.0, config.chirp.cycle * 2) * config.fs).rounded(.toNearestOrEven))
        if samples.count > capacity {
            let remove = samples.count - capacity
            samples.removeFirst(remove); firstSample += Int64(remove)
        }
        return fixes
    }
    private func template(_ id: String) -> [Double] {
        templates[id] ?? Chirp.samples(config: config.chirp, fs: config.fs, falling: id == "B1")
    }
    private func detect(_ id: String, start: Double, end: Double, minimum: Double) -> Peak? {
        let waveform = template(id)
        let margin = Int((0.005 * config.fs).rounded(.toNearestOrEven))
        let lower = max(0, Int(floor(start * config.fs)) - Int(firstSample) - margin)
        let upper = min(samples.count, Int(ceil(end * config.fs)) - Int(firstSample) + waveform.count + margin)
        guard upper > lower, end > start,
              end * config.fs + Double(waveform.count) <= Double(firstSample) + Double(samples.count) else { return nil }
        let envelope = DSP.envelope(signal: Array(samples[lower..<upper]), template: waveform, fs: config.fs,
                                    low: config.chirp.f_lo - 300, high: config.chirp.f_hi + 300)
        let origin = Double(firstSample) + Double(lower)
        guard let peak = Detection.firstArrival(envelope: envelope,
            range: Int(start * config.fs - origin)..<Int(end * config.fs - origin),
            lookback: Int((config.lookback_ms * config.fs / 1000).rounded(.toNearestOrEven)), minimumSNR: minimum) else { return nil }
        return Peak(sample: origin + peak.sample, snr: peak.snr)
    }
    private func acquire() {
        let begin = max(0, samples.count - Int((0.4 * config.fs).rounded(.toNearestOrEven)))
        let envelope = DSP.envelope(signal: Array(samples[begin...]), template: template("B1"), fs: config.fs,
                                    low: config.chirp.f_lo - 300, high: config.chirp.f_hi + 300)
        let gate = Int((config.gate_ms * config.fs / 1000).rounded(.toNearestOrEven))
        let lookback = Int((config.lookback_ms * config.fs / 1000).rounded(.toNearestOrEven))
        if let peak = Detection.markerCandidate(envelope: envelope, gate: gate, lookback: lookback, minimumSNR: config.snr_acquire) {
            _ = tracker.observe((Double(firstSample) + Double(begin) + peak.sample) / config.fs)
        }
    }
    private func updateMarkers(now: Double) {
        guard let expected = tracker.expected else { acquire(); return }
        let gate = config.gate_ms / 1000
        guard now >= expected + gate + Double(template("B1").count) / config.fs + 0.005 else { return }
        let marker = detect("B1", start: expected - gate, end: expected + gate, minimum: config.snr_acquire)
        let wasLocked = tracker.locked
        let arrival = marker.map { $0.sample / config.fs }
        let confirmed = tracker.observe(arrival)
        if confirmed || wasLocked { pending.append(arrival ?? expected) }
    }
    private func detectBeacon(_ beacon: Beacon, tau: Double, position: Vector3) -> Arrival? {
        let slot = tau + Double(beacon.slot) * config.chirp.slot
        var arrival = slot + (position - beacon.position).norm / config.speedOfSound
        if lastMic == nil {
            // Wide slots nominate a candidate; only the configured gate determines SNR.
            guard let candidate = detect(beacon.id, start: slot, end: slot + config.chirp.slot - 0.005, minimum: 0) else { return nil }
            arrival = candidate.sample / config.fs
        }
        let gate = config.gate_ms / 1000
        guard let peak = detect(beacon.id, start: arrival - gate, end: arrival + gate, minimum: config.snr_min) else { return nil }
        return Arrival(beacon: beacon.id, arrival: peak.sample / config.fs, snr: peak.snr)
    }
    private func processCycle(marker: Double, anchor: SampleAnchor) -> Fix? {
        let initial = lastMic ?? Vector3(0, 0, config.height.mean)
        guard let b1 = config.beacons.first(where: { $0.id == "B1" }) else { return nil }
        let tau = marker - Double(b1.slot) * config.chirp.slot - (initial - b1.position).norm / config.speedOfSound
        let detections = config.beacons.compactMap { detectBeacon($0, tau: tau, position: initial) }
        latestDetections = detections
        guard let solution = PositionSolver.solve(arrivals: detections, config: config, initial: lastMic) else { return nil }
        let meanSample = solution.used.map(\.arrival).reduce(0, +) / Double(solution.used.count) * config.fs
        let t = anchor.time(at: meanSample)
        let mic = filter.update(solution.position, time: t, quality: solution.quality, config: config)
        lastMic = mic
        return Fix(t: t, sampleIndex: meanSample, mic: mic, ear: mic + config.earOffset, quality: solution.quality,
                   used: solution.used.map(\.beacon), detections: detections, residual: solution.rmsMilliseconds)
    }
}
