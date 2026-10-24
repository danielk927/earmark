import EarmarkAudio
import EarmarkContracts
import Foundation

/// Decodes a bus message from JSON text (contract structs have no public memberwise initializers).
func bus(_ json: String) -> BusMessage {
    try! BusCoding.decode(Data(json.utf8))
}

/// Loads a contract example, e.g. example("guide_start", "01").
func example(_ type: String, _ name: String) -> BusMessage {
    let url = URL(fileURLWithPath: #filePath)
        .deletingLastPathComponent().deletingLastPathComponent().deletingLastPathComponent()
        .deletingLastPathComponent()
        .appendingPathComponent("contracts/examples/bus/\(type)/\(name).json")
    return try! BusCoding.decode(Data(contentsOf: url))
}

final class RecordingBus: BusSink {
    var isConnected = true
    private(set) var sent: [BusMessage] = []
    private let lock = NSLock()
    func send(_ message: BusMessage) { lock.withLock { sent.append(message) } }
    func clear() { lock.withLock { sent.removeAll() } }
    func ofType(_ t: String) -> [BusMessage] { lock.withLock { sent.filter { $0.type == t } } }
    var feedback: [GuideFeedback] {
        ofType("guide_feedback").compactMap { if case .guideFeedback(let f) = $0 { f } else { nil } }
    }
}

final class MockSpeech: SpeechOutput {
    var onPlayback: ((String, Playback.Event) -> Void)?
    var onSpeakingChanged: ((Bool) -> Void)?
    var isSpeaking = false
    private(set) var calls: [String] = []
    func start() throws { calls.append("start") }
    func restart() throws { calls.append("restart") }
    func handle(_ speak: Speak) { calls.append("speak \(speak.utteranceId) \(speak.seq)") }
    func playCached(phraseId: String, utteranceId: String, text: String) { calls.append("cached \(phraseId)") }
    func speakText(utteranceId: String, text: String) { calls.append("text \(utteranceId)") }
    func stopAll() { calls.append("stopAll") }
    func setMasterGain(_ gain: Float) {}
    /// Simulates playback starting/finishing.
    func emit(_ id: String, _ e: Playback.Event) {
        onPlayback?(id, e)
        if e == .started { onSpeakingChanged?(true) } else { onSpeakingChanged?(false) }
    }
}

final class MockTranscriber: TranscriberInput {
    private(set) var log: [String] = []
    private(set) var appended = 0
    func beginUtterance() { log.append("begin") }
    func append(_ samples: [Int16]) { appended += 1 }
    func endUtterance() { log.append("end") }
    func cancel() { log.append("cancel") }
}

final class TestClock {
    var now = 1_000.0
    func advance(_ s: Double) { now += s }
}

/// Polls until `condition` is true or the timeout passes (for callbacks delivered on the main queue).
func waitUntil(timeout: Double = 3, _ condition: @escaping () -> Bool) async -> Bool {
    let deadline = Date().addingTimeInterval(timeout)
    while Date() < deadline {
        if condition() { return true }
        try? await Task.sleep(nanoseconds: 20_000_000)
    }
    return condition()
}
