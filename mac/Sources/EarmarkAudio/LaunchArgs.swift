import Foundation

/// Command-line flags for both apps.
///
/// Value flags must use the single-token form `--key=value`. A separate bare value (`--bus-url ws://...`)
/// is treated by AppKit as a document to open at launch, and SwiftUI then opens no window at all.
public struct LaunchArgs: Sendable {
    public private(set) var switches: Set<String> = []
    public private(set) var values: [String: String] = [:]

    public init(_ args: [String] = CommandLine.arguments) {
        for a in args.dropFirst() {
            guard a.hasPrefix("--") else {
                if !a.hasPrefix("-") { Log.app("ignoring bare argument '\(a)': use --key=value for flag values") }
                continue
            }
            let body = String(a.dropFirst(2))
            if let eq = body.firstIndex(of: "=") {
                values[String(body[..<eq])] = String(body[body.index(after: eq)...])
            } else {
                switches.insert(body)
            }
        }
    }

    public func has(_ name: String) -> Bool { switches.contains(name) }
    public func value(_ name: String) -> String? { values[name] }
}
