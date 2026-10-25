import Foundation

/// Tap-to-mark knock detection from CoreMotion user acceleration.
///
/// Feed |userAcceleration| in g at the sample rate (50 Hz). `push` returns true on the sample where a knock is
/// detected: a spike above `spikeG` that follows at least `stillFor` seconds of quiet (the windowed RMS stayed
/// below `stillBelowG`), so bumps while walking don't count. After a knock the detector ignores samples for
/// `refractory` seconds so one knock fires once. Pure value type so it is unit-tested without a phone.
///
/// Every threshold is a calibration knob; tune `spikeG` first if knocks are missed (lower it) or false (raise it).
struct KnockDetector {
    let spikeG: Double
    let stillBelowG: Double
    let windowSize: Int
    /// `stillFor` and `refractory` converted to samples at `sampleHz`.
    let stillSamples: Int
    let refractorySamples: Int

    private var window: [Double] = []
    /// Consecutive samples (full window only) whose RMS was below `stillBelowG`.
    private var stillRun = 0
    /// Samples left in the refractory period.
    private var cooldown = 0

    /// - spikeG: a sample above this is a knock candidate. 1.5 g is a firm rap on a table.
    /// - stillBelowG: windowed RMS below this counts as still (above the 0.03 g still gate of `MotionClassifier`).
    /// - stillFor: seconds of stillness required before the spike.
    /// - refractory: seconds after a knock during which nothing fires.
    /// - windowSize: RMS window in samples (10 = 0.2 s at 50 Hz).
    init(spikeG: Double = 1.5, stillBelowG: Double = 0.05, stillFor: Double = 0.4, refractory: Double = 1.0,
         sampleHz: Double = 50, windowSize: Int = 10) {
        self.spikeG = spikeG
        self.stillBelowG = stillBelowG
        self.windowSize = max(1, windowSize)
        self.stillSamples = max(0, Int((stillFor * sampleHz).rounded()))
        self.refractorySamples = max(0, Int((refractory * sampleHz).rounded()))
    }

    /// Adds one sample. Returns true when this sample is a knock.
    mutating func push(_ magnitudeG: Double) -> Bool {
        let cooling = cooldown > 0
        if cooling { cooldown -= 1 }
        // Judge the spike against the stillness that came before it, then let the spike enter the window.
        let knock = !cooling && magnitudeG > spikeG && stillRun >= stillSamples
        if knock { cooldown = refractorySamples }

        window.append(magnitudeG)
        if window.count > windowSize { window.removeFirst(window.count - windowSize) }
        if window.count == windowSize {
            let rms = (window.reduce(0) { $0 + $1 * $1 } / Double(windowSize)).squareRoot()
            stillRun = rms < stillBelowG ? stillRun + 1 : 0
        }
        return knock
    }

    mutating func reset() {
        window.removeAll()
        stillRun = 0
        cooldown = 0
    }
}
