import SwiftUI
import UniformTypeIdentifiers
import EarmarkCore

struct RootView: View {
    @StateObject private var model = LocatorModel()
    @Environment(\.scenePhase) private var phase
    @State private var selectedTab = RootView.initialTab()
    private static func initialTab() -> String {
        #if DEBUG
        let requested = ProcessInfo.processInfo.environment["EARMARK_INITIAL_TAB"] ?? "Run"
        return ["Run", "Debug", "Calibrate", "Manual", "Settings"].contains(requested) ? requested : "Run"
        #else
        return "Run"
        #endif
    }
    var body: some View {
        VStack(spacing: 0) {
            if model.manual { Text("MANUAL MODE — testing only").font(.headline).padding().frame(maxWidth: .infinity).background(.yellow).foregroundStyle(.black) }
            TabView(selection: $selectedTab) {
                NavigationStack { RunView(model: model) }.tabItem { Label("Run", systemImage: "location.fill") }.tag("Run")
                NavigationStack { DebugView(model: model) }.tabItem { Label("Debug", systemImage: "waveform") }.tag("Debug")
                NavigationStack { CalibrationView(model: model) }.tabItem { Label("Calibrate", systemImage: "ruler") }.tag("Calibrate")
                NavigationStack { ManualView(model: model) }.tabItem { Label("Manual", systemImage: "hand.draw") }.tag("Manual")
                NavigationStack { SettingsView(model: model) }.tabItem { Label("Settings", systemImage: "gearshape") }.tag("Settings")
            }
        }
        .alert("Action needed", isPresented: Binding(get: { model.error != nil }, set: { if !$0 { model.error = nil } })) {
            Button("OK", role: .cancel) { model.error = nil }
        } message: { Text(model.error ?? "") }
        .onChange(of: phase) { _, newValue in if newValue == .background { model.stop() } }
    }
}

struct RunView: View {
    @ObservedObject var model: LocatorModel
    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 24) {
                Text(model.status).font(.largeTitle.bold()).accessibilityAddTraits(.updatesFrequently)
                if model.sessionState == .starting { ProgressView("Requesting microphone permission") }
                PositionReadout(position: model.ear, title: "Ear position · meters")
                BeaconIndicators(beacons: model.config.beacons, detections: model.detections)
                LabeledContent("Fixes per second", value: String(format: "%.1f", model.fixRate))
                LabeledContent("Hub", value: model.hub.state)
                LabeledContent("Input", value: model.route)
                if model.quality == .lost { Text("No valid fix. Keep the bottom microphone uncovered, face into the room, and check beacon power.").font(.headline) }
                Text(model.notice).foregroundStyle(.secondary)
                Button(model.running ? "Stop locator" : "Start locator") { model.running ? model.stop() : model.start() }
                    .buttonStyle(.borderedProminent).controlSize(.large).disabled(model.sessionState == .starting)
                Button(model.ptt ? "Stop push to talk" : "Start push to talk") { model.setPTT(!model.ptt) }
                    .font(.title2.bold()).frame(maxWidth: .infinity, minHeight: 72)
                    .buttonStyle(.borderedProminent).tint(model.ptt ? .red : .blue)
                    .disabled(model.sessionState != .microphone)
                    .accessibilityHint("Backup button. Activate once to start, again to stop. Positioning continues while speaking.")
                Text("The phone plays no audio. Connect AirPods to the Mac, not the phone.").font(.footnote)
            }.padding()
        }.navigationTitle("Earmark Locator")
    }
}

struct PositionReadout: View {
    let position: Vector3
    let title: String
    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            Text(title).font(.headline)
            Text(String(format: "x %.2f   y %.2f   z %.2f", position.x, position.y, position.z))
                .font(.title2.monospacedDigit()).minimumScaleFactor(0.7)
                .accessibilityLabel(String(format: "Right %.2f, forward %.2f, up %.2f meters", position.x, position.y, position.z))
        }
    }
}
struct BeaconIndicators: View {
    let beacons: [Beacon]
    let detections: [Arrival]
    var body: some View {
        LazyVGrid(columns: [GridItem(.adaptive(minimum: 85))], spacing: 12) {
            ForEach(beacons) { beacon in
                let detection = detections.first { $0.beacon == beacon.id }
                VStack {
                    Label(beacon.id, systemImage: detection == nil ? "circle.dashed" : "checkmark.circle.fill")
                    Text(detection.map { String(format: "SNR %.1f", $0.snr) } ?? "Not heard").font(.caption)
                }.padding(8).background(.quaternary, in: RoundedRectangle(cornerRadius: 10))
                    .accessibilityElement(children: .combine)
            }
        }
    }
}

