import Foundation

/// The Mac's address as typed on the phone.
///
/// - `192.168.1.20:8766` or `192.168.1.20`: the Mac on the same Wi-Fi (`ws://`, port 8766 if none is given).
/// - `some-words.trycloudflare.com`: the tunnel `make session TUNNEL=1` prints, for venue Wi-Fi that keeps phones
///   from reaching the Mac directly (`wss://`, port 443).
/// - A full `ws://`, `wss://`, `http://` or `https://` address (the last two as pasted from the terminal).
public enum PhoneAddress {
    public static let defaultPort = 8766

    public static func url(_ text: String) -> URL? {
        let t = text.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !t.isEmpty else { return nil }
        let full: String
        if let r = t.range(of: "://") {
            let scheme = t[..<r.lowerBound].lowercased()
            let rest = t[r.upperBound...]
            switch scheme {
            case "ws", "http": full = "ws://\(rest)"
            case "wss", "https": full = "wss://\(rest)"
            default: return nil
            }
        } else {
            let host = t.split(separator: "/", maxSplits: 1).first.map(String.init) ?? t
            let hasPort = host.contains(":")
            let local = host == "localhost" || host.split(separator: ".").allSatisfy { Int($0) != nil } || host.hasSuffix(".local")
            if hasPort { full = "ws://\(t)" } else if local { full = "ws://\(host):\(defaultPort)" } else { full = "wss://\(t)" }
        }
        guard let url = URL(string: full), url.host?.isEmpty == false else { return nil }
        return url
    }
}
