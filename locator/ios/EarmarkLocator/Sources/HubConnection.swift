import Foundation
import EarmarkCore

@MainActor
final class HubConnection: ObservableObject {
    @Published private(set) var state = "Disconnected"
    @Published private(set) var rates: [String: Double] = [:]
    private var socket: URLSessionWebSocketTask?
    private var connection: Task<Void, Never>?
    private var generation = UUID()
    private var connected = false
    private var sending = false
    private struct Outbound {
        let frames: [(Data, String)]
        let pose: ListenerPose?
    }
    private var pending: [Outbound] = []
    var onPoseSent: ((ListenerPose) -> Void)?
    private var counts: [String: Int] = [:]
    private var rateStart = Date()
    var onPTT: ((PTTMessage.State) -> Void)?
    var onChange: (() -> Void)?
    var onFailure: ((String) -> Void)?

    func connect(config: LocatorConfig) {
        disconnect()
        guard !config.hub_url.isEmpty else { state = "Enter hub URL in Settings"; onChange?(); return }
        let token = generation
        connection = Task { [weak self] in await self?.connectionLoop(config: config, generation: token) }
    }
    func disconnect() {
        generation = UUID(); connection?.cancel(); connection = nil
        socket?.cancel(with: .goingAway, reason: nil); socket = nil
        connected = false; sending = false; pending = []; state = "Disconnected"; onPTT?(.stop); onChange?()
    }
    private func connectionLoop(config: LocatorConfig, generation token: UUID) async {
        var delay = 0.5
        while !Task.isCancelled && token == generation {
            do {
                let url = try connectionURL(config)
                let ws = URLSession.shared.webSocketTask(with: url)
                socket = ws; state = "Connecting"; onChange?(); ws.resume()
                try await handshake(ws, config: config)
                guard token == generation, !Task.isCancelled else { return }
                connected = true; state = "Connected"; onChange?()
                let connectedAt = Date()
                try await receive(ws, generation: token)
                if Date().timeIntervalSince(connectedAt) > 5 { delay = 0.5 }
            } catch {
                guard token == generation, !Task.isCancelled else { return }
                connected = false; sending = false; pending = []; onPTT?(.stop)
                socket?.cancel(with: .goingAway, reason: nil)
                state = String(format: "Offline — retry in %.1f s", delay); onChange?()
                onFailure?("Hub disconnected: \(error.localizedDescription)")
            }
            do { try await Task.sleep(nanoseconds: UInt64(delay * 1e9)) }
            catch { return }
            delay = min(5, delay * 2)
        }
    }
    private func connectionURL(_ config: LocatorConfig) throws -> URL {
        guard var parts = URLComponents(string: config.hub_url) else { throw LocatorError.invalid("Invalid hub URL") }
        if config.hub_auth_mode == .query {
            parts.queryItems = (parts.queryItems ?? []).filter { $0.name != "token" } + [URLQueryItem(name: "token", value: config.hub_token)]
        }
        guard let url = parts.url else { throw LocatorError.invalid("Invalid hub URL") }
        return url
    }
    private func handshake(_ ws: URLSessionWebSocketTask, config: LocatorConfig) async throws {
        switch config.hub_auth_mode {
        case .native: try await ws.send(.string(String(decoding: JSONEncoder().encode(NativeHello()), as: UTF8.self)))
        case .hello: try await ws.send(.string(String(decoding: JSONEncoder().encode(TokenHello(token: config.hub_token)), as: UTF8.self)))
        case .query:
            // A successful ping confirms the HTTP upgrade without queuing a stale pose.
            try await withCheckedThrowingContinuation { (continuation: CheckedContinuation<Void, Error>) in
                ws.sendPing { error in
                    if let error { continuation.resume(throwing: error) } else { continuation.resume() }
                }
            }
        }
    }
    private func receive(_ ws: URLSessionWebSocketTask, generation token: UUID) async throws {
        while !Task.isCancelled && token == generation {
            let message = try await ws.receive()
            let data: Data
            switch message {
            case .data(let bytes): data = bytes
            case .string(let text): data = Data(text.utf8)
            @unknown default: continue
            }
            do { if let ptt = try PTTMessage.parse(data) { onPTT?(ptt.state) } }
            catch { onFailure?("Malformed hub message: \(error.localizedDescription)") }
        }
    }
    @discardableResult
    func send<T: Encodable>(_ value: T, type: String) -> Bool {
        do { return sendFrames([(try JSONEncoder().encode(value), type)], mayQueue: type == "ptt") }
        catch { onFailure?("Cannot encode \(type): \(error.localizedDescription)"); return false }
    }
    @discardableResult
    func sendPose(_ pose: ListenerPose, nativeBridge: Bool) -> Bool {
        do {
            var frames = [(try JSONEncoder().encode(pose), "listener_pose")]
            if nativeBridge && pose.quality != .lost {
                frames.insert((try JSONEncoder().encode(NativePose(position: pose.position)), "pose"), at: 0)
            }
            return sendFrames(frames, pose: pose)
        } catch { onFailure?("Cannot encode pose: \(error.localizedDescription)"); return false }
    }
    func sendSpeech(_ chunks: [MicAudio], stop: Bool) -> Bool {
        do {
            var frames = try chunks.map { (try JSONEncoder().encode($0), "mic_audio") }
            if stop { frames.append((try JSONEncoder().encode(PTTMessage(.stop)), "ptt")) }
            return frames.isEmpty || sendFrames(frames, mayQueue: true)
        } catch { onFailure?("Speech encoding failed: \(error.localizedDescription)"); return false }
    }
    private func sendFrames(_ frames: [(Data, String)], mayQueue: Bool = false, pose: ListenerPose? = nil) -> Bool {
        guard connected, socket != nil else { return false }
        if sending {
            guard mayQueue else { return false }
            guard pending.count < 4 else {
                onFailure?("Speech transport is too slow. Turn stopped; reconnect and retry.")
                connected = false; pending = []; socket?.cancel(with: .goingAway, reason: nil); onPTT?(.stop)
                return false
            }
            pending.append(Outbound(frames: frames, pose: pose))
            return true
        }
        transmit(Outbound(frames: frames, pose: pose))
        return true
    }
    private func transmit(_ outbound: Outbound) {
        guard let socket, connected else { return }
        sending = true
        let token = generation
        Task {
            do {
                for (data, type) in outbound.frames {
                    guard token == generation else { return }
                    try await socket.send(.string(String(decoding: data, as: UTF8.self)))
                    counts[type, default: 0] += 1
                }
                guard token == generation else { return }
                sending = false; updateRates()
                if let pose = outbound.pose { onPoseSent?(pose) }
                if !pending.isEmpty { transmit(pending.removeFirst()) }
            } catch {
                guard token == generation else { return }
                sending = false; connected = false; pending = []; onPTT?(.stop)
                socket.cancel(with: .goingAway, reason: nil)
                onFailure?("Hub send failed: \(error.localizedDescription)")
            }
        }
    }
    private func updateRates() {
        let elapsed = Date().timeIntervalSince(rateStart)
        guard elapsed >= 2 else { return }
        rates = counts.mapValues { Double($0) / elapsed }
        counts = [:]; rateStart = Date()
    }
}
