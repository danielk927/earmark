import AppKit
import EarmarkAudio
import EarmarkContracts
import EarmarkUI
import Foundation
import SwiftUI

/// Launch flags for unattended runs.
struct LaunchFlags {
    var mockHead = false
    var noMic = false
    var silent = false
    var debug = false
    var renderer: RendererKind?
    var mockYaw: Double?
    var busURL: URL?
    var listen: ListenMode?

    /// `--mock-head --no-mic --silent --debug --renderer=<kind> --bus-url=<ws url> --listen=ptt|always --mock-yaw=<deg>`
    static func parse(_ args: LaunchArgs = LaunchArgs()) -> LaunchFlags {
        var f = LaunchFlags()
        f.mockHead = args.has("mock-head")
        f.noMic = args.has("no-mic")
        f.silent = args.has("silent")
        f.debug = args.has("debug")
        f.renderer = args.value("renderer").flatMap(RendererKind.init(rawValue:))
        f.mockYaw = args.value("mock-yaw").flatMap(Double.init)
        f.busURL = args.value("bus-url").flatMap(URL.init(string:))
        f.listen = args.value("listen").map { $0.hasPrefix("always") ? .alwaysListening : .pushToTalk }
        return f
    }
}

/// Head pose and guidance numbers, published at 25 Hz for the map and the guidance card only.
@MainActor
final class PoseModel: ObservableObject {
    @Published var yaw = 0.0
    @Published var pitch = 0.0
    @Published var rateHz = 0.0
    @Published var tracking = false
    @Published var guidance: GuidanceState?
    /// Where the locator/UWB says the user stands (room frame); the origin when seated.
    @Published var listener: EarmarkPoint = .zero
    /// The head faces backward (|yaw| > 110 deg, back under 80): the map centers the listener so the cone stays visible.
    @Published var facingBack = false

    func update(yaw: Double) {
        self.yaw = yaw
        let a = abs(yaw)
        if !facingBack && a > 110 { facingBack = true } else if facingBack && a < 80 { facingBack = false }
    }
}

@MainActor
final class AppModel: ObservableObject {
    let flags = LaunchFlags.parse()
    let core: EarmarkCore
    let pose = PoseModel()
    private let busClient: BusClient
    private let speechPlayer: SpeechPlayer
    private let appleSpeech = AppleSpeechRecognizer()
    private let routes = AudioRouteController()
    private let pipeline: MicPipeline
    private var mic: MicCapture?
    private let keys = KeyMonitor()
    private var timer: Timer?
    private var tickCount = 0
    private var refreshPending = false

    /// Bumped (coalesced) whenever core state changes, so views re-read it.
    @Published private(set) var revision = 0
    @Published private(set) var busState: BusConnectionState = .idle
    @Published private(set) var micStatus = "Starting"
    @Published private(set) var micSeverity: Severity = .neutral
    @Published private(set) var appleStatus: String?
    @Published private(set) var micLevelDb = -120.0
    @Published private(set) var pttHeld = false
    @Published private(set) var routingNotice: String?
    @Published var showDebug: Bool
    @Published var showSettings = false

    @Published var mockHead: Bool { didSet { if mockHead != oldValue { core.replaceHead(makeHead()) } } }
    @Published var listenMode: ListenMode {
        didSet { pipeline.mode = listenMode; core.listenMode = listenMode; UserDefaults.standard.set(listenMode.rawValue, forKey: "listenMode") }
    }
    @Published var enforceBuiltInMic: Bool {
        didSet { routes.enforceBuiltInMic = enforceBuiltInMic; UserDefaults.standard.set(enforceBuiltInMic, forKey: "enforceBuiltInMic"); routingNotice = routes.lastAction }
    }
    @Published var rendererChoice: RendererKind {
        didSet { if rendererChoice != oldValue { core.applyRenderer(rendererChoice); UserDefaults.standard.set(rendererChoice.rawValue, forKey: "renderer") } }
    }
    @Published var timbre: PingTimbre { didSet { core.timbre = timbre; UserDefaults.standard.set(timbre.rawValue, forKey: "timbre") } }
    /// Walking guidance tuning, by ear (PRD 10.1).
    @Published var attenuation: DistanceAttenuation {
        didSet {
            core.distanceAttenuation = attenuation
            let d = UserDefaults.standard
            d.set(attenuation.referenceDistance, forKey: "attenuationReference")
            d.set(attenuation.maximumDistance, forKey: "attenuationMaximum")
            d.set(attenuation.rolloffFactor, forKey: "attenuationRolloff")
        }
    }

