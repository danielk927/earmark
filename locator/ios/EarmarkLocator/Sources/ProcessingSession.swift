import AVFoundation
import Foundation
import EarmarkCore

struct ProcessingSnapshot: Sendable {
    let fixes: [Fix]
    let detections: [Arrival]
    let lock: CycleState
    let dropped: Int
    let frames: Int
    let fs: Double
    let progress: Double?
}
private struct LogEvent: Encodable {
    let event: String
    let sample_index: Double
    let t: Double
    let detail: String
}

final class ProcessingSession: @unchecked Sendable {
    // All mutable state belongs to queue. Tap calls only enqueue through the bounded semaphore.
    private let queue = DispatchQueue(label: "earmark.locator.dsp", qos: .userInitiated)
    private let slots = DispatchSemaphore(value: 3)
    private let baseConfig: LocatorConfig
    private let directory: URL
    private let savedTemplates: [CapturedTemplate]
    private var config: LocatorConfig
    private var pipeline: LocatorPipeline?
    private var speech: SpeechStream?
    private var wallOffset = Date().timeIntervalSince1970 - AVAudioTime.seconds(forHostTime: mach_absolute_time())
    private var refreshed = ProcessInfo.processInfo.systemUptime
    private var recording: FileHandle?
    private var log: JSONLinesWriter?
    private var fixesWriter: JSONLinesWriter?
    private var recordingSamples = 0
    private var recordingRate = 0
    private var recordingURLs: [URL] = []
    private var capture: (beacon: String, samples: [Double])?
    private var timer: DispatchSourceTimer?
    private var stopped = false
    private var lastSample = 0.0
    private var lastTime = 0.0
    var onSnapshot: (@Sendable (ProcessingSnapshot) -> Void)?
    var onSpeech: (@Sendable ([MicAudio], Bool) -> Void)?
    var onError: (@Sendable (String) -> Void)?
    var onTemplate: (@Sendable (CapturedTemplate) -> Void)?
    var onFiles: (@Sendable ([URL]) -> Void)?
    var onFinished: (@Sendable () -> Void)?

