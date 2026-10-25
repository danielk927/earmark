import CoreMotion
import EarmarkContracts
import Foundation

/// Moving vs still for the hub's freeze logic (UWB-PRD 7.5): `CMMotionManager` device motion at 50 Hz,
/// |userAcceleration| (already in g, gravity removed) fed into `MotionClassifier` (0.5 s RMS, 0.03/0.06 g).
///
/// The same samples feed `KnockDetector` for tap-to-mark (a firm rap on a table after the phone was still).
///
/// Samples are processed on a private serial queue (Apple: don't use the main queue for high-rate motion);
/// only state changes and knocks hop to the main actor. The 1 s heartbeat is sent by the wearer controller.
final class MotionDetector {
    static let sampleHz = 50.0

    /// State changes (and the first decision ~0.5 s after start), on the main actor.
    var onChange: (@MainActor @Sendable (MotionState.State) -> Void)?
    /// A knock was detected, on the main actor.
    var onKnock: (@MainActor @Sendable () -> Void)?

    private let manager = CMMotionManager()
    private let queue: OperationQueue = {
        let q = OperationQueue()
        q.name = "earmark.motion"
        q.maxConcurrentOperationCount = 1
        return q
    }()
    // Touched only on `queue` while updates run.
    private var classifier = MotionClassifier(windowSize: Int(MotionDetector.sampleHz * 0.5))
    private var knockDetector = KnockDetector(sampleHz: MotionDetector.sampleHz)

    var isAvailable: Bool { manager.isDeviceMotionAvailable }

    func start() {
        guard manager.isDeviceMotionAvailable else {
            Log.motion.error("device motion not available")
            return
        }
        guard !manager.isDeviceMotionActive else { return }
        queue.addOperation { [weak self] in
            self?.classifier.reset()
            self?.knockDetector.reset()
        }
        manager.deviceMotionUpdateInterval = 1 / Self.sampleHz
        manager.startDeviceMotionUpdates(to: queue) { [weak self] motion, _ in
            guard let self, let a = motion?.userAcceleration else { return }
            let g = (a.x * a.x + a.y * a.y + a.z * a.z).squareRoot()
            if self.knockDetector.push(g), let cb = self.onKnock { onMain { cb() } }
            guard let state = self.classifier.push(g) else { return }
            if let cb = self.onChange { onMain { cb(state) } }
        }
    }

    func stop() {
        manager.stopDeviceMotionUpdates()
    }
}
