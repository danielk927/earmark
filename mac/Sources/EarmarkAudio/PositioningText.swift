import EarmarkContracts
import Foundation

/// Pure helpers for the dual-positioning display: names, staleness, distance between the two systems, text lines.
public enum PositioningText {
    /// A fix older than this is stale.
    public static let staleAfterS = 2.0

    public static func name(_ s: PositioningSystem) -> String { s == .uwb ? "UWB" : "Sound" }
    public static func other(_ s: PositioningSystem) -> PositioningSystem { s == .uwb ? .sound : .uwb }

    public static func fix(_ p: Positioning, _ s: PositioningSystem) -> PositioningFix? { s == .uwb ? p.uwb : p.sound }

    /// Stale = older than `staleAfterS` or quality lost.
    public static func isStale(_ f: PositioningFix) -> Bool { f.ageS > staleAfterS || f.quality == .lost }

    /// Horizontal (x, y) distance in meters between two fixes.
    public static func distance(_ a: PositioningFix, _ b: PositioningFix) -> Double? {
        guard a.position.count >= 2, b.position.count >= 2 else { return nil }
        let dx = a.position[0] - b.position[0], dy = a.position[1] - b.position[1]
        return (dx * dx + dy * dy).squareRoot()
    }

    /// The inactive system's fix when it is fresh enough to draw as a ghost dot; nil otherwise.
    public static func ghost(_ p: Positioning?) -> PositioningFix? {
        guard let p, let f = fix(p, other(p.active)), !isStale(f) else { return nil }
        return f
    }

    /// Line about the inactive system, e.g. "Sound: 0.18 m from UWB, 0.3 s old" or "Sound: not heard".
    public static func inactiveLine(_ p: Positioning) -> String {
        let me = other(p.active)
        let label = name(me)
        guard let f = fix(p, me) else { return me == .uwb ? "UWB: not tracking" : "Sound: not heard" }
        let age = String(format: "%.1f s old", max(0, f.ageS))
        if f.quality == .lost { return "\(label): lost, \(age)" }
        if f.ageS > staleAfterS { return "\(label): stale, \(age)" }
        if let active = fix(p, p.active), !isStale(active), let d = distance(f, active) {
            return String(format: "%@: %.2f m from %@, %@", label, d, name(p.active), age)
        }
        return "\(label): \(age)"
    }

    /// Line saying which system drives the audio.
    public static func activeLine(_ p: Positioning) -> String { "Audio follows \(name(p.active))" }
}
