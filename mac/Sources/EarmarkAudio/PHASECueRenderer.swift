import AVFAudio
import Foundation
import PHASE
import simd

/// Option B: PHASE with binaural output, its listener driven manually by our own head tracker.
/// No entitlements or provisioning profile needed (automatic head tracking and the personal HRTF profile
/// would need paid-team entitlements; docs/sponsors/vendor-notes/apple-spatial-audio.md section 4).
/// Each cue is a one-shot PHASESoundEvent at the target's PHASESource.
public final class PHASECueRenderer: SpatialRenderer {
    public let kind = RendererKind.phaseManual

    private var engine: PHASEEngine?
    private var listener: PHASEListener?
    private var source: PHASESource?
    private var mixerIDs: [String: String] = [:]
    private var active: [ObjectIdentifier: PHASESoundEvent] = [:]
    private let lock = NSLock()
    private lazy var driver = RepeatingCueDriver { [weak self] cue in self?.fire(cue, oneShot: false) }

    private var timbre: PingTimbre = .tone
    private var target: EarmarkPoint?
    private var yawDeg = 0.0
    private var pitchDeg = 0.0
    private var listenerPosition: EarmarkPoint = .zero
    private var attenuation = DistanceAttenuation()
    private var ducked = false
    private var masterGain: Float = 1
    private var proximityGain: Float = 1
    private var running = false

    private static let gainParameter = "earmark.cue.gain"

    public init() {}

    deinit { driver.stop(); engine?.stop() }

    public var isRunning: Bool { lock.withLock { running } }
    /// PHASE reports no latency; this is the default output device's latency from CoreAudio.
    public var presentationLatency: TimeInterval { AudioDevices.outputLatency(AudioDevices.defaultOutputID()) }
    public var outputSampleRate: Double { AudioDevices.defaultOutput()?.nominalSampleRate ?? 0 }

    /// PHASE rotations are right-handed about +Y (up), so a positive angle turns LEFT: negate Earmark yaw.
    /// VERIFIED LOCALLY: yaw +90 gives forward (1, 0, 0); pitch +30 gives forward y +0.5.
    /// The listener's position goes in the translation column (`PHASEObject.transform`: position in `columns.3`),
    /// mapped like every other point (Geometry.avPoint).
    public static func listenerTransform(yawDeg: Double, pitchDeg: Double, position: EarmarkPoint = .zero) -> simd_float4x4 {
        let yaw = simd_quatf(angle: Float(-yawDeg * .pi / 180), axis: SIMD3<Float>(0, 1, 0))
        let pitch = simd_quatf(angle: Float(pitchDeg * .pi / 180), axis: SIMD3<Float>(1, 0, 0))
        var m = simd_float4x4(yaw * pitch)
        let a = Geometry.avPoint(position)
        m.columns.3 = SIMD4<Float>(a.x, a.y, a.z, 1)
        return m
    }

    /// Geometric spreading (-6 dB per doubling of distance at rolloff 1). PHASE has no reference or maximum
    /// distance on this model, so only the rolloff carries over from Settings; rolloff 0 = no distance model.
    static func distanceModel(_ a: DistanceAttenuation) -> PHASEDistanceModelParameters? {
        guard a.rolloffFactor > 0 else { return nil }
        let d = PHASEGeometricSpreadingDistanceModelParameters()
        d.rolloffFactor = a.rolloffFactor
        return d
    }

    public static func sourceTransform(_ p: EarmarkPoint) -> simd_float4x4 {
        let a = Geometry.avPoint(p)
        var m = matrix_identity_float4x4
        m.columns.3 = SIMD4<Float>(a.x, a.y, a.z, 1)
        return m
    }

    private static func assetID(_ cue: Cue, _ timbre: PingTimbre) -> String {
        cue == .ping ? "earmark.ping.\(timbre.rawValue)" : "earmark.\(cue.rawValue)"
    }

    // MARK: Lifecycle

    public func start() throws {
        try lock.withLock {
            guard !running else { return }
            try buildLocked()
            try engine?.start()
            running = true
        }
        driver.start()
        Log.audio("renderer phase_manual started (binaural)")
    }

    public func stop() {
        driver.stop()
        lock.withLock {
            guard running else { return }
            for ev in active.values { ev.stopAndInvalidate() }
            active.removeAll()
            engine?.stop()
            running = false
        }
    }

    public func restart() throws {
        let restarted: Bool = try lock.withLock {
            guard running, let engine else { return false }
            engine.stop()
            try engine.start()
            return true
        }
        if restarted { Log.audio("renderer phase_manual restarted") }
    }

