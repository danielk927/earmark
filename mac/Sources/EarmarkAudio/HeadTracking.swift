import CoreMotion
import Foundation

public enum HeadTrackingState: String, Sendable {
    case off
    /// Started; waiting for the first motion sample (AirPods not connected or not in the ears yet).
    case waiting
    case connected
    case disconnected
    case notAvailable = "not_available"
    case notAuthorized = "not_authorized"
    case mock

    /// True when yaw/pitch are live and should drive the listener.
    public var isTracking: Bool { self == .connected || self == .mock }

    public var displayName: String {
        switch self {
        case .off: "Off"
        case .waiting: "Waiting for AirPods"
        case .connected: "Tracking"
        case .disconnected: "Disconnected"
        case .notAvailable: "Not available"
        case .notAuthorized: "Not authorized"
        case .mock: "Mock head"
        }
    }
}

public struct HeadPoseSample: Equatable, Sendable {
    /// Earmark degrees relative to the calibration: yaw + right, pitch + up.
    public var yawDeg: Double
    public var pitchDeg: Double
    /// Raw roll, for the nod-axis check on new AirPods models.
    public var rollDeg: Double
    /// Seconds (`ProcessInfo.systemUptime`).
    public var t: Double

    public init(yawDeg: Double = 0, pitchDeg: Double = 0, rollDeg: Double = 0, t: Double = 0) {
        self.yawDeg = yawDeg; self.pitchDeg = pitchDeg; self.rollDeg = rollDeg; self.t = t
    }
}

public protocol HeadTracking: AnyObject {
    var state: HeadTrackingState { get }
    /// Clear, human-readable status for the UI.
    var message: String { get }
    var latestPose: HeadPoseSample { get }
    /// Measured motion-sample rate over the last second.
    var updateRateHz: Double { get }
    /// Called for every sample, on an arbitrary thread (keep it fast).
    var onPose: ((HeadPoseSample) -> Void)? { get set }
    /// Called on the main thread when `state` or `message` changes.
    var onStateChange: ((HeadTrackingState, String) -> Void)? { get set }

    func start()
    func stop()
    /// The current head pose becomes yaw 0, pitch 0.
    func recenter()
}

/// Thread-safe state shared by the head trackers.
public class HeadTrackerBase {
    let stateLock = NSLock()
    private var _state: HeadTrackingState = .off
    private var _message = "Head tracking is off"
    private var _pose = HeadPoseSample()
    private var rate = RateMeter(window: 1)

    public init() {}

    public var onPose: ((HeadPoseSample) -> Void)?
    public var onStateChange: ((HeadTrackingState, String) -> Void)?

    public var state: HeadTrackingState { stateLock.withLock { _state } }
    public var message: String { stateLock.withLock { _message } }
    public var latestPose: HeadPoseSample { stateLock.withLock { _pose } }
    public var updateRateHz: Double {
        stateLock.withLock { rate.rate(now: ProcessInfo.processInfo.systemUptime) }
    }

    func setState(_ s: HeadTrackingState, _ message: String) {
        let changed: Bool = stateLock.withLock {
            guard s != _state || message != _message else { return false }
            _state = s; _message = message
            return true
        }
        guard changed else { return }
        Log.head("\(s.rawValue): \(message)")
        let cb = onStateChange
        if Thread.isMainThread { cb?(s, message) } else { DispatchQueue.main.async { cb?(s, message) } }
    }

    func publish(_ pose: HeadPoseSample) {
        stateLock.withLock {
            _pose = pose
            rate.record(pose.t)
        }
        onPose?(pose)
    }
}

/// AirPods head tracking through `CMHeadphoneMotionManager` (macOS 14+).
///
/// - "Connected" is driven by motion samples actually arriving, because `isDeviceMotionAvailable` means
///   "this Mac supports it", not "AirPods are connected" (VERIFIED LOCALLY).
/// - Recenter keeps a reference attitude and reports `attitude.multiply(byInverseOf: reference)`.
/// - Yaw/pitch are smoothed with a wrap-aware exponential filter, time constant 30 ms (brief: no noticeable lag).
public final class HeadphoneMotionTracker: HeadTrackerBase, HeadTracking {
    private var manager = CMHeadphoneMotionManager()
    private let queue: OperationQueue = {
        let q = OperationQueue()
        q.name = "earmark.head-motion"
        q.maxConcurrentOperationCount = 1
        q.qualityOfService = .userInteractive
        return q
    }()
    private let delegateProxy = MotionDelegateProxy()
    private var watchdog: Timer?
    private var lastRestartAt = ProcessInfo.processInfo.systemUptime
    /// Seconds between restarts of motion updates while disconnected or waiting.
    static let retryPeriod = 2.5

    // Touched only on `queue`.
    private var reference: CMAttitude?
    private var latestRaw: CMAttitude?
    private var yawSmoother = AngleSmoother(timeConstant: 0.03)
    private var pitchSmoother = AngleSmoother(timeConstant: 0.03)
    private var started = false

