import Foundation
import simd

/// The positioning engine: audio in, detections, calibration, tracking and guidance out.
///
/// `process` runs on the caller's serial capture queue. The correlation runs outside the lock;
/// everything the other calls read is guarded by `lock`, so they are safe from any thread.
public final class EarmarkEngine: EarmarkEngineProtocol {
    private let config: RoomConfig
    private let beaconPositions: [SIMD3<Double>]
    private let speedOfSound: Double
    private let kappa: Double
    private let lock = NSLock()

    // Capture queue only.
    private var detector: ChirpDetector?

    // Guarded by `lock`.
    private var status: TrackStatus = .notCalibrated
    private var calibration: Calibration?
    private var scheduleGeneration = 0
    private var tracker: Tracker?
    private var calibrationStart: Double?       // audio time of the first block after startCalibration
    private var calibrationDetections: [Detection] = []
    private var streamTime = 0.0
    private var beaconStats: [BeaconStats]
    private var processingMs = 0.0
    private var smoother = GuidanceSmoother()
    private var lastGuidanceValid = false

    private struct BeaconStats {
        var snrDB: Double?
        var rangeM: Double?
        var phase: Double?
        var accepted = false
        var ambiguous = false
        var recentTimes: [Double] = []
    }

    public convenience init(config: RoomConfig) throws {
        try self.init(config: config, kappa: Parameters.kappa)
    }

    /// `kappa` is the Doppler constant; tests set it to 0 to show the Doppler term matters.
    init(config: RoomConfig, kappa: Double) throws {
        try config.validate()
        self.config = config
        self.kappa = kappa
        beaconPositions = config.beaconPositions
        speedOfSound = config.speedOfSound
        beaconStats = Array(repeating: BeaconStats(), count: config.beacons.count)
    }

    // MARK: Audio

    public func process(_ block: AudioBlock) {
        guard !block.samples.isEmpty, block.sampleRate > 0 else { return }
        let started = DispatchTime.now().uptimeNanoseconds
        if detector?.sampleRate != block.sampleRate { detector = ChirpDetector(sampleRate: block.sampleRate) }
        let detector = detector!
        detector.ingest(block)

        lock.lock()
        defer { lock.unlock() }
        let detections = detector.detect(schedule: currentSchedule(), generation: scheduleGeneration)
        handle(detections, streamTime: detector.streamTime, dataStart: Double(block.sampleTime) / block.sampleRate)
        let ms = Double(DispatchTime.now().uptimeNanoseconds - started) / 1e6
        processingMs = processingMs == 0 ? ms : processingMs + 0.1 * (ms - processingMs)
    }

    /// Feeds detections that bypass the signal path (tests use the detection simulator this way).
    func ingest(_ detections: [Detection], streamTime: Double) {
        lock.lock()
        defer { lock.unlock() }
        handle(detections, streamTime: streamTime, dataStart: streamTime)
    }

    /// Test hook: knocks the filter's position off by `offset`.
    func displaceTrack(by offset: SIMD3<Double>) {
        lock.lock()
        defer { lock.unlock() }
        tracker?.displace(by: offset)
    }

    private func currentSchedule() -> WindowSchedule {
        if let calibration, let tracker, status != .calibrating {
            let positions = beaconPositions
            return .predicted(calibration: calibration, speedOfSound: speedOfSound) { k, t in
                simd_distance(tracker.state(at: t).position, positions[k])
            }
        }
        var beaconForSlot = [Int?](repeating: nil, count: Parameters.maxBeacons)
        for (k, beacon) in config.beacons.enumerated() { beaconForSlot[beacon.slot] = k }
        return .slots(beaconForSlot: beaconForSlot)
    }

    /// `dataStart` is the audio time of the first sample this call covers; calibration counts from there.
    private func handle(_ detections: [Detection], streamTime now: Double, dataStart: Double) {
        if status == .calibrating && calibrationStart == nil { calibrationStart = dataStart }
        for d in detections {
            var stats = beaconStats[d.beacon]
            stats.snrDB = d.snrDB
            stats.phase = positiveRemainder(d.wallClock, Parameters.cycle)
            stats.ambiguous = d.ambiguous
            stats.accepted = false
            stats.rangeM = nil
            stats.recentTimes.append(d.arrivalTime)
            stats.recentTimes.removeAll { $0 < d.arrivalTime - Parameters.diagnosticsWindow }
            switch status {
            case .calibrating:
                if d.arrivalTime >= calibrationStart! { calibrationDetections.append(d) }
            case .tracking, .recovering, .lost:
                if var tracker {
                    let result = tracker.update(d)
                    stats.rangeM = result.range
                    stats.accepted = result.accepted
                    self.tracker = tracker
                }
            case .notCalibrated:
                break
            }
            beaconStats[d.beacon] = stats
        }
        streamTime = now
        if tracker != nil && status != .calibrating {
            tracker!.tick(now: streamTime)
            status = tracker!.status
        }
    }