    init(config: LocatorConfig, directory: URL, templates: [CapturedTemplate]) {
        baseConfig = config; self.config = config; self.directory = directory; savedTemplates = templates
    }
    func enqueue(_ packet: AudioPacket) {
        guard slots.wait(timeout: .now()) == .success else { return }
        queue.async { [self] in
            defer { slots.signal() }
            guard !stopped else { return }
            do {
                let uptime = ProcessInfo.processInfo.systemUptime
                if uptime - refreshed >= 10 {
                    wallOffset = Date().timeIntervalSince1970 - AVAudioTime.seconds(forHostTime: mach_absolute_time()); refreshed = uptime
                }
                let anchor = SampleAnchor(sample: packet.sampleTime, unix: packet.hostSeconds + wallOffset - packet.inputLatency, fs: packet.sampleRate)
                try process(packet.samples, anchor: anchor, progress: nil)
            } catch { onError?(error.localizedDescription) }
        }
    }
    private func configure(rate: Double) throws {
        if pipeline == nil || config.fs != rate {
            config = baseConfig; config.fs = rate
            let applicable = savedTemplates.filter { $0.fs == rate && $0.chirp == config.chirp }
            pipeline = try LocatorPipeline(config: config, templates: Dictionary(uniqueKeysWithValues: applicable.map { ($0.beacon, $0.samples) }))
            speech = SpeechStream(inputRate: rate, outputRate: config.mic_audio_sample_rate)
        }
    }
    private func process(_ samples: [Double], anchor: SampleAnchor, progress: Double?) throws {
        try configure(rate: anchor.fs)
        guard let pipeline else { return }
        lastSample = Double(anchor.sample); lastTime = anchor.unix
        let beforeDrops = pipeline.droppedBuffers
        let fixes = pipeline.append(samples, anchor: anchor)
        if beforeDrops != pipeline.droppedBuffers {
            try log?.append(LogEvent(event: "discontinuity", sample_index: lastSample, t: lastTime, detail: "Tracking reset"))
            capture = nil
            if speech?.active == true { _ = speech?.stop(); onError?("Audio discontinuity during push-to-talk; stop and restart this turn") }
        }
        if recording != nil {
            try recording?.write(contentsOf: PCM.encode(samples)); recordingSamples += samples.count
            try log?.append(LogEvent(event: "buffer", sample_index: lastSample, t: lastTime, detail: "\(samples.count) frames at \(anchor.fs) Hz"))
            for detection in pipeline.latestDetections { try log?.append(detection) }
            for fix in fixes { try log?.append(fix) }
        }
        for fix in fixes { try fixesWriter?.append(fix) }
        if let chunks = speech?.append(samples), !chunks.isEmpty { onSpeech?(chunks, false) }
        try collectTemplate(samples)
        onSnapshot?(ProcessingSnapshot(fixes: fixes, detections: pipeline.latestDetections, lock: pipeline.state,
                                       dropped: pipeline.droppedBuffers, frames: samples.count, fs: anchor.fs, progress: progress))
    }
    func setPTT(_ active: Bool, broadcastStop: Bool = false) {
        queue.async { [self] in
            guard !stopped else { return }
            if active { speech?.start() }
            else { onSpeech?(speech?.stop() ?? [], broadcastStop) }
        }
    }
    func finishSpeech() -> [MicAudio] { queue.sync { speech?.stop() ?? [] } }
    func record(_ enabled: Bool) {
        queue.async { [self] in
            do { if enabled { try beginRecording() } else { try endRecording() } }
            catch { onError?("Recording: \(error.localizedDescription)") }
        }
    }
    private func beginRecording() throws {
        guard recording == nil, pipeline != nil else { throw LocatorError.invalid("Start microphone before recording") }
        let folder = directory.appendingPathComponent("recording-\(UUID().uuidString)")
        try FileManager.default.createDirectory(at: folder, withIntermediateDirectories: true)
        let wav = folder.appendingPathComponent("microphone.wav"), jsonl = folder.appendingPathComponent("log.jsonl")
        recordingRate = Int(config.fs); recordingSamples = 0
        try WaveFile.header(sampleRate: recordingRate, sampleCount: 0).write(to: wav)
        let handle = try FileHandle(forWritingTo: wav)
        try handle.seekToEnd()
        recording = handle; log = try JSONLinesWriter(url: jsonl); recordingURLs = [wav, jsonl]
    }
    private func endRecording() throws {
        guard let recording else { return }
        try recording.seek(toOffset: 0)
        try recording.write(contentsOf: WaveFile.header(sampleRate: recordingRate, sampleCount: recordingSamples))
        try recording.close(); self.recording = nil
        try log?.close(); log = nil
        onFiles?(recordingURLs)
    }
    func logPose(_ pose: ListenerPose, sent: Bool) {
        queue.async { [self] in
            do {
                try log?.append(LogEvent(event: sent ? "pose_sent" : "pose_dropped", sample_index: lastSample, t: pose.t, detail: pose.quality.rawValue))
            } catch { onError?("Log write: \(error.localizedDescription)") }
        }
    }
    func captureTemplate(_ beacon: String) {
        queue.async { [self] in capture = (beacon, []) }
    }
    private func collectTemplate(_ samples: [Double]) throws {
        guard var capture else { return }
        capture.samples += samples
        let needed = Int(max(3, 10 * config.chirp.cycle + config.chirp.duration) * config.fs)
        guard capture.samples.count >= needed else { self.capture = capture; return }
        self.capture = nil
        let result = try Calibration.template(samples: Array(capture.samples.prefix(needed)), beacon: capture.beacon, config: config)
        try pipeline?.setTemplate(beacon: result.beacon, samples: result.samples)
        onTemplate?(result)
    }
    func playFile(_ url: URL) {
        queue.async { [self] in
            do { try beginFile(url) } catch { onError?("File input: \(error.localizedDescription)"); onFinished?() }
        }
    }
    private func beginFile(_ url: URL) throws {
        let scoped = url.startAccessingSecurityScopedResource()
        defer { if scoped { url.stopAccessingSecurityScopedResource() } }
        let bytes = try Data(contentsOf: url)
        guard bytes.count <= 100_000_000 else { throw LocatorError.invalid("Use a WAV under 100 MB") }
        let wave = try WaveFile(data: bytes)
        try configure(rate: wave.sampleRate)
        let folder = directory.appendingPathComponent("file-\(UUID().uuidString)")
        try FileManager.default.createDirectory(at: folder, withIntermediateDirectories: true)
        let fixesURL = folder.appendingPathComponent("fixes.jsonl")
        fixesWriter = try JSONLinesWriter(url: fixesURL)
        var index = 0
        let epoch = Date().timeIntervalSince1970
        let timer = DispatchSource.makeTimerSource(queue: queue)
        self.timer = timer
        timer.schedule(deadline: .now(), repeating: Double(2400) / wave.sampleRate)
        timer.setEventHandler { [weak self] in
            guard let self, !self.stopped else { return }
            do {
                let end = min(wave.samples.count, index + 2400)
                let anchor = SampleAnchor(sample: Int64(index), unix: epoch + Double(index) / wave.sampleRate, fs: wave.sampleRate)
                try self.process(Array(wave.samples[index..<end]), anchor: anchor, progress: Double(end) / Double(max(1, wave.samples.count)))
                index = end
                if index == wave.samples.count {
                    self.timer?.cancel(); self.timer = nil
                    try self.fixesWriter?.close(); self.fixesWriter = nil
                    self.onFiles?([fixesURL]); self.onFinished?()
                }
            } catch { self.timer?.cancel(); self.timer = nil; self.onError?(error.localizedDescription); self.onFinished?() }
        }
        timer.resume()
    }
    func stop() {
        queue.async { [self] in
            stopped = true; timer?.cancel(); timer = nil
            if let chunks = speech?.stop(), !chunks.isEmpty { onSpeech?(chunks, false) }
            do { try endRecording(); try fixesWriter?.close(); fixesWriter = nil }
            catch { onError?("Closing recording: \(error.localizedDescription)") }
        }
    }
}
