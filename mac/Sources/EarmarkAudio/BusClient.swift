import EarmarkContracts
import Foundation

/// Where the app sends bus messages (BusClient in the app, a recorder in tests).
public protocol BusSink: AnyObject {
    var isConnected: Bool { get }
    func send(_ message: BusMessage)
}

public enum BusConnectionState: Equatable, Sendable {
    case idle
    case connecting
    case connected
    case disconnected(String)

    public var displayName: String {
        switch self {
        case .idle: "Off"
        case .connecting: "Connecting"
        case .connected: "Connected"
        case .disconnected: "Reconnecting"
        }
    }
}

/// WebSocket client for the local bus (`EARMARK_BUS_URL`, default ws://127.0.0.1:8765).
/// Sends `hello` as `mac_app` with an explicit subscribe list on every (re)connect, decodes with `BusCoding`,
/// and reconnects with exponential backoff (0.5 s doubling to 5 s, with jitter).
public final class BusClient: NSObject, BusSink, URLSessionWebSocketDelegate {
    /// Types the Mac app acts on or shows. `speak` must be explicit: without `subscribe` the hub withholds audio.
    public static let subscribeTypes = [
        "snapshot", "registry_update", "state_update",
        "guide_start", "guide_stop",
        "speak", "speak_cached", "speak_text",
        "stt_mode", "transcript", "status", "reset",
        "pickup", "pickup_result", "listener_pose",
    ]

    public static var defaultURL: URL {
        let env = ProcessInfo.processInfo.environment["EARMARK_BUS_URL"].flatMap { $0.isEmpty ? nil : $0 }
        return URL(string: env ?? "ws://127.0.0.1:8765")!
    }

    public let url: URL
    public let subscribe: [String]
    /// Main queue.
    public var onMessage: ((BusMessage) -> Void)?
    /// Main queue.
    public var onState: ((BusConnectionState) -> Void)?

    private let queue = DispatchQueue(label: "earmark.bus")
    private lazy var session: URLSession = {
        let ops = OperationQueue()
        ops.underlyingQueue = queue
        ops.maxConcurrentOperationCount = 1
        let cfg = URLSessionConfiguration.ephemeral
        cfg.timeoutIntervalForRequest = 5
        return URLSession(configuration: cfg, delegate: self, delegateQueue: ops)
    }()

    // Touched only on `queue`.
    private var task: URLSessionWebSocketTask?
    private var backoff = 0.5
    private var running = false
    private var pingTimer: DispatchSourceTimer?
    private var pending: [(data: String, t: Double)] = []
    private var undecodable: Set<String> = []
    private let connectedLock = NSLock()
    private var _connected = false

    public static let maxBackoff = 5.0
    /// Transcripts typed or recognized while the bus is down are delivered on reconnect if younger than this.
    public static let pendingTTL = 10.0

    public init(url: URL = BusClient.defaultURL, subscribe: [String] = BusClient.subscribeTypes) {
        self.url = url
        self.subscribe = subscribe
    }

    public var isConnected: Bool { connectedLock.withLock { _connected } }

    public func start() {
        queue.async {
            guard !self.running else { return }
            self.running = true
            self.connectLocked()
        }
    }

    public func stop() {
        queue.async {
            self.running = false
            self.task?.cancel(with: .goingAway, reason: nil)
            self.task = nil
            self.setConnected(false, .idle)
        }
    }

    public func send(_ message: BusMessage) {
        guard let data = try? BusCoding.encode(message), let text = String(data: data, encoding: .utf8) else {
            Log.bus("could not encode \(message.type)")
            return
        }
        let queueIfDown: Bool
        if case .transcript = message { queueIfDown = true } else { queueIfDown = false }
        queue.async {
            guard let task = self.task, self.isConnected else {
                if queueIfDown {
                    self.pending.append((text, ProcessInfo.processInfo.systemUptime))
                    if self.pending.count > 20 { self.pending.removeFirst() }
                }
                return
            }
            task.send(.string(text)) { error in
                if let error { Log.bus("send \(message.type) failed: \(error.localizedDescription)") }
            }
        }
    }

    // MARK: Connection (on `queue`)

