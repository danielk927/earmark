import Foundation

public struct ListenerPose: Encodable, Sendable {
    public let type = "listener_pose"
    public let position: Vector3
    public let quality: Quality
    public let beacons_heard: Int
    public let source: PoseSource
    public let t: Double
    public init(position: Vector3, quality: Quality, beacons: Int, source: PoseSource, t: Double) {
        self.position = position; self.quality = quality; beacons_heard = beacons; self.source = source; self.t = t
    }
}
public struct NativePose: Encodable, Sendable {
    public let type = "pose"
    public let pos: Vector3
    public let source = "beacons"
    public init(position: Vector3) { pos = position }
}
public struct NativeHello: Encodable {
    public let type = "hello", role = "sensor", name = "locator"
    public init() {}
}
public struct TokenHello: Encodable {
    public let type = "hello", component = "locator"
    public let token: String
    public init(token: String) { self.token = token }
}
public struct LocatorStatus: Encodable {
    public let type = "status", component = "locator"
    public let ok: Bool
    public let detail: String
    public init(ok: Bool, detail: String) { self.ok = ok; self.detail = detail }
}
public struct PTTMessage: Codable, Sendable {
    public enum State: String, Codable, Sendable { case start, stop }
    public var type = "ptt"
    public let state: State
    public init(_ state: State) { self.state = state }
    public static func parse(_ data: Data) throws -> PTTMessage? {
        struct Header: Decodable { let type: String }
        guard try JSONDecoder().decode(Header.self, from: data).type == "ptt" else { return nil }
        return try JSONDecoder().decode(PTTMessage.self, from: data)
    }
}
public struct MicAudio: Encodable, Sendable {
    public let type = "mic_audio"
    public let seq: Int
    public let sample_rate: Int
    public let encoding = "pcm_s16le"
    public let chunk_b64: String
    public init(sequence: Int, sampleRate: Int, samples: [Double]) {
        seq = sequence; sample_rate = sampleRate
        chunk_b64 = PCM.encode(samples).base64EncodedString()
    }
}
public struct PosePublisher {
    private var last: ListenerPose?
    private var lostSent = false
    public init() {}
    public mutating func accept(_ fix: Fix, source: PoseSource) -> ListenerPose {
        let pose = ListenerPose(position: fix.ear_position, quality: fix.quality, beacons: fix.beacons_used.count, source: source, t: fix.t)
        last = pose; lostSent = false
        return pose
    }
    public mutating func timeout(now: Double, seconds: Double) -> ListenerPose? {
        guard let last, !lostSent, now - last.t >= seconds else { return nil }
        lostSent = true
        // Retain measurement time: loss does not create a new position measurement.
        return ListenerPose(position: last.position, quality: .lost, beacons: 0, source: last.source, t: last.t)
    }
}

public enum PCM {
    public static func encode(_ samples: [Double]) -> Data {
        var data = Data(capacity: samples.count * 2)
        for sample in samples {
            let clipped = min(32767, max(-32768, (sample * 32768).rounded()))
            let value = UInt16(bitPattern: Int16(clipped.isFinite ? clipped : 0))
            data.append(UInt8(value & 255)); data.append(UInt8(value >> 8))
        }
        return data
    }
}

public struct SpeechStream {
    public let inputRate: Double
    public let outputRate: Int
    public private(set) var active = false
    private var input: [Double] = []
    private var cursor = 31.0
    private var pending: [Double] = []
    private var sequence = 0
    private let halfWidth = 31
    public init(inputRate: Double, outputRate: Int) { self.inputRate = inputRate; self.outputRate = outputRate }
    public mutating func start() {
        guard !active else { return }
        active = true; input = Array(repeating: 0, count: halfWidth)
        cursor = Double(halfWidth); pending = []; sequence = 0
    }
    public mutating func append(_ samples: [Double]) -> [MicAudio] {
        guard active else { return [] }
        input += samples
        resample()
        return chunks(flush: false)
    }
    public mutating func stop() -> [MicAudio] {
        guard active else { return [] }
        input += Array(repeating: 0, count: halfWidth)
        resample()
        let result = chunks(flush: true)
        active = false; input = []; pending = []
        return result
    }
    private mutating func resample() {
        let cutoff = min(0.45, 0.45 * Double(outputRate) / inputRate)
        while Int(cursor) + halfWidth < input.count {
            let center = Int(cursor)
            let offsets = (-halfWidth...halfWidth).map { Double($0 + center) - cursor }
            var weights = offsets.map { distance -> Double in
                let sinc = abs(distance) < 1e-12 ? 2 * cutoff : sin(2 * .pi * cutoff * distance) / (.pi * distance)
                return sinc * (0.5 + 0.5 * cos(.pi * distance / Double(halfWidth + 1)))
            }
            let sum = weights.reduce(0, +)
            weights = weights.map { $0 / sum }
            let values = Array(input[(center - halfWidth)...(center + halfWidth)])
            pending.append(DSP.dot(values, weights))
            cursor += inputRate / Double(outputRate)
        }
        let remove = max(0, Int(cursor) - halfWidth)
        if remove > 0 { input.removeFirst(remove); cursor -= Double(remove) }
    }
    private mutating func chunks(flush: Bool) -> [MicAudio] {
        var result: [MicAudio] = []
        let size = Int((Double(outputRate) * 0.04).rounded())
        while pending.count >= size || (flush && !pending.isEmpty) {
            let count = min(size, pending.count)
            let chunk = Array(pending.prefix(count)); pending.removeFirst(count)
            let rms = sqrt(DSP.dot(chunk, chunk) / Double(count))
            let gain = min(10, 0.1 / max(rms, 1e-9))
            result.append(MicAudio(sequence: sequence, sampleRate: outputRate, samples: chunk.map { $0 * gain }))
            sequence += 1
        }
        return result
    }
}
