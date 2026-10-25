import Foundation

public enum LocatorError: Error, LocalizedError {
    case invalid(String)
    public var errorDescription: String? {
        switch self { case .invalid(let reason): return reason }
    }
}

public struct Vector3: Codable, Equatable, Sendable {
    public var x: Double
    public var y: Double
    public var z: Double
    public init(_ x: Double, _ y: Double, _ z: Double) { self.x = x; self.y = y; self.z = z }
    public static let zero = Vector3(0, 0, 0)
    public var values: [Double] { [x, y, z] }
    public var norm: Double { sqrt(x * x + y * y + z * z) }
    public static func + (a: Self, b: Self) -> Self { Self(a.x + b.x, a.y + b.y, a.z + b.z) }
    public static func - (a: Self, b: Self) -> Self { Self(a.x - b.x, a.y - b.y, a.z - b.z) }
    public static func * (a: Self, b: Double) -> Self { Self(a.x * b, a.y * b, a.z * b) }
    public init(from decoder: Decoder) throws {
        let v = try decoder.singleValueContainer().decode([Double].self)
        guard v.count == 3, v.allSatisfy(\.isFinite) else { throw LocatorError.invalid("Position must be three finite numbers") }
        self.init(v[0], v[1], v[2])
    }
    public func encode(to encoder: Encoder) throws { var c = encoder.singleValueContainer(); try c.encode(values) }
}

public struct Beacon: Codable, Equatable, Identifiable, Sendable {
    public var id: String
    public var position: Vector3
    public var slot: Int
    public init(id: String, position: Vector3, slot: Int) { self.id = id; self.position = position; self.slot = slot }
    public static let defaults: [Beacon] = [
        Beacon(id: "B1", position: Vector3(-1.5, 1.5, 1.8), slot: 0),
        Beacon(id: "B2", position: Vector3(1.5, 1.5, 0.3), slot: 1),
        Beacon(id: "B3", position: Vector3(1.5, -1.5, 1.8), slot: 2),
        Beacon(id: "B4", position: Vector3(-1.5, -1.5, 0.3), slot: 3),
        Beacon(id: "B5", position: Vector3(-1.8, 0, 1), slot: 4)
    ]
    public static func importing(_ data: Data) throws -> [Beacon] {
        struct Space: Decodable { let beacons: [Beacon] }
        let beacons = try JSONDecoder().decode(Space.self, from: data).beacons
        try validate(beacons)
        return beacons.sorted { $0.slot < $1.slot }
    }
    public static func validate(_ beacons: [Beacon]) throws {
        guard beacons.count == 5, Set(beacons.map(\.id)) == Set(defaults.map(\.id)),
              Set(beacons.map(\.slot)) == Set(0..<5),
              beacons.allSatisfy({ $0.id == "B\($0.slot + 1)" && $0.position.values.allSatisfy(\.isFinite) }) else {
            throw LocatorError.invalid("Require B1–B5 in slots 0–4 with finite positions")
        }
        guard Set(beacons.map { "\($0.position)" }).count == 5 else { throw LocatorError.invalid("Beacon positions must be distinct") }
    }
}

public struct ChirpConfig: Codable, Equatable, Sendable {
    public struct Marker: Codable, Equatable, Sendable {
        public var beacon = "B1"
        public var direction = "down"
    }
    public var f_lo = 2000.0
    public var f_hi = 4500.0
    public var length_ms = 12.0
    public var slot_ms = 50.0
    public var n_slots = 6
    public var marker = Marker()
    public var others_direction = "up"
    public var version = 1
    public init() {}
    public var duration: Double { length_ms / 1000 }
    public var slot: Double { slot_ms / 1000 }
    public var cycle: Double { slot * Double(n_slots) }
    public func validate() throws {
        guard (1000...20000).contains(f_lo), (1000...20000).contains(f_hi), f_hi - f_lo >= 1000,
              (5...40).contains(length_ms), (30...100).contains(slot_ms), length_ms < slot_ms - 5,
              n_slots == 6, marker.beacon == "B1", marker.direction == "down", others_direction == "up", version == 1 else {
            throw LocatorError.invalid("Invalid chirp: 1–20 kHz, ≥1 kHz span, 5–40 ms length shorter than slot − 5 ms, 30–100 ms slots, six slots, B1 down")
        }
    }
}

