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
public enum ObjectStatus: String, Codable, Sendable { case onSpot = "on_spot", missing }
public enum Component: String, Codable, Sendable {
    case hub, concierge, macApp = "mac_app", simulator, trialCli = "trial_cli", dashboard, cli, memoryAgent = "memory_agent", locator
}

// MARK: - Shared payloads

public struct Spot: Codable, Sendable, Equatable {
    public var spot: Int
    public var label: String
    public var position: Vec3
    /// containers[].container id, or nil for a free-standing spot (Amendment 01).
    public var container: String?
    /// Spoken on arrival, e.g. "Top shelf, front left." (Amendment 01).
    public var detail: String?
}

public struct Container: Codable, Sendable, Equatable {
    public var container: String
    public var label: String
    public var position: Vec3
}

public struct Beacon: Codable, Sendable, Equatable {
    public var beacon: String
    public var slot: Int
    public var position: Vec3
}

public struct Mat: Codable, Sendable, Equatable {
    public var position: Vec3
    public var forward: Vec3
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
    /// Ear position used after 5 s without a listener_pose (required on the wire; optional here for older call sites).
    public var fallbackPosition: Vec3?
}

public struct Space: Codable, Sendable, Equatable {
    public var listener: Listener
    public var spots: [Spot]
    public var areas: [Area]
    public var receivers: [Receiver]
    // Amendment 01 (walking room). Required on the wire; optional here for older call sites.
    public var mat: Mat?
    public var containers: [Container]?
    public var beacons: [Beacon]?
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
    public enum Reason: String, Codable, Sendable { case arrived, cancelled, timeout, reset }
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
    public var component: Component
    public var subscribe: [String]?
    public var t: Double
    public init(component: Component, subscribe: [String]? = nil, t: Double = BusCoding.now) {
        self.component = component; self.subscribe = subscribe; self.t = t
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
    public enum Event: String, Codable, Sendable { case behind, front, locked }
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

// MARK: - Amendment 01 (walking)

/// Locator -> bus, ~3 Hz. `position` is the user's EAR position in room coordinates.
public struct ListenerPose: Codable, Sendable, Equatable {
    public enum Quality: String, Codable, Sendable { case ok, degraded, lost }
    public enum Source: String, Codable, Sendable { case beacons, steps, sim, manual }
    public var position: Vec3
    public var quality: Quality
    public var beaconsHeard: Int
    public var source: Source
    public var t: Double
    public init(position: Vec3, quality: Quality, beaconsHeard: Int, source: Source, t: Double = BusCoding.now) {
        self.position = position; self.quality = quality; self.beaconsHeard = beaconsHeard; self.source = source; self.t = t
    }
}

/// Mac app -> bus: horizontal distance to the guided target < 0.45 m.
public struct Arrived: Codable, Sendable, Equatable {
    public var objectId: String
    public var t: Double
    public init(objectId: String, t: Double = BusCoding.now) { self.objectId = objectId; self.t = t }
}

/// Mac app -> bus: push-to-talk (AirPods stem press or Space).
public struct Ptt: Codable, Sendable, Equatable {
    public enum State: String, Codable, Sendable { case start, stop }
    public var state: State
    public var t: Double
    public init(state: State, t: Double = BusCoding.now) { self.state = state; self.t = t }
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
    case status(Status)
    case reset(Reset)
    case listenerPose(ListenerPose)
    case arrived(Arrived)
    case ptt(Ptt)
    /// A valid bus type this app does not act on (trial_*, save_spot).
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
        case .status: "status"
        case .reset: "reset"
        case .listenerPose: "listener_pose"
        case .arrived: "arrived"
        case .ptt: "ptt"
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
        case "status": self = .status(try one.decode(Status.self))
        case "reset": self = .reset(try one.decode(Reset.self))
        case "listener_pose": self = .listenerPose(try one.decode(ListenerPose.self))
        case "arrived": self = .arrived(try one.decode(Arrived.self))
        case "ptt": self = .ptt(try one.decode(Ptt.self))
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
        case .status(let m): try m.encode(to: encoder)
        case .reset(let m): try m.encode(to: encoder)
        case .listenerPose(let m): try m.encode(to: encoder)
        case .arrived(let m): try m.encode(to: encoder)
        case .ptt(let m): try m.encode(to: encoder)
        case .other: break
        }
    }
}
