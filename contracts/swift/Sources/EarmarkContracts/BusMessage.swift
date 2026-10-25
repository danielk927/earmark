import Foundation

// Swift mirror of contracts/schemas/bus_message.schema.json.
// Keys are snake_case on the wire; use BusCoding.decoder / BusCoding.encoder,
// which convert to and from Swift camelCase.

public enum BusCoding {
    public static let decoder: JSONDecoder = {
        let d = JSONDecoder()
        d.keyDecodingStrategy = .convertFromSnakeCase
        return d
    }()

    public static let encoder: JSONEncoder = {
        let e = JSONEncoder()
        e.keyEncodingStrategy = .convertToSnakeCase
        e.outputFormatting = [.sortedKeys]
        return e
    }()

    public static func decode(_ data: Data) throws -> BusMessage {
        try decoder.decode(BusMessage.self, from: data)
    }

    public static func encode(_ message: BusMessage) throws -> Data {
        try encoder.encode(message)
    }

    public static var now: Double { Date().timeIntervalSince1970 }
}

/// Earmark coordinates: meters, +x right, +y forward, +z up, origin = calibrated head position.
public typealias Vec3 = [Double]

public enum Precision: String, Codable, Sendable { case exact, area, proximity, none }
public enum DistanceClass: String, Codable, Sendable { case near, mid, far }
public enum ObjectStatus: String, Codable, Sendable { case onSpot = "on_spot", held, missing, roaming }
public enum Component: String, Codable, Sendable {
    case hub, concierge, macApp = "mac_app", simulator, trialCli = "trial_cli", dashboard, cli, memoryAgent = "memory_agent", locator,
         iosAnchor = "ios_anchor", iosWearer = "ios_wearer"
}

// MARK: - Shared payloads

public struct Spot: Codable, Sendable, Equatable {
    public var spot: Int
    public var label: String
    public var position: Vec3
}

public struct Area: Codable, Sendable, Equatable {
    public var area: String
    public var label: String?
    public var position: Vec3
}

public struct Receiver: Codable, Sendable, Equatable {
    public var receiver: String
    public var label: String
    public var position: Vec3?
}

public struct Listener: Codable, Sendable, Equatable {
    public var label: String
    public var originNote: String
}

/// A fixed UWB anchor iPhone ("UWB Reader/Emitter N"), measured from the origin floor mark.
public struct Anchor: Codable, Sendable, Equatable {
    public var anchor: String
    public var label: String
    public var position: Vec3
    public init(anchor: String, label: String, position: Vec3) {
        self.anchor = anchor; self.label = label; self.position = position
    }
}

/// Wearer geometry set by calibration (overrides the hub's defaults).
public struct Tracking: Codable, Sendable, Equatable {
    public var phoneZ: Double?
    public var headOffsetM: Double?
    /// Ear height in the room frame (floor = 0); the UWB listener_pose z.
    public var earZM: Double?
    /// Height given to a tap-marked object when the tracker is 2D.
    public var markZM: Double?
    public init(phoneZ: Double? = nil, headOffsetM: Double? = nil, earZM: Double? = nil, markZM: Double? = nil) {
        self.phoneZ = phoneZ; self.headOffsetM = headOffsetM; self.earZM = earZM; self.markZM = markZM
    }
}

public struct Space: Codable, Sendable, Equatable {
    public var listener: Listener
    public var spots: [Spot]
    public var areas: [Area]
    public var receivers: [Receiver]
    /// Optional: UWB anchors for walking guidance.
    public var anchors: [Anchor]?
    /// Optional: wearer phone height / head offset.
    public var tracking: Tracking?
}

public struct RegistryObject: Codable, Sendable, Equatable, Identifiable {
    public var objectId: String
    public var name: String
    public var aliases: [String]
    public var notes: String
    public var description: String
    public var tag: String?
    public var homeSpot: Int?
    public var isMedication: Bool
    public var fobId: String?
    public var id: String { objectId }
}

public struct Location: Codable, Sendable, Equatable {
    public var spot: Int?
    public var position: Vec3?
    public var area: String?
    public var near: String?
    public var distanceClass: DistanceClass?
}

public struct ObjectState: Codable, Sendable, Equatable {
    public var objectId: String
    public var location: Location
    public var precision: Precision
    public var status: ObjectStatus
    public var homeSpot: Int?
    public var lastSeenT: Double?
    public var source: String
    public var t: Double
}

/// Untyped JSON scalar for `status.info`.
public enum JSONScalar: Codable, Sendable, Equatable {
    case string(String), number(Double), bool(Bool), null

