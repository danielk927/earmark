// Prints the CGWindowID of the largest on-screen window owned by a process name, for `screencapture -l <id>`.
// Usage: swiftc -O mac/tools/window_id.swift -o mac/build/window_id && mac/build/window_id Earmark
import CoreGraphics
import Foundation

let owner = CommandLine.arguments.dropFirst().first ?? "Earmark"
let list = CGWindowListCopyWindowInfo([.optionOnScreenOnly, .excludeDesktopElements], kCGNullWindowID) as? [[String: Any]] ?? []
let matches = list.filter { ($0[kCGWindowOwnerName as String] as? String) == owner && ($0[kCGWindowLayer as String] as? Int) == 0 }
let best = matches.max { a, b in
    func area(_ w: [String: Any]) -> Double {
        let b = w[kCGWindowBounds as String] as? [String: Double] ?? [:]
        return (b["Width"] ?? 0) * (b["Height"] ?? 0)
    }
    return area(a) < area(b)
}
guard let id = best?[kCGWindowNumber as String] as? Int else {
    FileHandle.standardError.write(Data("no on-screen window for \(owner)\n".utf8))
    exit(1)
}
print(id)
