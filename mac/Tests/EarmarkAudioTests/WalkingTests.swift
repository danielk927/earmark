import EarmarkAudio
import EarmarkContracts
import Foundation
import Testing

/// Map text list, status bar wording, and the calibration screen's pure pieces (UWB walking guidance).
@Suite struct WalkingTextTests {
    static let spaceJSON = """
    {
      "listener": { "label": "counter", "origin_note": "center of head, standing" },
      "spots": [ { "spot": 1, "label": "far left", "position": [-0.42, 0.42, 0.0] } ],
      "areas": [ { "area": "kitchen_counter", "label": "the counter", "position": [0, 0.6, 0] } ],
      "receivers": [ { "receiver": "hub", "label": "the counter", "position": [0, 0.6, 0] } ],
      "anchors": [
        { "anchor": "uwb_1", "label": "UWB Reader/Emitter 1", "position": [-0.9, 0.75, -0.25] },
        { "anchor": "uwb_2", "label": "UWB Reader/Emitter 2", "position": [0.9, 0.75, -0.25] },
        { "anchor": "uwb_3", "label": "UWB Reader/Emitter 3", "position": [-1.4, -1.8, -0.25] }
      ],
      "tracking": { "phone_z": -0.35, "head_offset_m": 0.2 }
    }
    """

    static var space: Space { try! BusCoding.decoder.decode(Space.self, from: Data(spaceJSON.utf8)) }

    static func pose(_ name: String) -> ListenerPose {
        guard case .listenerPose(let p) = example("listener_pose", name) else { fatalError("not a listener_pose") }
        return p
    }

    @Test func mapListsEveryAnchorWithItsStateInWords() {
        let lines = UWBText.anchors(space: Self.space, pose: Self.pose("01"), listener: [0.12, -1.85, 0])
        #expect(lines.map(\.text) == [
            "UWB Reader/Emitter 1: online, 2.7 m from you.",
            "UWB Reader/Emitter 2: online, 2.8 m from you.",
            "UWB Reader/Emitter 3: online, 1.5 m from you.",
        ])
        #expect(lines.allSatisfy { $0.position != nil })
    }

    @Test func blockedAndUnreportedAnchorsAreSpelledOut() {
        // Example 02: frozen, uwb_2 blocked, no per-anchor health.
        let lines = UWBText.anchors(space: Self.space, pose: Self.pose("02"), listener: [0.03, -0.02, 0])
        #expect(lines[1].state == .blocked)
        #expect(lines[1].text.hasPrefix("UWB Reader/Emitter 2: blocked"))
        #expect(lines[0].state == .unknown)
        #expect(lines[0].text.hasPrefix("UWB Reader/Emitter 1: no report yet, "))   // map distance from the listener
        // Without any pose the anchors still show, with no distance.
        let idle = UWBText.anchors(space: Self.space, pose: nil, listener: .zero)
        #expect(idle.map(\.text).first == "UWB Reader/Emitter 1: no report yet.")
    }

    @Test func anchorsTheHubReportsButSpaceLacksStillShow() {
        let lines = UWBText.anchors(space: nil, pose: Self.pose("01"), listener: .zero)
        #expect(lines.map(\.label) == ["UWB Reader/Emitter 1", "UWB Reader/Emitter 2", "UWB Reader/Emitter 3"])
        #expect(lines.allSatisfy { $0.position == nil && $0.state == .online })
    }

    @Test func modeBadgeAndStatusValue() {
        #expect(UWBText.mode(.tracked) == "Tracking")
        #expect(UWBText.mode(.frozen) == "Frozen at counter")
        #expect(UWBText.mode(.lost) == "Lost")
        #expect(UWBText.mode(.fixed) == "Fixed position")
        #expect(UWBText.mode(nil) == "Fixed position")
        #expect(UWBText.statusValue(pose: Self.pose("01"), anchorCount: 3) == "3/3 anchors \u{00B7} \u{00B1}0.06 m \u{00B7} Tracking")
        #expect(UWBText.statusValue(pose: Self.pose("02"), anchorCount: 3) == "2/3 anchors \u{00B7} \u{00B1}0.11 m \u{00B7} Frozen")
        #expect(UWBText.statusValue(pose: Self.pose("03"), anchorCount: 3) == "Fixed position")
        #expect(UWBText.statusValue(pose: nil, anchorCount: 0) == "Off - fixed position")
        #expect(UWBText.wearerLine(pose: Self.pose("01"), listener: [0, -2, 0]) == "You: tracking, 2.0 m from the counter mark.")
    }
}

