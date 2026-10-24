import Foundation
import PhoneCore
import SwiftUI

@MainActor
final class PhoneModel: ObservableObject {
    @AppStorage("server") var server = ""
    @AppStorage("isUser") var isUser = true
    @AppStorage("beaconNumber") var beaconNumber = 1

    @Published var running = false
    @Published var status = "Not started"
    @Published var problem: String?
    @Published var chirps = 0
    @Published var level: Float = 0
    @Published var fix: UserFix?
    @Published var chirpBand = ""

    private var client: PhoneClient?

    var slot: Int { isUser ? 0 : beaconNumber }
    var roleName: String { isUser ? "Your phone" : "Beacon \(beaconNumber)" }

    func start() {
        problem = nil
        let text = server.trimmingCharacters(in: .whitespaces)
        let address = text.hasPrefix("ws://") ? text : "ws://\(text)"
        guard !text.isEmpty, let url = URL(string: address), url.host != nil else {
            problem = "Type the Mac's address first, like 192.168.1.20:8766"
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
        #if os(iOS)
        UIApplication.shared.isIdleTimerDisabled = true  // a sleeping phone stops listening
        #endif
        c.start()
    }

    func stop() {
        client?.stop()
        client = nil
        running = false
        status = "Stopped"
        #if os(iOS)
        UIApplication.shared.isIdleTimerDisabled = false
        #endif
    }

    func testSweep() { client?.playTestSweep() }

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
