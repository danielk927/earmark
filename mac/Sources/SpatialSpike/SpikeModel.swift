import AppKit
import EarmarkAudio
import Foundation
import EarmarkUI
import SwiftUI

/// Phase 0.5 spike: one renderer at a time, preset and random target angles, the blind pointing test,
/// and the results logger. No bus, no network, no mic.
@MainActor
final class SpikeModel: ObservableObject {
    struct Flags {
        var mockHead = false
        var silent = false
        var renderer: RendererKind = .avaudioHRTFHQ
        var logPath = "logs/spatial_gate.jsonl"

        /// `--mock-head --silent --renderer=<kind> --log=<repo-relative path>`
        static func parse(_ args: LaunchArgs = LaunchArgs()) -> Flags {
            var f = Flags()
            f.mockHead = args.has("mock-head")
            f.silent = args.has("silent")
            if let k = args.value("renderer").flatMap(RendererKind.init(rawValue:)) { f.renderer = k }
            if let l = args.value("log") { f.logPath = l }
            return f
        }
    }

    // Head
    @Published var mockHead: Bool { didSet { if mockHead != oldValue { swapHead() } } }
    @Published private(set) var headState: HeadTrackingState = .off
    @Published private(set) var headMessage = ""
    @Published private(set) var yaw = 0.0
    @Published private(set) var pitch = 0.0
    @Published private(set) var roll = 0.0
    @Published private(set) var rateHz = 0.0

    // Renderer and cue
    @Published var rendererKind: RendererKind { didSet { if rendererKind != oldValue { applyRenderer() } } }
    @Published var timbre: PingTimbre = .tone { didSet { renderer?.setTimbre(timbre) } }
    @Published private(set) var rendererError: String?
    @Published private(set) var targetAzimuth: Double?
    @Published var elevation: Double = 0 { didSet { retarget() } }
    @Published var intervalMs: Double = 500 { didSet { updateInterval() } }
    @Published var guidanceRate = false { didSet { updateInterval() } }
    @Published private(set) var pinging = false

    // Devices
    @Published private(set) var outputDevice = "-"
    @Published private(set) var outputRate = 0.0
    @Published private(set) var outputTransport: AudioTransport = .other
    @Published private(set) var hfp = false
    @Published private(set) var latencyMs = 0.0
    @Published private(set) var routingNotice: String?
    @Published var enforceBuiltInMic = true { didSet { routes.enforceBuiltInMic = enforceBuiltInMic } }

    // Blind test
    @Published var trialSet: TrialSet = .front
    @Published var tester = "T1"
    @Published var logPath: String
    @Published private(set) var sessionId: String?
    @Published private(set) var trialNumber = 0
    @Published private(set) var testRunning = false
    @Published var response: Double?
    @Published private(set) var lastResult: GateTrial?
    @Published private(set) var sessionTrials: [GateTrial] = []
    @Published private(set) var logError: String?
    private var hiddenTarget: Double?
    private var previousTarget: Double?

    private(set) var head: HeadTracking
    /// Shared with the head-motion queue, which turns the listener on every sample.
    private let box = RendererBox()
    private var renderer: SpatialRenderer? { box.renderer }
    private let routes = AudioRouteController()
    private let keys = KeyMonitor()
    private var timer: Timer?
    let flags: Flags

    static let targetDistance = 1.0

    init() {
        flags = Flags.parse()
        mockHead = flags.mockHead
        rendererKind = flags.renderer
        logPath = flags.logPath
        head = flags.mockHead ? MockHeadTracker() : HeadphoneMotionTracker()
    }

    var resolvedLogURL: URL { RepoLocator.resolve(logPath) }
    var mock: MockHeadTracker? { head as? MockHeadTracker }