@Suite struct CalibrationTests {
    @Test func centimetersFollowCalibratePyConvention() {
        // forward = +y, side = +x (right), height = +z (above ear level); meters, rounded to mm.
        #expect(Calibration.position(forwardCm: 75, sideCm: -90, heightCm: -25) == [-0.9, 0.75, -0.25])
        #expect(Calibration.position(forwardCm: -180.04, sideCm: -140, heightCm: 0) == [-1.4, -1.8, 0])
    }

    @Test func verdictUsesMedianAndMaxTargets() throws {
        let pass = try #require(Calibration.verdict(errorsM: [0.1, 0.05, 0.3, 0.2, 0.15]))
        #expect(pass.medianM == 0.15 && pass.maxM == 0.3 && pass.passed)
        let maxFail = try #require(Calibration.verdict(errorsM: [0.1, 0.1, 0.4]))       // max over 0.35
        #expect(!maxFail.passed)
        let medianFail = try #require(Calibration.verdict(errorsM: [0.25, 0.3, 0.1]))   // median over 0.20
        #expect(!medianFail.passed)
        let even = try #require(Calibration.verdict(errorsM: [0.1, 0.3]))
        #expect(abs(even.medianM - 0.2) < 1e-12)
        #expect(Calibration.verdict(errorsM: []) == nil)
        #expect(Calibration.marks.count == 5 && Calibration.marks[0].expected == .zero)
    }

    @Test func meanOfSamples() {
        #expect(Calibration.mean([]) == nil)
        #expect(Calibration.mean([[0, 0, 0], [1, -2, 0]]) == EarmarkPoint(0.5, -1, 0))
    }

    @Test func savingKeepsOtherFieldsAndABackup() throws {
        let dir = FileManager.default.temporaryDirectory.appendingPathComponent("earmark-cal-\(UUID().uuidString)")
        try FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)
        defer { try? FileManager.default.removeItem(at: dir) }
        let url = dir.appendingPathComponent("space.json")
        let original = """
        { "listener": { "label": "demo chair", "origin_note": "center of head, seated" },
          "spots": [ { "spot": 3, "label": "center right", "position": [0.16, 0.58, 0.0] } ],
          "areas": [], "receivers": [ { "receiver": "hub", "label": "the counter", "position": [0, 0.6, 0] } ] }
        """
        try Data(original.utf8).write(to: url)

        var space = try Calibration.read(url)
        space.anchors = Calibration.defaultAnchors()
        space.tracking = Tracking(phoneZ: -0.3, headOffsetM: 0.18)
        try Calibration.write(space, to: url)

        #expect(try String(contentsOf: url.appendingPathExtension("bak"), encoding: .utf8) == original)
        let text = try String(contentsOf: url, encoding: .utf8)
        #expect(text.contains("\"origin_note\"") && text.contains("\"phone_z\"") && text.contains("\"head_offset_m\""))
        let back = try Calibration.read(url)
        #expect(back.listener == space.listener && back.spots == space.spots && back.receivers == space.receivers)
        #expect(back.anchors?.map(\.label) == ["UWB Reader/Emitter 1", "UWB Reader/Emitter 2", "UWB Reader/Emitter 3"])
        #expect(back.tracking == Tracking(phoneZ: -0.3, headOffsetM: 0.18))

        try Calibration.write(back, to: url)                  // a second save replaces the old backup
        #expect(try String(contentsOf: url.appendingPathExtension("bak"), encoding: .utf8) == text)
    }
}