    private func connectLocked() {
        guard running else { return }
        setConnected(false, .connecting)
        let t = session.webSocketTask(with: url)
        t.maximumMessageSize = 16 << 20
        task = t
        t.resume()
        receiveLocked(t)
    }

    private func receiveLocked(_ t: URLSessionWebSocketTask) {
        t.receive { [weak self] result in
            guard let self else { return }
            self.queue.async {
                guard t === self.task else { return }
                switch result {
                case .success(let message):
                    switch message {
                    case .string(let s): self.decode(Data(s.utf8))
                    case .data(let d): self.decode(d)
                    @unknown default: break
                    }
                    self.receiveLocked(t)
                case .failure(let error):
                    self.dropLocked(t, reason: error.localizedDescription)
                }
            }
        }
    }

    private func decode(_ data: Data) {
        do {
            let msg = try BusCoding.decode(data)
            let cb = onMessage
            DispatchQueue.main.async { cb?(msg) }
        } catch {
            let type = (try? JSONSerialization.jsonObject(with: data) as? [String: Any])?["type"] as? String ?? "?"
            if undecodable.insert(type).inserted { Log.bus("could not decode a \(type) message: \(error)") }
        }
    }

    private func dropLocked(_ t: URLSessionWebSocketTask, reason: String) {
        guard t === task else { return }
        task = nil
        t.cancel(with: .abnormalClosure, reason: nil)
        pingTimer?.cancel(); pingTimer = nil
        let wasConnected = isConnected
        setConnected(false, .disconnected(reason))
        if wasConnected { Log.bus("disconnected: \(reason)") }
        guard running else { return }
        let delay = backoff * Double.random(in: 0.8...1.2)
        backoff = min(backoff * 2, Self.maxBackoff)
        queue.asyncAfter(deadline: .now() + delay) { [weak self] in
            guard let self, self.task == nil else { return }
            self.connectLocked()
        }
    }

    private func setConnected(_ on: Bool, _ state: BusConnectionState) {
        connectedLock.withLock { _connected = on }
        let cb = onState
        DispatchQueue.main.async { cb?(state) }
    }

    private func startPingsLocked(_ t: URLSessionWebSocketTask) {
        pingTimer?.cancel()
        let timer = DispatchSource.makeTimerSource(queue: queue)
        timer.schedule(deadline: .now() + 5, repeating: 5)
        timer.setEventHandler { [weak self, weak t] in
            guard let t else { return }
            t.sendPing { error in
                guard let error, let self else { return }
                self.queue.async { self.dropLocked(t, reason: "ping failed: \(error.localizedDescription)") }
            }
        }
        pingTimer = timer
        timer.resume()
    }

    // MARK: URLSessionWebSocketDelegate (on `queue`)

    public func urlSession(_ session: URLSession, webSocketTask: URLSessionWebSocketTask, didOpenWithProtocol protocol: String?) {
        guard webSocketTask === task else { return }
        backoff = 0.5
        setConnected(true, .connected)
        Log.bus("connected to \(url.absoluteString)")
        let hello = BusMessage.hello(Hello(component: .macApp, subscribe: subscribe))
        if let data = try? BusCoding.encode(hello), let text = String(data: data, encoding: .utf8) {
            webSocketTask.send(.string(text)) { error in
                if let error { Log.bus("hello failed: \(error.localizedDescription)") }
            }
        }
        let now = ProcessInfo.processInfo.systemUptime
        for p in pending where now - p.t < Self.pendingTTL {
            webSocketTask.send(.string(p.data)) { _ in }
        }
        pending.removeAll()
        startPingsLocked(webSocketTask)
    }

    public func urlSession(_ session: URLSession, webSocketTask: URLSessionWebSocketTask,
                           didCloseWith closeCode: URLSessionWebSocketTask.CloseCode, reason: Data?) {
        dropLocked(webSocketTask, reason: "closed (\(closeCode.rawValue))")
    }

    public func urlSession(_ session: URLSession, task: URLSessionTask, didCompleteWithError error: Error?) {
        guard let ws = task as? URLSessionWebSocketTask else { return }
        dropLocked(ws, reason: error?.localizedDescription ?? "connection ended")
    }
}
