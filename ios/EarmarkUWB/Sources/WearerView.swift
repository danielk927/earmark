import EarmarkContracts
import SwiftUI

/// Wearer screen (UWB-PRD 7.4): "UWB Reader/Emitter 1: 2.41 m" rows with per-anchor rates, motion state, hub
/// connection, the hub's pose, the round-robin toggle, and a big hold-to-talk button and a Mark here button
/// (tap-to-mark also fires on a knock; see `MotionDetector`).
@MainActor
struct WearerView: View {
    @ObservedObject var controller: WearerController
    @ObservedObject var hub: HubConnection
    let onStop: @MainActor () -> Void

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 20) {
                Text("Wearer")
                    .font(.largeTitle.bold())
                    .accessibilityAddTraits(.isHeader)

                if !controller.uwbSupported {
                    UnsupportedBanner()
                }

                HubStatusView(hub: hub)

                Card {
                    ForEach(controller.rows) { row in
                        AnchorRowView(row: row)
                        if row.id != controller.rows.last?.id { Divider() }
                    }
                }

                Card {
                    InfoRow(title: "Motion", value: motionText)
                    if let pose = controller.poseSummary {
                        InfoRow(title: "Hub position", value: pose)
                    }
                    InfoRow(title: "Battery", value: controller.batteryText)
                }

                Card {
                    Toggle(isOn: $controller.roundRobin) {
                        VStack(alignment: .leading, spacing: 4) {
                            Text("Round-robin fallback")
                                .font(.headline)
                            Text("Range to two anchors at a time, rotating every 2 seconds. Use only if three sessions at once don't work.")
                                .font(.footnote)
                                .foregroundStyle(.secondary)
                        }
                    }
                    if let note = controller.roundRobinNote {
                        Text(note)
                            .font(.footnote)
                            .foregroundStyle(.orange)
                    }
                }

                TalkButton(talking: controller.talking) { controller.setTalking($0) }
                if let message = controller.micMessage {
                    Text(message)
                        .font(.callout)
                        .foregroundStyle(.red)
                }

                MarkButton { controller.markHere() }
                if let status = controller.markStatus {
                    Text(status)
                        .font(.callout)
                        .foregroundStyle(.secondary)
                }

                StopRoleButton(action: onStop)
            }
            .padding()
        }
    }

    private var motionText: String {
        switch controller.motion {
        case .moving?: "Moving"
        case .still?: "Still"
        case nil: "Measuring…"
        }
    }
}

@MainActor
private struct AnchorRowView: View {
    let row: WearerController.AnchorRow

    var body: some View {
        VStack(alignment: .leading, spacing: 4) {
            Text("\(row.label): \(distanceText)")
                .font(.title2.bold())
                .foregroundStyle(row.ranging ? Color.primary : Color.secondary)
            Text("\(Int(row.sentHz.rounded())) Hz sent, \(Int(row.measuredHz.rounded())) Hz measured")
                .font(.callout.monospacedDigit())
            Text(row.phase)
                .font(.callout)
                .foregroundStyle(.secondary)
            if !row.phoneOnline {
                Text("Anchor phone not reporting to the hub")
                    .font(.footnote)
                    .foregroundStyle(.orange)
            }
        }
        .accessibilityElement(children: .combine)
    }

    private var distanceText: String {
        guard let d = row.distance else { return "—" }
        return row.stale ? "\(metres(d)) (old)" : metres(d)
    }
}

/// Hold to talk. VoiceOver can't easily hold, so its activate action toggles instead.
@MainActor
private struct TalkButton: View {
    let talking: Bool
    let setTalking: @MainActor (Bool) -> Void

    var body: some View {
        Text(talking ? "Listening… release to send" : "Hold to Talk")
            .font(.title.bold())
            .foregroundStyle(.white)
            .multilineTextAlignment(.center)
            .padding()
            .frame(maxWidth: .infinity, minHeight: 120)
            .background(RoundedRectangle(cornerRadius: 24).fill(talking ? Color.red : Color.accentColor))
            .contentShape(RoundedRectangle(cornerRadius: 24))
            .gesture(
                DragGesture(minimumDistance: 0)
                    .onChanged { _ in if !talking { setTalking(true) } }
                    .onEnded { _ in setTalking(false) }
            )
            .accessibilityElement()
            .accessibilityLabel(talking ? "Stop talking" : "Talk")
            .accessibilityHint(talking ? "Double-tap to stop and send." : "Double-tap to start talking, then double-tap again to stop.")
            .accessibilityAddTraits(.isButton)
            .accessibilityAction { setTalking(!talking) }
    }
}

/// Saves the object next to the phone (same as knocking the phone on the table). A plain button, so VoiceOver's
/// double-tap just works.
@MainActor
private struct MarkButton: View {
    let mark: @MainActor () -> Void

    var body: some View {
        Button { mark() } label: {
            Text("Mark here")
                .font(.title.bold())
                .foregroundStyle(.white)
                .multilineTextAlignment(.center)
                .padding()
                .frame(maxWidth: .infinity, minHeight: 120)
                .background(RoundedRectangle(cornerRadius: 24).fill(Color.indigo))
                .contentShape(RoundedRectangle(cornerRadius: 24))
        }
        .buttonStyle(.plain)
        .accessibilityLabel("Mark here")
        .accessibilityHint("Saves the object next to your phone")
    }
}
