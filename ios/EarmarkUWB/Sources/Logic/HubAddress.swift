import Foundation

/// Turns what someone typed into the hub address field into a bus URL.
/// Accepts `ws://host:port`, `wss://...`, or a bare `host` / `host:port` (ws:// and port 8765 are added).
enum HubAddress {
    static let defaultPort = 8765

    static func parse(_ text: String) -> URL? {
        var s = text.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !s.isEmpty else { return nil }
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