    public init(from decoder: Decoder) throws {
        let c = try decoder.singleValueContainer()
        if c.decodeNil() { self = .null }
        else if let b = try? c.decode(Bool.self) { self = .bool(b) }
        else if let n = try? c.decode(Double.self) { self = .number(n) }
        else { self = .string(try c.decode(String.self)) }
    }

    public func encode(to encoder: Encoder) throws {
        var c = encoder.singleValueContainer()
        switch self {
        case .string(let s): try c.encode(s)
        case .number(let n): try c.encode(n)
        case .bool(let b): try c.encode(b)
        case .null: try c.encodeNil()
        }
    }
}

// MARK: - Messages the Mac app receives

public struct Household: Codable, Sendable, Equatable {
    public var name: String
    public var timezone: String
}

public struct Snapshot: Codable, Sendable {
    public var space: Space
    public var objects: [RegistryObject]
    public var states: [ObjectState]
    public var registryVersion: Double?
    public var t: Double
    /// Required on the wire; optional here so older call sites keep compiling.
    public var household: Household?
}

public struct RegistryUpdate: Codable, Sendable {
    public var objects: [RegistryObject]
    public var registryVersion: Double?
    public var t: Double
}

public struct GuideStart: Codable, Sendable, Equatable {
    public var objectId: String
    public var name: String
    public var targetPosition: Vec3
    public var precision: Precision
    public var utteranceId: String
    public var t: Double
}

public struct GuideStop: Codable, Sendable, Equatable {
    public enum Reason: String, Codable, Sendable { case found, cancelled, timeout, reset }
    public var reason: Reason
    public var objectId: String?
    public var t: Double
}

public struct Speak: Codable, Sendable {
    public enum Format: String, Codable, Sendable { case pcmS16le = "pcm_s16le", pcmF32le = "pcm_f32le" }
    public var utteranceId: String
    public var seq: Int
    public var format: Format
    public var sampleRate: Int
    public var chunkB64: String
    public var final: Bool
    public var text: String?
    public var t: Double
}

public struct SpeakCached: Codable, Sendable, Equatable {
    public var phraseId: String
    public var utteranceId: String
    public var text: String
    public var t: Double
}

public struct SpeakText: Codable, Sendable, Equatable {
    public var utteranceId: String
    public var text: String
    public var t: Double
}

public struct SttMode: Codable, Sendable, Equatable {
    public enum Engine: String, Codable, Sendable { case cartesia, apple }
    public var engine: Engine
    public var reason: String
    public var t: Double
}

// MARK: - Messages the Mac app sends

public struct Hello: Codable, Sendable, Equatable {
    public enum Role: String, Codable, Sendable { case anchor, wearer }
    public var component: Component
    public var subscribe: [String]?
    /// iPhone clients: "uwb_1" | "uwb_2" | "uwb_3" | "wearer". Used for addressed uwb_token delivery.
    public var deviceId: String?
    public var role: Role?
    /// EARMARK_BUS_SECRET. Required when connecting from a non-loopback address.
    public var secret: String?
    public var t: Double
    public init(component: Component, subscribe: [String]? = nil, deviceId: String? = nil, role: Role? = nil,
                secret: String? = nil, t: Double = BusCoding.now) {
        self.component = component; self.subscribe = subscribe; self.deviceId = deviceId; self.role = role
        self.secret = secret; self.t = t
    }
}

public struct MicAudio: Codable, Sendable, Equatable {
    public var seq: Int
    public var sampleRate: Int
    public var encoding: String
    public var chunkB64: String
    public var t: Double
    public init(seq: Int, sampleRate: Int, chunkB64: String, t: Double = BusCoding.now) {
        self.seq = seq; self.sampleRate = sampleRate; self.encoding = "pcm_s16le"; self.chunkB64 = chunkB64; self.t = t
    }
}

public struct Transcript: Codable, Sendable, Equatable {
    public enum Source: String, Codable, Sendable { case cartesia, apple, typed }
    public var text: String
    public var isFinal: Bool
    public var source: Source
    public var t: Double
    public init(text: String, isFinal: Bool, source: Source, t: Double = BusCoding.now) {
        self.text = text; self.isFinal = isFinal; self.source = source; self.t = t
    }
}

