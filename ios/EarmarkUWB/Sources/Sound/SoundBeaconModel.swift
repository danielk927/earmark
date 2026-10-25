import Foundation
import PhoneCore

/// The sound half of an anchor phone: `uwb_N` also chirps as beacon N (calibrate-then-listen protocol,
/// `services/ranging/README.md`). It runs a `SelfTimedBeacon`: no network, no microphone, `.playback` audio
/// session. Starting or stopping it never touches the Nearby Interaction session (separate subsystem).
@MainActor
final class SoundBeaconModel: ObservableObject {
    /// Band preset 0 of the standalone app (listen mode default) and its default volume.
    static let band: (Double, Double) = (12_000, 16_000)
    static let amplitude = 0.8
    private static let key = "earmark.soundBeacon"

    /// nil for roles that are not beacons.
    let beaconNumber: Int?

    @Published var enabled: Bool {
        didSet {
            guard enabled != oldValue else { return }
            UserDefaults.standard.set(enabled, forKey: Self.key)
            apply()
        }
    }
    @Published private(set) var chirping = false
    @Published private(set) var played = 0
    @Published private(set) var error: String?

    private var beacon: SelfTimedBeacon?
    private var running = false

    init(deviceId: String) {
        beaconNumber = BeaconNumber.forDevice(deviceId)
        enabled = UserDefaults.standard.object(forKey: Self.key) as? Bool ?? true
    }

    var statusLine: String {
        SoundStatusText.beacon(number: beaconNumber, enabled: enabled, chirping: chirping, played: played, error: error)
    }

    func start() {
        running = true
        apply()
    }

    func stop() {
        running = false
        apply()
    }

    /// Coming back to the foreground: an audio interruption leaves the beacon silent, so start it again.
    func appBecameActive() {
        if running, enabled, error != nil { restart() }
    }

    private func apply() {
        if running, enabled, beaconNumber != nil {
            if beacon == nil { startBeacon() }
        } else {
            stopBeacon()
        }
    }

    private func restart() {
        stopBeacon()
        startBeacon()
    }

    private func startBeacon() {
        guard let n = beaconNumber else { return }
        let b = SelfTimedBeacon(beaconNumber: n, band: Self.band, amplitude: Self.amplitude)
        b.onEvent = { [weak self] event in
            onMain { [weak self] in self?.handle(event) }
        }
        played = 0
        chirping = false
        error = nil
        do {
            try b.start()
            beacon = b
        } catch {
            self.error = "could not start the speaker (\(error.localizedDescription))"
            Log.mic.error("beacon start failed: \(error.localizedDescription, privacy: .public)")
        }
    }

    private func stopBeacon() {
        beacon?.stop()
        beacon = nil
        chirping = false
        played = 0
        error = nil
    }

    private func handle(_ event: SelfTimedBeaconEvent) {
        guard beacon != nil else { return }   // a late event from a beacon that was just stopped
        switch event {
        case .started:
            chirping = true
            error = nil
        case .played(let n):
            played = n
        case .error(let message):
            error = message
            chirping = false
        }
    }
}
