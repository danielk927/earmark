import AVFAudio
import EarmarkContracts
import Foundation

/// The non-spatial speech layer (centered, never through the environment node).
public protocol SpeechOutput: AnyObject {
    /// Playback progress for the bus (`playback` messages). Main queue.
    var onPlayback: ((String, Playback.Event) -> Void)? { get set }
    /// True while speech is audible; the app ducks the cue layer. Main queue.
    var onSpeakingChanged: ((Bool) -> Void)? { get set }
    var isSpeaking: Bool { get }

    func start() throws
    func restart() throws
    /// Streamed TTS chunk; plays as chunks arrive. A new utterance id interrupts the current one.
    func handle(_ speak: Speak)
    /// `config/phrases/<phrase_id>.wav`, falling back to `text` with the system voice.
    func playCached(phraseId: String, utteranceId: String, text: String)
    /// System voice (AVSpeechSynthesizer rendered into our player, so ducking and events still work).
    func speakText(utteranceId: String, text: String)
    /// Interrupts whatever is playing.
    func stopAll()
    func setMasterGain(_ gain: Float)
}

/// Finds cached phrase WAVs: `EARMARK_PHRASES_DIR`, then the app bundle's `Resources/phrases`,
/// then `<repo>/config/phrases`.
public struct PhraseLibrary: Sendable {
    public let directories: [URL]

    public init(directories: [URL]) { self.directories = directories }

    public static func standard(repoRoot: URL?) -> PhraseLibrary {
        var dirs: [URL] = []
        if let env = ProcessInfo.processInfo.environment["EARMARK_PHRASES_DIR"], !env.isEmpty {
            dirs.append(URL(fileURLWithPath: env, isDirectory: true))
        }
        if let res = Bundle.main.resourceURL { dirs.append(res.appendingPathComponent("phrases", isDirectory: true)) }
        if let repoRoot { dirs.append(repoRoot.appendingPathComponent("config/phrases", isDirectory: true)) }
        return PhraseLibrary(directories: dirs)
    }

    public func url(for phraseId: String) -> URL? {
        guard phraseId.range(of: "^[a-z0-9_]+$", options: .regularExpression) != nil else { return nil }
        return directories.lazy.map { $0.appendingPathComponent("\(phraseId).wav") }
            .first { FileManager.default.fileExists(atPath: $0.path) }
    }
}

public enum AudioFileLoader {
    /// Loads any audio file Core Audio can read and converts it to mono Float32 at `sampleRate`.
    public static func loadMono(_ url: URL, sampleRate: Double) throws -> AVAudioPCMBuffer {
        let file = try AVAudioFile(forReading: url)
        let frames = AVAudioFrameCount(file.length)
        guard let raw = AVAudioPCMBuffer(pcmFormat: file.processingFormat, frameCapacity: max(frames, 1)) else {
            throw CocoaError(.fileReadCorruptFile)
        }
        try file.read(into: raw)
        let target = PCM.monoFloat(sampleRate)
        if raw.format == target { return raw }
        guard let rs = PCMResampler(from: raw.format, to: target) else { throw CocoaError(.fileReadCorruptFile) }
        var parts: [AVAudioPCMBuffer] = []
        if let b = rs.convert(raw) { parts.append(b) }
        if let t = rs.flush() { parts.append(t) }
        return PCM.floatBuffer(parts.flatMap { PCM.floatSamples($0) }, format: target)
    }
}

public final class SpeechPlayer: SpeechOutput {
    public var onPlayback: ((String, Playback.Event) -> Void)?
    public var onSpeakingChanged: ((Bool) -> Void)?

    public let engine = AVAudioEngine()
    private let player = AVAudioPlayerNode()
    public static let playRate: Double = 48_000
    private let playFormat = PCM.monoFloat(SpeechPlayer.playRate)
    private let offlineFormat: AVAudioFormat?
    private let phrases: PhraseLibrary
    private let queue = DispatchQueue(label: "earmark.speech", qos: .userInitiated)
    private let callbackQueue: DispatchQueue
    private let synth = AVSpeechSynthesizer()

    private final class Utterance {
        let id: String
        let generation: Int
        var decoder: SpeakChunkDecoder?
        var resampler: PCMResampler?
        var sourceRate: Double = 0
        var outstanding = 0
        var finalReceived = false
        var started = false
        var sayProcess: Process?
        init(id: String, generation: Int) { self.id = id; self.generation = generation }
    }

    // Touched only on `queue`.
    private var current: Utterance?
    private var generation = 0
    private var ended: [String] = []
    private var running = false
    private var speaking = false
    private var masterGain: Float = 1

    /// - Parameter callbackQueue: where `onPlayback` and `onSpeakingChanged` run (main in the app).
    public init(phrases: PhraseLibrary, offlineRenderFormat: AVAudioFormat? = nil, callbackQueue: DispatchQueue = .main) {
        self.phrases = phrases
        self.offlineFormat = offlineRenderFormat
        self.callbackQueue = callbackQueue
    }

