import EarmarkContracts
import Foundation
import simd

/// Words for UWB walking guidance shown in the status bar, the map, and its text list (PRD 10.4, 10.5).
/// State is always spelled out in text, never color alone.
public enum UWBText {
    /// The map's mode badge.
    public static func mode(_ m: ListenerMode?) -> String {
        switch m {
        case .tracked?: "Tracking"
        case .frozen?: "Frozen at counter"
        case .lost?: "Lost"
        case .fixed?, nil: "Fixed position"
        }
    }

    /// Status bar value, e.g. "3/3 anchors · ±0.06 m · Frozen". `anchorCount` = anchors in space.json (0 if unknown).
    public static func statusValue(pose: ListenerPose?, anchorCount: Int) -> String {
        guard let pose, pose.mode != .fixed else { return pose == nil ? "Off - fixed position" : "Fixed position" }
        // A pose without a mode comes from the beacon / sound locator, not the UWB tracker: no anchors to count.
        guard pose.mode != nil else { return "Locator (\(pose.source.rawValue), \(pose.quality.rawValue))" }
        let used = pose.anchorsUsed ?? 0
        let total = max(anchorCount, pose.anchors?.count ?? 0, used)
        var parts = ["\(used)/\(total) anchors"]
        if let r = pose.residualM { parts.append(String(format: "\u{00B1}%.2f m", r)) }
        parts.append(pose.mode == .frozen ? "Frozen" : mode(pose.mode))
        return parts.joined(separator: " \u{00B7} ")
    }

    public enum AnchorState: String, Sendable { case online, blocked, offline, unknown }

    public struct AnchorLine: Equatable, Sendable, Identifiable {
        public var id: String
        public var label: String
        public var position: EarmarkPoint?
        public var state: AnchorState
        /// Measured range from the wearer when the hub reports one, else the map distance from the listener.
        public var distanceM: Double?

        /// "UWB Reader/Emitter 1: online, 2.4 m from you."
        public var text: String {
            let what: String
            switch state {
            case .online: what = "online"
            case .blocked: what = "blocked (something is between it and the wearer)"
            case .offline: what = "offline"
            case .unknown: what = "no report yet"
            }
            let dist = distanceM.map { String(format: ", %.1f m from you", $0) } ?? ""
            return "\(label): \(what)\(dist)."
        }
    }

    /// Anchors from space.json, plus any the hub reports that space.json does not list, in id order.
    public static func anchors(space: Space?, pose: ListenerPose?, listener: EarmarkPoint) -> [AnchorLine] {
        let configured = space?.anchors ?? []
        var ids = configured.map(\.anchor)
        for h in pose?.anchors ?? [] where !ids.contains(h.anchor) { ids.append(h.anchor) }
        let tracked = pose.map { $0.mode != .fixed } ?? false
        return ids.sorted().map { id in
            let a = configured.first { $0.anchor == id }
            let health = pose?.anchors?.first { $0.anchor == id }
            let position = a.flatMap { Geometry.point($0.position) }
            let state: AnchorState
            if pose?.blocked?.contains(id) == true { state = .blocked }
            else if let health { state = health.online ? .online : .offline }
            else { state = .unknown }
            var distance = health?.online == true ? health?.distanceM : nil
            if distance == nil, tracked, let position { distance = Geometry.horizontalDistance(position, from: listener) }
            return AnchorLine(id: id, label: a?.label ?? defaultLabel(id), position: position, state: state, distanceM: distance)
        }
    }

    /// "uwb_2" -> "UWB Reader/Emitter 2".
    public static func defaultLabel(_ id: String) -> String {
        id.hasPrefix("uwb_") ? "UWB Reader/Emitter " + String(id.dropFirst(4)) : id
    }

    /// The wearer line under the map.
    public static func wearerLine(pose: ListenerPose?, listener: EarmarkPoint) -> String {
        let fromMark = String(format: "%.1f m from the counter mark", Geometry.horizontalDistance(listener))
        if let pose, pose.mode == nil { return "You: located by the \(pose.source.rawValue) locator, \(fromMark)." }
        switch pose?.mode {
        case nil: return "You: fixed position at the counter mark (no walking tracker)."
        case .fixed?: return "You: fixed position at the counter mark."
        case .frozen?: return "You: frozen at the counter, \(fromMark)."
        case .tracked?: return "You: tracking, \(fromMark)."
        case .lost?: return "You: lost, last seen \(fromMark)."
        }
    }
}

