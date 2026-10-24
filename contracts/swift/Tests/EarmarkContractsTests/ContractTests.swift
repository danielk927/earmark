import Foundation
import Testing
@testable import EarmarkContracts

private let examplesDir = URL(fileURLWithPath: #filePath)
    .deletingLastPathComponent().deletingLastPathComponent().deletingLastPathComponent()
    .deletingLastPathComponent().appendingPathComponent("examples/bus")

private func examples(_ type: String) throws -> [Data] {
    let dir = examplesDir.appendingPathComponent(type)
    let files = try FileManager.default.contentsOfDirectory(at: dir, includingPropertiesForKeys: nil)
        .filter { $0.pathExtension == "json" }.sorted { $0.path < $1.path }
    return try files.map { try Data(contentsOf: $0) }
}

private func allTypes() throws -> [String] {
    try FileManager.default.contentsOfDirectory(atPath: examplesDir.path).filter { !$0.hasPrefix(".") }.sorted()
}

@Test func everyBusExampleDecodesWithItsType() throws {
    let types = try allTypes()
    #expect(types.count >= 25)
    for type in types {
        for data in try examples(type) {
            let msg = try BusCoding.decode(data)
            #expect(msg.type == type)
        }
    }
}

/// Messages the Mac app sends must re-encode to exactly the example JSON.
@Test(arguments: ["hello", "mic_audio", "transcript", "guide_feedback", "playback", "head_pose", "status", "reset", "listener_pose", "arrived", "ptt"])
func sentMessagesRoundTrip(type: String) throws {
    for data in try examples(type) {
        let msg = try BusCoding.decode(data)
        let back = try BusCoding.encode(msg)
        let a = try JSONSerialization.jsonObject(with: data) as! NSDictionary
        let b = try JSONSerialization.jsonObject(with: back) as! NSDictionary
        #expect(a == b, "\(type): \(String(decoding: back, as: UTF8.self))")
    }
}
