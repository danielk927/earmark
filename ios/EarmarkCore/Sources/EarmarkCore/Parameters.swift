import Foundation

/// Every tunable constant, with the values from the parameter table in spec B.
enum Parameters {
    // Signal
    static let f0 = 18_000.0                    // Hz
    static let f1 = 20_000.0                    // Hz
    static let chirpDuration = 0.012            // s
    static let fade = 0.001                     // s, raised-cosine fade at each end

    // Timing
    static let cycle = 0.5                      // s
    static let slotSpacing = 0.125              // s
    static let maxBeacons = 4

    // Detector
    static let fftSize = 8192
    static let preCalWindowBefore = 0.045       // s before the slot
    static let preCalWindowAfter = 0.060        // s after the slot
    static let postCalWindowHalfWidth = 0.008   // s
    static let minSNRdB = 12.0
    static let leadingEdgeRatio = 0.5
    static let ambiguityGap = 0.000_25          // s
    static let noiseTimeConstant = 2.0          // s
    static let noiseWarmup = 0.05               // s of noise samples before any detection

    // Calibration
    static let calibrationDuration = 15.0       // s
    static let minCalibrationDetections = 20
    static let madMultiplier = 3.0
    static let residualFloor = 0.000_030        // s
    static let robustFitPasses = 3
    static let timingNoiseFloor = 0.000_020     // s
    static let maxCalibrationResidual = 0.03    // m
    static let minSlotGap = 0.040               // s

    // Tracker
    // σ_a is 0.5, not the spec's 1.0: with 1.0 the predicted range spread of a beacon heard once a second
    // reaches ~25 cm, the χ² gate then admits most echoes, and simulated walks diverged by meters.
    static let accelerationSigma = 0.5          // m/s²
    static let rangeFloor = 0.01                // m
    static let initialPositionSigma = 0.03      // m
    static let initialVelocitySigma = 0.05      // m/s
    static let gateChiSquare = 9.0
    static let gateMinInnovation = 0.05         // m
    // Not in the spec. Echoes are 0.3 ms (10 cm) or more late and never early, so a measured range
    // more than this beyond the prediction is rejected, also while recovering.
    static let echoRejectAbove = 0.10           // m
    static let noUpdateTimeout = 1.0            // s
    static let rejectionsBeforeRecovery = 4     // within the last `rejectionWindow` updates (spec: in a row)
    static let rejectionWindow = 8
    static let uncertaintyLimit = 0.5           // m
    static let recoveryRangeAge = 0.6           // s
    static let recoveryAcceptRMS = 0.05         // m
    static let recoveryIterations = 10
    static let recoveryPositionSigma = 0.1      // m
    static let recoveryVelocitySigma = 0.3      // m/s
    // Not in the spec: on entering recovery, P is raised to at least this so ungated updates can move it.
    static let recoveringPositionSigma = 0.3    // m
    static let lostAfter = 3.0                  // s of failed recovery
    static let heightSigma = 0.05               // m

    // Physics
    static let kappa = 0.114                    // s, f_center / sweep rate
    static func speedOfSound(temperatureC: Double) -> Double { 331.3 + 0.606 * temperatureC }

    // Guidance
    static let guidanceTau = 0.25               // s
    static let farBeyond = 0.9                  // m, horizontal
    static let foundWithin = 0.45               // m, horizontal
    static let highAboveEarMinus = 0.10         // m
    static let lowBelowEarMinus = 0.60          // m

    // Diagnostics
    static let diagnosticsWindow = 5.0          // s
}