    public override init() {
        super.init()
        delegateProxy.onConnect = { [weak self] in
            guard let self, self.state != .connected else { return }
            self.setState(.waiting, "AirPods connected - waiting for motion data")
        }
        delegateProxy.onDisconnect = { [weak self] in
            self?.setState(.disconnected, "AirPods disconnected. Reconnect them to resume head tracking.")
        }
    }

    public func start() {
        assert(Thread.isMainThread)
        guard !started else { return }
        switch CMHeadphoneMotionManager.authorizationStatus() {
        case .denied, .restricted:
            setState(.notAuthorized, "Motion access is denied. Allow Earmark in System Settings > Privacy & Security > Motion & Fitness, then relaunch.")
            return
        default: break
        }
        guard manager.isDeviceMotionAvailable else {
            setState(.notAvailable, "Headphone motion is not available on this Mac.")
            return
        }
        started = true
        // CoreMotion picks a new arbitrary reference frame whenever updates start, so the old reference is invalid.
        queue.addOperation { [weak self] in
            self?.reference = nil
            self?.yawSmoother.reset()
            self?.pitchSmoother.reset()
        }
        setState(.waiting, "Waiting for AirPods head motion. Connect AirPods (Pro, Max, or 3rd gen or later) and wear them.")
        beginUpdates()
        watchdog = Timer.scheduledTimer(withTimeInterval: 0.5, repeats: true) { [weak self] _ in self?.checkStaleness() }
    }

    private func beginUpdates() {
        manager.delegate = delegateProxy
        manager.startConnectionStatusUpdates()
        manager.startDeviceMotionUpdates(to: queue) { [weak self] motion, error in
            guard let self else { return }
            if let error { self.handle(error); return }
            if let motion { self.handle(motion) }
        }
        lastRestartAt = ProcessInfo.processInfo.systemUptime
    }

    /// Tears CoreMotion down and starts it again with a fresh manager. A new manager gets a new reference frame.
    private func restartUpdates() {
        Log.head("restarting motion updates")
        manager.stopDeviceMotionUpdates()
        manager.stopConnectionStatusUpdates()
        manager.delegate = nil
        manager = CMHeadphoneMotionManager()
        queue.addOperation { [weak self] in
            self?.reference = nil
            self?.yawSmoother.reset()
            self?.pitchSmoother.reset()
        }
        beginUpdates()
    }

    /// True when it is time to restart motion updates: only while disconnected or waiting, at most every `retryPeriod`.
    static func shouldRetry(state: HeadTrackingState, now: Double, lastRestartAt: Double) -> Bool {
        (state == .disconnected || state == .waiting) && now - lastRestartAt >= retryPeriod
    }

    public func stop() {
        assert(Thread.isMainThread)
        guard started else { return }
        started = false
        watchdog?.invalidate(); watchdog = nil
        manager.stopDeviceMotionUpdates()
        manager.stopConnectionStatusUpdates()
        setState(.off, "Head tracking is off")
    }

    public func recenter() {
        queue.addOperation { [weak self] in
            guard let self else { return }
            self.reference = self.latestRaw?.copy() as? CMAttitude
            self.yawSmoother.reset()
            self.pitchSmoother.reset()
            Log.head("recentered")
        }
    }

    private func handle(_ error: Error) {
        let ns = error as NSError
        Log.head("motion error \(ns.domain) \(ns.code): \(ns.localizedDescription)")
        if ns.domain == CMErrorDomain && ns.code == Int(CMErrorMotionActivityNotAuthorized.rawValue) {
            setState(.notAuthorized, "Motion access is denied. Allow Earmark in System Settings > Privacy & Security > Motion & Fitness.")
        } else {
            setState(.disconnected, "Head motion error: \(ns.localizedDescription)")
        }
    }

    private func handle(_ motion: CMDeviceMotion) {
        let attitude = motion.attitude
        latestRaw = attitude.copy() as? CMAttitude
        if reference == nil { reference = attitude.copy() as? CMAttitude }
        guard let rel = attitude.copy() as? CMAttitude, let ref = reference else { return }
        rel.multiply(byInverseOf: ref)
        let t = ProcessInfo.processInfo.systemUptime
        let yaw = yawSmoother.update(HeadSigns.earmarkYawDeg(coreMotionYawRad: rel.yaw), t: t)
        let pitch = pitchSmoother.update(HeadSigns.earmarkPitchDeg(coreMotionPitchRad: rel.pitch), t: t)
        publish(HeadPoseSample(yawDeg: yaw, pitchDeg: pitch, rollDeg: rel.roll * 180 / .pi, t: t))
        if state != .connected {
            let bud = motion.sensorLocation == .headphoneLeft ? "left" : (motion.sensorLocation == .headphoneRight ? "right" : "default")
            setState(.connected, "AirPods head tracking active (\(bud) bud)")
        }
    }

