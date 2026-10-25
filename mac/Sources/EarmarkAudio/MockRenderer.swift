import Foundation

/// Records every call; used by tests and by `--renderer mock`.
public final class MockRenderer: SpatialRenderer {
    public let kind = RendererKind.mock
    private let lock = NSLock()

    public var failOnStart = false
    public private(set) var running = false
    public private(set) var target: EarmarkPoint?
    public private(set) var yawDeg = 0.0
    public private(set) var pitchDeg = 0.0
    /// Latest listener position, and every position in order (tests check the glide never jumps).
    public private(set) var listenerPosition: EarmarkPoint = .zero
    public private(set) var listenerPositions: [EarmarkPoint] = []
    public private(set) var attenuation = DistanceAttenuation()
    public private(set) var pingInterval: TimeInterval?
    public private(set) var repeatingCue: Cue = .ping
    public private(set) var played: [Cue] = []
    public private(set) var ducked = false
    public private(set) var timbre: PingTimbre = .tone
    public private(set) var masterGain: Float = 1
    public private(set) var restarts = 0

    public init() {}

    public var isRunning: Bool { lock.withLock { running } }
    public var presentationLatency: TimeInterval { 0 }
    public var outputSampleRate: Double { 48_000 }

    public func start() throws {
        if failOnStart { throw RendererError.renderFailed("mock start failure") }
        lock.withLock { running = true }
    }

    public func stop() { lock.withLock { running = false; pingInterval = nil } }
    public func restart() throws { lock.withLock { restarts += 1 } }
    public func setTarget(_ position: EarmarkPoint?) { lock.withLock { target = position } }
    public func setListener(yawDeg: Double, pitchDeg: Double) { lock.withLock { self.yawDeg = yawDeg; self.pitchDeg = pitchDeg } }
    public func setListener(position: EarmarkPoint) {
        lock.withLock { listenerPosition = position; listenerPositions.append(position) }
    }
    public func setDistanceAttenuation(_ attenuation: DistanceAttenuation) { lock.withLock { self.attenuation = attenuation } }
    public func setPingInterval(_ interval: TimeInterval?) { lock.withLock { pingInterval = interval } }
    public func setRepeatingCue(_ cue: Cue) { lock.withLock { repeatingCue = cue } }
    public func play(_ cue: Cue) { lock.withLock { played.append(cue) } }
    public func setDucked(_ ducked: Bool) { lock.withLock { self.ducked = ducked } }
    public func setTimbre(_ timbre: PingTimbre) { lock.withLock { self.timbre = timbre } }
    public func setMasterGain(_ gain: Float) { lock.withLock { masterGain = gain } }
}
