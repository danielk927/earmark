import EarmarkContracts
import Foundation
import NearbyInteraction

/// The handheld phone (UWB-PRD 7.4): three NISessions, one per anchor, each with its own token
/// (`uwb_token {from: "wearer", to: "uwb_N"}`). Every non-nil distance becomes `uwb_range` (per-anchor seq,
/// at most 20 Hz per anchor). Also sends `motion_state` (on change + 1 s heartbeat), push-to-talk `mic_audio`,
/// and `status` every 5 s.
///
/// Round-robin fallback (UWB-PRD 7.6 open risk): if the phone can't sustain three sessions, range to two at a
/// time and rotate the resting one every 2 s. Turned on by the toggle, or automatically when a session is
/// invalidated with `activeSessionsLimitExceeded`.
@MainActor
final class WearerController: ObservableObject {
    struct AnchorRow: Identifiable, Equatable {
        let id: String
        var label: String
        var distance: Double?
        var stale: Bool
        /// Distances per second from Nearby Interaction.
        var measuredHz: Double
        /// `uwb_range` messages per second sent to the hub (after decimation).
        var sentHz: Double
        var phase: String
        var ranging: Bool
        var held: Bool
        /// The anchor phone itself reported `status` recently.
        var phoneOnline: Bool
    }

    static let anchorIds = ["uwb_1", "uwb_2", "uwb_3"]
    static let maxRangeHz = 20.0
    static let roundRobinPeriod = 2.0
    static let statusInterval = 5.0
    static let motionHeartbeat = 1.0
    static let staleAfter = 2.0
    /// Anchors report status every 5 s; allow two missed reports.
    static let anchorStatusTimeout = 12.0
    private static let roundRobinKey = "earmark.roundRobin"

    let role = DeviceRole.wearer
    let hub: HubConnection
    let uwbSupported: Bool

    @Published private(set) var rows: [AnchorRow] = []
    @Published private(set) var motion: MotionState.State?
    @Published private(set) var talking = false
    @Published private(set) var micMessage: String?
    @Published private(set) var poseSummary: String?
    @Published private(set) var batteryText = "Unknown"
    @Published private(set) var roundRobinNote: String?
    @Published var roundRobin: Bool {
        didSet {
            guard roundRobin != oldValue else { return }
            UserDefaults.standard.set(roundRobin, forKey: Self.roundRobinKey)
            applyRoundRobin()
        }
    }

    private var slots: [String: PeerSession] = [:]
    private var decimators: [String: RangeDecimator] = [:]
    private var measuredMeters: [String: RateMeter] = [:]
    private var sentMeters: [String: RateMeter] = [:]
    private var seq: [String: Int] = [:]
    private var anchorStatusSeen: [String: Double] = [:]
    private let motionDetector = MotionDetector()
    private let mic = PushToTalk()
    private var micSeq = 0
    private var loops: [Task<Void, Never>] = []
    private var roundRobinLoop: Task<Void, Never>?
    private var roundRobinTick = 0
    private var running = false

    init(hub: HubConnection) {
        self.hub = hub
        self.uwbSupported = CapabilityCheck.supportsUWB
        self.roundRobin = UserDefaults.standard.bool(forKey: Self.roundRobinKey)
        for id in Self.anchorIds {
            let slot = PeerSession(localId: DeviceRole.wearer.deviceId, peerId: id)
            slot.onToken = { [weak self] token in self?.hub.send(.uwbToken(token)) }
            slot.onDistance = { [weak self] meters in self?.range(from: id, meters: meters) }
            slot.onPhase = { [weak self] _ in self?.refresh() }
            slot.onInvalidated = { [weak self] error in self?.sessionInvalidated(id, error: error) }
            slots[id] = slot
        }
    }

    func label(for anchorId: String) -> String {
        hub.anchorLabels[anchorId] ?? DeviceRole.defaultLabel(for: anchorId)
    }