    func start() {
        Log.app("SpatialSpike starting (renderer \(rendererKind.rawValue), mock head \(mockHead), silent \(flags.silent))")
        routes.onDevicesChanged = { [weak self] r in self?.apply(r) }
        routes.onRestartNeeded = { [weak self] why in self?.restartAudio(why) }
        routes.start()                      // routing rule first, then playback
        routingNotice = routes.lastAction
        attachHead()
        head.start()
        applyRenderer()
        keys.on(.character("r")) { [weak self] down, rep, _ in if down && !rep { self?.recenter() }; return true }
        keys.on(.left) { [weak self] down, _, shift in self?.nudge(down, shift ? -5 : -15) ?? false }
        keys.on(.right) { [weak self] down, _, shift in self?.nudge(down, shift ? 5 : 15) ?? false }
        keys.start()
        timer = Timer.scheduledTimer(withTimeInterval: 1.0 / 30, repeats: true) { [weak self] _ in
            MainActor.assumeIsolated { self?.refresh() }
        }
    }

    private func nudge(_ down: Bool, _ deg: Double) -> Bool {
        guard let mock else { return false }
        if down { mock.turn(byDeg: deg) }
        return true
    }

    // MARK: Head

    private func attachHead() {
        let box = self.box
        let tracker = head
        head.onPose = { [weak tracker] s in
            guard let tracker, tracker.state.isTracking else { return }
            box.renderer?.setListener(yawDeg: s.yawDeg, pitchDeg: s.pitchDeg)
        }
        head.onStateChange = { [weak self] state, msg in
            guard let self else { return }
            self.headState = state
            self.headMessage = msg
            if !state.isTracking { self.renderer?.setListener(yawDeg: 0, pitchDeg: 0) }
        }
        headState = head.state
        headMessage = head.message
    }

    private func swapHead() {
        head.stop()
        head.onPose = nil
        head.onStateChange = nil
        head = mockHead ? MockHeadTracker() : HeadphoneMotionTracker()
        attachHead()
        head.start()
    }

    func recenter() {
        head.recenter()
        Log.head("recenter requested")
    }

    // MARK: Renderer

    private func applyRenderer() {
        let old = box.renderer
        box.renderer = nil
        old?.stop()
        let r = RendererFactory.make(rendererKind)
        do {
            try r.start()
            rendererError = nil
        } catch {
            rendererError = "\(rendererKind.displayName) failed to start: \(error)"
            Log.audio(rendererError!)
            return
        }
        r.setMasterGain(flags.silent ? 0 : 1)
        r.setTimbre(timbre)
        let p = head.latestPose
        r.setListener(yawDeg: head.state.isTracking ? p.yawDeg : 0, pitchDeg: head.state.isTracking ? p.pitchDeg : 0)
        if let a = targetAzimuth ?? hiddenTarget {
            r.setTarget(Geometry.point(azimuthDeg: a, elevationDeg: elevation, distance: Self.targetDistance))
        }
        box.renderer = r
        updateInterval()
        latencyMs = r.presentationLatency * 1000
    }

    private func restartAudio(_ why: String) {
        Log.route("restarting audio: \(why)")
        do { try renderer?.restart() } catch {
            Log.audio("restart failed: \(error); rebuilding")
            applyRenderer()
        }
        if !head.state.isTracking && head.state != .notAuthorized && head.state != .notAvailable { head.stop(); head.start() }
        head.recenter()
        latencyMs = (renderer?.presentationLatency ?? 0) * 1000
    }

    private func apply(_ r: DeviceReport) {
        outputDevice = r.outputDevice
        outputRate = r.outputSampleRate
        outputTransport = r.outputTransport
        hfp = r.hfpSuspected
        routingNotice = routes.lastAction
        latencyMs = (renderer?.presentationLatency ?? 0) * 1000
    }

    // MARK: Cue control

    /// Places the ping at an azimuth (deg, + right) relative to the calibrated forward, fixed in the room.
    func place(_ azimuth: Double, reveal: Bool = true) {
        if reveal { targetAzimuth = azimuth }
        renderer?.setTarget(Geometry.point(azimuthDeg: azimuth, elevationDeg: elevation, distance: Self.targetDistance))
        pinging = true
        updateInterval()
    }

