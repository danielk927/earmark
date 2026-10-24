import EarmarkContracts
import Foundation

/// The fallback ladder (brief 5.E), applied automatically and shown in the UI.
public enum GuidanceMode: String, Sendable {
    /// 1. Spatial audio with head tracking (normal).
    case spatialTracked = "spatial_tracked"
    /// 2. Spatial audio without head tracking: yaw fixed at 0, relative to the calibrated forward.
    case spatialUntracked = "spatial_untracked"
    /// 3. Exaggerated stereo panning.
    case stereoPan = "stereo_pan"
    /// 4. Speech only.
    case speechOnly = "speech_only"

    public var level: Int {
        switch self { case .spatialTracked: 1; case .spatialUntracked: 2; case .stereoPan: 3; case .speechOnly: 4 }
    }

    public var displayName: String {
        switch self {
        case .spatialTracked: "Spatial + head tracking"
        case .spatialUntracked: "Spatial, head fixed forward"
        case .stereoPan: "Stereo panning"
        case .speechOnly: "Speech only"
        }
    }

    public static func resolve(renderer: RendererKind?, headTracking: Bool) -> GuidanceMode {
        guard let renderer else { return .speechOnly }
        if renderer == .stereoPan { return .stereoPan }
        return headTracking ? .spatialTracked : .spatialUntracked
    }
}

public struct CaptionLine: Identifiable, Equatable, Sendable {
    public enum Speaker: String, Sendable { case earmark, user, system }
    public let id: Int
    public var speaker: Speaker
    public var text: String
    public var isFinal: Bool
    public var source: String
}

/// Devices and routing facts the app reports into the core (for status and the UI).
public struct DeviceReport: Equatable, Sendable {
    public var inputDevice = "unknown"
    public var outputDevice = "unknown"
    public var outputSampleRate: Double = 0
    public var outputTransport: AudioTransport = .other
    public var hfpSuspected = false
    public init() {}
}

/// Wires bus messages to guidance, the renderer, speech, and STT. Call everything on the main thread except
/// `ingestHeadPose` and `ingestGate`, which are safe from the head-motion and mic queues.
public final class EarmarkCore {
    public enum MicRoute: String, Sendable { case none, cartesia, apple }

    // Dependencies
    private let makeRenderer: (RendererKind) -> SpatialRenderer
    public private(set) var head: HeadTracking
    public let speech: SpeechOutput
    public let bus: BusSink
    public var apple: TranscriberInput?
    private let clock: () -> Double
    public let guidanceConfig: GuidanceConfig

    // Observable state (main thread)
    public private(set) var space: Space?
    public private(set) var objects: [RegistryObject] = []
    public private(set) var states: [String: ObjectState] = [:]
    public private(set) var guide: GuideStart?
    public private(set) var guideTarget: EarmarkPoint?
    public private(set) var guidanceState: GuidanceState?
    /// Where the locator says the user stands (room frame); the mat origin until a fix arrives.
    public private(set) var listenerPosition = EarmarkPoint(0, 0, 0)
    /// Distance in meters (horizontal) to the guide target while a locator fix is fresh; nil otherwise.
    public private(set) var targetDistanceM: Double?
    public private(set) var lastFeedback: GuideFeedback?
    public private(set) var preferredRenderer: RendererKind
    public private(set) var rendererFailures: [String] = []
    public private(set) var sttEngine: SttMode.Engine = .cartesia
    public private(set) var sttReason = "default"
    public private(set) var busConnected = false
    public private(set) var captions: [CaptionLine] = []
    public private(set) var recentMessages: [String] = []
    public private(set) var componentStatus: [String: Status] = [:]
    public private(set) var isSpeaking = false
    public private(set) var userSpeaking = false
    public private(set) var devices = DeviceReport()
    public var micEnabled = true { didSet { updateRoute() } }
    public var listenMode: ListenMode = .pushToTalk
    public var timbre: PingTimbre = .tone { didSet { renderer?.setTimbre(timbre) } }
    public var masterGain: Float = 1 { didSet { renderer?.setMasterGain(masterGain); speech.setMasterGain(masterGain) } }
    /// Called after any state change the UI should show (main thread).
    public var onChange: (() -> Void)?
    /// The concierge asked for Apple Speech (the app requests permission and starts the recognizer).
    public var onAppleSpeechNeeded: (() -> Void)?

