import EarmarkContracts
import Foundation
import NearbyInteraction

/// NIDiscoveryToken <-> base64 for `uwb_token.token_b64` (NSKeyedArchiver with secure coding, UWB-PRD 7.3).
enum TokenCodec {
    static func encode(_ token: NIDiscoveryToken) -> String? {
        do {
            return try NSKeyedArchiver.archivedData(withRootObject: token, requiringSecureCoding: true).base64EncodedString()
        } catch {
            Log.ni.error("token archive failed: \(error.localizedDescription, privacy: .public)")
            return nil
        }
    }

    static func decode(_ b64: String) -> NIDiscoveryToken? {
        guard let data = Data(base64Encoded: b64) else { return nil }
        return try? NSKeyedUnarchiver.unarchivedObject(ofClass: NIDiscoveryToken.self, from: data)
    }
}

/// One `NISession` ranging to one peer, plus the recovery rules of UWB-PRD 7.6:
///
/// | Event | Action |
/// |---|---|
/// | `sessionWasSuspended` | phase "Paused"; the owner reports status |
/// | `sessionSuspensionEnded` | re-run the same configuration |
/// | `didRemove .timeout` | re-run with the last peer token; on the 3rd failure, new session + new token |
/// | `didRemove .peerEnded` | wait for a fresh token from that peer |
/// | `didInvalidateWith` | new session + publish a new token (1 s, 2 s, 4 s ... 10 s apart if it keeps failing) |
/// | app backgrounded | NI suspends the session itself; the suspension rows above resume it on foreground |
///
/// The anchor role owns one of these (peer "wearer"); the wearer owns three (peers "uwb_1/2/3").
/// The session's delegate queue is set to main, so delegate callbacks are main-actor via `assumeIsolated`.
@MainActor
final class PeerSession: NSObject, NISessionDelegate {
    enum Phase: Equatable {
        case unsupported
        case waitingForPeer
        case starting
        case running
        case held
        case suspended
        case retrying(Int)
        case peerEnded
        case denied
        case failed(String)

        var label: String {
            switch self {
            case .unsupported: "UWB not supported"
            case .waitingForPeer: "Waiting for the other phone's token"
            case .starting: "Starting"
            case .running: "Ranging"
            case .held: "Resting (round-robin)"
            case .suspended: "Paused"
            case .retrying(let n): "Lost the other phone, retry \(n)"
            case .peerEnded: "Other phone stopped; waiting for it"
            case .denied: "Nearby Interaction is off for Earmark (Settings > Privacy & Security > Nearby Interactions)"
            case .failed(let why): "Restarting: \(why)"
            }
        }
    }

    /// The 3rd consecutive timeout replaces the session (UWB-PRD 7.6).
    static let maxTimeoutRetries = 3

    let localId: String
    let peerId: String

    private(set) var phase: Phase = .waitingForPeer {
        didSet { if phase != oldValue { onPhase?(phase) } }
    }
    private(set) var lastDistance: Double?
    private(set) var lastDistanceUptime: Double?
    private(set) var myTokenB64: String?

    /// Publish this token to the hub (`uwb_token {from: localId, to: peerId}`).
    var onToken: (@MainActor (UwbToken) -> Void)?
    /// Every non-nil distance, meters.
    var onDistance: (@MainActor (Double) -> Void)?
    var onPhase: (@MainActor (Phase) -> Void)?
    /// The session was invalidated (not by us); the error tells e.g. `activeSessionsLimitExceeded`.
    var onInvalidated: (@MainActor (Error) -> Void)?

    private var session: NISession?
    private var peerToken: NIDiscoveryToken?
    private var peerTokenB64: String?
    private var timeouts = 0
    private var held = false
    private var stopped = true
    private var invalidationStreak = 0
    private var restartTask: Task<Void, Never>?

    init(localId: String, peerId: String) {
        self.localId = localId
        self.peerId = peerId
        super.init()
    }

    var isRanging: Bool { phase == .running }
    var isHeld: Bool { held }
    /// Seconds since the last distance, nil if none yet.
    var distanceAge: Double? { lastDistanceUptime.map { uptime() - $0 } }

    func start() {
        stopped = false
        guard CapabilityCheck.supportsUWB else {
            phase = .unsupported
            return
        }
        makeSession()
    }

    func stop() {
        stopped = true
        restartTask?.cancel(); restartTask = nil
        teardown()
    }

    /// Re-send our current token (hub reconnect). The hub also keeps the latest one and replays it to the peer.
    func publishToken() {
        guard let b64 = myTokenB64, !stopped else { return }
        onToken?(UwbToken(from: localId, to: peerId, tokenB64: b64))
    }

    /// The peer's token arrived over the bus (or was replayed by the hub after a reconnect).
    func receivePeerToken(_ b64: String) {
        guard !stopped, phase != .unsupported else { return }
        guard let token = TokenCodec.decode(b64) else {
            Log.ni.error("unreadable token from \(self.peerId, privacy: .public)")
            return
        }
        if b64 == peerTokenB64, phase == .running || phase == .starting { return }
        peerToken = token
        peerTokenB64 = b64
        timeouts = 0
        guard session != nil else { return }   // a restart is pending; it runs with this token
        if held { phase = .held } else { runPeer() }
        Log.ni.info("\(self.localId, privacy: .public) got token from \(self.peerId, privacy: .public)")
    }

    /// Round-robin rest: stop ranging without losing the session or tokens.
    func hold() {
        guard !held else { return }
        held = true
        session?.pause()
        if session != nil { phase = .held }
    }

    func release() {
        guard held else { return }
        held = false
        guard session != nil else { return }
        if peerToken != nil { runPeer() } else { phase = .waitingForPeer }
    }