public struct GuideFeedback: Codable, Sendable, Equatable {
    public enum Event: String, Codable, Sendable { case behind, front, locked, arrived }
    public enum Turn: String, Codable, Sendable { case left, right }
    public var objectId: String
    public var event: Event
    public var turn: Turn?
    public var errorDeg: Double
    public var t: Double
    public init(objectId: String, event: Event, turn: Turn?, errorDeg: Double, t: Double = BusCoding.now) {
        self.objectId = objectId; self.event = event; self.turn = turn; self.errorDeg = errorDeg; self.t = t
    }
    // `turn` is required-nullable in the schema, so encode an explicit null.
    private enum CodingKeys: String, CodingKey { case objectId, event, turn, errorDeg, t }
    public func encode(to encoder: Encoder) throws {
        var c = encoder.container(keyedBy: CodingKeys.self)
        try c.encode(objectId, forKey: .objectId)
        try c.encode(event, forKey: .event)
        try c.encode(turn, forKey: .turn)
        try c.encode(errorDeg, forKey: .errorDeg)
        try c.encode(t, forKey: .t)
    }
}

public struct Playback: Codable, Sendable, Equatable {
    public enum Event: String, Codable, Sendable { case started, finished, interrupted }
    public var utteranceId: String
    public var event: Event
    public var t: Double
    public init(utteranceId: String, event: Event, t: Double = BusCoding.now) {
        self.utteranceId = utteranceId; self.event = event; self.t = t
    }
}

public struct HeadPose: Codable, Sendable, Equatable {
    public var yaw: Double
    public var pitch: Double
    public var t: Double
    public init(yaw: Double, pitch: Double, t: Double = BusCoding.now) {
        self.yaw = yaw; self.pitch = pitch; self.t = t
    }
}

public struct Ptt: Codable, Sendable, Equatable {
    public enum State: String, Codable, Sendable { case start, stop }
    public var state: State
    public var t: Double
    public init(state: State, t: Double = BusCoding.now) { self.state = state; self.t = t }
}

public struct Status: Codable, Sendable, Equatable {
    public var component: Component
    public var ok: Bool
    public var detail: String
    public var info: [String: JSONScalar]?
    public var t: Double
    public init(component: Component, ok: Bool, detail: String, info: [String: JSONScalar]? = nil, t: Double = BusCoding.now) {
        self.component = component; self.ok = ok; self.detail = detail; self.info = info; self.t = t
    }
}

public struct Reset: Codable, Sendable, Equatable {
    public var t: Double
    public init(t: Double = BusCoding.now) { self.t = t }
}

// MARK: - Messages the Mac app only observes (kept for the map/debug panel)

public struct Pickup: Codable, Sendable, Equatable {
    public var objectId: String
    public var fromSpot: Int
    public var t: Double
}

public struct PickupResult: Codable, Sendable, Equatable {
    public var expected: String
    public var actual: String
    public var correct: Bool
    public var t: Double
}

// MARK: - UWB walking guidance

/// iPhone -> hub -> iPhone. A Nearby Interaction discovery token, NSKeyedArchiver (secure coding), base64.
public struct UwbToken: Codable, Sendable, Equatable {
    public var from: String
    public var to: String
    public var tokenB64: String
    public var t: Double
    public init(from: String, to: String, tokenB64: String, t: Double = BusCoding.now) {
        self.from = from; self.to = to; self.tokenB64 = tokenB64; self.t = t
    }
}

/// Wearer -> hub. One distance to an anchor, meters.
public struct UwbRange: Codable, Sendable, Equatable {
    public var anchor: String
    public var distanceM: Double
    public var seq: Int
    public var t: Double
    public init(anchor: String, distanceM: Double, seq: Int, t: Double = BusCoding.now) {
        self.anchor = anchor; self.distanceM = distanceM; self.seq = seq; self.t = t
    }
}

/// Wearer -> hub. Moving vs still (CoreMotion).
public struct MotionState: Codable, Sendable, Equatable {
    public enum State: String, Codable, Sendable { case moving, still }
    public var state: State
    public var t: Double
    public init(state: State, t: Double = BusCoding.now) { self.state = state; self.t = t }
}

public enum ListenerMode: String, Codable, Sendable { case tracked, frozen, lost, fixed }
public enum PoseSource: String, Codable, Sendable { case beacons, uwb, sound, steps, sim, manual, none }

public struct AnchorHealth: Codable, Sendable, Equatable {
    public var anchor: String
    public var online: Bool
    public var distanceM: Double?
    public init(anchor: String, online: Bool, distanceM: Double?) {
        self.anchor = anchor; self.online = online; self.distanceM = distanceM
    }
    private enum CodingKeys: String, CodingKey { case anchor, online, distanceM }
    // `distance_m` is required-nullable in the schema, so encode an explicit null.
    public func encode(to encoder: Encoder) throws {
        var c = encoder.container(keyedBy: CodingKeys.self)
        try c.encode(anchor, forKey: .anchor)
        try c.encode(online, forKey: .online)
        try c.encode(distanceM, forKey: .distanceM)
    }
}

