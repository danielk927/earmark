import SwiftUI

/// Launch screen (UWB-PRD 7.2): pick this iPhone's job, the hub address, and the pairing secret, then Connect.
/// Remembers the last choices.
@MainActor
struct RolePickerView: View {
    @ObservedObject var model: AppModel
    @FocusState private var focusedField: Field?

    private enum Field { case hub, secret }

    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(alignment: .leading, spacing: 24) {
                    if !CapabilityCheck.supportsUWB {
                        UnsupportedBanner()
                    }

                    VStack(alignment: .leading, spacing: 12) {
                        Text("This iPhone is")
                            .font(.title2.bold())
                            .accessibilityAddTraits(.isHeader)
                        ForEach(DeviceRole.allCases) { role in
                            roleButton(role)
                        }
                    }

                    VStack(alignment: .leading, spacing: 8) {
                        Text("Hub address")
                            .font(.headline)
                        TextField(AppModel.defaultHubAddress, text: $model.hubAddress)
                            .font(.title3.monospaced())
                            .keyboardType(.URL)
                            .textInputAutocapitalization(.never)
                            .autocorrectionDisabled()
                            .textFieldStyle(.roundedBorder)
                            .submitLabel(.next)
                            .focused($focusedField, equals: .hub)
                            .onSubmit { focusedField = .secret }
                            .accessibilityLabel("Hub address")
                            .accessibilityHint("The Mac's bus address, for example ws://192.168.8.10:8765")
                        if model.hubURL == nil {
                            Text("Enter an address like ws://192.168.8.10:8765")
                                .font(.footnote)
                                .foregroundStyle(.red)
                        }
                    }

                    VStack(alignment: .leading, spacing: 8) {
                        Text("Pairing secret")
                            .font(.headline)
                        SecureField("EARMARK_BUS_SECRET", text: $model.secret)
                            .font(.title3)
                            .textInputAutocapitalization(.never)
                            .autocorrectionDisabled()
                            .textFieldStyle(.roundedBorder)
                            .submitLabel(.go)
                            .focused($focusedField, equals: .secret)
                            .onSubmit { connect() }
                            .accessibilityLabel("Pairing secret")
                            .accessibilityHint("The EARMARK_BUS_SECRET value set on the hub")
                    }

                    Button {
                        connect()
                    } label: {
                        Text("Connect")
                            .font(.title2.bold())
                            .frame(maxWidth: .infinity, minHeight: 64)
                    }
                    .buttonStyle(.borderedProminent)
                    .disabled(!model.canConnect)
                    .accessibilityHint(connectHint)
                }
                .padding()
            }
            .navigationTitle("Earmark UWB")
        }
    }

    private var connectHint: String {
        guard let role = model.selectedRole else { return "Choose this iPhone's job first" }
        return "Starts \(role.label)"
    }

    private func connect() {
        focusedField = nil
        model.connect()
    }

    private func roleButton(_ role: DeviceRole) -> some View {
        let selected = model.selectedRole == role
        return Button {
            model.selectedRole = role
        } label: {
            HStack(spacing: 16) {
                Image(systemName: role.isAnchor ? "dot.radiowaves.left.and.right" : "figure.walk")
                    .font(.title)
                    .frame(width: 44)
                    .accessibilityHidden(true)
                Text(role.label)
                    .font(.title2.bold())
                    .multilineTextAlignment(.leading)
                Spacer(minLength: 0)
                if selected {
                    Image(systemName: "checkmark.circle.fill")
                        .font(.title)
                        .accessibilityHidden(true)
                }
            }
            .padding()
            .frame(maxWidth: .infinity, minHeight: 76, alignment: .leading)
            .contentShape(Rectangle())
            .background(
                RoundedRectangle(cornerRadius: 16)
                    .fill(selected ? Color.accentColor.opacity(0.18) : Color(.secondarySystemBackground))
            )
            .overlay(
                RoundedRectangle(cornerRadius: 16)
                    .stroke(selected ? Color.accentColor : Color.clear, lineWidth: 3)
            )
        }
        .buttonStyle(.plain)
        .accessibilityLabel(role.label)
        .accessibilityHint(role.isAnchor ? "Fixed anchor phone" : "The phone the user holds while walking")
        .accessibilityAddTraits(selected ? [.isSelected] : [])
    }
}
