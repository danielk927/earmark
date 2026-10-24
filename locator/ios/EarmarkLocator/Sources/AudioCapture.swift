import AVFoundation
import Foundation
import EarmarkCore

struct AudioPacket: Sendable {
    let samples: [Double]
    let sampleTime: Int64
    let hostSeconds: Double
    let sampleRate: Double
    let inputLatency: Double
}

@MainActor
final class AudioCapture {
    private let engine = AVAudioEngine()
    private var tapInstalled = false
    private var observers: [NSObjectProtocol] = []
    var onRouteChange: (() -> Void)?
    var onInterruption: (() -> Void)?
    private(set) var route = "Not running"
    private(set) var actualRate = 0.0

    init() {
        observers.append(NotificationCenter.default.addObserver(forName: AVAudioSession.routeChangeNotification, object: nil, queue: .main) { [weak self] _ in
            Task { @MainActor [weak self] in self?.onRouteChange?() }
        })
        observers.append(NotificationCenter.default.addObserver(forName: AVAudioSession.interruptionNotification, object: nil, queue: .main) { [weak self] _ in
            Task { @MainActor [weak self] in self?.onInterruption?() }
        })
    }
    deinit { for observer in observers { NotificationCenter.default.removeObserver(observer) } }

    func start(preferredRate: Double, receive: @escaping @Sendable (AudioPacket) -> Void,
               invalidClock: @escaping @Sendable () -> Void) throws {
        let session = AVAudioSession.sharedInstance()
        try session.setCategory(.record, mode: .measurement, options: [])
        try session.setPreferredSampleRate(preferredRate)
        try session.setPreferredIOBufferDuration(0.05)
        try session.setActive(true)
        guard let builtIn = session.availableInputs?.first(where: { $0.portType == .builtInMic }) else {
            throw LocatorError.invalid("Built-in microphone unavailable. Disconnect external inputs and retry.")
        }
        if let bottom = builtIn.dataSources?.first(where: { $0.orientation == .bottom }) {
            if bottom.supportedPolarPatterns?.contains(.omnidirectional) == true {
                try bottom.setPreferredPolarPattern(.omnidirectional)
            }
            try builtIn.setPreferredDataSource(bottom)
        }
        try session.setPreferredInput(builtIn)
        guard session.currentRoute.inputs.allSatisfy({ $0.portType == .builtInMic }), !session.currentRoute.inputs.isEmpty else {
            throw LocatorError.invalid("Input is not the built-in microphone. Retry after disconnecting Bluetooth.")
        }
        let input = engine.inputNode
        let format = input.outputFormat(forBus: 0)
        guard format.sampleRate > 0, format.channelCount > 0 else { throw LocatorError.invalid("Microphone has no valid input format") }
        actualRate = format.sampleRate
        route = session.currentRoute.inputs.map { "\($0.portName) / \($0.selectedDataSource?.dataSourceName ?? "default")" }.joined(separator: ", ")
        let latency = session.inputLatency
        input.installTap(onBus: 0, bufferSize: 2400, format: format) { buffer, time in
            guard time.isSampleTimeValid, time.isHostTimeValid, let channel = buffer.floatChannelData?[0] else { invalidClock(); return }
            let samples = (0..<Int(buffer.frameLength)).map { Double(channel[$0]) }
            receive(AudioPacket(samples: samples, sampleTime: time.sampleTime,
                                hostSeconds: AVAudioTime.seconds(forHostTime: time.hostTime),
                                sampleRate: format.sampleRate, inputLatency: latency))
        }
        tapInstalled = true
        engine.prepare()
        try engine.start()
    }
    func stop() throws {
        engine.stop()
        if tapInstalled { engine.inputNode.removeTap(onBus: 0); tapInstalled = false }
        try AVAudioSession.sharedInstance().setActive(false)
        route = "Not running"
    }
}
