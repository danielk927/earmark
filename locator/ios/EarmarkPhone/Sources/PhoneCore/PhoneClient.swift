import AVFoundation
import Foundation

public let phoneSampleRate = 48000.0
public let chunkSamples = 2400  // 50 ms per message

public struct UserFix: Equatable, Sendable {
    public var x: Double, y: Double, z: Double
    public var quality: String
    public var used: Int
}

public enum PhoneEvent: Sendable {
    case connecting
    case connected(slot: Int, chirp: ChirpSpec)
    case played(count: Int)
    case level(Float)
    case fix(UserFix)
    case error(String)
    case disconnected
}

/// Joins the ranging service, streams what the microphone hears, and plays a chirp whenever told to.
public final class PhoneClient: @unchecked Sendable {
    public let slot: Int
    public let name: String
    private let url: URL
    private var session: URLSession?
    private var task: URLSessionWebSocketTask?
    private let audio = PhoneAudio()
    private var chirp = ChirpSpec()
    private var played = 0
    private var running = false
    private var sentSamples = 0
    private let queue = DispatchQueue(label: "earmark.phone.client")
    public var onEvent: (@Sendable (PhoneEvent) -> Void)?
    /// Every raw microphone buffer the listener captures (audio thread, hardware format; valid only during the
    /// call). Lets a host app reuse this one capture path instead of opening a second engine. Set before `start`.
    public var onMicBuffer: (@Sendable (AVAudioPCMBuffer) -> Void)? {
        get { audio.micTap }
        set { audio.micTap = newValue }
    }

    public init(url: URL, slot: Int, name: String) {
        self.url = url; self.slot = slot; self.name = name
    }

    public func start() {
        queue.async { [self] in
            guard !running else { return }
            running = true
            connect()
        }
    }

    public func stop() {
        queue.async { [self] in
            running = false
            audio.stop()
            task?.cancel(with: .goingAway, reason: nil)
            task = nil
            onEvent?(.disconnected)
        }
    }

    /// Plays the 14 second test sweep so another phone can record what this one can produce.
    public func playTestSweep() { audio.playTestSweep() }

    private func connect() {
        onEvent?(.connecting)
        let s = URLSession(configuration: .default)
        session = s
        let t = s.webSocketTask(with: url)
        task = t
        t.maximumMessageSize = 1 << 22
        t.resume()
        send(["type": "join", "slot": slot, "name": name, "fs": Int(phoneSampleRate)])
        receive(t)
    }

    private func receive(_ t: URLSessionWebSocketTask) {
        t.receive { [weak self] result in
            guard let self else { return }
            self.queue.async {
                guard self.running, self.task === t else { return }
                switch result {
                case .failure(let error):
                    self.onEvent?(.error("Lost the connection: \(error.localizedDescription). Retrying."))
                    self.audio.stop()
                    self.retry()
                case .success(let message):
                    if case .string(let text) = message { self.handle(text) }
                    self.receive(t)
                }
            }
        }
    }

    private func retry() {
        queue.asyncAfter(deadline: .now() + 2) { [self] in
            guard running else { return }
            connect()
        }
    }

    private func handle(_ text: String) {
        guard let data = text.data(using: .utf8),
              let msg = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
              let type = msg["type"] as? String else { return }
        switch type {
        case "config":
            guard let c = msg["chirp"] as? [String: Any],
                  let lo = c["f_lo"] as? Double, let hi = c["f_hi"] as? Double, let len = c["length_ms"] as? Double,
                  let amp = c["amplitude"] as? Double, let dir = c["direction"] as? String else { return }
            chirp = ChirpSpec(fLo: lo, fHi: hi, lengthMs: len, amplitude: amp, direction: dir)
            do {
                try audio.start(chirp: chirp,
                                onChunk: { [weak self] start, pcm in self?.sendAudio(start: start, pcm: pcm) },
                                onLevel: { [weak self] level in self?.onEvent?(.level(level)) })
                onEvent?(.connected(slot: slot, chirp: chirp))
            } catch {
                onEvent?(.error("Could not start the microphone and speaker: \(error.localizedDescription)"))
            }
        case "play":
            audio.playChirp()
            played += 1
            onEvent?(.played(count: played))
        case "fix":
            if let x = msg["x"] as? Double, let y = msg["y"] as? Double, let z = msg["z"] as? Double {
                onEvent?(.fix(UserFix(x: x, y: y, z: z, quality: msg["quality"] as? String ?? "?", used: msg["used"] as? Int ?? 0)))
            }
        case "error":
            onEvent?(.error(msg["detail"] as? String ?? "the service refused this phone"))
        default:
            break
        }
    }

    private func sendAudio(start: Int, pcm: Data) {
        send(["type": "audio", "start": start, "pcm": pcm.base64EncodedString()])
    }

    private func send(_ object: [String: Any]) {
        guard let t = task, let data = try? JSONSerialization.data(withJSONObject: object),
              let text = String(data: data, encoding: .utf8) else { return }
        t.send(.string(text)) { _ in }
    }
}