    // Cross-thread state
    private let lock = NSLock()
    private var _renderer: SpatialRenderer?
    private var _pose = HeadPoseSample()
    private var _tracking = false
    private var _route: MicRoute = .cartesia
    private var utteranceRoute: MicRoute = .none
    private var micSeq = 0

    // Timing
    private var guidance: Guidance?
    private var lastFixAt: Double?
    /// A locator fix older than this is dropped and the user is assumed to be back on the mat (brief: 5 s).
    public static let fixTimeout = 5.0
    private var lastHeadPoseSent = -Double.infinity
    private var lastStatusSent = -Double.infinity
    private var lastStatusKey = ""
    private var captionID = 0
    public static let headPosePeriod = 0.1
    public static let statusHeartbeat = 10.0

    public init(head: HeadTracking, speech: SpeechOutput, bus: BusSink,
                preferredRenderer: RendererKind = .avaudioHRTFHQ,
                guidanceConfig: GuidanceConfig = GuidanceConfig(),
                clock: @escaping () -> Double = { ProcessInfo.processInfo.systemUptime },
                makeRenderer: @escaping (RendererKind) -> SpatialRenderer = RendererFactory.make) {
        self.head = head
        self.speech = speech
        self.bus = bus
        self.preferredRenderer = preferredRenderer
        self.guidanceConfig = guidanceConfig
        self.clock = clock
        self.makeRenderer = makeRenderer
        speech.onPlayback = { [weak self] id, event in self?.playbackEvent(id, event) }
        speech.onSpeakingChanged = { [weak self] on in self?.speakingChanged(on) }
        attachHead()
    }

    public var renderer: SpatialRenderer? { lock.withLock { _renderer } }
    public var latestPose: HeadPoseSample { lock.withLock { _pose } }
    public var micRoute: MicRoute { lock.withLock { _route } }

    public var guidanceMode: GuidanceMode {
        GuidanceMode.resolve(renderer: renderer?.kind == .mock ? .avaudioHRTFHQ : renderer?.kind, headTracking: head.state.isTracking)
    }

    // MARK: Setup

    private func attachHead() {
        let tracking = head.state.isTracking
        lock.withLock { _tracking = tracking }
        head.onPose = { [weak self] s in self?.ingestHeadPose(s) }
        head.onStateChange = { [weak self] _, _ in self?.headStateChanged() }
    }

    /// Swaps the head tracker (Settings: mock head on/off).
    public func replaceHead(_ new: HeadTracking) {
        head.stop()
        head.onPose = nil
        head.onStateChange = nil
        head = new
        attachHead()
        new.start()
        headStateChanged()
    }

    /// Starts speech and the renderer ladder.
    public func startAudio() {
        do { try speech.start() } catch { Log.speech("speech player failed to start: \(error)") }
        applyRenderer(preferredRenderer)
    }

    /// Renderer ladder: the preferred renderer, then stereo pan, then speech only.
    public func applyRenderer(_ preferred: RendererKind) {
        preferredRenderer = preferred
        let old: SpatialRenderer? = lock.withLock { let r = _renderer; _renderer = nil; return r }
        old?.stop()
        var ladder = [preferred]
        if preferred != .stereoPan && preferred != .mock { ladder.append(.stereoPan) }
        rendererFailures = []
        var chosen: SpatialRenderer?
        for kind in ladder {
            let r = makeRenderer(kind)
            do {
                try r.start()
                chosen = r
                break
            } catch {
                rendererFailures.append("\(kind.displayName): \(error)")
                Log.audio("renderer \(kind.rawValue) failed to start: \(error); falling back")
            }
        }
        if let r = chosen { configure(r) } else { Log.audio("no renderer could start: speech only") }
        lock.withLock { _renderer = chosen }
        Log.app("guidance mode: \(guidanceMode.rawValue)")
        tick()
        changed()
    }

    private func configure(_ r: SpatialRenderer) {
        r.setMasterGain(masterGain)
        r.setTimbre(timbre)
        r.setDucked(isSpeaking)
        r.setTarget(guideTarget)
        let (yaw, pitch) = listenerAngles()
        r.setListener(yawDeg: yaw, pitchDeg: pitch)
        if let s = guidanceState {
            r.setRepeatingCue(s.zone == .behind ? .behind : .ping)
            r.setPingInterval(s.pingIntervalSec)
        }
    }

