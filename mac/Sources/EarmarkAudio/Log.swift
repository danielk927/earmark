import Foundation
import os

/// Line-oriented logging to stdout (captured by `open --stdout`) and the unified log.
/// Never logs secrets or audio payloads.
public enum Log {
    private static let logger = Logger(subsystem: "com.earmark", category: "app")
    private static let lock = NSLock()
    nonisolated(unsafe) public static var sink: ((String) -> Void)?

    private static let stamp: DateFormatter = {
        let f = DateFormatter()
        f.dateFormat = "HH:mm:ss.SSS"
        return f
    }()

    public static func write(_ category: String, _ message: String) {
        let line = lock.withLock { "\(stamp.string(from: Date())) [\(category)] \(message)\n" }
        FileHandle.standardOutput.write(Data(line.utf8))
        logger.info("[\(category, privacy: .public)] \(message, privacy: .public)")
        sink?(line)
    }

    public static func audio(_ m: String) { write("audio", m) }
    public static func head(_ m: String) { write("head", m) }
    public static func route(_ m: String) { write("route", m) }
    public static func bus(_ m: String) { write("bus", m) }
    public static func speech(_ m: String) { write("speech", m) }
    public static func mic(_ m: String) { write("mic", m) }
    public static func app(_ m: String) { write("app", m) }
}
