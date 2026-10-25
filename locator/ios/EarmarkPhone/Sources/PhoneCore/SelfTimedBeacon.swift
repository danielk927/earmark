import AVFoundation
import Foundation

public enum SelfTimedBeaconEvent: Sendable {
    /// The output stream is running and the first chirp is placed at this wall-clock time.
    case started(firstChirpAt: Date)
    case played(count: Int)
    case error(String)
}

public enum SelfTimedBeaconError: Error, LocalizedError {
    case badBeaconNumber
    case noOutputFormat
    public var errorDescription: String? {
        switch self {
        case .badBeaconNumber: return "The beacon number must be 1 to 4."
        case .noOutputFormat: return "Could not make a 48 kHz mono output format."
        }
    }
}

/// A beacon that chirps on its own clock, with no network and no microphone.
///
/// Timing is the whole point. The chirps are written straight into the output stream by an `AVAudioSourceNode`
/// render block that keeps a running count of output samples: chirp k starts at output sample
/// `firstStart + k * round(cycle * sampleRate)`, so the spacing between chirps is exact in the device's audio
/// clock. Nothing is timed by a Timer or a dispatch queue. The only wall-clock step is choosing `firstStart`
/// once, from the host time of the first rendered buffer, so that this beacon's chirps land in its own slot of
/// the 0.5 s cycle (beacon N at phase (N-1) * 0.125 s).
public final class SelfTimedBeacon: @unchecked Sendable {
    public let beaconNumber: Int
    public let spec: ChirpSpec
    public let cycleSeconds: Double
    public let slotSeconds: Double
    public let sampleRate: Double
    /// Called from a background queue; never from the audio thread.
    public var onEvent: (@Sendable (SelfTimedBeaconEvent) -> Void)?

    private let engine = AVAudioEngine()
    private var source: AVAudioSourceNode?
    private var renderer: BeaconRenderer?
    private var poll: DispatchSourceTimer?
    private let queue = DispatchQueue(label: "earmark.beacon.selftimed")
    private var observers: [NSObjectProtocol] = []

    public init(beaconNumber: Int, band: (Double, Double), amplitude: Double,
                cycleSeconds: Double = 0.5, slotSeconds: Double = 0.125, sampleRate: Double = 48000) {
        self.beaconNumber = beaconNumber
        self.spec = ChirpSpec(fLo: band.0, fHi: band.1, lengthMs: 40, amplitude: min(max(amplitude, 0), 1),
                              direction: SelfTimedBeacon.direction(forBeacon: beaconNumber))
        self.cycleSeconds = cycleSeconds
        self.slotSeconds = slotSeconds
        self.sampleRate = sampleRate
    }

    /// Odd beacons (1, 3) sweep up; even beacons (2, 4) sweep down.
    public static func direction(forBeacon n: Int) -> String { n % 2 == 1 ? "up" : "down" }

    /// The time within each cycle at which this beacon's chirp starts.
    public var phaseSeconds: Double { ChirpScheduler.phase(beaconNumber: beaconNumber, slotSeconds: slotSeconds) }

    deinit { stop() }

    // MARK: Start and stop

    public func start() throws {
        stop()
        guard (1...4).contains(beaconNumber) else { throw SelfTimedBeaconError.badBeaconNumber }
        var outputLatency = 0.0
        #if os(iOS)
        let session = AVAudioSession.sharedInstance()
        try session.setCategory(.playback, mode: .default)   // no microphone; the bottom speaker is the default route
        try session.setPreferredSampleRate(sampleRate)
        try session.setPreferredIOBufferDuration(0.005)
        try session.setActive(true)
        outputLatency = session.outputLatency
        #endif
        guard let format = AVAudioFormat(commonFormat: .pcmFormatFloat32, sampleRate: sampleRate, channels: 1, interleaved: false) else {
            throw SelfTimedBeaconError.noOutputFormat
        }
        let r = BeaconRenderer(beacon: self, outputLatency: outputLatency, fixedFirstStart: nil)
        let node = AVAudioSourceNode(format: format, renderBlock: r.renderBlock)
        renderer = r
        source = node
        engine.attach(node)
        engine.connect(node, to: engine.mainMixerNode, format: format)
        engine.connect(engine.mainMixerNode, to: engine.outputNode, format: nil)
        engine.mainMixerNode.outputVolume = 1
        engine.prepare()
        try engine.start()
        watchEngine()
        startPolling(r)
    }

    public func stop() {
        poll?.cancel()
        poll = nil
        for o in observers { NotificationCenter.default.removeObserver(o) }
        observers = []
        if engine.isRunning { engine.stop() }
        if let s = source { engine.detach(s) }
        source = nil
        renderer = nil
    }

    /// Chirps started so far (reads the render thread's counter).
    public var chirpsPlayed: Int { renderer?.played ?? 0 }

    // MARK: Offline rendering (tests, and anyone who wants to look at the stream)

    /// The same source node the live beacon plays, but with the first chirp pinned to a known sample so it can be
    /// rendered with no device and no clock. Attach it to an engine in manual rendering mode.
    public func makeOfflineSourceNode(firstStart: Int) -> AVAudioSourceNode {
        let format = AVAudioFormat(commonFormat: .pcmFormatFloat32, sampleRate: sampleRate, channels: 1, interleaved: false)!
        let r = BeaconRenderer(beacon: self, outputLatency: 0, fixedFirstStart: firstStart)
        let node = AVAudioSourceNode(format: format, renderBlock: r.renderBlock)
        objc_setAssociatedObject(node, &BeaconRenderer.key, r, .OBJC_ASSOCIATION_RETAIN)  // keep the renderer alive with the node
        return node
    }

