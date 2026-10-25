import AVFAudio
import Foundation
import Speech

/// Receives gated mic audio. Cartesia streaming goes over the bus; Apple Speech is local.
public protocol TranscriberInput: AnyObject {
    func beginUtterance()
    /// 16 kHz mono Int16, 100 ms chunks.
    func append(_ samples: [Int16])
    func endUtterance()
    func cancel()
}

/// `SFSpeechRecognizer` fallback (docs/sponsors/vendor-notes/apple-speech.md): on-device when supported,
/// partial results for captions, `contextualStrings` from registry names and aliases, and a fresh task per
/// utterance (the gate opens and closes utterances), rolled over before the one-minute limit.
public final class AppleSpeechRecognizer: TranscriberInput {
    /// (text, isFinal). Main queue.
    public var onTranscript: ((String, Bool) -> Void)?
    /// Human-readable engine status. Main queue.
    public var onStatus: ((String) -> Void)?

    private let recognizer = SFSpeechRecognizer(locale: Locale(identifier: "en-US"))
    private let queue = DispatchQueue(label: "earmark.apple-speech")
    private var request: SFSpeechAudioBufferRecognitionRequest?
    private var task: SFSpeechRecognitionTask?
    private var converter: PCMResampler?
    private var taskStart: Double = 0
    private var vocabulary: [String] = []
    private let authLock = NSLock()
    private var _authorized = false
    /// Written on main, read on the recognizer queue.
    public private(set) var authorized: Bool {
        get { authLock.withLock { _authorized } }
        set { authLock.withLock { _authorized = newValue } }
    }

    /// Roll over to a new task at 50 s (Apple: plan for a one-minute limit).
    public static let rolloverSeconds = 50.0

    public init() {}

    public static var authorizationStatus: SFSpeechRecognizerAuthorizationStatus { SFSpeechRecognizer.authorizationStatus() }

    /// Prompts only the first time; later calls return the recorded answer.
    public func requestAuthorization(_ done: @escaping (Bool) -> Void) {
        SFSpeechRecognizer.requestAuthorization { status in
            DispatchQueue.main.async {
                self.authorized = status == .authorized
                if !self.authorized { self.status("Speech recognition not authorized (System Settings > Privacy & Security > Speech Recognition)") }
                done(self.authorized)
            }
        }
    }

    /// Object names and aliases (max 100 phrases, short ones preferred).
    public func setVocabulary(_ phrases: [String]) {
        let cleaned = Array(Set(phrases.map { $0.trimmingCharacters(in: .whitespaces) }.filter { !$0.isEmpty })).sorted()
        queue.async { self.vocabulary = Array(cleaned.prefix(100)) }
    }

    public func beginUtterance() {
        queue.async { self.startTaskLocked() }
    }

    public func append(_ samples: [Int16]) {
        queue.async {
            guard let req = self.request else { return }
            if ProcessInfo.processInfo.systemUptime - self.taskStart > Self.rolloverSeconds {
                req.endAudio()
                self.startTaskLocked()
            }
            guard let req2 = self.request else { return }
            let src = PCM.int16Buffer(samples)
            let native = req2.nativeAudioFormat
            if native.sampleRate > 0 && native != src.format {
                if self.converter?.output != native { self.converter = PCMResampler(from: src.format, to: native) }
                if let out = self.converter?.convert(src) { req2.append(out) }
            } else {
                req2.append(src)
            }
        }
    }

    public func endUtterance() {
        queue.async {
            self.request?.endAudio()   // the task delivers the final result
            self.request = nil
        }
    }

    public func cancel() {
        queue.async {
            self.task?.cancel()
            self.task = nil
            self.request = nil
        }
    }

    private func startTaskLocked() {
        guard authorized, let recognizer, recognizer.isAvailable else {
            status(recognizer == nil ? "Apple Speech: en-US not supported" : (authorized ? "Apple Speech unavailable right now" : "Apple Speech not authorized"))
            return
        }
        task?.finish()
        let req = SFSpeechAudioBufferRecognitionRequest()
        req.shouldReportPartialResults = true
        req.requiresOnDeviceRecognition = recognizer.supportsOnDeviceRecognition
        req.contextualStrings = vocabulary
        req.taskHint = .search
        request = req
        converter = nil
        taskStart = ProcessInfo.processInfo.systemUptime
        let onDevice = req.requiresOnDeviceRecognition
        task = recognizer.recognitionTask(with: req) { [weak self] result, error in
            guard let self else { return }
            if let result {
                let text = result.bestTranscription.formattedString
                let final = result.isFinal
                DispatchQueue.main.async { self.onTranscript?(text, final) }
            }
            if let error {
                let ns = error as NSError
                // 1110 = no speech detected; not worth surfacing.
                if ns.code != 1110 && ns.code != 216 { self.status("Apple Speech error \(ns.code): \(ns.localizedDescription)") }
            }
        }
        status(onDevice ? "Apple Speech listening (on device)" : "Apple Speech listening (server)")
    }

    private func status(_ s: String) {
        Log.speech(s)
        DispatchQueue.main.async { self.onStatus?(s) }
    }
}
