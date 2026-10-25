import EarmarkContracts
import SwiftUI
import UIKit

/// What this iPhone is. Raw values are the bus `device_id`s.
enum DeviceRole: String, CaseIterable, Identifiable {
    case uwb1 = "uwb_1"
    case uwb2 = "uwb_2"
    case uwb3 = "uwb_3"
    case wearer = "wearer"

    var id: String { rawValue }
    var deviceId: String { rawValue }
    var isAnchor: Bool { self != .wearer }
    var label: String { isAnchor ? Self.defaultLabel(for: rawValue) : "Wearer" }
    var component: Component { isAnchor ? .iosAnchor : .iosWearer }
    var helloRole: Hello.Role { isAnchor ? .anchor : .wearer }

    /// "uwb_2" -> "UWB Reader/Emitter 2" (used until the hub's snapshot provides `space.anchors` labels).
    static func defaultLabel(for anchorId: String) -> String {
        anchorId.hasPrefix("uwb_") ? "UWB Reader/Emitter \(anchorId.dropFirst(4))" : anchorId
    }
}

/// App state: the chosen role, hub address, and pairing secret (remembered in UserDefaults), and the running
/// role controller. Keeps the screen awake while a role runs (Nearby Interaction suspends in the background).
@MainActor
final class AppModel: ObservableObject {
    enum Active {
        case anchor(AnchorController)
        case wearer(WearerController)
    }

    static let defaultHubAddress = "ws://192.168.8.10:8765"
    private enum Key {
        static let role = "earmark.role"
        static let hub = "earmark.hubAddress"
        static let secret = "earmark.secret"
    }

    @Published var selectedRole: DeviceRole? {
        didSet { UserDefaults.standard.set(selectedRole?.rawValue, forKey: Key.role) }
    }
    @Published var hubAddress: String {
        didSet { UserDefaults.standard.set(hubAddress, forKey: Key.hub) }
    }
    // ponytail: the bus secret sits in UserDefaults; it only guards a private demo network. Keychain if that changes.
    @Published var secret: String {
        didSet { UserDefaults.standard.set(secret, forKey: Key.secret) }
    }
    @Published private(set) var active: Active?

    init() {
        let defaults = UserDefaults.standard
        selectedRole = defaults.string(forKey: Key.role).flatMap(DeviceRole.init(rawValue:))
        hubAddress = defaults.string(forKey: Key.hub) ?? Self.defaultHubAddress
        secret = defaults.string(forKey: Key.secret) ?? ""
    }

    var hubURL: URL? { HubAddress.parse(hubAddress) }
    var canConnect: Bool { selectedRole != nil && hubURL != nil }

    func connect() {
        guard active == nil, let role = selectedRole, let url = hubURL else { return }
        UIDevice.current.isBatteryMonitoringEnabled = true
        UIApplication.shared.isIdleTimerDisabled = true
        let trimmed = secret.trimmingCharacters(in: .whitespacesAndNewlines)
        let hub = HubConnection(url: url, component: role.component, deviceId: role.deviceId,
                                role: role.helloRole, secret: trimmed.isEmpty ? nil : trimmed)
        if role.isAnchor {
            let controller = AnchorController(role: role, hub: hub)
            controller.start()
            active = .anchor(controller)
        } else {
            let controller = WearerController(hub: hub)
            controller.start()
            active = .wearer(controller)
        }
    }

    func disconnect() {
        switch active {
        case .anchor(let c)?: c.stop()
        case .wearer(let c)?: c.stop()
        case nil: break
        }
        active = nil
        UIApplication.shared.isIdleTimerDisabled = false
    }

    func scenePhaseChanged(_ phase: ScenePhase) {
        switch (phase, active) {
        case (.active, .anchor(let c)?): c.appBecameActive()
        case (.active, .wearer(let c)?): c.appBecameActive()
        case (.background, .anchor(let c)?): c.appWentToBackground()
        case (.background, .wearer(let c)?): c.appWentToBackground()
        default: break
        }
        // The idle timer resets when the app leaves the foreground on some iOS versions; set it again.
        if phase == .active, active != nil { UIApplication.shared.isIdleTimerDisabled = true }
    }
}