/// Pure pieces of the UWB calibration screen (PRD 10.6): verify marks, pass/fail, writing space.json.
public enum Calibration {
    /// listener_pose samples are averaged over this long at each mark.
    public static let verifySeconds = 2.0
    /// PRD section 3: static position error at 5 floor marks.
    public static let medianTargetM = 0.20
    public static let maxTargetM = 0.35
    /// PRD section 5 defaults (also the hub's).
    /// Phone height RELATIVE TO THE EARS (schema rule: tracking.phone_z).
    public static let defaultPhoneZ = -0.35
    public static let defaultHeadOffsetM = 0.20
    /// Room frame (floor = 0): ear height and tap-marked table-top height, meters above the floor.
    public static let defaultEarZM = 1.55
    public static let defaultMarkZM = 0.9

    public struct Mark: Identifiable, Sendable, Equatable {
        public var id: String
        public var name: String
        public var expected: EarmarkPoint
        public var instruction: String
    }

    public static let marks: [Mark] = [
        Mark(id: "origin", name: "Origin mark", expected: [0, 0, 0],
             instruction: "Stand on the origin mark, facing the counter, and press Verify."),
        Mark(id: "back1", name: "1 m back", expected: [0, -1, 0],
             instruction: "Stand on the mark 1 m back from the origin, facing the counter, and press Verify."),
        Mark(id: "back2", name: "2 m back", expected: [0, -2, 0],
             instruction: "Stand on the mark 2 m back from the origin, facing the counter, and press Verify."),
        Mark(id: "left1", name: "1 m left", expected: [-1, 0, 0],
             instruction: "Stand on the mark 1 m to the left of the origin, facing the counter, and press Verify."),
        Mark(id: "right1", name: "1 m right", expected: [1, 0, 0],
             instruction: "Stand on the mark 1 m to the right of the origin, facing the counter, and press Verify."),
    ]

    public struct Verdict: Sendable, Equatable {
        public var medianM: Double
        public var maxM: Double
        public var passed: Bool { medianM <= Calibration.medianTargetM && maxM <= Calibration.maxTargetM }
    }

    /// Horizontal errors in meters -> median and max against the PRD targets; nil when empty.
    public static func verdict(errorsM: [Double]) -> Verdict? {
        guard !errorsM.isEmpty else { return nil }
        let s = errorsM.sorted()
        let mid = s.count / 2
        let median = s.count % 2 == 1 ? s[mid] : (s[mid - 1] + s[mid]) / 2
        return Verdict(medianM: median, maxM: s.last!)
    }

    public static func mean(_ points: [EarmarkPoint]) -> EarmarkPoint? {
        guard !points.isEmpty else { return nil }
        return points.reduce(EarmarkPoint.zero, +) / Double(points.count)
    }

    /// PRD 9.1 placeholders, used until the anchors are measured. z is meters above the floor.
    public static func defaultAnchors() -> [Anchor] {
        [Anchor(anchor: "uwb_1", label: "UWB Reader/Emitter 1", position: [-0.9, 0.75, 1.3]),
         Anchor(anchor: "uwb_2", label: "UWB Reader/Emitter 2", position: [0.9, 0.75, 1.3]),
         Anchor(anchor: "uwb_3", label: "UWB Reader/Emitter 3", position: [-1.4, -1.8, 1.3])]
    }

    /// Same as scripts/calibrate.py: cm from the floor origin mark, forward = +y (behind is negative),
    /// side = +x to the right (left is negative), height = +z ABOVE THE FLOOR (room frame). Rounded to mm.
    public static func position(forwardCm: Double, sideCm: Double, heightCm: Double) -> [Double] {
        [sideCm, forwardCm, heightCm].map { ($0 * 10).rounded() / 1000 }
    }