    /// Restart after a route or configuration change, then re-check head tracking and recenter.
    public func restartAudio(reason: String) {
        Log.route("restarting audio: \(reason)")
        if let r = renderer {
            do { try r.restart() } catch {
                Log.audio("renderer restart failed (\(error)); re-running the ladder")
                applyRenderer(preferredRenderer)
            }
        }
        do { try speech.restart() } catch { Log.speech("speech restart failed: \(error)") }
        if !head.state.isTracking && head.state != .notAuthorized && head.state != .notAvailable {
            head.stop()
            head.start()
        }
        head.recenter()
        changed()
    }

    public func updateDevices(_ report: DeviceReport) {
        guard report != devices else { return }
        devices = report
        changed()
    }

    public func setInitialSpace(_ s: Space) {
        if space == nil { space = s; changed() }
    }

    public func recenter() {
        head.recenter()
        addCaption(.system, "Recentered: this direction is now straight ahead.", source: "app")
    }

    // MARK: Bus input

    public func handle(_ message: BusMessage) {
        note("<- \(summary(message))")
        switch message {
        case .snapshot(let s):
            space = s.space
            objects = s.objects
            states = Dictionary(s.states.map { ($0.objectId, $0) }, uniquingKeysWith: { _, b in b })
            updateVocabulary()
        case .registryUpdate(let r):
            objects = r.objects
            updateVocabulary()
        case .stateUpdate(let st):
            states[st.objectId] = st
        case .guideStart(let g):
            startGuidance(g)
        case .guideStop(let g):
            stopGuidance(reason: g.reason.rawValue)
        case .speak(let s):
            if s.seq == 0, let text = s.text { addCaption(.earmark, text, source: "cartesia") }
            speech.handle(s)
        case .speakCached(let s):
            addCaption(.earmark, s.text, source: "cached")
            speech.playCached(phraseId: s.phraseId, utteranceId: s.utteranceId, text: s.text)
        case .speakText(let s):
            addCaption(.earmark, s.text, source: "system voice")
            speech.speakText(utteranceId: s.utteranceId, text: s.text)
        case .sttMode(let m):
            setSttEngine(m.engine, reason: m.reason)
        case .transcript(let t):
            if t.source != .apple { setHeard(t.text, final: t.isFinal, source: t.source.rawValue) }
        case .status(let st):
            if st.component != .macApp { componentStatus[st.component.rawValue] = st }
        case .listenerPose(let p):
            applyListenerPose(p)
        case .reset:
            reset()
        case .pickup, .pickupResult, .hello, .guideFeedback, .micAudio, .playback, .headPose, .ptt, .other:
            break
        }
        changed()
    }

    public func busStateChanged(_ state: BusConnectionState) {
        let on = state == .connected
        guard on != busConnected else { return }
        busConnected = on
        if on { lastStatusKey = ""; lastStatusSent = -.infinity }
        updateRoute()
        tick()
        changed()
    }

    private func startGuidance(_ g: GuideStart) {
        guard let p = Geometry.point(g.targetPosition) else {
            Log.app("guide_start for \(g.objectId) has an invalid target_position; ignored")
            return
        }
        guide = g
        guideTarget = p
        let rel = relativeTarget(p)
        guidance = Guidance(target: rel, config: guidanceConfig)
        guidanceState = nil
        lastFeedback = nil
        renderer?.setTarget(rel)
        renderer?.setRepeatingCue(.ping)
        Log.app(String(format: "guiding to %@ at (%.2f, %.2f, %.2f), azimuth %.0f deg, elevation %.0f deg",
                       g.objectId, p.x, p.y, p.z, Geometry.azimuthDeg(p), Geometry.elevationDeg(p)))
        tick()   // first ping and any initial "behind" feedback go out immediately
    }

    private func stopGuidance(reason: String) {
        guard guide != nil else { return }
        Log.app("guidance stopped: \(reason)")
        guide = nil
        guideTarget = nil
        guidance = nil
        guidanceState = nil
        targetDistanceM = nil
        renderer?.setProximityGain(1)
        renderer?.setPingInterval(nil)
        renderer?.setTarget(nil)
    }