    func start() {
        guard !running else { return }
        running = true
        hub.onMessage = { [weak self] message in self?.handle(message) }
        hub.onConnected = { [weak self] in self?.hubConnected() }
        hub.start()

        motionDetector.onChange = { [weak self] state in self?.motionChanged(state) }
        motionDetector.start()
        mic.onChunk = { [weak self] data in self?.sendMic(data) }

        for id in Self.anchorIds { slots[id]?.start() }
        applyRoundRobin()
        refresh()
        loops = [
            everySeconds(0.25) { [weak self] in self?.refresh() },
            everySeconds(Self.motionHeartbeat) { [weak self] in self?.motionHeartbeat() },
            everySeconds(Self.statusInterval) { [weak self] in self?.sendStatus() },
        ]
    }

    func stop() {
        running = false
        loops.forEach { $0.cancel() }
        loops = []
        roundRobinLoop?.cancel(); roundRobinLoop = nil
        setTalking(false)
        motionDetector.stop()
        slots.values.forEach { $0.stop() }
        hub.stop()
    }

    func appBecameActive() {
        hub.reconnectNow()
        refresh()
    }

    func appWentToBackground() {
        setTalking(false)   // never leave the mic open in the background
    }

    // MARK: Push-to-talk

    func setTalking(_ on: Bool) {
        guard on != talking else { return }
        if !on {
            talking = false
            mic.stop()
            return
        }
        talking = true
        micMessage = nil
        Task { [weak self] in
            let granted = await PushToTalk.requestPermission()
            guard let self, self.talking else { return }
            guard granted else {
                self.talking = false
                self.micMessage = "Microphone access is off. Turn it on in Settings > Privacy & Security > Microphone."
                return
            }
            do {
                try self.mic.start()
            } catch {
                self.talking = false
                self.micMessage = "Microphone error: \(error.localizedDescription)"
                Log.mic.error("talk start failed: \(error.localizedDescription, privacy: .public)")
            }
        }
    }

    private func sendMic(_ data: Data) {
        guard talking else { return }
        hub.send(.micAudio(MicAudio(seq: micSeq, sampleRate: PushToTalk.sampleRate, chunkB64: data.base64EncodedString())))
        micSeq += 1
    }

    // MARK: Ranging

    private func range(from anchor: String, meters: Double) {
        let now = uptime()
        measuredMeters[anchor, default: RateMeter()].record(now)
        guard decimators[anchor, default: RangeDecimator(maxHz: Self.maxRangeHz)].shouldSend(at: now) else { return }
        let n = seq[anchor, default: 0]
        seq[anchor] = n + 1
        sentMeters[anchor, default: RateMeter()].record(now)
        hub.send(.uwbRange(UwbRange(anchor: anchor, distanceM: meters, seq: n)))
    }

    private func sessionInvalidated(_ anchor: String, error: Error) {
        guard (error as? NIError)?.code == .activeSessionsLimitExceeded, !roundRobin else { return }
        Log.ni.error("session limit hit on \(anchor, privacy: .public); switching to round-robin")
        roundRobinNote = "This iPhone can't run three sessions at once, so round-robin was turned on."
        roundRobin = true
    }

    private func applyRoundRobin() {
        roundRobinLoop?.cancel(); roundRobinLoop = nil
        guard running else { return }
        guard roundRobin else {
            slots.values.forEach { $0.release() }
            return
        }
        rotate()
        roundRobinLoop = everySeconds(Self.roundRobinPeriod) { [weak self] in self?.rotate() }
    }

    /// Rest one anchor, run the other two. Hold first, then release, so three never run at once.
    private func rotate() {
        let resting = Self.anchorIds[roundRobinTick % Self.anchorIds.count]
        roundRobinTick += 1
        slots[resting]?.hold()
        for id in Self.anchorIds where id != resting { slots[id]?.release() }
    }

    // MARK: Motion

    private func motionChanged(_ state: MotionState.State) {
        motion = state
        hub.send(.motionState(MotionState(state: state)))
    }