/// Locator or hub -> bus. Where the listener's ears are, room frame. One shape for both producers: the beacon
/// locator sends `beaconsHeard`; the UWB tracker sends `mode`, `residualM`, `anchorsUsed`, `blocked`, `anchors`.
/// Consumers only need `position` and `quality`.
public struct ListenerPose: Codable, Sendable, Equatable {
    public enum Quality: String, Codable, Sendable { case ok, degraded, lost }
    public var position: Vec3
    public var quality: Quality
    public var source: PoseSource
    public var beaconsHeard: Int?
    public var mode: ListenerMode?
    public var residualM: Double?
    public var anchorsUsed: Int?
    public var blocked: [String]?
    public var anchors: [AnchorHealth]?
    public var t: Double
    public init(position: Vec3, quality: Quality, source: PoseSource, beaconsHeard: Int? = nil, mode: ListenerMode? = nil,
                residualM: Double? = nil, anchorsUsed: Int? = nil, blocked: [String]? = nil, anchors: [AnchorHealth]? = nil,
                t: Double = BusCoding.now) {
        self.position = position; self.quality = quality; self.source = source; self.beaconsHeard = beaconsHeard
        self.mode = mode; self.residualM = residualM; self.anchorsUsed = anchorsUsed; self.blocked = blocked
        self.anchors = anchors; self.t = t
    }
}

/// Concierge or Mac app -> bus. freeze = "I'm here"; recenter = re-zero AirPods yaw.
public struct ListenerCommand: Codable, Sendable, Equatable {
    public enum Action: String, Codable, Sendable { case freeze, recenter }
    public var action: Action
    public var t: Double
    public init(action: Action, t: Double = BusCoding.now) { self.action = action; self.t = t }
}

/// Wearer iPhone or concierge -> hub. The phone was tapped next to an object; carries no data.
public struct ObjectTap: Codable, Sendable, Equatable {
    public var t: Double
    public init(t: Double = BusCoding.now) { self.t = t }
}

/// Hub -> bus, the answer to object_tap: where the phone was (room frame), or ok == false.
public struct TapPosition: Codable, Sendable, Equatable {
    public var ok: Bool
    public var position: Vec3?
    public var source: PoseSource
    public var t: Double
    public init(ok: Bool, position: Vec3? = nil, source: PoseSource, t: Double = BusCoding.now) {
        self.ok = ok; self.position = position; self.source = source; self.t = t
    }
}

// MARK: - Union

public enum BusMessage: Sendable {
    case hello(Hello)
    case snapshot(Snapshot)
    case registryUpdate(RegistryUpdate)
    case stateUpdate(ObjectState)
    case guideStart(GuideStart)
    case guideStop(GuideStop)
    case guideFeedback(GuideFeedback)
    case speak(Speak)
    case speakCached(SpeakCached)
    case speakText(SpeakText)
    case sttMode(SttMode)
    case micAudio(MicAudio)
    case transcript(Transcript)
    case playback(Playback)
    case headPose(HeadPose)
    case listenerPose(ListenerPose)
    case ptt(Ptt)
    case status(Status)
    case reset(Reset)
    case pickup(Pickup)
    case pickupResult(PickupResult)
    case uwbToken(UwbToken)
    case uwbRange(UwbRange)
    case motionState(MotionState)
    case listenerCommand(ListenerCommand)
    case objectTap(ObjectTap)
    case tapPosition(TapPosition)
    /// A valid bus type this app does not act on (detection, chirp, trial_*, label, unknown_tag).
    case other(type: String)

    public var type: String {
        switch self {
        case .hello: "hello"
        case .snapshot: "snapshot"
        case .registryUpdate: "registry_update"
        case .stateUpdate: "state_update"
        case .guideStart: "guide_start"
        case .guideStop: "guide_stop"
        case .guideFeedback: "guide_feedback"
        case .speak: "speak"
        case .speakCached: "speak_cached"
        case .speakText: "speak_text"
        case .sttMode: "stt_mode"
        case .micAudio: "mic_audio"
        case .transcript: "transcript"
        case .playback: "playback"
        case .headPose: "head_pose"
        case .listenerPose: "listener_pose"
        case .ptt: "ptt"
        case .status: "status"
        case .reset: "reset"
        case .pickup: "pickup"
        case .pickupResult: "pickup_result"
        case .uwbToken: "uwb_token"
        case .uwbRange: "uwb_range"
        case .motionState: "motion_state"
        case .listenerCommand: "listener_command"
        case .objectTap: "object_tap"
        case .tapPosition: "tap_position"
        case .other(let type): type
        }
    }
}