    /// The target as the listener sees it: the room-frame target minus where the user stands.
    private func relativeTarget(_ p: EarmarkPoint) -> EarmarkPoint {
        EarmarkPoint(p.x - listenerPosition.x, p.y - listenerPosition.y, p.z - listenerPosition.z)
    }

    private func applyListenerPose(_ p: ListenerPose) {
        guard p.quality != .lost, let pt = Geometry.point(p.position) else { return }
        listenerPosition = pt
        lastFixAt = clock()
        retarget()
    }

    private func retarget() {
        guard let t = guideTarget else { return }
        let rel = relativeTarget(t)
        guidance?.retarget(rel)
        renderer?.setTarget(rel)
    }

    private func reset() {
        stopGuidance(reason: "reset")
        speech.stopAll()
        apple?.cancel()
        lock.withLock { utteranceRoute = .none }
        setSttEngine(.cartesia, reason: "reset")
        captions.removeAll()
        addCaption(.system, "Reset to the demo starting state.", source: "app")
    }

    private func setSttEngine(_ e: SttMode.Engine, reason: String) {
        sttEngine = e
        sttReason = reason
        Log.app("stt engine -> \(e.rawValue) (\(reason))")
        updateRoute()
        if e == .apple { onAppleSpeechNeeded?() }
    }

    private func updateVocabulary() {
        guard let rec = apple as? AppleSpeechRecognizer else { return }
        rec.setVocabulary(objects.flatMap { [$0.name] + $0.aliases } + ["Earmark", "where's", "stop"])
    }

    // MARK: Head pose (any thread)

    private func listenerAngles() -> (Double, Double) {
        lock.withLock { _tracking ? (_pose.yawDeg, _pose.pitchDeg) : (0, 0) }
    }

    public func ingestHeadPose(_ s: HeadPoseSample) {
        let (r, tracking): (SpatialRenderer?, Bool) = lock.withLock {
            _pose = s
            return (_renderer, _tracking)
        }
        // Lowest-latency path: the listener turns on every motion sample, straight from the motion queue.
        if tracking { r?.setListener(yawDeg: s.yawDeg, pitchDeg: s.pitchDeg) }
    }

    private func headStateChanged() {
        let tracking = head.state.isTracking
        let was = lock.withLock { () -> Bool in let w = _tracking; _tracking = tracking; return w }
        if was != tracking {
            let (yaw, pitch) = listenerAngles()
            renderer?.setListener(yawDeg: yaw, pitchDeg: pitch)
            Log.app("guidance mode: \(guidanceMode.rawValue) (head tracking \(head.state.rawValue))")
        }
        tick()
        changed()
    }

    // MARK: Mic (any thread)

    private func updateRoute() {
        let r: MicRoute
        if !micEnabled { r = .none } else if sttEngine == .apple || !busConnected { r = .apple } else { r = .cartesia }
        let old = lock.withLock { () -> MicRoute in let o = _route; _route = r; return o }
        if old != r { Log.mic("mic route -> \(r.rawValue)") }
        if r == .apple && old != .apple && micEnabled { onAppleSpeechNeeded?() }
    }

    /// Effective STT engine for the status bar.
    public var effectiveSttEngine: String {
        switch micRoute {
        case .none: sttEngine.rawValue
        case .cartesia: "cartesia"
        case .apple: "apple"
        }
    }

    public func ingestGate(_ out: GateOutput) {
        switch out {
        case .began:
            send(.ptt(Ptt(state: .start)), log: false)
            let route = lock.withLock { () -> MicRoute in utteranceRoute = _route; return _route }
            if route == .apple { apple?.beginUtterance() }
            DispatchQueue.main.async { self.userSpeaking = true; self.changed() }
        case .audio(let samples):
            let (route, seq): (MicRoute, Int) = lock.withLock {
                let s = micSeq
                if utteranceRoute == .cartesia { micSeq += 1 }
                return (utteranceRoute, s)
            }
            switch route {
            case .cartesia:
                let chunk = PCM.int16LEData(samples).base64EncodedString()
                bus.send(.micAudio(MicAudio(seq: seq, sampleRate: PCM.micSampleRate, chunkB64: chunk)))
            case .apple: apple?.append(samples)
            case .none: break
            }
        case .ended:
            send(.ptt(Ptt(state: .stop)), log: false)
            let route = lock.withLock { () -> MicRoute in let r = utteranceRoute; utteranceRoute = .none; return r }
            if route == .apple { apple?.endUtterance() }
            DispatchQueue.main.async { self.userSpeaking = false; self.changed() }
        }
    }