    private func motionHeartbeat() {
        guard let motion else { return }
        hub.send(.motionState(MotionState(state: motion)))
    }

    // MARK: Bus

    private func hubConnected() {
        for id in Self.anchorIds { slots[id]?.publishToken() }
        if let motion { hub.send(.motionState(MotionState(state: motion))) }
        sendStatus()
    }

    private func handle(_ message: BusMessage) {
        switch message {
        case .uwbToken(let token):
            guard token.to == role.deviceId, let slot = slots[token.from] else { return }
            slot.receivePeerToken(token.tokenB64)
        case .listenerPose(let pose):
            poseSummary = Self.describe(pose)
        case .status(let status):
            guard status.component == .iosAnchor, case .string(let id)? = status.info?["device_id"] else { return }
            anchorStatusSeen[id] = uptime()
        case .reset:
            break   // UWB-PRD 8.1: reset clears nothing; sessions keep running
        default:
            break
        }
    }

    // MARK: UI and status

    private func refresh() {
        let now = uptime()
        var next: [AnchorRow] = []
        for id in Self.anchorIds {
            guard let slot = slots[id] else { continue }
            next.append(AnchorRow(
                id: id,
                label: label(for: id),
                distance: slot.lastDistance,
                stale: (slot.distanceAge ?? .infinity) > Self.staleAfter,
                measuredHz: measuredMeters[id, default: RateMeter()].rate(at: now),
                sentHz: sentMeters[id, default: RateMeter()].rate(at: now),
                phase: slot.phase.label,
                ranging: slot.isRanging,
                held: slot.isHeld,
                phoneOnline: anchorStatusSeen[id].map { now - $0 < Self.anchorStatusTimeout } ?? false
            ))
        }
        if next != rows { rows = next }
        let battery = DeviceInfo.batteryText
        if battery != batteryText { batteryText = battery }
    }

    private func sendStatus() {
        refresh()
        var info = CapabilityCheck.info
        info["role"] = .string("wearer")
        info["device_id"] = .string(role.deviceId)
        info["round_robin"] = .bool(roundRobin)
        info["talking"] = .bool(talking)
        info["motion"] = motion.map { JSONScalar.string($0.rawValue) } ?? .null
        info["battery"] = DeviceInfo.batteryLevel.map { JSONScalar.number($0) } ?? .null
        info["charging"] = .bool(DeviceInfo.isCharging)
        info["sessions_running"] = .number(Double(rows.filter(\.ranging).count))
        for row in rows {
            info["\(row.id)_hz"] = .number((row.sentHz * 10).rounded() / 10)
            info["\(row.id)_measured_hz"] = .number((row.measuredHz * 10).rounded() / 10)
            info["\(row.id)_m"] = row.distance.map { JSONScalar.number($0) } ?? .null
            info["\(row.id)_state"] = .string(row.phase)
        }

        let missing = rows.filter { !$0.ranging && !$0.held }.map(\.label)
        let ok: Bool
        let detail: String
        if !uwbSupported {
            ok = false; detail = "Wearer: UWB not supported on this iPhone"
        } else if missing.isEmpty {
            ok = true; detail = "Wearer: ranging" + (roundRobin ? " (round-robin)" : " to all anchors")
        } else {
            ok = false; detail = "Wearer: not ranging to " + missing.joined(separator: ", ")
        }
        hub.send(.status(Status(component: .iosWearer, ok: ok, detail: detail, info: info)))
    }

    private static func describe(_ pose: ListenerPose) -> String {
        let x = pose.position.count > 0 ? pose.position[0] : 0
        let y = pose.position.count > 1 ? pose.position[1] : 0
        var text = "\(pose.mode?.rawValue ?? "none"), \(pose.anchorsUsed ?? 0) anchors, x \(String(format: "%.2f", x)) m, y \(String(format: "%.2f", y)) m"
        if let blocked = pose.blocked, !blocked.isEmpty { text += ", blocked: " + blocked.joined(separator: ", ") }
        return text
    }
}