    // MARK: Private

    private func startPolling(_ r: BeaconRenderer) {
        let t = DispatchSource.makeTimerSource(queue: queue)
        var reportedStart = false
        var lastCount = 0
        t.schedule(deadline: .now() + 0.05, repeating: 0.1)
        t.setEventHandler { [weak self, r] in
            guard let self else { return }
            if !reportedStart, r.firstStart >= 0 {
                reportedStart = true
                self.onEvent?(.started(firstChirpAt: Date(timeIntervalSince1970: r.firstChirpWall)))
            }
            let n = r.played
            if n != lastCount {
                lastCount = n
                self.onEvent?(.played(count: n))
            }
        }
        t.resume()
        poll = t
    }

    private func watchEngine() {
        let nc = NotificationCenter.default
        observers.append(nc.addObserver(forName: .AVAudioEngineConfigurationChange, object: engine, queue: nil) { [weak self] _ in
            self?.onEvent?(.error("The audio output changed (headphones, speaker or sample rate). Press Stop, then Start again so the chirps line up."))
        })
        #if os(iOS)
        observers.append(nc.addObserver(forName: AVAudioSession.interruptionNotification, object: nil, queue: nil) { [weak self] _ in
            self?.onEvent?(.error("Another app interrupted the audio. Press Stop, then Start again."))
        })
        #endif
    }
}

/// The state the render block uses. Plain memory, read from the audio thread without locks or allocation.
/// Counters live behind raw pointers so the debug-mode exclusivity checker never trips on a reader thread.
final class BeaconRenderer: @unchecked Sendable {
    static var key = 0
    private let chirp: UnsafeMutablePointer<Float>
    private let chirpLength: Int
    private let period: Int
    private let sampleRate: Double
    private let beaconNumber: Int
    private let cycleSeconds: Double
    private let slotSeconds: Double
    private let outputLatency: Double
    /// Seconds between the first rendered buffer and the first chirp, at least. Gives the engine time to settle.
    private let lead = 0.25
    // state[0] = position (output samples rendered so far), state[1] = firstStart (-1 until chosen), state[2] = played
    private let state: UnsafeMutablePointer<Int>
    private let wall: UnsafeMutablePointer<Double>  // wall[0] = wall-clock time of the first chirp

    init(beacon: SelfTimedBeacon, outputLatency: Double, fixedFirstStart: Int?) {
        let samples = beacon.spec.samples(sampleRate: beacon.sampleRate)
        chirpLength = samples.count
        let c = UnsafeMutablePointer<Float>.allocate(capacity: max(1, samples.count))
        samples.withUnsafeBufferPointer { c.update(from: $0.baseAddress!, count: samples.count) }
        chirp = c
        period = ChirpScheduler.period(cycleSeconds: beacon.cycleSeconds, sampleRate: beacon.sampleRate)
        sampleRate = beacon.sampleRate
        beaconNumber = beacon.beaconNumber
        cycleSeconds = beacon.cycleSeconds
        slotSeconds = beacon.slotSeconds
        self.outputLatency = outputLatency
        state = UnsafeMutablePointer<Int>.allocate(capacity: 3)
        state[0] = 0
        state[1] = fixedFirstStart ?? -1
        state[2] = 0
        wall = UnsafeMutablePointer<Double>.allocate(capacity: 1)
        wall[0] = 0
    }

    deinit {
        chirp.deallocate()
        state.deallocate()
        wall.deallocate()
    }

    var position: Int { state[0] }
    var firstStart: Int { state[1] }
    var played: Int { state[2] }
    var firstChirpWall: Double { wall[0] }

    /// Runs on the audio thread. No allocation, no locks, no Objective-C messaging beyond the time conversion.
    lazy var renderBlock: AVAudioSourceNodeRenderBlock = { [unowned self] isSilence, timestamp, frameCount, outputData in
        let count = Int(frameCount)
        let position = self.state[0]
        if self.state[1] < 0 { self.chooseFirstStart(timestamp.pointee) }
        let scheduler = ChirpScheduler(period: self.period, firstStart: self.state[1], chirpLength: self.chirpLength)
        let buffers = UnsafeMutableAudioBufferListPointer(outputData)
        for b in buffers {
            guard let data = b.mData else { continue }
            scheduler.fill(data.assumingMemoryBound(to: Float.self), count: count, position: position, chirp: self.chirp)
        }
        self.state[0] = position + count
        self.state[2] = scheduler.chirpsStarted(before: position + count)
        isSilence.pointee = false
        return noErr
    }

    /// Done once, on the first render: find the wall-clock time at which this buffer's first sample leaves the
    /// speaker, then pick the first chirp so it starts at this beacon's phase within the 0.5 s cycle.
    private func chooseFirstStart(_ ts: AudioTimeStamp) {
        let wallNow = Date().timeIntervalSince1970
        var bufferWall = wallNow + outputLatency
        if ts.mFlags.contains(.hostTimeValid) {
            bufferWall += AVAudioTime.seconds(forHostTime: ts.mHostTime) - AVAudioTime.seconds(forHostTime: mach_absolute_time())
        }
        let t0 = ChirpScheduler.firstChirpTime(after: bufferWall, beaconNumber: beaconNumber, cycleSeconds: cycleSeconds,
                                               slotSeconds: slotSeconds, lead: lead)
        state[1] = Int(((t0 - bufferWall) * sampleRate).rounded())
        wall[0] = t0
    }
}