    init() {
        let d = UserDefaults.standard
        let renderer = flags.renderer ?? d.string(forKey: "renderer").flatMap(RendererKind.init(rawValue:)) ?? .avaudioHRTFHQ
        let listen = flags.listen ?? d.string(forKey: "listenMode").flatMap(ListenMode.init(rawValue:)) ?? .pushToTalk
        rendererChoice = renderer
        listenMode = listen
        timbre = d.string(forKey: "timbre").flatMap(PingTimbre.init(rawValue:)) ?? .tone
        enforceBuiltInMic = d.object(forKey: "enforceBuiltInMic") as? Bool ?? true
        var att = DistanceAttenuation()
        if let v = d.object(forKey: "attenuationReference") as? Double { att.referenceDistance = v }
        if let v = d.object(forKey: "attenuationMaximum") as? Double { att.maximumDistance = v }
        if let v = d.object(forKey: "attenuationRolloff") as? Double { att.rolloffFactor = v }
        attenuation = att
        mockHead = flags.mockHead
        showDebug = flags.debug

        busClient = BusClient(url: flags.busURL ?? BusClient.defaultURL)
        speechPlayer = SpeechPlayer(phrases: PhraseLibrary.standard(repoRoot: RepoLocator.root()))
        pipeline = MicPipeline(mode: listen)
        let head: HeadTracking = flags.mockHead ? MockHeadTracker() : HeadphoneMotionTracker()
        core = EarmarkCore(head: head, speech: speechPlayer, bus: busClient, preferredRenderer: renderer)
        core.listenMode = listen
        core.timbre = timbre
        core.micEnabled = !flags.noMic
        core.distanceAttenuation = att
        routes.enforceBuiltInMic = enforceBuiltInMic
    }

    /// config/space.json in the repo (EARMARK_REPO_ROOT, the build_app.sh Info.plist key, or a parent folder).
    var spaceFileURL: URL? { RepoLocator.root()?.appendingPathComponent("config/space.json") }

    /// The UWB calibration sheet's state (kept while the app runs; the form reloads from disk on open).
    lazy var calibration = CalibrationModel(core: core, fileURL: spaceFileURL)

    var mockTracker: MockHeadTracker? { core.head as? MockHeadTracker }

    private func makeHead() -> HeadTracking { mockHead ? MockHeadTracker() : HeadphoneMotionTracker() }

    func start() {
        guard timer == nil else { return }
        Log.app("Earmark starting: bus \(busClient.url.absoluteString), renderer \(rendererChoice.rawValue), mock head \(mockHead), mic \(flags.noMic ? "off" : listenMode.rawValue), silent \(flags.silent)")
        core.onChange = { [weak self] in self?.scheduleRefresh() }
        loadInitialSpace()

        // 1. Routing rule before any playback engine exists.
        routes.onDevicesChanged = { [weak self] r in self?.devicesChanged(r) }
        routes.onRestartNeeded = { [weak self] why in self?.core.restartAudio(reason: why) }
        routes.start()
        routingNotice = routes.lastAction

        // 2. Playback: speech layer and the renderer ladder.
        core.masterGain = flags.silent ? 0 : 1
        core.startAudio()

        // 3. Head tracking.
        core.head.start()
        if let yaw = flags.mockYaw { mockTracker?.setRawPose(yawDeg: yaw) }

        // 4. Speech input.
        core.apple = appleSpeech
        appleSpeech.onTranscript = { [weak self] text, final in self?.core.appleTranscript(text, final: final) }
        appleSpeech.onStatus = { [weak self] s in self?.appleStatus = s }
        core.onAppleSpeechNeeded = { [weak self] in self?.ensureAppleSpeech() }
        pipeline.onOutput = { [weak self] out in self?.core.ingestGate(out) }
        startMic()

        // 5. Bus.
        busClient.onState = { [weak self] s in
            guard let self else { return }
            self.busState = s
            self.core.busStateChanged(s)
        }
        busClient.onMessage = { [weak self] m in self?.core.handle(m) }
        busClient.start()

        installKeys()
        timer = Timer.scheduledTimer(withTimeInterval: 1.0 / 50, repeats: true) { [weak self] _ in
            MainActor.assumeIsolated { self?.tick() }
        }
        RunLoop.main.add(timer!, forMode: .common)
    }

