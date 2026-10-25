import Foundation
import os
import UIKit

enum Log {
    private static let subsystem = "com.earmark.uwb"
    static let hub = Logger(subsystem: subsystem, category: "hub")
    static let ni = Logger(subsystem: subsystem, category: "nearby")
    static let motion = Logger(subsystem: subsystem, category: "motion")
    static let mic = Logger(subsystem: subsystem, category: "mic")
}

/// Runs `body` on the main queue (FIFO, so ordering is kept) as main-actor code.
/// Used to hop from URLSession completion handlers, the CoreMotion queue, and the audio tap thread.
func onMain(_ body: @escaping @MainActor @Sendable () -> Void) {
    DispatchQueue.main.async { MainActor.assumeIsolated(body) }
}

/// Calls `tick` every `seconds` on the main actor until the returned task is cancelled.
/// Used instead of Timer / asyncAfter so every periodic job stays main-actor isolated.
@MainActor
func everySeconds(_ seconds: Double, _ tick: @escaping @MainActor () -> Void) -> Task<Void, Never> {
    Task { @MainActor in
        while !Task.isCancelled {
            try? await Task.sleep(for: .seconds(seconds))
            if Task.isCancelled { return }
            tick()
        }
    }
}

/// Monotonic seconds (rate meters, decimation, staleness). Bus timestamps use `BusCoding.now` (unix time).
func uptime() -> Double { ProcessInfo.processInfo.systemUptime }

func metres(_ d: Double?) -> String {
    guard let d else { return "—" }
    return String(format: "%.2f m", d)
}

@MainActor
enum DeviceInfo {
    /// 0...1, or nil when unknown (battery monitoring off, simulator).
    static var batteryLevel: Double? {
        let level = UIDevice.current.batteryLevel
        return level < 0 ? nil : Double(level)
    }

    static var isCharging: Bool {
        let state = UIDevice.current.batteryState
        return state == .charging || state == .full
    }

    static var batteryText: String {
        guard let level = batteryLevel else { return "Unknown" }
        return "\(Int((level * 100).rounded()))%" + (isCharging ? ", charging" : "")
    }
}
