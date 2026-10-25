import Foundation

/// The sound-positioning side of the app: where the ranging service is, which beacon an anchor is, and the
/// one-line status texts. Pure functions so they can be unit tested without a device.

/// Address of the ranging service (`earmark-ranging listen`, ws://<mac>:8766).
enum RangingAddress {
    static let defaultPort = 8766

    /// What the field shows when nothing was typed: the hub's host with the ranging port.
    /// nil when the hub address does not parse.
    static func derived(fromHub hubText: String) -> String? {
        guard let host = HubAddress.parse(hubText)?.host else { return nil }
        let bare = host.contains(":") && !host.hasPrefix("[") ? "[\(host)]" : host   // IPv6 literal
        return "ws://\(bare):\(defaultPort)"
    }

    /// Typed text -> URL. Accepts `ws://host:port` or a bare `host` / `host:port` (ws:// and port 8766 added).
    /// Empty text means "use the default derived from the hub address".
    static func resolve(typed: String, hubText: String) -> URL? {
        let trimmed = typed.trimmingCharacters(in: .whitespacesAndNewlines)
        if trimmed.isEmpty { return derived(fromHub: hubText).flatMap { URL(string: $0) } }
        var s = trimmed
        if !s.contains("://") { s = "ws://" + s }
        guard var c = URLComponents(string: s),
              let scheme = c.scheme?.lowercased(), scheme == "ws" || scheme == "wss",
              c.host?.isEmpty == false
        else { return nil }
        c.scheme = scheme
        if c.port == nil { c.port = defaultPort }
        return c.url
    }
}

enum BeaconNumber {
    /// "uwb_2" -> 2. Beacons are 1 to 4 (the sound system's slots); anything else (the wearer, "uwb_9") -> nil.
    static func forDevice(_ deviceId: String) -> Int? {
        guard deviceId.hasPrefix("uwb_"), let n = Int(deviceId.dropFirst(4)), (1...4).contains(n) else { return nil }
        return n
    }
}

/// Texts for the status lines (also read by VoiceOver).
enum SoundStatusText {
    /// Wearer's sound-listener line. `fixAge` is seconds since the last fix, nil if none yet.
    static func listener(enabled: Bool, connected: Bool, fixAge: Double?, error: String?) -> String {
        guard enabled else { return "Sound positioning: off" }
        if let error, !connected { return "Sound positioning: \(error)" }
        guard connected else { return "Sound positioning: connecting" }
        guard let age = fixAge else { return "Sound positioning: connected, no fix yet" }
        return "Sound positioning: connected, last fix \(ageText(age)) ago"
    }

    static func ageText(_ seconds: Double) -> String {
        seconds < 10 ? String(format: "%.1f s", max(0, seconds)) : "\(Int(seconds.rounded())) s"
    }

    /// Anchor's beacon line.
    static func beacon(number: Int?, enabled: Bool, chirping: Bool, played: Int, error: String?) -> String {
        guard let number else { return "Sound beacon: not available for this role" }
        guard enabled else { return "Sound beacon \(number): off" }
        if let error { return "Sound beacon \(number): \(error)" }
        return chirping ? "Sound beacon \(number): chirping, \(played) chirps played" : "Sound beacon \(number): starting"
    }

    /// `active` is the hub's `positioning.active` raw value.
    static func audioFollows(_ active: String?) -> String {
        switch active {
        case "uwb"?: "Audio follows: UWB"
        case "sound"?: "Audio follows: Sound"
        default: "Audio follows: waiting for the hub"
        }
    }
}
