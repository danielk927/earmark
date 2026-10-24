import AVFoundation
import SwiftUI
import EarmarkCore

@MainActor
final class LocatorModel: ObservableObject {
    enum SessionState: Equatable { case stopped, starting, microphone, file }
    @Published var config = LocatorConfig()
    @Published private(set) var sessionState = SessionState.stopped
    @Published private(set) var quality: Quality?
    @Published private(set) var ear = Vector3.zero
    @Published private(set) var mic: Vector3?
    @Published private(set) var detections: [Arrival] = []
    @Published private(set) var history: [String: [Double]] = [:]
    @Published private(set) var residual = 0.0
    @Published private(set) var lock = CycleState.acquiring
    @Published private(set) var dropped = 0
    @Published private(set) var frames = 0
    @Published private(set) var actualRate = 0.0
    @Published private(set) var fixRate = 0.0
    @Published private(set) var route = "Not running"
    @Published private(set) var ptt = false
    @Published private(set) var recording = false
    @Published private(set) var manual = false
    @Published private(set) var manualEar = Vector3(0, 0, 1.60)
    @Published private(set) var progress: Double?
    @Published var error: String?
    @Published var notice = "Start on the mat, phone upright at chest height. AirPods stay connected to the Mac."
    @Published private(set) var templates: [CapturedTemplate] = []
    @Published private(set) var savedPoints: [SavedPoint] = []
    @Published private(set) var captureBeacon: String?
    @Published private(set) var files: [URL] = []
    let hub = HubConnection()
    private let audio = AudioCapture()
    private var processing: ProcessingSession?
    private var publisher = PosePublisher()
    private var recentFixes: [Fix] = []
    private var fixTimes: [Double] = []
    private var tickTimer: Timer?
    private var lastStatus = Date.distantPast
    private var lastManual = Date.distantPast
    private var joystick = Vector3.zero
    private var startingAt: Double?
    private var generation = UUID()
    private var lastQuality: Quality?
    private let directory: URL

