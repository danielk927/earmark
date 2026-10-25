import Foundation
import simd

/// B1 stub: compiles against the full C6 API and returns placeholder values.
public final class EarmarkEngine: EarmarkEngineProtocol {
    private let config: RoomConfig

    public init(config: RoomConfig) throws {
        try config.validate()
        self.config = config
    }

    public func process(_ block: AudioBlock) {}
    public func startCalibration() {}

    public var calibrationProgress: CalibrationProgress {
        CalibrationProgress(elapsed: 0, required: Parameters.calibrationDuration,
                            detections: Dictionary(uniqueKeysWithValues: config.beacons.map { ($0.id, 0) }))
    }

    public func finishCalibration() -> CalibrationReport {
        CalibrationReport(ok: false, beacons: [], problems: ["calibration is not implemented yet"])
    }

    public func invalidateCalibration() {}

    public func state(at audioTime: Double) -> TrackState {
        TrackState(time: audioTime, position: config.calibrationPosition, velocity: .zero, uncertainty: 0, status: .notCalibrated)
    }

    public func guidance(at audioTime: Double, headYaw: Double, destination: String) -> Guidance {
        Guidance(destination: destination, distance: 0, horizontalDistance: 0, headRelative: .zero,
                 azimuthDeg: 0, elevationDeg: 0, mode: .far, heightHint: .chest, valid: false)
    }

    public var diagnostics: Diagnostics {
        Diagnostics(beacons: [], acceptedTotal: 0, rejectedTotal: 0, recoveries: 0, processingMsPerBlock: 0)
    }
}
