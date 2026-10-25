import SwiftUI

/// Hub connection line with a colored dot, plus the last error and a hint when the hub never accepted us.
@MainActor
struct HubStatusView: View {
    @ObservedObject var hub: HubConnection

    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            HStack(spacing: 10) {
                Circle()
                    .fill(color)
                    .frame(width: 16, height: 16)
                    .accessibilityHidden(true)
                Text("Hub: \(hub.state.label)")
                    .font(.title3.weight(.semibold))
            }
            if let refusal = hub.refusal {
                Text("Hub refused this iPhone: \(refusal)")
                    .font(.callout.weight(.semibold))
                    .foregroundStyle(.red)
            }
            if case .disconnected(let why) = hub.state {
                Text(why)
                    .font(.footnote)
                    .foregroundStyle(.secondary)
                if !hub.everAccepted {
                    Text("Check the hub address and pairing secret, and that this iPhone is on the same private Wi-Fi as the Mac.")
                        .font(.footnote)
                        .foregroundStyle(.orange)
                }
            } else if hub.state == .connected && !hub.helloAccepted {
                Text("Waiting for the hub to accept this iPhone…")
                    .font(.footnote)
                    .foregroundStyle(.secondary)
            }
            Text(hub.url.absoluteString)
                .font(.footnote.monospaced())
                .foregroundStyle(.secondary)
                .accessibilityLabel("Hub address \(hub.url.absoluteString)")
        }
        .accessibilityElement(children: .combine)
    }

    private var color: Color {
        switch hub.state {
        case .connected: hub.helloAccepted ? .green : .yellow
        case .connecting: .yellow
        case .disconnected: .red
        case .idle: .gray
        }
    }
}

/// "Title ........ value" row, combined into one VoiceOver element.
struct InfoRow: View {
    let title: String
    let value: String

    var body: some View {
        HStack(alignment: .firstTextBaseline) {
            Text(title)
                .foregroundStyle(.secondary)
            Spacer(minLength: 12)
            Text(value)
                .fontWeight(.semibold)
                .multilineTextAlignment(.trailing)
        }
        .font(.title3)
        .accessibilityElement(children: .combine)
    }
}

/// Large red banner shown when this iPhone has no UWB.
struct UnsupportedBanner: View {
    var body: some View {
        Label(CapabilityCheck.unsupportedMessage, systemImage: "exclamationmark.triangle.fill")
            .font(.title2.bold())
            .foregroundStyle(.white)
            .padding()
            .frame(maxWidth: .infinity, alignment: .leading)
            .background(RoundedRectangle(cornerRadius: 16).fill(Color.red))
    }
}

/// Stop button with a confirmation, so a bump at the booth doesn't end a role.
@MainActor
struct StopRoleButton: View {
    let action: @MainActor () -> Void
    @State private var confirming = false

    var body: some View {
        Button(role: .destructive) {
            confirming = true
        } label: {
            Text("Stop and change role")
                .font(.headline)
                .frame(maxWidth: .infinity, minHeight: 50)
        }
        .buttonStyle(.bordered)
        .confirmationDialog("Stop this iPhone's UWB role?", isPresented: $confirming, titleVisibility: .visible) {
            Button("Stop", role: .destructive) { action() }
            Button("Cancel", role: .cancel) {}
        }
    }
}

/// Grouped card background that works in light and dark mode.
struct Card<Content: View>: View {
    @ViewBuilder let content: Content

    var body: some View {
        VStack(alignment: .leading, spacing: 12) { content }
            .padding()
            .frame(maxWidth: .infinity, alignment: .leading)
            .background(RoundedRectangle(cornerRadius: 16).fill(Color(.secondarySystemBackground)))
    }
}