    init() {
        directory = FileManager.default.urls(for: .documentDirectory, in: .userDomainMask)[0]
        load()
        hub.onPTT = { [weak self] state in self?.setPTT(state == .start, broadcast: false) }
        hub.onChange = { [weak self] in self?.objectWillChange.send(); self?.sendStatus() }
        hub.onFailure = { [weak self] message in self?.notice = message }
        hub.onPoseSent = { [weak self] pose in self?.processing?.logPose(pose, sent: true) }
        audio.onRouteChange = { [weak self] in self?.checkRoute() }
        audio.onInterruption = { [weak self] in
            guard let self, self.sessionState == .microphone else { return }
            self.stop(); self.error = "Microphone interrupted. Return to the app and tap Start to reacquire."
        }
        tickTimer = Timer.scheduledTimer(withTimeInterval: 0.05, repeats: true) { [weak self] _ in
            Task { @MainActor [weak self] in self?.tick() }
        }
    }
    private func load() {
        do {
            let settings = directory.appendingPathComponent("settings.json")
            if FileManager.default.fileExists(atPath: settings.path) { config = try LocatorConfig.importing(Data(contentsOf: settings)) }
            let templateURL = directory.appendingPathComponent("templates.json")
            if FileManager.default.fileExists(atPath: templateURL.path) { templates = try JSONDecoder().decode([CapturedTemplate].self, from: Data(contentsOf: templateURL)) }
            let pointsURL = directory.appendingPathComponent("points.json")
            if FileManager.default.fileExists(atPath: pointsURL.path) { savedPoints = try JSONDecoder().decode([SavedPoint].self, from: Data(contentsOf: pointsURL)) }
        } catch { self.error = "Saved data could not load: \(error.localizedDescription). Review Settings before starting." }
    }
    var running: Bool { sessionState == .microphone || sessionState == .file }
    var status: String {
        if manual { return "MANUAL — TESTING ONLY" }
        if sessionState == .starting { return "STARTING" }
        switch quality {
        case .ok: return "TRACKING"
        case .degraded: return "DEGRADED"
        case .lost: return "LOST"
        case nil: return running ? "ACQUIRING" : "STOPPED"
        }
    }
    func applySettings(_ updated: LocatorConfig) throws {
        try updated.validate()
        stop(); config = updated
        try updated.exported().write(to: directory.appendingPathComponent("settings.json"), options: .atomic)
        hub.connect(config: config)
        notice = "Settings saved. Start to acquire with the new configuration."
    }
    func start() {
        guard sessionState == .stopped else { return }
        sessionState = .starting; error = nil
        let token = UUID(); generation = token
        Task {
            guard await AVAudioApplication.requestRecordPermission() else {
                guard generation == token else { return }
                sessionState = .stopped; error = "Microphone permission denied. Enable Earmark Locator in Settings → Privacy & Security → Microphone, then retry."
                return
            }
            guard generation == token else { return }
            do {
                try config.validate()
                let worker = makeProcessing()
                try audio.start(preferredRate: config.fs, receive: { worker.enqueue($0) }, invalidClock: { [weak self] in
                    Task { @MainActor [weak self] in self?.error = "Audio clock unavailable; stop and retry capture." }
                })
                route = audio.route; actualRate = audio.actualRate
                sessionState = .microphone; beginSession()
            } catch { stop(); self.error = error.localizedDescription }
        }
    }
    private func beginSession() {
        publisher = PosePublisher(); quality = nil; mic = nil; recentFixes = []; fixTimes = []; fixRate = 0
        startingAt = Date().timeIntervalSince1970
        UIApplication.shared.isIdleTimerDisabled = true
        hub.connect(config: config); sendStatus()
    }
    private func makeProcessing() -> ProcessingSession {
        let worker = ProcessingSession(config: config, directory: directory, templates: templates)
        let token = generation
        worker.onSnapshot = { [weak self] snapshot in Task { @MainActor [weak self] in
            guard let self, self.generation == token else { return }; self.receive(snapshot)
        } }
        worker.onSpeech = { [weak self] chunks, stop in Task { @MainActor [weak self] in
            guard let self, self.generation == token else { return }; self.sendSpeech(chunks, stop: stop)
        } }
        worker.onError = { [weak self] message in Task { @MainActor [weak self] in
            guard let self, self.generation == token else { return }
            self.error = message; self.captureBeacon = nil
        } }
        worker.onTemplate = { [weak self] template in Task { @MainActor [weak self] in
            guard let self, self.generation == token else { return }; self.storeTemplate(template)
        } }
        worker.onFiles = { [weak self] urls in Task { @MainActor [weak self] in self?.files = urls } }
        worker.onFinished = { [weak self] in Task { @MainActor [weak self] in
            guard let self, self.generation == token else { return }; self.stop()
        } }
        processing = worker
        return worker
    }
    func stop() {
        if ptt { sendSpeech(processing?.finishSpeech() ?? [], stop: true); ptt = false }
        processing?.stop(); processing = nil
        do { try audio.stop() } catch { self.error = "Audio shutdown: \(error.localizedDescription)" }
        generation = UUID(); sessionState = .stopped; recording = false; captureBeacon = nil
        manual = false; joystick = .zero; quality = nil; startingAt = nil
        UIApplication.shared.isIdleTimerDisabled = false
        sendStatus()
    }
    private func checkRoute() {
        guard sessionState == .microphone else { return }
        let inputs = AVAudioSession.sharedInstance().currentRoute.inputs
        guard inputs.allSatisfy({ $0.portType == .builtInMic }), !inputs.isEmpty,
              AVAudioSession.sharedInstance().sampleRate == actualRate else {
            stop(); error = "Microphone route changed. Tap Start to select the built-in microphone and reset tracking."
            return
        }
        route = inputs.map(\.portName).joined(separator: ", ")
    }
    private func receive(_ snapshot: ProcessingSnapshot) {
        detections = snapshot.detections; lock = snapshot.lock; dropped = snapshot.dropped
        frames = snapshot.frames; actualRate = snapshot.fs; progress = snapshot.progress
        for beacon in config.beacons {
            history[beacon.id, default: []].append(snapshot.detections.first { $0.beacon == beacon.id }?.snr ?? 0)
            history[beacon.id] = Array(history[beacon.id, default: []].suffix(80))
        }
        for fix in snapshot.fixes { receiveFix(fix) }
    }
    private func receiveFix(_ fix: Fix) {
        mic = fix.mic_position; residual = fix.residual_rms_ms
        recentFixes.append(fix); recentFixes = recentFixes.filter { fix.t - $0.t <= 3 }
        fixTimes.append(fix.t)
        guard !manual else { return }
        ear = fix.ear_position; quality = fix.quality
        let pose = publisher.accept(fix, source: sessionState == .file ? .sim : .beacons)
        let sent = hub.sendPose(pose, nativeBridge: config.hub_auth_mode == .native)
        if !sent { processing?.logPose(pose, sent: false) }
        if lastQuality != quality { lastQuality = quality; sendStatus() }
    }
    private func tick() {
        let now = Date().timeIntervalSince1970
        fixTimes = fixTimes.filter { now - $0 <= 3 }
        fixRate = Double(fixTimes.count) / min(3, max(0.3, now - (startingAt ?? now)))
        if manual { manualTick(now: now) }
        else if running {
            if let lost = publisher.timeout(now: now, seconds: config.lost_timeout) {
                quality = .lost
                let sent = hub.sendPose(lost, nativeBridge: false)
                if !sent { processing?.logPose(lost, sent: false) }; sendStatus()
            } else if quality == nil, let startingAt, now - startingAt >= config.lost_timeout { quality = .lost; sendStatus() }
        }
        if Date().timeIntervalSince(lastStatus) >= 2 { sendStatus() }
    }
    func sendStatus() {
        let detail = "beacons \(detections.count)/5, \(String(format: "%.1f", fixRate)) fix/s, quality \(quality?.rawValue ?? "acquiring"), src \(manual ? "manual" : sessionState == .file ? "sim" : "beacons")"
        _ = hub.send(LocatorStatus(ok: running && quality != .lost, detail: detail), type: "status")
        lastStatus = Date()
    }
    func setPTT(_ active: Bool, broadcast: Bool = true) {
        guard ptt != active, !active || sessionState == .microphone else { return }
        if active && broadcast && !hub.send(PTTMessage(.start), type: "ptt") {
            error = "Hub is not ready for push-to-talk. Check its connection and retry."; return
        }
        ptt = active; processing?.setPTT(active, broadcastStop: !active && broadcast); sendStatus()
    }
    private func sendSpeech(_ chunks: [MicAudio], stop: Bool) {
        if !hub.sendSpeech(chunks, stop: stop) {
            notice = "Speech transport unavailable. Release push-to-talk and retry after reconnecting."
        }
    }
    func setRecording(_ active: Bool) {
        guard sessionState == .microphone else { return }
        recording = active; processing?.record(active)
    }
    func runFile(_ url: URL) {
        stop(); error = nil; generation = UUID(); sessionState = .file
        let worker = makeProcessing(); beginSession(); route = "WAV file — simulated input"; worker.playFile(url)
    }
    func captureTemplate(_ beacon: String) {
        guard sessionState == .microphone else { error = "Start the microphone before capturing a template."; return }
        captureBeacon = beacon; processing?.captureTemplate(beacon)
    }
    private func storeTemplate(_ template: CapturedTemplate) {
        do {
            templates.removeAll { $0.beacon == template.beacon }; templates.append(template)
            try JSONEncoder().encode(templates).write(to: directory.appendingPathComponent("templates.json"), options: .atomic)
            captureBeacon = nil; notice = "\(template.beacon): PASS, \(template.copies)/10 copies, SNR \(Int(template.snr))"
        } catch { captureBeacon = nil; self.error = "Template save: \(error.localizedDescription)" }
    }
    func savePoint(label: String) {
        do {
            guard !manual, sessionState == .microphone else { throw LocatorError.invalid("Save points using live beacons, not manual or file mode") }
            let point = try Calibration.savePoint(recentFixes, label: label, now: Date().timeIntervalSince1970)
            savedPoints.append(point)
            try JSONEncoder().encode(savedPoints).write(to: directory.appendingPathComponent("points.json"), options: .atomic)
            copyJSON(point); notice = "Point saved using microphone position, not ear position."
        } catch { self.error = error.localizedDescription }
    }
    func copyJSON<T: Encodable>(_ value: T) {
        do { let encoder = JSONEncoder(); encoder.outputFormatting = [.prettyPrinted, .sortedKeys]
            UIPasteboard.general.string = String(decoding: try encoder.encode(value), as: UTF8.self)
        } catch { self.error = error.localizedDescription }
    }
    func setManual(_ enabled: Bool) {
        manual = enabled; joystick = .zero; lastManual = Date()
        if enabled { hub.connect(config: config); UIApplication.shared.isIdleTimerDisabled = true }
        else { publisher = PosePublisher(); quality = nil; UIApplication.shared.isIdleTimerDisabled = running }
        sendStatus()
    }
    func steer(x: Double, y: Double) {
        let length = max(1, hypot(x, y)); joystick = Vector3(x / length, y / length, 0)
    }
    private func manualTick(now: Double) {
        let dt = Date().timeIntervalSince(lastManual)
        guard dt >= 0.2 else { return }
        lastManual = Date(); manualEar = manualEar + joystick * (min(dt, 0.25) * 1.2)
        ear = manualEar
        _ = hub.sendPose(ListenerPose(position: manualEar, quality: .ok, beacons: 0, source: .manual, t: now), nativeBridge: config.hub_auth_mode == .native)
    }
}