struct DebugView: View {
    @ObservedObject var model: LocatorModel
    @ObservedObject private var hub: HubConnection
    @State private var importing = false
    init(model: LocatorModel) { self.model = model; hub = model.hub }
    var body: some View {
        Form {
            Section("Signal") {
                ForEach(model.config.beacons) { beacon in
                    VStack(alignment: .leading) {
                        Text(beacon.id).font(.headline)
                        Sparkline(values: model.history[beacon.id] ?? []).frame(height: 52)
                            .accessibilityLabel("\(beacon.id) SNR history")
                            .accessibilityValue(model.detections.first(where: { $0.beacon == beacon.id }).map { String(format: "Current SNR %.1f", $0.snr) } ?? "Not heard")
                    }
                }
                LabeledContent("Residual RMS", value: String(format: "%.3f ms", model.residual))
                LabeledContent("Cycle lock", value: model.lock.rawValue)
                ForEach(model.detections, id: \.beacon) { detection in
                    LabeledContent("\(detection.beacon) arrival", value: String(format: "%.6f s", detection.arrival))
                }
                if model.detections.isEmpty { Text("No detections yet. Start the locator or run a simulator WAV.") }
            }
            Section("Audio clock") {
                LabeledContent("Route", value: model.route)
                LabeledContent("Actual rate", value: String(format: "%.0f Hz", model.actualRate))
                LabeledContent("Delivered buffer", value: "\(model.frames) frames (requested 2400)")
                LabeledContent("Discontinuities", value: "\(model.dropped)")
                Toggle("Record raw microphone + log", isOn: Binding(get: { model.recording }, set: { model.setRecording($0) }))
                    .disabled(model.sessionState != .microphone)
            }
            Section("File input and export") {
                Button("Run on file") { importing = true }
                Text("Select a mono, 16-bit PCM WAV. Processing runs in real time and exports fixes.jsonl with source sim.")
                if let progress = model.progress, model.sessionState == .file { ProgressView("Processing WAV", value: progress) }
                if model.files.isEmpty { Text("Stop a recording or finish file input to export files.").foregroundStyle(.secondary) }
                ForEach(model.files, id: \.self) { url in ShareLink(item: url) { Label(url.lastPathComponent, systemImage: "square.and.arrow.up") } }
            }
            Section("Sent message rates — no contents logged") {
                LabeledContent("Connection", value: hub.state)
                ForEach(hub.rates.keys.sorted(), id: \.self) { type in LabeledContent(type, value: String(format: "%.1f / s", hub.rates[type] ?? 0)) }
                if hub.rates.isEmpty { Text("No messages sent yet. Configure a hub in Settings.") }
                Button("Reconnect hub") { hub.connect(config: model.config) }
            }
        }.navigationTitle("Debug")
            .fileImporter(isPresented: $importing, allowedContentTypes: [.wav]) { result in
                switch result { case .success(let url): model.runFile(url); case .failure(let error): model.error = error.localizedDescription }
            }
    }
}
struct Sparkline: View {
    let values: [Double]
    var body: some View {
        GeometryReader { geometry in
            if values.isEmpty { Text("Waiting for audio").foregroundStyle(.secondary) }
            else {
                Path { path in
                    let maximum = max(10, values.max() ?? 10)
                    for (index, value) in values.enumerated() {
                        let point = CGPoint(x: Double(index) / Double(max(1, values.count - 1)) * geometry.size.width,
                                            y: (1 - min(value / maximum, 1)) * geometry.size.height)
                        if index == 0 { path.move(to: point) } else { path.addLine(to: point) }
                    }
                }.stroke(.primary, lineWidth: 2)
            }
        }
    }
}