    private func loadInitialSpace() {
        let candidates = [RepoLocator.root()?.appendingPathComponent("config/space.json"),
                          Bundle.main.resourceURL?.appendingPathComponent("space.json")].compactMap { $0 }
        for url in candidates {
            if let data = try? Data(contentsOf: url), let s = try? BusCoding.decoder.decode(Space.self, from: data) {
                core.setInitialSpace(s)
                return
            }
        }
    }

    private func devicesChanged(_ r: DeviceReport) {
        var report = r
        if let mic, mic.isRunning { report.inputDevice = mic.deviceName }
        core.updateDevices(report)
        routingNotice = routes.lastAction
    }

    private func startMic() {
        guard !flags.noMic else {
            micStatus = "Off (--no-mic)"
            micSeverity = .neutral
            devicesChanged(routes.report())
            return
        }
        let uid = ProcessInfo.processInfo.environment["EARMARK_MIC_UID"].flatMap { $0.isEmpty ? nil : $0 }
        let m = MicCapture(preferredUID: uid)
        m.onChunk = { [weak self] chunk in self?.pipeline.process(chunk) }
        mic = m
        m.start { [weak self] error in
            guard let self else { return }
            if let error {
                self.micStatus = "\(error)"
                self.micSeverity = .bad
                self.core.micEnabled = false
            } else {
                self.micStatus = m.deviceName
                self.micSeverity = .ok
            }
            self.devicesChanged(self.routes.report(captureDevice: m.isRunning ? m.deviceName : nil))
        }
    }

    private func ensureAppleSpeech() {
        guard core.micEnabled, !appleSpeech.authorized else { return }
        appleSpeech.requestAuthorization { [weak self] ok in
            self?.appleStatus = ok ? "Apple Speech ready" : "Apple Speech not authorized"
        }
    }

    private func installKeys() {
        keys.on(.space) { [weak self] down, rep, _ in
            guard let self, self.listenMode == .pushToTalk, !rep else { return self?.listenMode == .pushToTalk }
            self.setPTT(down)
            return true
        }
        keys.on(.character("r")) { [weak self] down, rep, _ in
            if down && !rep { self?.core.recenter() }
            return true
        }
        keys.on(.character("p")) { [weak self] down, rep, _ in
            if down && !rep { self?.togglePositioning() }
            return true
        }
        keys.on(.left) { [weak self] down, _, shift in self?.nudge(down, shift ? -5 : -15) ?? false }
        keys.on(.right) { [weak self] down, _, shift in self?.nudge(down, shift ? 5 : 15) ?? false }
        keys.start()
    }

    private func nudge(_ down: Bool, _ d: Double) -> Bool {
        guard let mock = mockTracker else { return false }
        if down { mock.turn(byDeg: d) }
        return true
    }

    func setPTT(_ held: Bool) {
        guard held != pttHeld else { return }
        pttHeld = held
        pipeline.setPushToTalk(held: held)
    }

    func recenter() { core.recenter() }

    /// Hub-confirmed active system; UWB until the hub says otherwise.
    var activePositioning: PositioningSystem { core.positioning?.active ?? .uwb }
    func selectPositioning(_ s: PositioningSystem) { core.selectPositioning(s) }
    func togglePositioning() { core.selectPositioning(PositioningText.other(activePositioning)) }

    private func tick() {
        core.tick()
        tickCount += 1
        guard tickCount % 2 == 0 else { return }
        let p = core.latestPose
        let tracking = core.head.state.isTracking
        pose.tracking = tracking
        pose.update(yaw: tracking ? p.yawDeg : 0)
        pose.pitch = tracking ? p.pitchDeg : 0
        pose.rateHz = core.head.updateRateHz
        pose.guidance = core.guidanceState
        if pose.listener != core.listenerPosition { pose.listener = core.listenerPosition }
        if mic != nil { micLevelDb = pipeline.levelDb }
    }

    private func scheduleRefresh() {
        guard !refreshPending else { return }
        refreshPending = true
        DispatchQueue.main.async { [weak self] in
            guard let self else { return }
            self.refreshPending = false
            self.revision &+= 1
        }
    }

    var micThresholdDb: Double { pipeline.thresholdDb }
    var busURL: String { busClient.url.absoluteString }
}
