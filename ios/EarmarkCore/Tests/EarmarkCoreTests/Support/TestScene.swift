import Foundation
@testable import EarmarkCore

/// Paths and scene loading for tests. The repo root is found from this file's location.
enum TestScene {
    static let repoRoot: URL = URL(fileURLWithPath: #filePath)
        .deletingLastPathComponent()   // Support
        .deletingLastPathComponent()   // EarmarkCoreTests
        .deletingLastPathComponent()   // Tests
        .deletingLastPathComponent()   // EarmarkCore
        .deletingLastPathComponent()   // ios
        .deletingLastPathComponent()   // repo root

    static let fixtures = repoRoot.appendingPathComponent("fixtures")

    /// The C4 example scene, verbatim.
    static let c4Example = """
    {
      "version": 1,
      "temperatureC": 21.0,
      "cycleSeconds": 0.5,
      "slotSeconds": 0.125,
      "chirp": { "f0": 18000, "f1": 20000, "duration": 0.012 },
      "beacons": [
        { "id": "B1", "slot": 0, "device": "iPhone (name)", "speaker": "left",  "position": [-1.50,  1.50, 1.90] },
        { "id": "B2", "slot": 1, "device": "iPhone (name)", "speaker": "left",  "position": [ 1.50,  1.50, 1.70] },
        { "id": "B3", "slot": 2, "device": "iPhone (name)", "speaker": "left",  "position": [ 1.50, -1.50, 2.00] },
        { "id": "B4", "slot": 3, "device": "MacBook",       "speaker": "right", "position": [-1.70, -0.30, 1.00] }
      ],
      "calibrationPoint": [0.0, 0.0, 1.45],
      "receiverHeight": 1.45,
      "earHeight": 1.62,
      "destinations": [
        { "name": "sugar jar",   "position": [ 1.20, 1.00, 0.90] },
        { "name": "keys",        "position": [-1.10, 0.90, 1.30] },
        { "name": "spice jar",   "position": [ 1.25, 1.05, 1.35] },
        { "name": "pill bottle", "position": [-1.00, -1.00, 0.45] }
      ]
    }
    """

    /// The repo's scene.json when A has pushed one, otherwise the C4 example.
    static func load(receiverHeight: Double?? = nil) throws -> RoomConfig {
        let url = repoRoot.appendingPathComponent("scene.json")
        var data = (try? Data(contentsOf: url)) ?? Data(c4Example.utf8)
        if let override = receiverHeight {
            var json = try JSONSerialization.jsonObject(with: data) as! [String: Any]
            json["receiverHeight"] = override.map { $0 as Any } ?? NSNull()
            data = try JSONSerialization.data(withJSONObject: json)
        }
        return try RoomConfig.load(from: data)
    }
}
