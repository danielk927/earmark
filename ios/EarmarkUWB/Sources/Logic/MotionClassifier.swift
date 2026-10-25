import EarmarkContracts
import Foundation

/// Moving vs still from CoreMotion user acceleration (UWB-PRD 7.5).
///
/// Feed |userAcceleration| in g at the sample rate (50 Hz). Over a sliding window (0.5 s = 25 samples)
/// the RMS decides: `still` below 0.03 g, `moving` above 0.06 g, otherwise keep the current state (hysteresis).
/// Pure value type so it is unit-tested without a phone.
struct MotionClassifier {
    let windowSize: Int
    let stillBelowG: Double
    let movingAboveG: Double

    private(set) var state: MotionState.State?
    private(set) var lastRMS: Double = 0
    private var window: [Double] = []

    init(windowSize: Int = 25, stillBelowG: Double = 0.03, movingAboveG: Double = 0.06) {
        self.windowSize = max(1, windowSize)
        self.stillBelowG = stillBelowG
        self.movingAboveG = movingAboveG
    }

    /// Adds one sample. Returns the new state when it changes (including the first decision once the window is full).
    mutating func push(_ magnitudeG: Double) -> MotionState.State? {
        window.append(magnitudeG)
        if window.count > windowSize { window.removeFirst(window.count - windowSize) }
        guard window.count == windowSize else { return nil }
        // ponytail: recomputed over 25 samples each time; a running sum drifts and saves nothing at 50 Hz.
        let rms = (window.reduce(0) { $0 + $1 * $1 } / Double(windowSize)).squareRoot()
        lastRMS = rms
        let next: MotionState.State
        switch state {
        case nil: next = rms >= (stillBelowG + movingAboveG) / 2 ? .moving : .still
        case .still?: next = rms > movingAboveG ? .moving : .still
        case .moving?: next = rms < stillBelowG ? .still : .moving
        }
        guard next != state else { return nil }
        state = next
        return next
    }

    mutating func reset() {
        window.removeAll()
        state = nil
        lastRMS = 0
    }
}
