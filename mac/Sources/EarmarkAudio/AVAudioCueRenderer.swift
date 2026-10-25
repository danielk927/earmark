import AVFAudio
import Foundation

/// Option A (`AVAudioEnvironmentNode` with `.HRTFHQ` or `.auto`) and the exaggerated stereo-pan fallback.
///
/// Graph: cuePlayer + lockedPlayer (mono) -> cue bus (environment node, or a plain mixer for stereo pan)
/// -> main mixer -> output. The listener is rotated on every head-motion sample and moved (already glided by
/// EarmarkCore) on every listener_pose; sources stay fixed in the room. Speech never goes through this engine
/// (see SpeechPlayer), so cues and speech stay separate layers.
public final class AVAudioCueRenderer: SpatialRenderer {
    public let kind: RendererKind
    public let engine = AVAudioEngine()

    private let env: AVAudioEnvironmentNode?
    private let panMixer: AVAudioMixerNode?
    private let cuePlayer = AVAudioPlayerNode()
    private let lockedPlayer = AVAudioPlayerNode()
    private let cueFormat = PCM.monoFloat(CueSynth.sampleRate)
    private let offlineFormat: AVAudioFormat?
    private let lock = NSLock()
    private lazy var driver = RepeatingCueDriver { [weak self] cue in self?.fire(cue) }

    private var buffers: [Cue: AVAudioPCMBuffer] = [:]
    private var timbre: PingTimbre = .tone
    private var target: EarmarkPoint?
    private var yawDeg = 0.0
    private var pitchDeg = 0.0
    private var listenerPosition: EarmarkPoint = .zero
    private var attenuation = DistanceAttenuation()
    private var ducked = false
    private var masterGain: Float = 1
    private var running = false
    private var graphBuilt = false

    /// Ducked cue gain while speech plays (-12 dB).
    public static let duckGain: Float = 0.25

    /// - Parameter offlineRenderFormat: when set, the engine runs in offline manual-rendering mode
    ///   (used by the convention tests), and the repeating-cue timer is not started.
    public init(kind: RendererKind, offlineRenderFormat: AVAudioFormat? = nil) {
        precondition(kind == .avaudioHRTFHQ || kind == .avaudioAuto || kind == .stereoPan)
        self.kind = kind
        self.offlineFormat = offlineRenderFormat
        if kind == .stereoPan {
            env = nil
            panMixer = AVAudioMixerNode()
        } else {
            env = AVAudioEnvironmentNode()
            panMixer = nil
        }
        rebuildCueBuffers()
    }

    deinit { driver.stop(); engine.stop() }

    public var isRunning: Bool { lock.withLock { running } }
    public var presentationLatency: TimeInterval { offlineFormat == nil ? engine.outputNode.presentationLatency : 0 }
    public var outputSampleRate: Double {
        offlineFormat?.sampleRate ?? engine.outputNode.outputFormat(forBus: 0).sampleRate
    }

    // MARK: Lifecycle

    public func start() throws {
        try lock.withLock {
            guard !running else { return }
            if !graphBuilt { try buildGraph() }
            try startEngineLocked()
            running = true
        }
        if offlineFormat == nil { driver.start() }
        Log.audio("renderer \(kind.rawValue) started at \(Int(outputSampleRate)) Hz, latency \(String(format: "%.0f", presentationLatency * 1000)) ms")
    }

    public func stop() {
        driver.stop()
        lock.withLock {
            guard running else { return }
            cuePlayer.stop(); lockedPlayer.stop()
            engine.stop()
            running = false
        }
    }

    public func restart() throws {
        let restarted: Bool = try lock.withLock {
            guard graphBuilt, running else { return false }
            cuePlayer.stop(); lockedPlayer.stop()
            engine.stop()
            running = false
            reconnectOutputLocked()
            try startEngineLocked()
            running = true
            return true
        }
        guard restarted else { return }
        if offlineFormat == nil { driver.start() }
        Log.audio("renderer \(kind.rawValue) restarted at \(Int(outputSampleRate)) Hz")
    }

