import EarmarkContracts
import Foundation

/// WebSocket client for the Earmark bus (`ws://<mac-ip>:8765`), mirroring the Mac app's `BusClient`:
/// `hello` first on every (re)connect, `BusCoding` encode/decode, ping every 5 s, reconnect with backoff
/// 0.5 s doubling to 5 s (with jitter).
///
/// Threading: everything here is main-actor. The URLSession delegate queue is `OperationQueue.main`, so the
/// delegate callbacks run on the main thread and use `MainActor.assumeIsolated`; completion handlers hop with
/// `onMain` (FIFO, so message order is kept).
@MainActor
final class HubConnection: NSObject, ObservableObject, URLSessionWebSocketDelegate {
    enum State: Equatable {
        case idle
        case connecting
        case connected
        case disconnected(String)

        var label: String {
            switch self {
            case .idle: "Off"
            case .connecting: "Connecting…"
            case .connected: "Connected"
            case .disconnected: "Reconnecting…"
            }
        }
    }

    /// `snapshot` always arrives after hello; `uwb_token` is delivered only when `to` equals our device id.
    static let subscribeTypes = ["uwb_token", "reset", "snapshot", "listener_pose", "status"]
    static let pingInterval = 5.0

    let url: URL
    let deviceId: String
    private let component: Component
    private let role: Hello.Role
    private let secret: String?

    @Published private(set) var state: State = .idle
    /// True once the hub answered our hello with a snapshot (so the secret was accepted).
    @Published private(set) var helloAccepted = false
    /// True if any hello was ever accepted during this run (used to hint "check the secret" otherwise).
    @Published private(set) var everAccepted = false
    /// Anchor labels from `snapshot.space.anchors` (e.g. "uwb_1" -> "UWB Reader/Emitter 1").
    @Published private(set) var anchorLabels: [String: String] = [:]
    /// Why the hub refused our hello (e.g. "wrong or missing bus secret in hello"), until a later hello succeeds.
    @Published private(set) var refusal: String?

    /// Every decoded message, on the main actor.
    var onMessage: (@MainActor (BusMessage) -> Void)?
    /// After each (re)connect, right after `hello` was sent. Controllers re-send their tokens here.
    var onConnected: (@MainActor () -> Void)?

    private lazy var urlSession: URLSession = {
        let cfg = URLSessionConfiguration.ephemeral
        cfg.timeoutIntervalForRequest = 5
        cfg.waitsForConnectivity = false
        return URLSession(configuration: cfg, delegate: self, delegateQueue: OperationQueue.main)
    }()

    private var task: URLSessionWebSocketTask?
    private var running = false
    private var backoff = Backoff()
    private var pingLoop: Task<Void, Never>?
    private var reconnectLoop: Task<Void, Never>?
    private var undecodable: Set<String> = []

    init(url: URL, component: Component, deviceId: String, role: Hello.Role, secret: String?) {
        self.url = url
        self.component = component
        self.deviceId = deviceId
        self.role = role
        self.secret = secret
        super.init()
    }

    var isConnected: Bool { state == .connected }

    func start() {
        guard !running else { return }
        running = true
        connect()
    }

    /// Final: the URLSession is invalidated, so make a new HubConnection to connect again.
    func stop() {
        running = false
        reconnectLoop?.cancel(); reconnectLoop = nil
        pingLoop?.cancel(); pingLoop = nil
        task?.cancel(with: .goingAway, reason: nil)
        task = nil
        state = .idle
        helloAccepted = false
        urlSession.invalidateAndCancel()
    }

    /// Skip the backoff wait (e.g. the app just came back to the foreground).
    func reconnectNow() {
        guard running, task == nil else { return }
        reconnectLoop?.cancel(); reconnectLoop = nil
        backoff.reset()
        connect()
    }

    /// Fire and forget. Dropped while disconnected: ranges and motion are real-time, and tokens and status are
    /// re-sent from `onConnected`.
    func send(_ message: BusMessage) {
        guard let task, state == .connected else { return }
        guard let data = try? BusCoding.encode(message), let text = String(data: data, encoding: .utf8) else {
            Log.hub.error("could not encode \(message.type, privacy: .public)")
            return
        }
        let type = message.type
        task.send(.string(text)) { error in
            if let error { Log.hub.error("send \(type, privacy: .public) failed: \(error.localizedDescription, privacy: .public)") }
        }
    }

    // MARK: Connection

    private func connect() {
        guard running else { return }
        state = .connecting
        helloAccepted = false
        let t = urlSession.webSocketTask(with: url)
        t.maximumMessageSize = 16 << 20
        task = t
        t.resume()
        receive(t)
    }