    private func buildLocked() throws {
        if engine != nil { return }
        let e = PHASEEngine(updateMode: .automatic)
        e.outputSpatializationMode = .alwaysUseBinaural

        let l = PHASEListener(engine: e)
        l.transform = Self.listenerTransform(yawDeg: yawDeg, pitchDeg: pitchDeg, position: listenerPosition)
        try e.rootObject.addChild(l)

        let s = PHASESource(engine: e)
        s.transform = Self.sourceTransform(target ?? EarmarkPoint(0, 1, 0))
        try e.rootObject.addChild(s)

        let format = PCM.monoFloat(CueSynth.sampleRate)
        var variants: [(Cue, PingTimbre)] = PingTimbre.allCases.map { (.ping, $0) }
        variants.append((.behind, .tone))
        variants.append((.locked, .tone))

        for (cue, t) in variants {
            let id = Self.assetID(cue, t)
            let samples = CueSynth.samples(cue, timbre: t)
            let data = samples.withUnsafeBufferPointer { Data(buffer: $0) }
            try e.assetRegistry.registerSoundAsset(data: data, identifier: id, format: format, normalizationMode: .none)

            guard let pipeline = PHASESpatialPipeline(flags: [.directPathTransmission]) else {
                throw RendererError.phase("could not create the spatial pipeline")
            }
            pipeline.entries[PHASESpatialCategory.directPathTransmission]?.sendLevel = 1
            let mixer = PHASESpatialMixerDefinition(spatialPipeline: pipeline)
            mixer.distanceModelParameters = Self.distanceModel(attenuation)
            mixer.gainMetaParameterDefinition = PHASENumberMetaParameterDefinition(
                value: 1, minimum: 0, maximum: 1, identifier: Self.gainParameter + "." + id)

            let sampler = PHASESamplerNodeDefinition(soundAssetIdentifier: id, mixerDefinition: mixer)
            sampler.playbackMode = .oneShot
            sampler.setCalibrationMode(calibrationMode: .relativeSpl, level: 0)
            try e.assetRegistry.registerSoundEventAsset(rootNode: sampler, identifier: id + ".event")
            mixerIDs[id] = mixer.identifier
        }
        engine = e; listener = l; source = s
    }

    // MARK: Parameters

    public func setTarget(_ position: EarmarkPoint?) {
        lock.withLock {
            target = position
            if let position { source?.transform = Self.sourceTransform(position) }
        }
    }

    public func setListener(yawDeg: Double, pitchDeg: Double) {
        lock.withLock {
            self.yawDeg = yawDeg
            self.pitchDeg = pitchDeg
            listener?.transform = Self.listenerTransform(yawDeg: yawDeg, pitchDeg: pitchDeg, position: listenerPosition)
        }
    }

    public func setListener(position: EarmarkPoint) {
        lock.withLock {
            listenerPosition = position
            listener?.transform = Self.listenerTransform(yawDeg: yawDeg, pitchDeg: pitchDeg, position: position)
        }
    }

    /// The distance model lives on the registered mixer definitions, so a change applies the next time the
    /// renderer is built (EarmarkCore sets it before start(); after a change, switch renderers away and back).
    /// ponytail: no live re-registration of the sound assets.
    public func setDistanceAttenuation(_ attenuation: DistanceAttenuation) {
        lock.withLock { self.attenuation = attenuation }
    }

    public func setPingInterval(_ interval: TimeInterval?) { driver.setInterval(interval) }
    public func setRepeatingCue(_ cue: Cue) { driver.setCue(cue) }
    public func setDucked(_ ducked: Bool) { lock.withLock { self.ducked = ducked } }
    public func setTimbre(_ timbre: PingTimbre) { lock.withLock { self.timbre = timbre } }
    public func setMasterGain(_ gain: Float) { lock.withLock { masterGain = min(max(gain, 0), 1) } }
    public func setProximityGain(_ gain: Float) { lock.withLock { proximityGain = min(max(gain, 0), 1) } }

    // MARK: Playback

    public func play(_ cue: Cue) { fire(cue, oneShot: true) }

    private func fire(_ cue: Cue, oneShot: Bool) {
        lock.withLock {
            guard running, let engine, let listener, let source, target != nil || oneShot else { return }
            let id = Self.assetID(cue, cue == .ping ? timbre : .tone)
            guard let mixerID = mixerIDs[id] else { return }
            let params = PHASEMixerParameters()
            params.addSpatialMixerParameters(identifier: mixerID, source: source, listener: listener)
            do {
                let ev = try PHASESoundEvent(engine: engine, assetIdentifier: id + ".event", mixerParameters: params)
                let gain = Double(masterGain * proximityGain * (ducked ? AVAudioCueRenderer.duckGain : 1))
                ev.metaParameters[Self.gainParameter + "." + id]?.value = NSNumber(value: gain)
                let key = ObjectIdentifier(ev)
                active[key] = ev
                ev.start { [weak self] _ in
                    guard let self else { return }
                    self.lock.withLock { _ = self.active.removeValue(forKey: key) }
                }
            } catch {
                Log.audio("PHASE cue failed: \(error.localizedDescription)")
            }
        }
    }
}