    private var cueBus: AVAudioNode { (env as AVAudioNode?) ?? panMixer! }

    private func buildGraph() throws {
        if let offlineFormat {
            try engine.enableManualRenderingMode(.offline, format: offlineFormat, maximumFrameCount: 4_096)
        }
        engine.attach(cueBus)
        engine.attach(cuePlayer)
        engine.attach(lockedPlayer)
        engine.connect(cuePlayer, to: cueBus, format: cueFormat)   // mono in = spatialized
        engine.connect(lockedPlayer, to: cueBus, format: cueFormat)
        reconnectOutputLocked()

        if let env {
            env.outputType = .headphones
            env.reverbParameters.enable = false
            env.distanceAttenuationParameters.distanceAttenuationModel = .inverse
            let algorithm: AVAudio3DMixingRenderingAlgorithm = kind == .avaudioAuto ? .auto : .HRTFHQ
            for p in [cuePlayer, lockedPlayer] {
                p.renderingAlgorithm = algorithm
                p.sourceMode = .pointSource
                p.reverbBlend = 0
            }
        }
        applyGainLocked()
        applyAttenuationLocked()
        applyPoseLocked()
        graphBuilt = true
    }

    /// (Re)connects the cue bus to the main mixer at the current hardware rate.
    private func reconnectOutputLocked() {
        let rate: Double
        if let offlineFormat { rate = offlineFormat.sampleRate } else {
            let hw = engine.outputNode.outputFormat(forBus: 0).sampleRate
            rate = hw > 0 ? hw : 48_000
        }
        let stereo = AVAudioFormat(standardFormatWithSampleRate: rate, channels: 2)!
        engine.disconnectNodeOutput(cueBus)
        engine.connect(cueBus, to: engine.mainMixerNode, format: stereo)
    }

    private func startEngineLocked() throws {
        engine.prepare()
        try engine.start()
        cuePlayer.play()
        lockedPlayer.play()
    }

    // MARK: Parameters

    public func setTarget(_ position: EarmarkPoint?) {
        lock.withLock {
            target = position
            applyPoseLocked()
        }
    }

    public func setListener(yawDeg: Double, pitchDeg: Double) {
        lock.withLock {
            self.yawDeg = yawDeg
            self.pitchDeg = pitchDeg
            applyPoseLocked()
        }
    }

    public func setListener(position: EarmarkPoint) {
        lock.withLock {
            listenerPosition = position
            applyPoseLocked()
        }
    }

    public func setDistanceAttenuation(_ attenuation: DistanceAttenuation) {
        lock.withLock {
            self.attenuation = attenuation
            applyAttenuationLocked()
        }
    }

    public func setPingInterval(_ interval: TimeInterval?) { driver.setInterval(interval) }
    public func setRepeatingCue(_ cue: Cue) { driver.setCue(cue) }

    public func setDucked(_ ducked: Bool) {
        lock.withLock { self.ducked = ducked; applyGainLocked() }
    }

    public func setMasterGain(_ gain: Float) {
        lock.withLock { masterGain = min(max(gain, 0), 1); applyGainLocked() }
    }

    public func setTimbre(_ timbre: PingTimbre) {
        lock.withLock {
            guard timbre != self.timbre else { return }
            self.timbre = timbre
        }
        rebuildCueBuffers()
    }

    private func rebuildCueBuffers() {
        let t = lock.withLock { timbre }
        var b: [Cue: AVAudioPCMBuffer] = [:]
        for cue in Cue.allCases { b[cue] = CueSynth.buffer(cue, timbre: t, format: cueFormat) }
        lock.withLock { buffers = b }
    }

    private func applyGainLocked() {
        let g = masterGain * (ducked ? Self.duckGain : 1)
        if let env { env.outputVolume = g } else { panMixer?.outputVolume = g }
    }