    // MARK: Session management

    private func makeSession() {
        teardown()
        timeouts = 0
        let s = NISession()
        s.delegateQueue = DispatchQueue.main
        s.delegate = self
        session = s
        guard let token = s.discoveryToken, let b64 = TokenCodec.encode(token) else {
            phase = .failed("no discovery token")
            return
        }
        myTokenB64 = b64
        Log.ni.info("\(self.localId, privacy: .public) new session for \(self.peerId, privacy: .public)")
        publishToken()
        if peerToken == nil {
            phase = .waitingForPeer
        } else if held {
            phase = .held
        } else {
            runPeer()
        }
    }

    private func teardown() {
        guard let s = session else { return }
        s.delegate = nil          // no callbacks (incl. didInvalidate) for a session we end ourselves
        s.invalidate()
        session = nil
    }

    private func runPeer() {
        guard let s = session, let token = peerToken else { return }
        // Camera assistance stays off (no camera; distance only). Extended distance is not needed in a booth.
        s.run(NINearbyPeerConfiguration(peerToken: token))
        phase = .starting
    }

    private func isCurrent(_ id: ObjectIdentifier) -> Bool {
        session.map { ObjectIdentifier($0) } == id
    }

    private func scheduleRestart() {
        guard !stopped else { return }
        invalidationStreak += 1
        let delay = min(10, pow(2, Double(invalidationStreak - 1)))
        restartTask?.cancel()
        restartTask = Task { [weak self] in
            try? await Task.sleep(for: .seconds(delay))
            guard let self, !Task.isCancelled, !self.stopped, self.session == nil else { return }
            self.makeSession()
        }
    }

    // MARK: Delegate handlers (main actor)

    private func updated(_ id: ObjectIdentifier, distances: [Float]) {
        guard isCurrent(id), let d = distances.last else { return }
        let meters = Double(max(0, d))
        lastDistance = meters
        lastDistanceUptime = uptime()
        timeouts = 0
        invalidationStreak = 0
        if !held { phase = .running }
        onDistance?(meters)
    }

    private func removed(_ id: ObjectIdentifier, timedOut: Bool) {
        guard isCurrent(id), !stopped else { return }
        guard timedOut else {
            Log.ni.info("\(self.peerId, privacy: .public) ended its session; waiting for a fresh token")
            phase = .peerEnded
            return
        }
        guard !held else { return }
        timeouts += 1
        if timeouts < Self.maxTimeoutRetries {
            Log.ni.info("\(self.peerId, privacy: .public) timed out (\(self.timeouts)); re-running")
            runPeer()
            phase = .retrying(timeouts)
        } else {
            Log.ni.info("\(self.peerId, privacy: .public) timed out \(self.timeouts) times; new session and token")
            makeSession()
        }
    }

    private func suspended(_ id: ObjectIdentifier) {
        guard isCurrent(id) else { return }
        phase = .suspended
    }

    private func suspensionEnded(_ id: ObjectIdentifier) {
        guard isCurrent(id), !stopped, let s = session else { return }
        if held {
            phase = .held
        } else if let config = s.configuration {
            s.run(config)          // "re-run the same configuration"
            phase = .starting
        } else if peerToken != nil {
            runPeer()
        } else {
            phase = .waitingForPeer
        }
    }

    private func started(_ id: ObjectIdentifier) {
        guard isCurrent(id), !held else { return }
        if phase == .starting || phase == .suspended { phase = .running }
    }

    private func invalidated(_ id: ObjectIdentifier, error: Error, denied: Bool) {
        guard isCurrent(id) else { return }
        session = nil
        Log.ni.error("\(self.localId, privacy: .public)->\(self.peerId, privacy: .public) invalidated: \(error.localizedDescription, privacy: .public)")
        if denied {
            phase = .denied        // retrying would just fail again; the user must allow it in Settings
            return
        }
        phase = .failed(error.localizedDescription)
        onInvalidated?(error)
        scheduleRestart()
    }

    // MARK: NISessionDelegate (delegate queue = main)

    nonisolated func session(_ session: NISession, didUpdate nearbyObjects: [NINearbyObject]) {
        let id = ObjectIdentifier(session)
        let distances = nearbyObjects.compactMap { $0.distance }   // direction is ignored
        MainActor.assumeIsolated { self.updated(id, distances: distances) }
    }

    nonisolated func session(_ session: NISession, didRemove nearbyObjects: [NINearbyObject],
                             reason: NINearbyObject.RemovalReason) {
        let id = ObjectIdentifier(session)
        let timedOut: Bool
        switch reason {
        case .peerEnded: timedOut = false
        case .timeout: timedOut = true
        @unknown default: timedOut = true
        }
        MainActor.assumeIsolated { self.removed(id, timedOut: timedOut) }
    }

    nonisolated func sessionWasSuspended(_ session: NISession) {
        let id = ObjectIdentifier(session)
        MainActor.assumeIsolated { self.suspended(id) }
    }

    nonisolated func sessionSuspensionEnded(_ session: NISession) {
        let id = ObjectIdentifier(session)
        MainActor.assumeIsolated { self.suspensionEnded(id) }
    }

    nonisolated func sessionDidStartRunning(_ session: NISession) {
        let id = ObjectIdentifier(session)
        MainActor.assumeIsolated { self.started(id) }
    }

    nonisolated func session(_ session: NISession, didInvalidateWith error: Error) {
        let id = ObjectIdentifier(session)
        let denied = (error as? NIError)?.code == .userDidNotAllow
        MainActor.assumeIsolated { self.invalidated(id, error: error, denied: denied) }
    }
}