public enum CarryMode: String, Codable, CaseIterable, Sendable { case hand, pocket }
public enum HubAuth: String, Codable, CaseIterable, Sendable { case native, query, hello }

public struct HeightPrior: Codable, Equatable, Sendable {
    public var mean: Double
    public var sigma: Double
    public init(mean: Double, sigma: Double) { self.mean = mean; self.sigma = sigma }
}

public struct LocatorConfig: Codable, Equatable, Sendable {
    public var fs = 48000.0
    public var chirp = ChirpConfig()
    public var beacons = Beacon.defaults
    public var mode = CarryMode.hand
    public var gate_ms = 3.0
    public var lookback_ms = 2.0
    public var snr_min = 8.0
    public var snr_acquire = 10.0
    public var resid_max_ms = 0.30
    public var resid_ok_ms = 0.15
    public var height_hand = HeightPrior(mean: 1.25, sigma: 0.25)
    public var height_pocket = HeightPrior(mean: 1.30, sigma: 0.20)
    public var ear_offset_hand = Vector3(0, 0, 0.35)
    public var ear_offset_pocket = Vector3(0, 0, 0.30)
    public var kalman_acceleration_sigma = 1.5
    public var kalman_measurement_sigma_ok = 0.05
    public var kalman_measurement_sigma_degraded = 0.15
    public var lost_timeout = 1.5
    public var air_temperature = 22.0
    public var mic_audio_sample_rate = 16000
    public var mic_audio_chunk_ms = 40.0
    public var hub_url = ""
    public var hub_token = ""
    public var hub_auth_mode = HubAuth.native
    public init() {}
    public var speedOfSound: Double { 331.3 + 0.606 * air_temperature }
    public var height: HeightPrior { mode == .hand ? height_hand : height_pocket }
    public var earOffset: Vector3 { mode == .hand ? ear_offset_hand : ear_offset_pocket }
    public func validate() throws {
        try chirp.validate(); try Beacon.validate(beacons)
        let positive = [fs, gate_ms, lookback_ms, snr_min, snr_acquire, resid_max_ms, resid_ok_ms,
                        height_hand.sigma, height_pocket.sigma, kalman_acceleration_sigma,
                        kalman_measurement_sigma_ok, kalman_measurement_sigma_degraded, lost_timeout]
        guard positive.allSatisfy({ $0.isFinite && $0 > 0 }), fs >= 2 * (chirp.f_hi + 300), fs <= 192000,
              resid_ok_ms <= resid_max_ms, gate_ms < chirp.slot_ms / 2, lookback_ms < chirp.slot_ms / 2,
              (-40...60).contains(air_temperature), (8000...48000).contains(mic_audio_sample_rate),
              mic_audio_chunk_ms == 40, height_hand.mean.isFinite, height_pocket.mean.isFinite,
              ear_offset_hand.values.allSatisfy(\.isFinite), ear_offset_pocket.values.allSatisfy(\.isFinite) else {
            throw LocatorError.invalid("Invalid locator parameters: use positive finite values; sample rate must cover the chirp band; speech uses 40 ms chunks")
        }
        if !hub_url.isEmpty {
            guard let url = URLComponents(string: hub_url), ["ws", "wss"].contains(url.scheme), url.host != nil,
                  url.user == nil, url.password == nil else { throw LocatorError.invalid("Hub URL must be ws://host:8765/ws or wss://host/path") }
        }
    }
    public static func importing(_ data: Data) throws -> Self {
        let config = try JSONDecoder().decode(Self.self, from: data)
        try config.validate()
        return config
    }
    public func exported() throws -> Data {
        try validate()
        let encoder = JSONEncoder(); encoder.outputFormatting = [.prettyPrinted, .sortedKeys]
        return try encoder.encode(self)
    }
}