    public var isSpeaking: Bool { queue.sync { speaking } }

    // MARK: Lifecycle

    public func start() throws {
        try queue.sync {
            guard !running else { return }
            if let offlineFormat {
                try engine.enableManualRenderingMode(.offline, format: offlineFormat, maximumFrameCount: 4_096)
            }
            engine.attach(player)
            engine.connect(player, to: engine.mainMixerNode, format: playFormat)
            engine.mainMixerNode.outputVolume = masterGain
            engine.prepare()
            try engine.start()
            player.play()
            running = true
        }
        Log.speech("speech player started")
    }

    public func restart() throws {
        try queue.sync {
            guard running else { return }
            interruptLocked()
            engine.stop()
            engine.disconnectNodeOutput(player)
            engine.connect(player, to: engine.mainMixerNode, format: playFormat)
            engine.prepare()
            try engine.start()
            player.play()
        }
        Log.speech("speech player restarted")
    }

    public func setMasterGain(_ gain: Float) {
        queue.async { self.masterGain = gain; self.engine.mainMixerNode.outputVolume = gain }
    }

    // MARK: Requests

    public func handle(_ speak: Speak) {
        queue.async { self.handleLocked(speak) }
    }

    public func playCached(phraseId: String, utteranceId: String, text: String) {
        queue.async {
            guard let url = self.phrases.url(for: phraseId) else {
                Log.speech("phrase \(phraseId).wav missing; speaking its text with the system voice")
                self.speakTextLocked(utteranceId: utteranceId, text: text)
                return
            }
            do {
                let buf = try AudioFileLoader.loadMono(url, sampleRate: Self.playRate)
                let u = self.beginLocked(utteranceId)
                self.scheduleLocked(buf, u)
                u.finalReceived = true
                self.finishIfDoneLocked(u)
            } catch {
                Log.speech("phrase \(phraseId).wav unreadable (\(error.localizedDescription)); using the system voice")
                self.speakTextLocked(utteranceId: utteranceId, text: text)
            }
        }
    }

    public func speakText(utteranceId: String, text: String) {
        queue.async { self.speakTextLocked(utteranceId: utteranceId, text: text) }
    }

    public func stopAll() {
        queue.async { self.interruptLocked() }
    }

    // MARK: Internals (on `queue`)

    private func handleLocked(_ speak: Speak) {
        var u = current
        if u?.id != speak.utteranceId {
            if ended.contains(speak.utteranceId) { return }     // late chunk of an interrupted utterance
            u = beginLocked(speak.utteranceId)
        }
        guard let u else { return }
        if u.decoder == nil || u.decoder?.format != speak.format { u.decoder = SpeakChunkDecoder(format: speak.format) }
        let rate = Double(speak.sampleRate)
        if rate != u.sourceRate {
            u.sourceRate = rate
            u.resampler = rate == Self.playRate ? nil : PCMResampler(from: PCM.monoFloat(rate), to: playFormat)
        }
        guard let samples = u.decoder?.decode(base64: speak.chunkB64) else {
            Log.speech("speak \(speak.utteranceId) seq \(speak.seq): invalid base64, chunk dropped")
            return
        }
        if !samples.isEmpty {
            let src = PCM.floatBuffer(samples, format: PCM.monoFloat(rate))
            if let rs = u.resampler {
                if let out = rs.convert(src), out.frameLength > 0 { scheduleLocked(out, u) }
            } else {
                scheduleLocked(src, u)
            }
        }
        if speak.final {
            if let rs = u.resampler, let tail = rs.flush() { scheduleLocked(tail, u) }
            u.finalReceived = true
            finishIfDoneLocked(u)
        }
    }

    @discardableResult
    private func beginLocked(_ id: String) -> Utterance {
        interruptLocked()
        generation += 1
        let u = Utterance(id: id, generation: generation)
        current = u
        return u
    }

    private func scheduleLocked(_ buffer: AVAudioPCMBuffer, _ u: Utterance) {
        guard running, buffer.frameLength > 0 else { return }
        if !engine.isRunning { try? engine.start() }
        if !player.isPlaying { player.play() }
        u.outstanding += 1
        let gen = u.generation
        // `.dataPlayedBack` means audible at the device; it never fires in offline rendering (tests), where
        // `.dataRendered` is the closest equivalent.
        let type: AVAudioPlayerNodeCompletionCallbackType = offlineFormat == nil ? .dataPlayedBack : .dataRendered
        player.scheduleBuffer(buffer, completionCallbackType: type) { [weak self] _ in
            self?.queue.async {
                guard let self, let cur = self.current, cur.generation == gen else { return }
                cur.outstanding -= 1
                self.finishIfDoneLocked(cur)
            }
        }
        if !u.started { markStartedLocked(u) }
    }