    private func checkStaleness() {
        let now = ProcessInfo.processInfo.systemUptime
        let age = now - latestPose.t
        if state == .connected && age > 1.0 {
            setState(.disconnected, "No head motion for 1 s. Check that the AirPods are in your ears and connected.")
        }
        if Self.shouldRetry(state: state, now: now, lastRestartAt: lastRestartAt) { restartUpdates() }
    }
}

/// CoreMotion delegate callbacks, kept off the public API.
private final class MotionDelegateProxy: NSObject, CMHeadphoneMotionManagerDelegate {
    var onConnect: (() -> Void)?
    var onDisconnect: (() -> Void)?
    func headphoneMotionManagerDidConnect(_ manager: CMHeadphoneMotionManager) { onConnect?() }
    func headphoneMotionManagerDidDisconnect(_ manager: CMHeadphoneMotionManager) { onDisconnect?() }
}

/// Scriptable and interactive "virtual head" for demos and tests without AirPods.
/// - `setRawPose` moves the virtual head (keyboard, slider).
/// - `run(script:)` plays keyframes; `sweep` oscillates yaw +-60 deg for unattended demos.
/// - Recenter works exactly like the real tracker: the current raw pose becomes 0.
public final class MockHeadTracker: HeadTrackerBase, HeadTracking {
    public struct Keyframe: Sendable {
        public var t: Double, yawDeg: Double, pitchDeg: Double
        public init(t: Double, yawDeg: Double, pitchDeg: Double = 0) { self.t = t; self.yawDeg = yawDeg; self.pitchDeg = pitchDeg }
    }

    private var rawYaw = 0.0, rawPitch = 0.0
    private var refYaw = 0.0, refPitch = 0.0
    private var timer: Timer?
    private var script: [Keyframe] = []
    private var scriptStart = 0.0
    public private(set) var sweeping = false

    public override init() { super.init() }

    public var rawYawDeg: Double { stateLock.withLock { rawYaw } }

    public func start() {
        setState(.mock, "Mock head: no AirPods. Use the arrow keys or the slider to turn the virtual head.")
        emit()
        timer = Timer.scheduledTimer(withTimeInterval: 1.0 / 50, repeats: true) { [weak self] _ in self?.tick() }
    }

    public func stop() {
        timer?.invalidate(); timer = nil
        setState(.off, "Head tracking is off")
    }

    public func recenter() {
        stateLock.withLock { refYaw = rawYaw; refPitch = rawPitch }
        emit()
    }

    /// Absolute virtual head pose (before recentering), Earmark degrees.
    public func setRawPose(yawDeg: Double, pitchDeg: Double? = nil) {
        stateLock.withLock {
            rawYaw = Angles.wrapDeg(yawDeg)
            if let pitchDeg { rawPitch = min(max(pitchDeg, -80), 80) }
        }
        emit()
    }

    public func turn(byDeg d: Double) { setRawPose(yawDeg: rawYawDeg + d) }

    public func run(script: [Keyframe]) {
        stateLock.withLock { self.script = script.sorted { $0.t < $1.t }; scriptStart = ProcessInfo.processInfo.systemUptime }
    }

    public func setSweeping(_ on: Bool) {
        stateLock.withLock { sweeping = on; scriptStart = ProcessInfo.processInfo.systemUptime }
    }

    private func tick() {
        let now = ProcessInfo.processInfo.systemUptime
        let (sweep, frames, start) = stateLock.withLock { (sweeping, script, scriptStart) }
        if sweep {
            setRawPose(yawDeg: 60 * sin(2 * .pi * (now - start) / 8))
        } else if !frames.isEmpty {
            let t = now - start
            if let pose = Self.interpolate(frames, at: t) { setRawPose(yawDeg: pose.yawDeg, pitchDeg: pose.pitchDeg) }
            if let last = frames.last, t > last.t { stateLock.withLock { script = [] } }
        } else {
            emit()  // steady 50 Hz stream, like real AirPods
        }
    }

    public static func interpolate(_ frames: [Keyframe], at t: Double) -> Keyframe? {
        guard let first = frames.first else { return nil }
        if t <= first.t { return first }
        for (a, b) in zip(frames, frames.dropFirst()) where t <= b.t {
            let u = b.t > a.t ? (t - a.t) / (b.t - a.t) : 1
            return Keyframe(t: t, yawDeg: a.yawDeg + u * Angles.wrapDeg(b.yawDeg - a.yawDeg), pitchDeg: a.pitchDeg + u * (b.pitchDeg - a.pitchDeg))
        }
        return frames.last
    }

    private func emit() {
        let (y, p) = stateLock.withLock { (Angles.wrapDeg(rawYaw - refYaw), rawPitch - refPitch) }
        publish(HeadPoseSample(yawDeg: y, pitchDeg: p, rollDeg: 0, t: ProcessInfo.processInfo.systemUptime))
    }
}