    // MARK: Calibration

    public func startCalibration() {
        lock.lock()
        defer { lock.unlock() }
        status = .calibrating
        calibration = nil
        tracker = nil
        scheduleGeneration += 1
        calibrationStart = nil
        calibrationDetections = []
    }

    public var calibrationProgress: CalibrationProgress {
        lock.lock()
        defer { lock.unlock() }
        var counts: [String: Int] = [:]
        for (k, beacon) in config.beacons.enumerated() {
            counts[beacon.id] = status == .calibrating ? calibrationDetections.filter { $0.beacon == k }.count : 0
        }
        let elapsed = status == .calibrating ? streamTime - (calibrationStart ?? streamTime) : 0
        return CalibrationProgress(elapsed: elapsed, required: Parameters.calibrationDuration, detections: counts)
    }

    public func finishCalibration() -> CalibrationReport {
        lock.lock()
        defer { lock.unlock() }
        guard status == .calibrating else {
            return CalibrationReport(ok: false, beacons: [], problems: ["Calibration was not started."])
        }
        let (report, fit) = Calibrator.fit(config: config, detections: calibrationDetections,
                                              elapsed: streamTime - (calibrationStart ?? streamTime))
        calibrationDetections = []
        scheduleGeneration += 1
        if let fit {
            calibration = fit
            tracker = Tracker(start: config.calibrationPosition, time: streamTime, beacons: beaconPositions, timings: fit.beacons,
                              speedOfSound: speedOfSound, kappa: kappa, receiverHeight: config.receiverHeight)
            status = .tracking
        } else {
            status = .notCalibrated
        }
        return report
    }

    public func invalidateCalibration() {
        lock.lock()
        defer { lock.unlock() }
        status = .notCalibrated
        calibration = nil
        tracker = nil
        calibrationDetections = []
        scheduleGeneration += 1
    }

    // MARK: Outputs

    public func state(at audioTime: Double) -> TrackState {
        lock.lock()
        defer { lock.unlock() }
        return currentState(at: audioTime)
    }

    private func currentState(at t: Double) -> TrackState {
        if let tracker, status != .calibrating { return tracker.state(at: t) }
        // Not tracking: the calibration point, with no meaningful uncertainty.
        return TrackState(time: t, position: config.calibrationPosition, velocity: .zero, uncertainty: 0, status: status)
    }

    public func guidance(at audioTime: Double, headYaw: Double, destination: String) -> Guidance {
        lock.lock()
        defer { lock.unlock() }
        guard let target = config.destinations.first(where: { $0.name == destination }) else {
            return Guidance(destination: destination, distance: 0, horizontalDistance: 0, headRelative: .zero,
                            azimuthDeg: 0, elevationDeg: 0, mode: .far, heightHint: .chest, valid: false)
        }
        let state = currentState(at: audioTime)
        let valid = state.status == .tracking || state.status == .recovering
        let head = SIMD3(state.position.x, state.position.y, config.earHeight)
        let targetPosition = SIMD3(target.position[0], target.position[1], target.position[2])
        let delta = smoother.smooth(targetPosition - head, at: audioTime, destination: destination, restart: valid != lastGuidanceValid)
        lastGuidanceValid = valid
        return GuidanceMath.guidance(destination: destination, delta: delta, headYaw: headYaw,
                                     targetHeight: targetPosition.z, earHeight: config.earHeight, valid: valid)
    }

    public var diagnostics: Diagnostics {
        lock.lock()
        defer { lock.unlock() }
        let beacons = zip(config.beacons, beaconStats).map { beacon, stats in
            BeaconDiagnostics(id: beacon.id, lastSNRdB: stats.snrDB, lastRangeM: stats.rangeM, lastPhaseSeconds: stats.phase,
                              lastAccepted: stats.accepted, lastAmbiguous: stats.ambiguous,
                              detectionsLast5s: stats.recentTimes.filter { $0 >= streamTime - Parameters.diagnosticsWindow }.count)
        }
        return Diagnostics(beacons: beacons, acceptedTotal: tracker?.accepted ?? 0, rejectedTotal: tracker?.rejected ?? 0,
                           recoveries: tracker?.recoveries ?? 0, processingMsPerBlock: processingMs)
    }
}
