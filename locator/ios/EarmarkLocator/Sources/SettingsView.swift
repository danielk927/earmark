import SwiftUI
import EarmarkCore

struct SettingsView: View {
    @ObservedObject var model: LocatorModel
    @State private var draft = LocatorConfig()
    @State private var chirpJSON = ""
    @State private var settingsJSON = ""
    @State private var problem: String?
    @State private var importing = false
    var body: some View {
        Form {
            Section("Mac hub") {
                TextField("ws://mac-ip:8765/ws", text: $draft.hub_url).textInputAutocapitalization(.never).autocorrectionDisabled().keyboardType(.URL)
                    .accessibilityLabel("Hub WebSocket URL")
                Picker("Protocol", selection: $draft.hub_auth_mode) {
                    Text("Native hub · no token").tag(HubAuth.native)
                    Text("Contract · query token").tag(HubAuth.query)
                    Text("Contract · hello token").tag(HubAuth.hello)
                }
                SecureField("Shared token (contract modes only)", text: $draft.hub_token).disabled(draft.hub_auth_mode == .native)
                Text("Native mode sends hello with role sensor and name locator, then pos-only pose plus listener_pose. The current Mac hub does not handle mic_audio or ptt yet.").font(.footnote)
            }
            Section("Carry mode and environment") {
                Picker("Phone placement", selection: $draft.mode) {
                    Text("Hand · upright at chest").tag(CarryMode.hand)
                    Text("Shirt pocket · upside down").tag(CarryMode.pocket)
                }
                NumberField(title: "Air temperature °C · default 22", value: $draft.air_temperature)
                NumberField(title: "Preferred sample rate · default 48000", value: $draft.fs)
                Text("Mode selects the height prior and ear offset below. Pants pockets are not supported.")
            }
            Section("Chirp · defaults 2000–4500 Hz, 12 ms, 50 ms slots") {
                NumberField(title: "Low frequency Hz", value: $draft.chirp.f_lo)
                NumberField(title: "High frequency Hz", value: $draft.chirp.f_hi)
                NumberField(title: "Length ms", value: $draft.chirp.length_ms)
                NumberField(title: "Slot ms", value: $draft.chirp.slot_ms)
                Text("Six slots, B1 falling, B2–B5 rising. Match firmware config exactly; choose band using the band test.")
                TextEditor(text: $chirpJSON).frame(minHeight: 90).font(.system(.caption, design: .monospaced)).accessibilityLabel("Paste chirp config JSON")
                Button("Apply pasted chirp to draft") { applyChirp() }
            }
            Section("Detection · defaults shown") {
                NumberField(title: "Gate ms · 3.0", value: $draft.gate_ms)
                NumberField(title: "Lookback ms · 2.0", value: $draft.lookback_ms)
                NumberField(title: "Minimum SNR · 8", value: $draft.snr_min)
                NumberField(title: "Acquisition SNR · 10", value: $draft.snr_acquire)
                NumberField(title: "Max residual ms · 0.30", value: $draft.resid_max_ms)
                NumberField(title: "OK residual ms · 0.15", value: $draft.resid_ok_ms)
                NumberField(title: "Lost timeout seconds · 1.5", value: $draft.lost_timeout)
            }
            Section("Height prior · meters") {
                NumberField(title: "Hand mean · 1.25", value: $draft.height_hand.mean)
                NumberField(title: "Hand sigma · 0.25", value: $draft.height_hand.sigma)
                NumberField(title: "Pocket mean · 1.30", value: $draft.height_pocket.mean)
                NumberField(title: "Pocket sigma · 0.20", value: $draft.height_pocket.sigma)
            }
            Section("Ear offset · meters") {
                VectorEditor(title: "Hand · default [0, 0, 0.35]", value: $draft.ear_offset_hand)
                VectorEditor(title: "Pocket · default [0, 0, 0.30]", value: $draft.ear_offset_pocket)
            }
            Section("Kalman filter") {
                NumberField(title: "Acceleration sigma m/s² · 1.5", value: $draft.kalman_acceleration_sigma)
                NumberField(title: "OK measurement sigma m · 0.05", value: $draft.kalman_measurement_sigma_ok)
                NumberField(title: "Degraded measurement sigma m · 0.15", value: $draft.kalman_measurement_sigma_degraded)
            }
            Section("Push-to-talk speech") {
                HStack {
                    Text("Sample rate · default 16000")
                    TextField("Speech sample rate", value: $draft.mic_audio_sample_rate, format: .number).keyboardType(.numberPad).multilineTextAlignment(.trailing)
                        .accessibilityLabel("Speech sample rate")
                }
                Text("40 ms chunks, mono s16le. Sequence resets to zero each turn. Confirm the sample rate with the hub team.")
            }
            Section("Import and export") {
                Button("Import beacon config / full space.json") { importing = true }
                Text("Current geometry: \(draft.beacons.count) beacons. Use Calibrate to edit individual positions.")
                Button("Export all settings to clipboard") { export() }
                Text("Export includes the shared token. Share only with your demo team.").font(.footnote)
                TextEditor(text: $settingsJSON).frame(minHeight: 100).font(.system(.caption, design: .monospaced)).accessibilityLabel("Paste all settings JSON")
                Button("Import pasted settings to draft") { importSettings() }
            }
            Section {
                if let problem { Text(problem).foregroundStyle(.red).accessibilityLabel("Validation error: \(problem)") }
                Button("Save and apply settings") { save() }.buttonStyle(.borderedProminent)
                Text("Saving stops the current session and reconnects the hub. Start again to reacquire. Invalid settings are never applied.")
            }
        }.navigationTitle("Settings")
            .onAppear { draft = model.config }
            .fileImporter(isPresented: $importing, allowedContentTypes: [.json]) { result in
                do {
                    let url = try result.get(); let scoped = url.startAccessingSecurityScopedResource()
                    defer { if scoped { url.stopAccessingSecurityScopedResource() } }
                    draft.beacons = try Beacon.importing(Data(contentsOf: url)); problem = nil
                } catch { problem = error.localizedDescription }
            }
    }
    private func applyChirp() {
        do { let value = try JSONDecoder().decode(ChirpConfig.self, from: Data(chirpJSON.utf8)); try value.validate(); draft.chirp = value; problem = nil }
        catch { problem = error.localizedDescription }
    }
    private func importSettings() {
        do { draft = try LocatorConfig.importing(Data(settingsJSON.utf8)); problem = nil }
        catch { problem = error.localizedDescription }
    }
    private func export() {
        do { UIPasteboard.general.string = String(decoding: try draft.exported(), as: UTF8.self); problem = nil }
        catch { problem = error.localizedDescription }
    }
    private func save() {
        do { try model.applySettings(draft); problem = nil }
        catch { problem = error.localizedDescription }
    }
}
