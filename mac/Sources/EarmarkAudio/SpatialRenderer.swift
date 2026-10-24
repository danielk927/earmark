import Foundation

public enum RendererKind: String, CaseIterable, Sendable, Identifiable {
    /// Option A: AVAudioEnvironmentNode, `.HRTFHQ` rendering, manual head tracking.
    case avaudioHRTFHQ = "avaudio_hrtfhq"
    /// Option A: AVAudioEnvironmentNode, `.auto` rendering (the only algorithm that can use a personal HRTF).
    case avaudioAuto = "avaudio_auto"
    /// Option B: PHASE, listener driven manually by the same head tracker (no entitlements).
    case phaseManual = "phase_manual"
    /// Fallback level 3: exaggerated stereo panning.
    case stereoPan = "stereo_pan"
    /// Test double.
    case mock

    public var id: String { rawValue }

    public var displayName: String {
        switch self {
        case .avaudioHRTFHQ: "A - AVAudio HRTF-HQ"
        case .avaudioAuto: "A - AVAudio auto"
        case .phaseManual: "B - PHASE, manual tracking"
        case .stereoPan: "Stereo pan (fallback)"
        case .mock: "Mock renderer"
        }
    }

    /// True for the HRTF renderers (ladder levels 1-2).
    public var isSpatial: Bool { self != .stereoPan }

    /// Renderers a user can pick in the apps.
    public static let selectable: [RendererKind] = [.avaudioHRTFHQ, .avaudioAuto, .phaseManual, .stereoPan]
}

/// Renders the guidance cue at a target position in Earmark coordinates.
/// Implementations must accept `setListener` from any thread (head-motion samples arrive on a CoreMotion queue).
public protocol SpatialRenderer: AnyObject {
    var kind: RendererKind { get }
    var isRunning: Bool { get }
    /// Output latency of the device in seconds (`presentationLatency`), 0 if unknown.
    var presentationLatency: TimeInterval { get }
    /// Hardware output sample rate the renderer is running at, 0 if unknown.
    var outputSampleRate: Double { get }

    func start() throws
    func stop()
    /// Rebuilds the graph for the current output device (after a route or configuration change).
    func restart() throws

    /// Target in Earmark coordinates; nil silences the repeating cue.
    func setTarget(_ position: EarmarkPoint?)
    /// Listener (head) orientation in Earmark degrees: yaw + right, pitch + up.
    func setListener(yawDeg: Double, pitchDeg: Double)
    /// Interval of the repeating cue; nil stops repeating.
    func setPingInterval(_ interval: TimeInterval?)
    /// Which cue repeats: `.ping` normally, `.behind` while the target is behind the listener.
    func setRepeatingCue(_ cue: Cue)
    /// One-shot cue at the target position.
    func play(_ cue: Cue)
    /// Speech ducks the cue layer.
    func setDucked(_ ducked: Bool)
    func setTimbre(_ timbre: PingTimbre)
    /// Master gain for the cue layer, 0...1 (`--silent` sets 0 for unattended runs).
    func setMasterGain(_ gain: Float)
}

public extension SpatialRenderer {
    var name: String { kind.rawValue }
    func playLockedTone() { play(.locked) }
    func playBehindCue() { play(.behind) }
}

/// Decides when the repeating cue is due. Pure; driven by `RepeatingCueDriver`.
/// When the interval shrinks the next cue comes at lastFire + newInterval, so speeding up is immediate.
public struct CueClock: Sendable {
    public var interval: TimeInterval?
    public var cue: Cue = .ping
    public private(set) var lastFire: TimeInterval?

    public init() {}

    public mutating func setInterval(_ i: TimeInterval?) {
        if i == nil { lastFire = nil }
        interval = i
    }

    public mutating func due(now: TimeInterval) -> Cue? {
        guard let interval else { return nil }
        if let last = lastFire, now - last < interval { return nil }
        lastFire = now
        return cue
    }
}

/// A 5 ms timer on a private queue that fires the repeating cue when due.
public final class RepeatingCueDriver {
    private let queue = DispatchQueue(label: "earmark.cue-driver", qos: .userInteractive)
    private var timer: DispatchSourceTimer?
    private var clock = CueClock()
    private let lock = NSLock()
    private let fire: (Cue) -> Void

    public init(fire: @escaping (Cue) -> Void) { self.fire = fire }

    deinit { timer?.cancel() }

    public func start() {
        lock.lock(); defer { lock.unlock() }
        guard timer == nil else { return }
        let t = DispatchSource.makeTimerSource(queue: queue)
        t.schedule(deadline: .now(), repeating: .milliseconds(5), leeway: .milliseconds(1))
        t.setEventHandler { [weak self] in self?.tick() }
        timer = t
        t.resume()
    }

    public func stop() {
        lock.lock(); defer { lock.unlock() }
        timer?.cancel()
        timer = nil
        clock.setInterval(nil)
    }

    public func setInterval(_ interval: TimeInterval?) {
        lock.lock(); clock.setInterval(interval); lock.unlock()
    }

    public func setCue(_ cue: Cue) {
        lock.lock(); clock.cue = cue; lock.unlock()
    }

    private func tick() {
        lock.lock()
        let cue = clock.due(now: ProcessInfo.processInfo.systemUptime)
        lock.unlock()
        if let cue { fire(cue) }
    }
}

public enum RendererFactory {
    public static func make(_ kind: RendererKind) -> SpatialRenderer {
        switch kind {
        case .avaudioHRTFHQ, .avaudioAuto, .stereoPan: AVAudioCueRenderer(kind: kind)
        case .phaseManual: PHASECueRenderer()
        case .mock: MockRenderer()
        }
    }
}