    /// Inverse model, reference 0.6 m, maximum 8 m, rolloff 1 by default (PRD 10.1). Stereo pan: no distance cue.
    private func applyAttenuationLocked() {
        guard let env else { return }
        let p = env.distanceAttenuationParameters
        p.referenceDistance = Float(max(attenuation.referenceDistance, 0.01))
        p.maximumDistance = Float(max(attenuation.maximumDistance, attenuation.referenceDistance))
        p.rolloffFactor = Float(max(attenuation.rolloffFactor, 0))
    }

    private func applyPoseLocked() {
        if let env {
            env.listenerPosition = Geometry.avPoint(listenerPosition)
            env.listenerAngularOrientation = AVAudio3DAngularOrientation(yaw: Float(yawDeg), pitch: Float(pitchDeg), roll: 0)
            if let target {
                let p = Geometry.avPoint(target)
                cuePlayer.position = p
                lockedPlayer.position = p
            }
        } else if let target {
            let pan = Self.exaggeratedPan(relativeAzimuthDeg: Geometry.azimuthDeg(target, from: listenerPosition) - yawDeg)
            cuePlayer.pan = pan
            lockedPlayer.pan = pan
        }
    }

    /// Stereo fallback: full pan at 45 deg, and anything beyond 90 deg pans fully to the shorter-turn side.
    public static func exaggeratedPan(relativeAzimuthDeg: Double) -> Float {
        let r = Angles.wrapDeg(relativeAzimuthDeg)
        if abs(r) >= 90 { return r >= 0 ? 1 : -1 }
        return Float(min(max(r / 45, -1), 1))
    }

    // MARK: Playback

    public func play(_ cue: Cue) { fire(cue, oneShot: true) }

    private func fire(_ cue: Cue) { fire(cue, oneShot: false) }

    private func fire(_ cue: Cue, oneShot: Bool) {
        lock.withLock {
            guard running, engine.isRunning, target != nil || oneShot, let buf = buffers[cue] else { return }
            let player = cue == .locked ? lockedPlayer : cuePlayer
            if !player.isPlaying { player.play() }
            player.scheduleBuffer(buf, at: nil, options: [], completionHandler: nil)
        }
    }

    // MARK: Offline rendering (tests)

    /// Renders `frames` frames in offline manual-rendering mode.
    public func renderOffline(frames: Int) throws -> AVAudioPCMBuffer {
        guard let offlineFormat else { throw RendererError.notOffline }
        let out = AVAudioPCMBuffer(pcmFormat: offlineFormat, frameCapacity: AVAudioFrameCount(frames))!
        let block = AVAudioPCMBuffer(pcmFormat: offlineFormat, frameCapacity: 4_096)!
        var done = 0
        while done < frames {
            let n = AVAudioFrameCount(min(4_096, frames - done))
            let status = try engine.renderOffline(n, to: block)
            guard status == .success else { throw RendererError.renderFailed(String(describing: status)) }
            for c in 0..<Int(offlineFormat.channelCount) {
                out.floatChannelData![c].advanced(by: done).update(from: block.floatChannelData![c], count: Int(block.frameLength))
            }
            done += Int(block.frameLength)
        }
        out.frameLength = AVAudioFrameCount(done)
        return out
    }

    /// Schedules an arbitrary mono buffer on the cue player (tests use broadband noise).
    public func scheduleForTest(_ buffer: AVAudioPCMBuffer, loops: Bool) {
        lock.withLock {
            cuePlayer.scheduleBuffer(buffer, at: nil, options: loops ? .loops : [], completionHandler: nil)
        }
    }
}

public enum RendererError: Error, CustomStringConvertible {
    case notOffline
    case renderFailed(String)
    case phase(String)

    public var description: String {
        switch self {
        case .notOffline: "renderer is not in offline mode"
        case .renderFailed(let s): "offline render failed: \(s)"
        case .phase(let s): "PHASE: \(s)"
        }
    }
}