    private func markStartedLocked(_ u: Utterance) {
        u.started = true
        emit(u.id, .started)
        setSpeakingLocked(true)
    }

    private func finishIfDoneLocked(_ u: Utterance) {
        guard u.finalReceived, u.outstanding <= 0, current === u else { return }
        current = nil
        remember(u.id)
        if !u.started { markStartedLocked(u) }   // empty utterance: still report a start/finish pair
        emit(u.id, .finished)
        releaseSpeakingSoon()
    }

    private func interruptLocked() {
        guard let u = current else { return }
        current = nil
        remember(u.id)
        player.stop()                      // completion handlers fire; the generation check ignores them
        if u.sayProcess?.isRunning == true { u.sayProcess?.terminate() }
        if synth.isSpeaking { synth.stopSpeaking(at: .immediate) }
        emit(u.id, .interrupted)
        if running { player.play() }
        releaseSpeakingSoon()
    }

    private func remember(_ id: String) {
        ended.append(id)
        if ended.count > 32 { ended.removeFirst(ended.count - 32) }
    }

    private func setSpeakingLocked(_ on: Bool) {
        guard on != speaking else { return }
        speaking = on
        let cb = onSpeakingChanged
        callbackQueue.async { cb?(on) }
    }

    /// Releases the duck 200 ms after speech ends, unless another utterance started (no pumping between sentences).
    private func releaseSpeakingSoon() {
        queue.asyncAfter(deadline: .now() + 0.2) { [weak self] in
            guard let self, self.current == nil else { return }
            self.setSpeakingLocked(false)
        }
    }

    private func emit(_ id: String, _ event: Playback.Event) {
        Log.speech("playback \(event.rawValue) \(id)")
        let cb = onPlayback
        callbackQueue.async { cb?(id, event) }
    }

    // MARK: System voice

    private func speakTextLocked(utteranceId: String, text: String) {
        let u = beginLocked(utteranceId)
        let gen = u.generation
        let utterance = AVSpeechUtterance(string: text)
        utterance.voice = AVSpeechSynthesisVoice(language: "en-US")
        var gotBuffer = false
        var converter: PCMResampler?
        synth.write(utterance) { [weak self] buffer in
            guard let self, let pcm = buffer as? AVAudioPCMBuffer else { return }
            self.queue.async {
                guard let cur = self.current, cur.generation == gen else { return }
                gotBuffer = true
                if pcm.frameLength == 0 {
                    if let tail = converter?.flush() { self.scheduleLocked(tail, cur) }
                    cur.finalReceived = true
                    self.finishIfDoneLocked(cur)
                    return
                }
                if pcm.format == self.playFormat {
                    self.scheduleLocked(pcm, cur)
                } else {
                    if converter?.input != pcm.format { converter = PCMResampler(from: pcm.format, to: self.playFormat) }
                    if let out = converter?.convert(pcm) { self.scheduleLocked(out, cur) }
                }
            }
        }
        // Last resort (brief rule 5): macOS `say`, if the synthesizer produced nothing.
        queue.asyncAfter(deadline: .now() + 2.5) { [weak self] in
            guard let self, !gotBuffer, let cur = self.current, cur.generation == gen else { return }
            Log.speech("system voice produced no audio for \(utteranceId); falling back to /usr/bin/say")
            self.sayLocked(text, cur)
        }
    }

    private func sayLocked(_ text: String, _ u: Utterance) {
        let p = Process()
        p.executableURL = URL(fileURLWithPath: "/usr/bin/say")
        var args = [text]
        if masterGain == 0 { args = ["-o", NSTemporaryDirectory() + "earmark-say.aiff", text] }
        p.arguments = args
        let gen = u.generation
        p.terminationHandler = { [weak self] _ in
            self?.queue.async {
                guard let self, let cur = self.current, cur.generation == gen else { return }
                cur.finalReceived = true
                self.finishIfDoneLocked(cur)
            }
        }
        do {
            try p.run()
            u.sayProcess = p
            markStartedLocked(u)
        } catch {
            Log.speech("say failed: \(error.localizedDescription)")
            u.finalReceived = true
            finishIfDoneLocked(u)
        }
    }

    // MARK: Offline rendering (tests)

    public func renderOffline(frames: Int) throws {
        guard let offlineFormat else { throw RendererError.notOffline }
        let block = AVAudioPCMBuffer(pcmFormat: offlineFormat, frameCapacity: 4_096)!
        var done = 0
        while done < frames {
            let n = AVAudioFrameCount(min(4_096, frames - done))
            _ = try queue.sync { try engine.renderOffline(n, to: block) }
            done += Int(n)
        }
    }

    /// Waits until everything queued on the speech queue so far has run (tests).
    public func drain() { queue.sync {} }
}