    /// Apple Speech results (main thread). Finals go to the concierge as `transcript` (source apple).
    public func appleTranscript(_ text: String, final: Bool) {
        setHeard(text, final: final, source: "apple")
        if final && !text.isEmpty {
            send(.transcript(Transcript(text: text, isFinal: true, source: .apple)))
        }
        changed()
    }

    // MARK: Speech events

    private func playbackEvent(_ id: String, _ event: Playback.Event) {
        send(.playback(Playback(utteranceId: id, event: event)))
        changed()
    }

    private func speakingChanged(_ on: Bool) {
        isSpeaking = on
        renderer?.setDucked(on)
        changed()
    }

    // MARK: Tick (main thread, ~50 Hz)

    public func tick() {
        let now = clock()
        let (yaw, pitch) = listenerAngles()

        if let at = lastFixAt, now - at > Self.fixTimeout {
            lastFixAt = nil
            listenerPosition = EarmarkPoint(0, 0, 0)
            retarget()
        }

        if var g = guidance {
            let fresh = lastFixAt != nil
            let distance = fresh ? Geometry.horizontalDistance(g.target) : nil
            targetDistanceM = distance
            let (state, events) = g.update(headYawDeg: yaw, now: now, distanceM: distance)
            guidance = g
            guidanceState = state
            let r = renderer
            r?.setRepeatingCue(state.zone == .behind ? .behind : .ping)
            r?.setPingInterval(state.pingIntervalSec)
            r?.setProximityGain(Guidance.proximityGain(distanceM: distance, config: guidanceConfig))
            for e in events { feedback(e, objectId: guide?.objectId ?? "") }
            if let d = distance, d <= guidanceConfig.arriveM, let id = guide?.objectId { arrive(objectId: id) }
        }

        if busConnected && head.state.isTracking && now - lastHeadPoseSent >= Self.headPosePeriod {
            lastHeadPoseSent = now
            send(.headPose(HeadPose(yaw: (yaw * 10).rounded() / 10, pitch: (pitch * 10).rounded() / 10)), log: false)
        }

        if busConnected {
            let status = currentStatus()
            let key = statusKey(status)
            let changedKey = key != lastStatusKey
            if changedKey || now - lastStatusSent >= Self.statusHeartbeat {
                lastStatusKey = key
                lastStatusSent = now
                if changedKey { Log.app("status: \(status.detail)") }
                send(.status(status), log: changedKey)
            }
        }
    }

    /// Within half a meter of the target: stop pinging, play the arrival tone, and tell the concierge so it can say where to reach.
    private func arrive(objectId: String) {
        renderer?.playLockedTone()
        let msg = GuideFeedback(objectId: objectId, event: .arrived, turn: nil, errorDeg: (guidanceState?.errorDeg ?? 0).rounded1)
        lastFeedback = msg
        Log.app("guide_feedback arrived at \(objectId)")
        send(.guideFeedback(msg))
        stopGuidance(reason: "arrived")
    }

    private func feedback(_ e: GuidanceEvent, objectId: String) {
        let msg: GuideFeedback
        switch e {
        case .behind(let turn, let err):
            msg = GuideFeedback(objectId: objectId, event: .behind, turn: turn == .left ? .left : .right, errorDeg: err.rounded1)
        case .front(let err):
            msg = GuideFeedback(objectId: objectId, event: .front, turn: nil, errorDeg: err.rounded1)
        case .locked(let err):
            renderer?.playLockedTone()
            msg = GuideFeedback(objectId: objectId, event: .locked, turn: nil, errorDeg: err.rounded1)
        case .unlocked:
            return
        }
        lastFeedback = msg
        Log.app("guide_feedback \(msg.event.rawValue)\(msg.turn.map { " turn " + $0.rawValue } ?? "") error \(msg.errorDeg)")
        send(.guideFeedback(msg))
    }

