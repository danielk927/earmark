import EarmarkContracts
import NearbyInteraction

/// UWB support check (UWB-PRD 4.1 and 7.2 step 4).
///
/// `NISession.deviceCapabilities` is iOS 16+; the older `NISession.isSupported` is deprecated since iOS 16 and
/// equivalent to `supportsPreciseDistanceMeasurement` (Apple docs), so with an iOS 17 deployment target only the
/// new API is used. iPhone 11 and later (not SE) report true; the simulator reports false.
enum CapabilityCheck {
    static var supportsUWB: Bool {
        NISession.deviceCapabilities.supportsPreciseDistanceMeasurement
    }

    static var info: [String: JSONScalar] {
        let caps = NISession.deviceCapabilities
        return [
            "uwb_supported": .bool(caps.supportsPreciseDistanceMeasurement),
            "direction_supported": .bool(caps.supportsDirectionMeasurement),
            "camera_assistance_supported": .bool(caps.supportsCameraAssistance),
        ]
    }

    static let unsupportedMessage =
        "This iPhone can't measure UWB distance. Use an iPhone 11 or later (not an iPhone SE)."
}
