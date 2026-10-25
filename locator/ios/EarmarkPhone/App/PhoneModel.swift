import Foundation
import PhoneCore
import SwiftUI

/// What this phone is doing. The two Mac-connected roles are unchanged; `selfTimed` chirps on its own clock.
enum PhoneRole: String, CaseIterable {
    case user, beacon, selfTimed
}

/// Chirp bands offered in the app. Index 0 is the default.
let bandPresets: [(lo: Int, hi: Int, name: String)] = [
    (12000, 16000, "12 to 16 kHz (default)"),
    (14000, 18000, "14 to 18 kHz"),
    (17000, 20000, "17 to 20 kHz (quietest)"),
]

@MainActor
final class PhoneModel: ObservableObject {
    @AppStorage("server") var server = ""
    @AppStorage("role") var role: PhoneRole = .user
    @AppStorage("beaconNumber") var beaconNumber = 1
    @AppStorage("bandPreset") var bandPreset = 0
    @AppStorage("volume") var volume = 0.8

    @Published var running = false
    @Published var status = "Not started"
    @Published var problem: String?
    @Published var chirps = 0
    @Published var level: Float = 0
    @Published var fix: UserFix?
    @Published var chirpBand = ""
    @Published var firstChirpAt: Date?

    private var client: PhoneClient?
    private var selfTimed: SelfTimedBeacon?

    var isUser: Bool { role == .user }
    var slot: Int { isUser ? 0 : beaconNumber }
    var roleName: String {
        switch role {
        case .user: return "Your phone"
        case .beacon: return "Beacon \(beaconNumber)"
        case .selfTimed: return "Beacon \(beaconNumber) (no Mac)"
        }
    }
    var band: (lo: Int, hi: Int, name: String) { bandPresets[min(max(bandPreset, 0), bandPresets.count - 1)] }
    /// Seconds into each 0.5 s cycle at which this beacon's chirp starts.
    var slotPhase: Double { Double(beaconNumber - 1) * 0.125 }

    func start() {
        problem = nil
        if role == .selfTimed { startSelfTimed(); return }
        guard let url = PhoneAddress.url(server) else {
            problem = "Type the Mac's address first: the name the Mac printed, like some-words.trycloudflare.com, or 192.168.1.20:8766 on the same Wi-Fi"
            return
        }
        let c = PhoneClient(url: url, slot: slot, name: UIDeviceName.value)
        c.onEvent = { [weak self] event in
            Task { @MainActor in self?.handle(event) }
        }
        client = c
        running = true
        chirps = 0
        status = "Connecting..."
        keepAwake(true)
        c.start()
    }

    private func startSelfTimed() {
        let n = min(max(beaconNumber, 1), 4)
        beaconNumber = n
        let b = SelfTimedBeacon(beaconNumber: n, band: (Double(band.lo), Double(band.hi)), amplitude: volume)
        b.onEvent = { [weak self] event in
            Task { @MainActor in self?.handle(event) }
        }
        selfTimed = b
        chirps = 0
        firstChirpAt = nil
        chirpBand = "\(band.lo) to \(band.hi) Hz, sweeping \(b.spec.direction)"
        do {
            try b.start()
            running = true
            status = "Starting the speaker..."
            keepAwake(true)
        } catch {
            problem = "Could not start the speaker: \(error.localizedDescription)"
            selfTimed = nil
        }
    }

    func stop() {
        client?.stop()
        client = nil
        selfTimed?.stop()
        selfTimed = nil
        running = false
        status = "Stopped"
        keepAwake(false)
    }

    func testSweep() { client?.playTestSweep() }

    private func keepAwake(_ on: Bool) {
        #if os(iOS)
        UIApplication.shared.isIdleTimerDisabled = on  // a sleeping phone stops listening or chirping
        #endif
    }

    private func handle(_ event: PhoneEvent) {
        switch event {
        case .connecting: status = "Connecting..."
        case .connected(_, let chirp):
            status = "Connected"
            problem = nil
            chirpBand = "\(Int(chirp.fLo)) to \(Int(chirp.fHi)) Hz"
        case .played(let n): chirps = n
        case .level(let l): level = l
        case .fix(let f): fix = f
        case .error(let e): problem = e
        case .disconnected: status = "Stopped"
        }
    }

    private func handle(_ event: SelfTimedBeaconEvent) {
        switch event {
        case .started(let t):
            firstChirpAt = t
            status = "Chirping"
            problem = nil
        case .played(let n): chirps = n
        case .error(let e): problem = e
        }
    }
}

enum UIDeviceName {
    static var value: String {
        #if os(iOS)
        return UIDevice.current.name
        #else
        return Host.current().localizedName ?? "Mac"
        #endif
    }
}