    // MARK: Status

    public func currentStatus() -> Status {
        let mode = guidanceMode
        var info: [String: JSONScalar] = [
            "renderer": .string(renderer?.kind.rawValue ?? "none"),
            "head_tracking": .string(head.state.rawValue),
            "guidance_mode": .string(mode.rawValue),
            "input_device": .string(micEnabled ? devices.inputDevice : "off"),
            "output_device": .string(devices.outputDevice),
            "output_sample_rate": .number(devices.outputSampleRate),
            "stt_engine": .string(effectiveSttEngine),
            "mic": .string(micEnabled ? listenMode.rawValue : "off"),
            "hfp_suspected": .bool(devices.hfpSuspected),
        ]
        info["yaw"] = .number(latestPose.yawDeg.rounded1)
        var detail: String
        switch mode {
        case .spatialTracked: detail = "spatial + head tracking"
        case .spatialUntracked: detail = "spatial, no head tracking (\(head.state.rawValue))"
        case .stereoPan: detail = "stereo panning fallback"
        case .speechOnly: detail = "speech only: no renderer could start"
        }
        if devices.hfpSuspected { detail += "; WARNING output at \(Int(devices.outputSampleRate)) Hz (hands-free mode)" }
        return Status(component: .macApp, ok: mode.level <= 2 && !devices.hfpSuspected, detail: detail, info: info)
    }

    private func statusKey(_ s: Status) -> String {
        var info = s.info ?? [:]
        info["yaw"] = nil
        return "\(s.ok)|\(s.detail)|" + info.keys.sorted().map { "\($0)=\(info[$0]!)" }.joined(separator: ",")
    }

    // MARK: Helpers

    private func send(_ m: BusMessage, log: Bool = true) {
        guard bus.isConnected else { return }
        bus.send(m)
        if log && m.type != "mic_audio" { note("-> \(summary(m))") }
    }

    private func note(_ s: String) {
        recentMessages.append(s)
        if recentMessages.count > 14 { recentMessages.removeFirst(recentMessages.count - 14) }
    }

    private func summary(_ m: BusMessage) -> String {
        switch m {
        case .guideStart(let g): "guide_start \(g.objectId)"
        case .guideStop(let g): "guide_stop \(g.reason.rawValue)"
        case .guideFeedback(let f): "guide_feedback \(f.event.rawValue)\(f.turn.map { " " + $0.rawValue } ?? "")"
        case .speak(let s): "speak \(s.utteranceId) #\(s.seq)\(s.final ? " final" : "")"
        case .speakCached(let s): "speak_cached \(s.phraseId)"
        case .speakText(let s): "speak_text \(s.utteranceId)"
        case .playback(let p): "playback \(p.event.rawValue) \(p.utteranceId)"
        case .stateUpdate(let s): "state_update \(s.objectId) \(s.status.rawValue)"
        case .sttMode(let s): "stt_mode \(s.engine.rawValue)"
        case .status(let s): "status \(s.component.rawValue): \(s.detail)"
        case .transcript(let t): "transcript \(t.source.rawValue)\(t.isFinal ? " final" : "")"
        case .pickup(let p): "pickup \(p.objectId)"
        case .pickupResult(let p): "pickup_result \(p.correct ? "correct" : "wrong: " + p.actual)"
        default: m.type
        }
    }

    private func setHeard(_ text: String, final: Bool, source: String) {
        guard !text.isEmpty else { return }
        if let last = captions.last, last.speaker == .user, !last.isFinal {
            captions[captions.count - 1].text = text
            captions[captions.count - 1].isFinal = final
            captions[captions.count - 1].source = source
        } else {
            addCaption(.user, text, source: source, final: final)
        }
    }

    private func addCaption(_ who: CaptionLine.Speaker, _ text: String, source: String, final: Bool = true) {
        captionID += 1
        captions.append(CaptionLine(id: captionID, speaker: who, text: text, isFinal: final, source: source))
        if captions.count > 8 { captions.removeFirst(captions.count - 8) }
    }

    private func changed() { onChange?() }
}

extension Double {
    var rounded1: Double { (self * 10).rounded() / 10 }
}
