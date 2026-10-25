import Foundation

/// Caps one anchor's `uwb_range` stream at `maxHz` (UWB-PRD 7.4: forward every update, decimate to 20 Hz).
///
/// Sends sit on a fixed grid of `1/maxHz` that may lag the clock by at most one interval, so a 30 Hz input
/// becomes 20 Hz (two of every three), not 15 Hz as a plain "at least 50 ms apart" rule would give.
/// Inputs at or below `maxHz` all pass. Times are seconds on any monotonic clock.
struct RangeDecimator {
    let minInterval: Double
    private var nextDue = -Double.infinity

    init(maxHz: Double = 20) {
        minInterval = 1 / maxHz
    }

    mutating func shouldSend(at t: Double) -> Bool {
        guard t >= nextDue else { return false }
        nextDue = max(nextDue, t - minInterval) + minInterval
        return true
    }
}

/// Events per second over a sliding window (per-anchor update-rate meter).
struct RateMeter {
    let window: Double
    private var times: [Double] = []

    init(window: Double = 2) {
        self.window = window
    }

    mutating func record(_ t: Double) {
        times.append(t)
        trim(t)
    }

    mutating func rate(at now: Double) -> Double {
        trim(now)
        return Double(times.count) / window
    }

    private mutating func trim(_ now: Double) {
        let cutoff = now - window
        if let keep = times.firstIndex(where: { $0 > cutoff }) {
            if keep > 0 { times.removeFirst(keep) }
        } else {
            times.removeAll()
        }
    }
}

/// Reconnect delay: 0.5 s doubling to 5 s (same as the Mac app's BusClient). The caller adds jitter.
struct Backoff {
    let initial: Double
    let maximum: Double
    private(set) var current: Double

    init(initial: Double = 0.5, maximum: Double = 5) {
        self.initial = initial
        self.maximum = maximum
        current = initial
    }

    mutating func next() -> Double {
        let delay = current
        current = min(current * 2, maximum)
        return delay
    }

    mutating func reset() {
        current = initial
    }
}