    /// One anchor as shown in the form: centimeters, height above the floor.
    public struct AnchorRow: Identifiable, Equatable, Sendable {
        public var id: String
        public var label: String
        public var forwardCm: Double
        public var sideCm: Double
        public var heightCm: Double
        public init(id: String, label: String, forwardCm: Double, sideCm: Double, heightCm: Double) {
            self.id = id; self.label = label; self.forwardCm = forwardCm; self.sideCm = sideCm; self.heightCm = heightCm
        }
    }

    /// Everything the calibration form edits, in centimeters.
    public struct Form: Equatable, Sendable {
        public var anchors: [AnchorRow]
        /// Phone height relative to the ears (negative = below), as tracking.phone_z.
        public var phoneZCm: Double
        public var headOffsetCm: Double
        /// Ear and table-top height above the floor.
        public var earZCm: Double
        public var markZCm: Double
        public init(anchors: [AnchorRow], phoneZCm: Double, headOffsetCm: Double, earZCm: Double, markZCm: Double) {
            self.anchors = anchors; self.phoneZCm = phoneZCm; self.headOffsetCm = headOffsetCm
            self.earZCm = earZCm; self.markZCm = markZCm
        }
        /// Phone height above the floor implied by the ear height and the relative phone height.
        public var phoneAboveFloorCm: Double { ((earZCm + phoneZCm) * 10).rounded() / 10 }
    }

    static func cm(_ m: Double) -> Double { (m * 1000).rounded() / 10 }

    /// Fills the form from a space (nil or missing parts fall back to the defaults). Anchor z is already floor-based.
    public static func form(from space: Space?) -> Form {
        let list = (space?.anchors).flatMap { $0.isEmpty ? nil : $0 } ?? defaultAnchors()
        let rows = list.map { a -> AnchorRow in
            let p = Geometry.point(a.position) ?? .zero
            return AnchorRow(id: a.anchor, label: a.label, forwardCm: cm(p.y), sideCm: cm(p.x), heightCm: cm(p.z))
        }
        let t = space?.tracking
        return Form(anchors: rows, phoneZCm: cm(t?.phoneZ ?? defaultPhoneZ),
                    headOffsetCm: cm(t?.headOffsetM ?? defaultHeadOffsetM),
                    earZCm: cm(t?.earZM ?? defaultEarZM), markZCm: cm(t?.markZM ?? defaultMarkZM))
    }

    /// Writes the form into a space (other fields untouched). Anchor z = height above the floor; phone_z stays ear-relative.
    public static func apply(_ form: Form, to space: Space) -> Space {
        var out = space
        out.anchors = form.anchors.map {
            Anchor(anchor: $0.id, label: $0.label,
                   position: position(forwardCm: $0.forwardCm, sideCm: $0.sideCm, heightCm: $0.heightCm))
        }
        func m(_ c: Double) -> Double { (c * 10).rounded() / 1000 }
        out.tracking = Tracking(phoneZ: m(form.phoneZCm), headOffsetM: m(form.headOffsetCm),
                                earZM: m(form.earZCm), markZM: m(form.markZCm))
        return out
    }

    /// Pretty, sorted, snake_case JSON (the hub reads space.json with the same field names as the bus).
    public static func encode(_ space: Space) throws -> Data {
        let e = JSONEncoder()
        e.keyEncodingStrategy = .convertToSnakeCase
        e.outputFormatting = [.prettyPrinted, .sortedKeys, .withoutEscapingSlashes]
        return try e.encode(space) + Data("\n".utf8)
    }

    /// Writes space.json, keeping the previous file as space.json.bak (like scripts/calibrate.py).
    public static func write(_ space: Space, to url: URL) throws {
        let data = try encode(space)
        let fm = FileManager.default
        if fm.fileExists(atPath: url.path) {
            let bak = url.appendingPathExtension("bak")
            if fm.fileExists(atPath: bak.path) { try fm.removeItem(at: bak) }
            try fm.copyItem(at: url, to: bak)
        }
        try data.write(to: url, options: .atomic)
    }

    /// Reads and decodes space.json (snake_case).
    public static func read(_ url: URL) throws -> Space {
        try BusCoding.decoder.decode(Space.self, from: Data(contentsOf: url))
    }
}