    private func receive(_ t: URLSessionWebSocketTask) {
        t.receive { result in
            switch result {
            case .success(let message):
                let data: Data?
                switch message {
                case .string(let s): data = Data(s.utf8)
                case .data(let d): data = d
                @unknown default: data = nil
                }
                onMain { [weak self] in
                    guard let self, t === self.task else { return }
                    if let data { self.handleIncoming(data) }
                    self.receive(t)
                }
            case .failure(let error):
                let reason = error.localizedDescription
                onMain { [weak self] in self?.drop(t, reason: reason) }
            }
        }
    }

    private func handleIncoming(_ data: Data) {
        let message: BusMessage
        do {
            message = try BusCoding.decode(data)
        } catch {
            let type = (try? JSONSerialization.jsonObject(with: data) as? [String: Any])?["type"] as? String ?? "?"
            // A snapshot we can't fully decode still means the hub accepted our hello.
            if type == "snapshot" { markAccepted() }
            if undecodable.insert(type).inserted {
                Log.hub.error("could not decode a \(type, privacy: .public) message: \(String(describing: error), privacy: .public)")
            }
            return
        }
        // The hub refuses a bad hello with `status {component: hub, ok: false, detail}` then closes (1008).
        if case .status(let status) = message, status.component == .hub, !status.ok, !helloAccepted {
            refusal = status.detail
        }
        if case .snapshot(let snapshot) = message {
            refusal = nil
            markAccepted()
            var labels: [String: String] = [:]
            for anchor in snapshot.space.anchors ?? [] { labels[anchor.anchor] = anchor.label }
            anchorLabels = labels
        }
        onMessage?(message)
    }

    private func markAccepted() {
        helloAccepted = true
        everAccepted = true
    }

    private func opened(_ t: URLSessionWebSocketTask) {
        guard t === task else { return }
        backoff.reset()
        state = .connected
        Log.hub.info("connected to \(self.url.absoluteString, privacy: .public)")
        let hello = Hello(component: component, subscribe: Self.subscribeTypes, deviceId: deviceId, role: role, secret: secret)
        send(.hello(hello))
        onConnected?()
        startPings(t)
    }

    private func drop(_ t: URLSessionWebSocketTask, reason: String) {
        guard t === task else { return }
        task = nil
        t.cancel(with: .goingAway, reason: nil)
        pingLoop?.cancel(); pingLoop = nil
        let wasConnected = state == .connected
        helloAccepted = false
        state = .disconnected(reason)
        if wasConnected { Log.hub.info("disconnected: \(reason, privacy: .public)") }
        scheduleReconnect()
    }

    private func scheduleReconnect() {
        guard running else { return }
        let delay = backoff.next() * Double.random(in: 0.8...1.2)
        reconnectLoop?.cancel()
        reconnectLoop = Task { [weak self] in
            try? await Task.sleep(for: .seconds(delay))
            guard !Task.isCancelled, let self, self.task == nil else { return }
            self.connect()
        }
    }

    private func startPings(_ t: URLSessionWebSocketTask) {
        pingLoop?.cancel()
        pingLoop = everySeconds(Self.pingInterval) { [weak self] in
            guard let self, t === self.task else { return }
            t.sendPing { error in
                guard let error else { return }
                let reason = "ping failed: \(error.localizedDescription)"
                onMain { [weak self] in self?.drop(t, reason: reason) }
            }
        }
    }

    // MARK: URLSessionWebSocketDelegate (delegate queue = main)

    nonisolated func urlSession(_ session: URLSession, webSocketTask: URLSessionWebSocketTask,
                                didOpenWithProtocol proto: String?) {
        MainActor.assumeIsolated { self.opened(webSocketTask) }
    }

    nonisolated func urlSession(_ session: URLSession, webSocketTask: URLSessionWebSocketTask,
                                didCloseWith closeCode: URLSessionWebSocketTask.CloseCode, reason: Data?) {
        let text = reason.flatMap { String(data: $0, encoding: .utf8) } ?? ""
        let why = "closed by hub (code \(closeCode.rawValue))" + (text.isEmpty ? "" : ": \(text)")
        MainActor.assumeIsolated { self.drop(webSocketTask, reason: why) }
    }

    nonisolated func urlSession(_ session: URLSession, task: URLSessionTask, didCompleteWithError error: Error?) {
        guard let ws = task as? URLSessionWebSocketTask else { return }
        let why = error?.localizedDescription ?? "connection ended"
        MainActor.assumeIsolated { self.drop(ws, reason: why) }
    }
}
