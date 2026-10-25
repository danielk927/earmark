import Foundation
import PhoneCore

/// The sound half of the wearer: a `PhoneClient` ("the user's phone", slot 0) that streams 48 kHz microphone
/// audio to the ranging service and receives `fix` messages. The listener owns the microphone and the audio
/// session while it captures; `PushToTalk` reads the same buffers (see `PushToTalk.feed`).
@MainActor
final class SoundListenerModel: ObservableObject {
    private static let key = "earmark.soundListen"

    @Published var enabled: Bool {
        didSet {
            guard enabled != oldValue else { return }
            UserDefaults.standard.set(enabled, forKey: Self.key)
            apply()
        }
    }
    @Published private(set) var statusLine = "Sound positioning: off"
    @Published private(set) var connected = false

    /// True while the listener's audio engine is running (config received, microphone open). Main actor.
    private(set) var capturing = false
    /// Called on the main actor whenever `capturing` changes.
    var onCaptureChanged: ((Bool) -> Void)?

    private let mic: PushToTalk
    private let urlProvider: () -> URL?
    private var client: PhoneClient?
    private var running = false
    private var lastFixAt: Double?
    private var error: String?

    init(mic: PushToTalk, url: @escaping () -> URL?) {
        self.mic = mic
        self.urlProvider = url
        enabled = UserDefaults.standard.object(forKey: Self.key) as? Bool ?? true
        refreshStatus()
    }

    var lastFixAge: Double? { lastFixAt.map { uptime() - $0 } }

    func start() {
        running = true
        apply()
    }

    func stop() {
        running = false
        apply()
    }

    func appBecameActive() {
        // PhoneClient retries a lost connection by itself; only a failed start needs a nudge.
        if running, enabled, client != nil, !capturing, error != nil { restart() }
    }

    func refreshStatus() {
        let line = SoundStatusText.listener(enabled: enabled, connected: connected, fixAge: lastFixAge, error: error)
        if line != statusLine { statusLine = line }
    }

    private func apply() {
        if running, enabled {
            if client == nil { startClient() }
        } else {
            stopClient()
        }
        refreshStatus()
    }

    private func restart() {
        stopClient()
        startClient()
    }

    private func startClient() {
        guard let url = urlProvider() else {
            error = "the ranging address is not valid"
            refreshStatus()
            return
        }
        error = nil
        lastFixAt = nil
        let c = PhoneClient(url: url, slot: 0, name: Self.deviceName)
        let mic = self.mic
        c.onMicBuffer = { buffer in mic.feed(buffer) }
        c.onEvent = { [weak self] event in
            onMain { [weak self] in self?.handle(event) }
        }
        client = c
        c.start()
    }

    private func stopClient() {
        client?.stop()
        client = nil
        connected = false
        lastFixAt = nil
        error = nil
        setCapturing(false)
    }

    private func setCapturing(_ on: Bool) {
        guard on != capturing else { return }
        capturing = on
        onCaptureChanged?(on)
    }

    private func handle(_ event: PhoneEvent) {
        guard client != nil else { return }   // late event after stop
        switch event {
        case .connecting:
            connected = false
            setCapturing(false)
        case .connected:
            connected = true
            error = nil
            setCapturing(true)
        case .fix:
            lastFixAt = uptime()
        case .error(let message):
            error = message
            connected = false
            setCapturing(false)
        case .disconnected:
            connected = false
            setCapturing(false)
        case .played, .level:
            break
        }
        refreshStatus()
    }

    private static var deviceName: String { "Earmark wearer" }
}
