import Foundation
import simd

// The public API from the shared contract (C6). The public initializers on the value types are
// there so the app can build these values itself, for example in a MockEngine.

public struct RoomConfig: Codable {          // mirrors scene.json; named to avoid SwiftUI's `Scene`
    public struct Chirp: Codable { public let f0: Double; public let f1: Double; public let duration: Double }
    public struct Beacon: Codable { public let id: String; public let slot: Int; public let device: String?; public let speaker: String?; public let position: [Double] }
    public struct Destination: Codable { public let name: String; public let position: [Double] }
    public let version: Int
    public let temperatureC: Double
    public let cycleSeconds: Double
    public let slotSeconds: Double
    public let chirp: Chirp
    public let beacons: [Beacon]
    public let calibrationPoint: [Double]
    public let receiverHeight: Double?
    public let earHeight: Double
    public let destinations: [Destination]

    /// Decodes scene.json and checks that it fits the signal contract (C3) and has usable geometry.
    public static func load(from data: Data) throws -> RoomConfig {
        let config = try JSONDecoder().decode(RoomConfig.self, from: data)
        try config.validate()
        return config
    }
}

public struct AudioBlock {
    public let samples: [Float]      // mono, nominally -1...1
    public let sampleRate: Double
    public let sampleTime: Int64     // audio-clock index of samples[0]; grows by samples.count unless buffers were dropped
    public let wallClock: Double     // Unix seconds at samples[0]; used only to assign slots before calibration
    public init(samples: [Float], sampleRate: Double, sampleTime: Int64, wallClock: Double) {
        self.samples = samples
        self.sampleRate = sampleRate
        self.sampleTime = sampleTime
        self.wallClock = wallClock
    }
}

public enum TrackStatus: String { case notCalibrated, calibrating, tracking, recovering, lost }

public struct TrackState {
    public let time: Double                 // audio-clock seconds this state describes
    public let position: SIMD3<Double>      // m, room frame
    public let velocity: SIMD3<Double>      // m/s
    public let uncertainty: Double          // m, sqrt(trace of position covariance)
    public let status: TrackStatus
    public init(time: Double, position: SIMD3<Double>, velocity: SIMD3<Double>, uncertainty: Double, status: TrackStatus) {
        self.time = time
        self.position = position
        self.velocity = velocity
        self.uncertainty = uncertainty
        self.status = status
    }
}

public enum GuidanceMode: String { case far, near, found }
public enum HeightHint: String { case low, chest, high }

public struct Guidance {
    public let destination: String
    public let distance: Double             // m, 3D, head point to destination
    public let horizontalDistance: Double   // m, floor-plane distance; decides the mode
    public let headRelative: SIMD3<Double>  // m; x = right, y = forward, z = up
    public let azimuthDeg: Double           // clockwise from straight ahead, -180...180
    public let elevationDeg: Double
    public let mode: GuidanceMode           // far > 0.9 m, near 0.45–0.9 m, found < 0.45 m (horizontal)
    public let heightHint: HeightHint       // vs earHeight: high > ear-0.10 m, chest ear-0.60...ear-0.10, low < ear-0.60
    public let valid: Bool                  // false unless status is tracking or recovering
    public init(destination: String, distance: Double, horizontalDistance: Double, headRelative: SIMD3<Double>,
                azimuthDeg: Double, elevationDeg: Double, mode: GuidanceMode, heightHint: HeightHint, valid: Bool) {
        self.destination = destination
        self.distance = distance
        self.horizontalDistance = horizontalDistance
        self.headRelative = headRelative
        self.azimuthDeg = azimuthDeg
        self.elevationDeg = elevationDeg
        self.mode = mode
        self.heightHint = heightHint
        self.valid = valid
    }
}

public struct BeaconDiagnostics {
    public let id: String
    public let lastSNRdB: Double?
    public let lastRangeM: Double?
    public let lastPhaseSeconds: Double?    // arrival phase within the cycle, wall-clock based
    public let lastAccepted: Bool
    public let lastAmbiguous: Bool
    public let detectionsLast5s: Int
    public init(id: String, lastSNRdB: Double?, lastRangeM: Double?, lastPhaseSeconds: Double?,
                lastAccepted: Bool, lastAmbiguous: Bool, detectionsLast5s: Int) {
        self.id = id
        self.lastSNRdB = lastSNRdB
        self.lastRangeM = lastRangeM
        self.lastPhaseSeconds = lastPhaseSeconds
        self.lastAccepted = lastAccepted
        self.lastAmbiguous = lastAmbiguous
        self.detectionsLast5s = detectionsLast5s
    }
}

public struct Diagnostics {
    public let beacons: [BeaconDiagnostics]
    public let acceptedTotal: Int
    public let rejectedTotal: Int
    public let recoveries: Int
    public let processingMsPerBlock: Double
    public init(beacons: [BeaconDiagnostics], acceptedTotal: Int, rejectedTotal: Int, recoveries: Int, processingMsPerBlock: Double) {
        self.beacons = beacons
        self.acceptedTotal = acceptedTotal
        self.rejectedTotal = rejectedTotal
        self.recoveries = recoveries
        self.processingMsPerBlock = processingMsPerBlock
    }
}

public struct BeaconCalibration {
    public let id: String; public let detections: Int; public let residualCm: Double; public let phaseSeconds: Double
    public init(id: String, detections: Int, residualCm: Double, phaseSeconds: Double) {
        self.id = id
        self.detections = detections
        self.residualCm = residualCm
        self.phaseSeconds = phaseSeconds
    }
}
public struct CalibrationReport {
    public let ok: Bool; public let beacons: [BeaconCalibration]; public let problems: [String]
    public init(ok: Bool, beacons: [BeaconCalibration], problems: [String]) {
        self.ok = ok
        self.beacons = beacons
        self.problems = problems
    }
}
public struct CalibrationProgress {
    public let elapsed: Double; public let required: Double; public let detections: [String: Int]
    public init(elapsed: Double, required: Double, detections: [String: Int]) {
        self.elapsed = elapsed
        self.required = required
        self.detections = detections
    }
}

public protocol EarmarkEngineProtocol: AnyObject {
    init(config: RoomConfig) throws
    /// Call from one serial queue, in sampleTime order. Must return in < 15 ms for 4096 samples on an iPhone.
    func process(_ block: AudioBlock)
    /// Receiver at config.calibrationPoint, judge facing +y, holding still.
    func startCalibration()
    var calibrationProgress: CalibrationProgress { get }
    /// If ok == false, status returns to .notCalibrated and problems says why.
    func finishCalibration() -> CalibrationReport
    /// Call after an audio route change or engine restart.
    func invalidateCalibration()
    /// Extrapolates without changing the filter. Thread-safe, < 1 ms.
    func state(at audioTime: Double) -> TrackState
    /// headYaw = ψ (C2). Thread-safe, < 1 ms, called at 30 Hz.
    func guidance(at audioTime: Double, headYaw: Double, destination: String) -> Guidance
    var diagnostics: Diagnostics { get }
}
