import Foundation

/// Glue between mic capture (capture queue) and the core: runs the voice gate on every 100 ms chunk.
public final class MicPipeline {
    private let lock = NSLock()
    private var gate: VoiceGate
    /// Gate output, on the capture queue.
    public var onOutput: ((GateOutput) -> Void)?

    public init(mode: ListenMode) { gate = VoiceGate(mode: mode) }

    public var mode: ListenMode {
        get { lock.withLock { gate.mode } }
        set { lock.withLock { gate.mode = newValue } }
    }

    public func setPushToTalk(held: Bool) { lock.withLock { gate.setPushToTalk(held: held) } }

    /// A squeeze utterance (see `VoiceGate.startHandsFree`); false in always-listening mode.
    @discardableResult
    public func startHandsFree() -> Bool { lock.withLock { gate.startHandsFree() } }
    public func stopHandsFree() { lock.withLock { gate.stopHandsFree() } }
    /// False once the squeeze utterance ended, by a second squeeze or on its own.
    public var handsFreeActive: Bool { lock.withLock { gate.handsFree } }

    public var levelDb: Double { lock.withLock { gate.lastLevelDb } }
    public var thresholdDb: Double { lock.withLock { gate.speechThresholdDb } }
    public var isOpen: Bool { lock.withLock { gate.isOpen } }

    public func process(_ chunk: [Int16]) {
        let out = lock.withLock { gate.process(chunk) }
        for o in out { onOutput?(o) }
    }
}
