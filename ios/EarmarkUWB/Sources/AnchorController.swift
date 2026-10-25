import EarmarkContracts
import Foundation

/// "UWB Reader/Emitter N" (UWB-PRD 7.3): one NISession dedicated to the wearer.
/// Publishes its token to the wearer, runs when the wearer's token arrives, and reports `status` every 5 s.
/// Anchors never send `uwb_range` (the wearer is the single source of measurements).
@MainActor
final class AnchorController: ObservableObject {
    static let statusInterval = 5.0
    /// Distance older than this is shown as stale.
    static let staleAfter = 2.0

    let role: DeviceRole
    let hub: HubConnection
    let uwbSupported: Bool

    @Published private(set) var phase: PeerSession.Phase = .waitingForPeer
    @Published private(set) var distance: Double?
    @Published private(set) var distanceStale = true
    @Published private(set) var batteryText = "Unknown"

    private let peer: PeerSession
    private var loops: [Task<Void, Never>] = []

    init(role: DeviceRole, hub: HubConnection) {
        precondition(role.isAnchor, "AnchorController needs an anchor role")
        self.role = role
        self.hub = hub
        self.uwbSupported = CapabilityCheck.supportsUWB
        self.peer = PeerSession(localId: role.deviceId, peerId: DeviceRole.wearer.deviceId)
        peer.onToken = { [weak self] token in self?.hub.send(.uwbToken(token)) }
        peer.onPhase = { [weak self] phase in self?.phaseChanged(phase) }
    }

    /// Label from the hub's snapshot (`space.anchors`), else "UWB Reader/Emitter N".
    var label: String { hub.anchorLabels[role.deviceId] ?? role.label }

    func start() {
        hub.onMessage = { [weak self] message in self?.handle(message) }
        hub.onConnected = { [weak self] in
            self?.peer.publishToken()
            self?.sendStatus()
        }
        hub.start()
        peer.start()
        refresh()
        loops = [
            everySeconds(0.25) { [weak self] in self?.refresh() },
            everySeconds(Self.statusInterval) { [weak self] in self?.sendStatus() },
        ]
    }

    func stop() {
        loops.forEach { $0.cancel() }
        loops = []
        peer.stop()
        hub.stop()
    }

    func appBecameActive() {
        hub.reconnectNow()
        refresh()
    }

    func appWentToBackground() {
        // Nearby Interaction suspends the session itself (sessionWasSuspended) and resumes via
        // sessionSuspensionEnded; nothing to do here.
    }

    // MARK: Bus

    private func handle(_ message: BusMessage) {
        switch message {
        case .uwbToken(let token):
            guard token.to == role.deviceId, token.from == DeviceRole.wearer.deviceId else { return }
            peer.receivePeerToken(token.tokenB64)
        case .reset:
            break   // UWB-PRD 8.1: reset clears nothing; sessions keep running
        default:
            break
        }
    }

    private func phaseChanged(_ phase: PeerSession.Phase) {
        self.phase = phase
        switch phase {
        case .suspended, .denied, .unsupported, .failed, .peerEnded, .running:
            sendStatus()   // report notable changes right away, not only on the 5 s tick
        default:
            break
        }
    }

    private func refresh() {
        phase = peer.phase
        distance = peer.lastDistance
        distanceStale = (peer.distanceAge ?? .infinity) > Self.staleAfter
        batteryText = DeviceInfo.batteryText
    }

    private func sendStatus() {
        let running = peer.isRanging
        var info = CapabilityCheck.info
        info["role"] = .string("anchor")
        info["device_id"] = .string(role.deviceId)
        info["label"] = .string(label)
        info["uwb_running"] = .bool(running)
        info["session_state"] = .string(peer.phase.label)
        info["last_distance_m"] = peer.lastDistance.map { JSONScalar.number($0) } ?? .null
        info["distance_age_s"] = peer.distanceAge.map { JSONScalar.number(($0 * 10).rounded() / 10) } ?? .null
        info["battery"] = DeviceInfo.batteryLevel.map { JSONScalar.number($0) } ?? .null
        info["charging"] = .bool(DeviceInfo.isCharging)

        let ok: Bool
        let detail: String
        switch peer.phase {
        case .unsupported:
            ok = false; detail = "\(label): UWB not supported on this iPhone"
        case .denied:
            ok = false; detail = "\(label): Nearby Interaction permission denied"
        case .failed(let why):
            ok = false; detail = "\(label): session failed (\(why)), restarting"
        case .running:
            ok = true; detail = "\(label): ranging to wearer" + (peer.lastDistance.map { ", \(metres($0))" } ?? "")
        default:
            ok = true; detail = "\(label): \(peer.phase.label)"
        }
        hub.send(.status(Status(component: .iosAnchor, ok: ok, detail: detail, info: info)))
    }
}
