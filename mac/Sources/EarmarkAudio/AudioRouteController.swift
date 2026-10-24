import AVFAudio
import Foundation

/// Applies the audio-routing rule and coalesces route changes into one restart.
///
/// Routing rule (brief 5.E, docs/sponsors/vendor-notes/apple-spatial-audio.md section 5b): on macOS AVAudioEngine follows
/// the system default devices and may aggregate the default input even for playback, so if the system default
/// input is Bluetooth (the AirPods mic), switch it to the built-in mic before any playback engine is built,
/// and re-assert it whenever it changes. This changes a user-visible system setting: it is logged, shown in the
/// UI, and can be turned off in Settings.
public final class AudioRouteController {
    public var enforceBuiltInMic: Bool {
        didSet { if enforceBuiltInMic && !oldValue { _ = enforceInputRule() } }
    }
    /// A debounced restart is due (main queue). The argument says why.
    public var onRestartNeeded: ((String) -> Void)?
    /// Device facts changed (main queue).
    public var onDevicesChanged: ((DeviceReport) -> Void)?
    /// Human-readable last routing action, for the UI.
    public private(set) var lastAction: String?

    private var watcher: AudioDeviceWatcher?
    private var configObserver: NSObjectProtocol?
    private var reasons: [String] = []
    private var knownDevices: Set<String> = []
    private var suppressUntil = DispatchTime(uptimeNanoseconds: 0)
    private lazy var restart = DebouncedTrigger(delay: 0.4, minSpacing: 1.5) { [weak self] in self?.fireRestart() }

    public init(enforceBuiltInMic: Bool = true) {
        self.enforceBuiltInMic = enforceBuiltInMic
    }

    deinit {
        if let configObserver { NotificationCenter.default.removeObserver(configObserver) }
    }

    /// Call once at launch, BEFORE building any playback engine.
    public func start() {
        knownDevices = Self.realDeviceUIDs()
        _ = enforceInputRule()
        watcher = AudioDeviceWatcher { [weak self] change in self?.deviceChanged(change) }
        configObserver = NotificationCenter.default.addObserver(forName: .AVAudioEngineConfigurationChange, object: nil, queue: .main) { [weak self] _ in
            guard let self else { return }
            // Our own restarts can post configuration changes; ignore those (no restart storms).
            guard DispatchTime.now() > self.suppressUntil else { return }
            self.schedule("audio engine configuration changed")
        }
        onDevicesChanged?(report())
    }

    /// Switches a Bluetooth default input to the built-in mic. Returns the action taken, if any.
    @discardableResult
    public func enforceInputRule() -> String? {
        guard enforceBuiltInMic else { return nil }
        let input = AudioDevices.defaultInput()
        guard let target = RoutingPolicy.inputSwitchTarget(defaultInput: input, devices: AudioDevices.all()) else {
            if let i = input, i.transport.isBluetooth {
                lastAction = "Default input is \(i.name) (Bluetooth) and no built-in mic was found. Expect hands-free audio."
                Log.route(lastAction!)
            }
            return nil
        }
        let status = AudioDevices.setDefaultInput(target.id)
        let msg: String
        if status == noErr {
            msg = "Switched the system input from \(input?.name ?? "?") (Bluetooth) to \(target.name), so the AirPods stay in high-quality stereo."
        } else {
            msg = "Could not switch the system input from \(input?.name ?? "?") to \(target.name) (error \(status))."
        }
        lastAction = msg
        Log.route(msg)
        return msg
    }

    public func report(captureDevice: String? = nil) -> DeviceReport {
        var r = DeviceReport()
        r.inputDevice = captureDevice ?? AudioDevices.defaultInput()?.name ?? "none"
        if let o = AudioDevices.defaultOutput() {
            r.outputDevice = o.name
            r.outputSampleRate = o.nominalSampleRate
            r.outputTransport = o.transport
            r.hfpSuspected = RoutingPolicy.hfpSuspected(o)
        }
        return r
    }

    /// Call right after restarting engines so their own notifications are ignored.
    public func didRestart() { suppressUntil = .now() + 1.0 }

    /// UIDs of real devices; engines create and destroy private aggregate devices, which must not trigger restarts.
    static func realDeviceUIDs() -> Set<String> {
        Set(AudioDevices.all().filter { $0.transport != .aggregate && !$0.uid.isEmpty }.map(\.uid))
    }

    private func deviceChanged(_ change: AudioDeviceWatcher.Change) {
        if change == .deviceList {
            let now = Self.realDeviceUIDs()
            guard now != knownDevices else { return }
            knownDevices = now
        }
        Log.route("device change: \(change.rawValue)")
        if change == .defaultInput { _ = enforceInputRule() }
        let r = report()
        if r.hfpSuspected {
            Log.route("WARNING: \(r.outputDevice) output is at \(Int(r.outputSampleRate)) Hz: hands-free (HFP) mode, spatial cues will be destroyed")
        }
        onDevicesChanged?(r)
        schedule(change.rawValue)
    }

    private func schedule(_ reason: String) {
        reasons.append(reason)
        restart.trigger()
    }

    private func fireRestart() {
        let why = Array(Set(reasons)).sorted().joined(separator: ", ")
        reasons.removeAll()
        onRestartNeeded?(why)
        didRestart()
    }
}
