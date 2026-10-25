import SwiftUI

/// Anchor screen (UWB-PRD 7.3): huge "UWB Reader/Emitter N", hub connection, session state, last distance to
/// the wearer, battery.
@MainActor
struct AnchorView: View {
    @ObservedObject var controller: AnchorController
    @ObservedObject var hub: HubConnection
    @ObservedObject var beacon: SoundBeaconModel
    let onStop: @MainActor () -> Void

    @ScaledMetric(relativeTo: .largeTitle) private var titleSize: CGFloat = 52

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 24) {
                Text(controller.label)
                    .font(.system(size: titleSize, weight: .heavy, design: .rounded))
                    .lineLimit(3)
                    .minimumScaleFactor(0.5)
                    .accessibilityAddTraits(.isHeader)

                if !controller.uwbSupported {
                    UnsupportedBanner()
                }

                HubStatusView(hub: hub)

                Card {
                    InfoRow(title: "Session", value: controller.phase.label)
                    InfoRow(title: "Distance to wearer", value: distanceText)
                    InfoRow(title: "Battery", value: controller.batteryText)
                }

                if beacon.beaconNumber != nil {
                    Card {
                        Toggle(isOn: $beacon.enabled) {
                            Text("Sound beacon")
                                .font(.headline)
                        }
                        .accessibilityHint("Chirps a quiet high sound every half second so the sound positioning system can locate this anchor")
                        Text(beacon.statusLine)
                            .font(.title3)
                            .foregroundStyle(beacon.error == nil ? Color.primary : Color.red)
                    }
                }

                Text("Keep this iPhone plugged in, screen on, and this app open. Don't move it after its position is measured.")
                    .font(.body)
                    .foregroundStyle(.secondary)

                StopRoleButton(action: onStop)
            }
            .padding()
        }
    }

    private var distanceText: String {
        guard let d = controller.distance else { return "—" }
        return controller.distanceStale ? "\(metres(d)) (old)" : metres(d)
    }
}