extension BusMessage: Codable {
    private enum TypeKey: String, CodingKey { case type }

    public init(from decoder: Decoder) throws {
        let type = try decoder.container(keyedBy: TypeKey.self).decode(String.self, forKey: .type)
        let one = try decoder.singleValueContainer()
        switch type {
        case "hello": self = .hello(try one.decode(Hello.self))
        case "snapshot": self = .snapshot(try one.decode(Snapshot.self))
        case "registry_update": self = .registryUpdate(try one.decode(RegistryUpdate.self))
        case "state_update": self = .stateUpdate(try one.decode(ObjectState.self))
        case "guide_start": self = .guideStart(try one.decode(GuideStart.self))
        case "guide_stop": self = .guideStop(try one.decode(GuideStop.self))
        case "guide_feedback": self = .guideFeedback(try one.decode(GuideFeedback.self))
        case "speak": self = .speak(try one.decode(Speak.self))
        case "speak_cached": self = .speakCached(try one.decode(SpeakCached.self))
        case "speak_text": self = .speakText(try one.decode(SpeakText.self))
        case "stt_mode": self = .sttMode(try one.decode(SttMode.self))
        case "mic_audio": self = .micAudio(try one.decode(MicAudio.self))
        case "transcript": self = .transcript(try one.decode(Transcript.self))
        case "playback": self = .playback(try one.decode(Playback.self))
        case "head_pose": self = .headPose(try one.decode(HeadPose.self))
        case "listener_pose": self = .listenerPose(try one.decode(ListenerPose.self))
        case "ptt": self = .ptt(try one.decode(Ptt.self))
        case "status": self = .status(try one.decode(Status.self))
        case "reset": self = .reset(try one.decode(Reset.self))
        case "pickup": self = .pickup(try one.decode(Pickup.self))
        case "pickup_result": self = .pickupResult(try one.decode(PickupResult.self))
        case "uwb_token": self = .uwbToken(try one.decode(UwbToken.self))
        case "uwb_range": self = .uwbRange(try one.decode(UwbRange.self))
        case "motion_state": self = .motionState(try one.decode(MotionState.self))
        case "listener_command": self = .listenerCommand(try one.decode(ListenerCommand.self))
        case "object_tap": self = .objectTap(try one.decode(ObjectTap.self))
        case "tap_position": self = .tapPosition(try one.decode(TapPosition.self))
        default: self = .other(type: type)
        }
    }

    public func encode(to encoder: Encoder) throws {
        var tc = encoder.container(keyedBy: TypeKey.self)
        try tc.encode(type, forKey: .type)
        switch self {
        case .hello(let m): try m.encode(to: encoder)
        case .snapshot(let m): try m.encode(to: encoder)
        case .registryUpdate(let m): try m.encode(to: encoder)
        case .stateUpdate(let m): try m.encode(to: encoder)
        case .guideStart(let m): try m.encode(to: encoder)
        case .guideStop(let m): try m.encode(to: encoder)
        case .guideFeedback(let m): try m.encode(to: encoder)
        case .speak(let m): try m.encode(to: encoder)
        case .speakCached(let m): try m.encode(to: encoder)
        case .speakText(let m): try m.encode(to: encoder)
        case .sttMode(let m): try m.encode(to: encoder)
        case .micAudio(let m): try m.encode(to: encoder)
        case .transcript(let m): try m.encode(to: encoder)
        case .playback(let m): try m.encode(to: encoder)
        case .headPose(let m): try m.encode(to: encoder)
        case .listenerPose(let m): try m.encode(to: encoder)
        case .ptt(let m): try m.encode(to: encoder)
        case .status(let m): try m.encode(to: encoder)
        case .reset(let m): try m.encode(to: encoder)
        case .pickup(let m): try m.encode(to: encoder)
        case .pickupResult(let m): try m.encode(to: encoder)
        case .uwbToken(let m): try m.encode(to: encoder)
        case .uwbRange(let m): try m.encode(to: encoder)
        case .motionState(let m): try m.encode(to: encoder)
        case .listenerCommand(let m): try m.encode(to: encoder)
        case .objectTap(let m): try m.encode(to: encoder)
        case .tapPosition(let m): try m.encode(to: encoder)
        case .other: break
        }
    }
}
