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
///
/// A dropped link does not stop the microphone: chunks recorded meanwhile are held (`OutageBuffer`) and sent after
/// the rejoin, and the join names the unbroken recording (`timeline`), so the Mac keeps its calibration instead of
/// asking for a new one on the mat.
public final class PhoneClient: @unchecked Sendable {
    public let slot: Int
    public let name: String
    private let url: URL
    private var session: URLSession?
    private var task: URLSessionWebSocketTask?
    private let audio: AudioSource
    private var chirp = ChirpSpec()
    private var played = 0
    private var running = false
    /// Names the current unbroken recording; a new one whenever the microphone (re)starts.
    private var timeline = UUID().uuidString
    /// The Mac answered this connection's join, so audio goes straight out instead of into `outage`.
    private var linked = false
    private var outage = OutageBuffer()
    private let retryDelay: Double
    private let queue = DispatchQueue(label: "earmark.phone.client")
    public var onEvent: (@Sendable (PhoneEvent) -> Void)?

    public convenience init(url: URL, slot: Int, name: String) {
        self.init(url: url, slot: slot, name: name, audio: PhoneAudio())
    }

    init(url: URL, slot: Int, name: String, audio: AudioSource, retryDelay: Double = 2) {
        self.url = url; self.slot = slot; self.name = name; self.audio = audio; self.retryDelay = retryDelay
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
            linked = false
            audio.stop()
            outage = OutageBuffer()
            task?.cancel(with: .goingAway, reason: nil)
            task = nil
            session?.invalidateAndCancel()
            session = nil
            onEvent?(.disconnected)
        }
    }

    /// Plays the 14 second test sweep so another phone can record what this one can produce.
    public func playTestSweep() { audio.playTestSweep() }

    private func connect() {
        onEvent?(.connecting)
        session?.invalidateAndCancel()  // one session per attempt; drop the failed one
        let s = URLSession(configuration: .default)
        session = s
        let t = s.webSocketTask(with: url)
        task = t
        t.maximumMessageSize = 1 << 22
        t.resume()
        linked = false
        if !audio.isRunning { timeline = UUID().uuidString }  // the recording that starts after this join is a new one
        sendJoin()
        receive(t)
    }

    private func sendJoin() {
        send(["type": "join", "slot": slot, "name": name, "fs": Int(phoneSampleRate), "timeline": timeline])
    }

    private func receive(_ t: URLSessionWebSocketTask) {
        t.receive { [weak self] result in
            guard let self else { return }
            self.queue.async {
                guard self.running, self.task === t else { return }
                switch result {
                case .failure(let error):
                    self.onEvent?(.error("Lost the connection: \(error.localizedDescription). Retrying; still recording."))
                    self.linked = false
                    self.retry()
                case .success(let message):
                    if case .string(let text) = message { self.handle(text) }
                    self.receive(t)
                }
            }
        }
    }

    private func retry() {
        queue.asyncAfter(deadline: .now() + retryDelay) { [self] in
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
            let spec = ChirpSpec(fLo: lo, fHi: hi, lengthMs: len, amplitude: amp, direction: dir)
            if audio.isRunning && audio.runningChirp != spec {
                // The Mac wants a different chirp (it restarted with new settings): the recording has to restart,
                // so it is a new one. Say so with a fresh join; the Mac starts over and sends its config again.
                audio.stop()
                timeline = UUID().uuidString
                outage = OutageBuffer()
                sendJoin()
                return
            }
            chirp = spec
            if !audio.isRunning {
                do {
                    try audio.start(chirp: chirp,
                                    onChunk: { [weak self] start, pcm in self?.queue.async { self?.chunk(start, pcm) } },
                                    onLevel: { [weak self] level in self?.onEvent?(.level(level)) })
                } catch {
                    onEvent?(.error("Could not start the microphone and speaker: \(error.localizedDescription)"))
                    return
                }
            }
            linked = true
            for held in outage.drain() { sendAudio(start: held.start, pcm: held.pcm, resent: true) }
            onEvent?(.connected(slot: slot, chirp: chirp))
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

    /// One microphone chunk (on `queue`): out now, or held until the link is back.
    private func chunk(_ start: Int, _ pcm: Data) {
        guard running else { return }
        if linked { sendAudio(start: start, pcm: pcm, resent: false) } else { outage.append(start: start, pcm: pcm) }
    }

    /// `resent` marks audio held through a dropout: it arrives late, so the Mac must not judge network lag by it.
    private func sendAudio(start: Int, pcm: Data, resent: Bool) {
        var m: [String: Any] = ["type": "audio", "start": start, "pcm": pcm.base64EncodedString()]
        if resent { m["resent"] = true }
        send(m)
    }

    private func send(_ object: [String: Any]) {
        guard let t = task, let data = try? JSONSerialization.data(withJSONObject: object),
              let text = String(data: data, encoding: .utf8) else { return }
        t.send(.string(text)) { _ in }
    }
}