    private func retarget() {
        guard let a = targetAzimuth ?? hiddenTarget else { return }
        renderer?.setTarget(Geometry.point(azimuthDeg: a, elevationDeg: elevation, distance: Self.targetDistance))
    }

    func stopPing() {
        pinging = false
        targetAzimuth = nil
        renderer?.setTarget(nil)
        renderer?.setPingInterval(nil)
    }

    func playOnce(_ cue: Cue) { renderer?.play(cue) }

    private func updateInterval() {
        guard pinging else { renderer?.setPingInterval(nil); return }
        renderer?.setRepeatingCue(.ping)
        renderer?.setPingInterval(currentInterval())
    }

    private func currentInterval() -> Double {
        // The blind test always uses a fixed rate: a rate that follows the error would give the answer away.
        if guidanceRate && !testRunning, let a = targetAzimuth {
            return Guidance.pingInterval(errorDeg: Guidance.signedErrorDeg(targetAzimuthDeg: a, headYawDeg: yaw))
        }
        return intervalMs / 1000
    }

    // MARK: Blind test

    var tally: GateTally {
        GateTally(trials: sessionTrials.filter { $0.renderer == rendererKind.rawValue && $0.timbre == timbre.rawValue })
    }

    func startSession() {
        sessionId = Self.newSessionID()
        sessionTrials = []
        trialNumber = 0
        lastResult = nil
        logError = nil
        Log.app("gate session \(sessionId!) started, logging to \(resolvedLogURL.path)")
    }

    func nextTrial() {
        if sessionId == nil { startSession() }
        var g = SystemRandomNumberGenerator()
        let a = GateMath.randomAngle(trialSet, previous: previousTarget, using: &g)
        previousTarget = a
        hiddenTarget = a
        trialNumber += 1
        response = nil
        lastResult = nil
        testRunning = true
        targetAzimuth = nil
        place(a, reveal: false)
    }

    func recordResponse() {
        guard let target = hiddenTarget, let resp = response, let session = sessionId else { return }
        let trial = GateTrial(sessionId: session, trial: trialNumber, set: trialSet, renderer: rendererKind.rawValue,
                              timbre: timbre.rawValue, targetDeg: target, responseDeg: resp,
                              headTracking: headState.rawValue, yawAtResponseDeg: (yaw * 10).rounded() / 10,
                              outputDevice: outputDevice, outputSampleRate: outputRate, mockHead: mockHead, tester: tester)
        do {
            try GateLogger(url: resolvedLogURL).append(trial)
            logError = nil
        } catch {
            logError = "Could not write \(resolvedLogURL.path): \(error.localizedDescription)"
        }
        sessionTrials.append(trial)
        lastResult = trial
        testRunning = false
        hiddenTarget = nil
        targetAzimuth = target            // reveal
        Log.app(String(format: "trial %d (%@): target %+.0f response %+.0f error %+.0f%@", trialNumber, trialSet.rawValue,
                       target, resp, trial.errorDeg, trial.frontBackConfusion ? " FRONT/BACK CONFUSION" : ""))
    }

    func cancelTrial() {
        testRunning = false
        hiddenTarget = nil
        stopPing()
    }

    static func newSessionID() -> String {
        let f = DateFormatter()
        f.dateFormat = "yyyyMMdd-HHmmss"
        return f.string(from: Date())
    }

    // MARK: Refresh (30 Hz)

    private func refresh() {
        let p = head.latestPose
        let tracking = head.state.isTracking
        yaw = tracking ? p.yawDeg : 0
        pitch = tracking ? p.pitchDeg : 0
        roll = tracking ? p.rollDeg : 0
        rateHz = head.updateRateHz
        if guidanceRate && pinging { renderer?.setPingInterval(currentInterval()) }
    }
}

/// Lock-protected renderer reference readable from the head-motion queue.
final class RendererBox: @unchecked Sendable {
    private let lock = NSLock()
    private var _renderer: SpatialRenderer?
    var renderer: SpatialRenderer? {
        get { lock.withLock { _renderer } }
        set { lock.withLock { _renderer = newValue } }
    }
}
