import SwiftUI
import EarmarkCore

struct CalibrationView: View {
    @ObservedObject var model: LocatorModel
    @State private var editing = false
    @State private var label = ""
    @State private var mark = Vector3.zero
    private var heightSpread: Double {
        let heights = model.config.beacons.map(\.position.z)
        return (heights.max() ?? 0) - (heights.min() ?? 0)
    }
    var body: some View {
        Form {
            Section("1 · Beacon positions") {
                Text("Origin: floor below mat center. +x right, +y tape arrow, +z up. Measure in meters.")
                RoomMap(beacons: model.config.beacons, position: model.mic).frame(height: 220)
                ForEach(model.config.beacons) { beacon in
                    LabeledContent(beacon.id, value: String(format: "%.2f, %.2f, %.2f m", beacon.position.x, beacon.position.y, beacon.position.z))
                }
                Text(heightSpread < 0.5 ? "WARNING: beacon heights span less than 0.5 m. Use different heights." : "PASS: beacon heights span at least 0.5 m.")
                Button("Edit or import beacon positions") { editing = true }
            }
            Section("2 · Capture templates") {
                Text("Run all five beacons. Hold the bottom edge about 10 cm from the selected beacon. Stay still for 10 cycles (at least 3 seconds). Keep B1 audible so slots can be identified.")
                ForEach(model.config.beacons) { beacon in templateRow(beacon) }
                if let beacon = model.captureBeacon { ProgressView("Capturing \(beacon)…") }
                if !model.running { Button("Start microphone") { model.start() } }
            }
            Section("3 · Verify on mat") {
                Text("Stand on the mat. Hold the phone at chest height. Target microphone position: [0, 0, 1.25] m.")
                if let mic = model.mic {
                    PositionReadout(position: mic, title: "Solved microphone")
                    Text(String(format: "Distance to target: %.2f m", (mic - Vector3(0, 0, 1.25)).norm))
                    Text(hypot(mic.x, mic.y) < 0.1 && (0.75...1.75).contains(mic.z) && model.quality != .lost ? "PASS: <10 cm horizontal error and plausible height" : "FAIL: check geometry, microphone, and templates")
                } else { Text("Waiting for a valid fix. Start capture and check the Run tab.") }
            }
            Section("4 · Optional taped mark") {
                VectorEditor(title: "Known microphone position at mark", value: $mark)
                if let mic = model.mic {
                    Text(String(format: "Current 3D error: %.1f cm", (mic - mark).norm * 100))
                } else { Text("Enter a measured mark, stand on it, and wait for tracking.") }
            }
            Section("5 · Save item point") {
                Text("Hold the bottom microphone where the item lives, still for at least 2 seconds. The saved point uses microphone position, not ear position. Standard deviation must be <2 cm.")
                TextField("Item label", text: $label)
                Button("Save point and copy JSON") { model.savePoint(label: label) }.disabled(label.isEmpty || !model.running)
                if model.savedPoints.isEmpty { Text("No item points saved yet.").foregroundStyle(.secondary) }
                ForEach(Array(model.savedPoints.enumerated()), id: \.offset) { _, point in
                    Button("Copy \(point.label)") { model.copyJSON(point) }
                }
                Button("Copy all saved points as JSON") { model.copyJSON(model.savedPoints) }.disabled(model.savedPoints.isEmpty)
            }
        }.navigationTitle("Calibrate")
            .sheet(isPresented: $editing) { BeaconEditor(model: model) }
    }
    @ViewBuilder private func templateRow(_ beacon: Beacon) -> some View {
        VStack(alignment: .leading) {
            if let captured = model.templates.first(where: { $0.beacon == beacon.id }) {
                Text("\(beacon.id): \(captured.copies)/10, SNR \(Int(captured.snr))")
                if captured.chirp != model.config.chirp || (model.actualRate > 0 && captured.fs != model.actualRate) {
                    Text("STALE: band or sample rate changed. Capture again.").foregroundStyle(.red)
                } else { Text("PASS").font(.headline) }
            } else { Text("\(beacon.id): synthesized template — capture recommended") }
            Button("Capture \(beacon.id)") { model.captureTemplate(beacon.id) }
                .disabled(model.captureBeacon != nil || model.sessionState != .microphone)
        }
    }
}

struct BeaconEditor: View {
    @ObservedObject var model: LocatorModel
    @Environment(\.dismiss) private var dismiss
    @State private var beacons = Beacon.defaults
    @State private var importing = false
    @State private var problem: String?
    var body: some View {
        NavigationStack {
            Form {
                Section { Text("Bare {beacons:[…]} and full space.json are both accepted; other keys are ignored.")
                    Button("Import beacon JSON") { importing = true }
                }
                ForEach($beacons) { $beacon in VectorEditor(title: beacon.id, value: $beacon.position) }
                if let problem { Text(problem).foregroundStyle(.red) }
            }.navigationTitle("Beacon positions")
                .toolbar {
                    ToolbarItem(placement: .cancellationAction) { Button("Cancel") { dismiss() } }
                    ToolbarItem(placement: .confirmationAction) { Button("Save") { save() } }
                }
                .onAppear { beacons = model.config.beacons }
                .fileImporter(isPresented: $importing, allowedContentTypes: [.json]) { result in
                    do {
                        let url = try result.get(); let scoped = url.startAccessingSecurityScopedResource()
                        defer { if scoped { url.stopAccessingSecurityScopedResource() } }
                        beacons = try Beacon.importing(Data(contentsOf: url)); problem = nil
                    } catch { problem = error.localizedDescription }
                }
        }
    }
    private func save() {
        do { var updated = model.config; updated.beacons = beacons; try model.applySettings(updated); dismiss() }
        catch { problem = error.localizedDescription }
    }
}
struct VectorEditor: View {
    let title: String
    @Binding var value: Vector3
    var body: some View {
        VStack(alignment: .leading) {
            Text(title).font(.headline)
            NumberField(title: "x · right", value: $value.x)
            NumberField(title: "y · forward", value: $value.y)
            NumberField(title: "z · up", value: $value.z)
        }
    }
}
struct NumberField: View {
    let title: String
    @Binding var value: Double
    var body: some View {
        HStack {
            Text(title)
            Spacer()
            TextField(title, value: $value, format: .number).multilineTextAlignment(.trailing)
                .keyboardType(.numbersAndPunctuation).accessibilityLabel(title)
        }
    }
}
struct RoomMap: View {
    let beacons: [Beacon]
    let position: Vector3?
    var body: some View {
        GeometryReader { proxy in
            let extent = max(2.2, beacons.flatMap { [abs($0.position.x), abs($0.position.y)] }.max() ?? 2.2)
            ZStack {
                Rectangle().fill(.quaternary)
                Text("MAT ↑ +y").font(.caption.bold()).position(point(.zero, size: proxy.size, extent: extent))
                ForEach(beacons) { beacon in
                    Text(beacon.id).font(.caption.bold()).padding(6).background(.blue, in: Circle()).foregroundStyle(.white)
                        .position(point(beacon.position, size: proxy.size, extent: extent))
                }
                if let position {
                    Image(systemName: "person.fill").font(.title).position(point(position, size: proxy.size, extent: extent))
                }
            }
        }.accessibilityElement(children: .ignore).accessibilityLabel("Top-down room map. Mat at center. Forward is up; right is right.")
    }
    private func point(_ position: Vector3, size: CGSize, extent: Double) -> CGPoint {
        CGPoint(x: size.width * (0.5 + position.x / (extent * 2.4)), y: size.height * (0.5 - position.y / (extent * 2.4)))
    }
}
struct ManualView: View {
    @ObservedObject var model: LocatorModel
    var body: some View {
        ScrollView {
            VStack(spacing: 24) {
                Text("TESTING ONLY").font(.title.bold())
                Text("Virtual ear position at 1.60 m. Maximum speed 1.2 m/s; sends at 5 Hz. Do not use this mode for blindfolded walking.")
                Toggle("Enable manual mode", isOn: Binding(get: { model.manual }, set: { model.setManual($0) }))
                RoomMap(beacons: model.config.beacons, position: model.manualEar).frame(height: 250)
                PositionReadout(position: model.manualEar, title: "Virtual ear · meters")
                Joystick(model: model).disabled(!model.manual)
                Button("Return to acoustic tracking") { model.setManual(false) }.disabled(!model.manual)
            }.padding()
        }.navigationTitle("Manual")
    }
}
struct Joystick: View {
    @ObservedObject var model: LocatorModel
    var body: some View {
        VStack {
            Button("Forward") { nudge(0, 1) }
            HStack {
                Button("Left") { nudge(-1, 0) }
                Circle().fill(.quaternary).frame(width: 150, height: 150)
                    .overlay(Image(systemName: "arrow.up.and.down.and.arrow.left.and.right").font(.largeTitle))
                    .gesture(DragGesture(minimumDistance: 0)
                        .onChanged { model.steer(x: $0.translation.width / 60, y: -$0.translation.height / 60) }
                        .onEnded { _ in model.steer(x: 0, y: 0) })
                    .accessibilityLabel("Walking joystick").accessibilityHint("Use the four direction buttons with VoiceOver.")
                Button("Right") { nudge(1, 0) }
            }
            Button("Back") { nudge(0, -1) }
        }.buttonStyle(.bordered).controlSize(.large)
    }
    private func nudge(_ x: Double, _ y: Double) {
        model.steer(x: x, y: y)
        Task {
            do { try await Task.sleep(nanoseconds: 250_000_000) }
            catch { model.steer(x: 0, y: 0); return }
            model.steer(x: 0, y: 0)
        }
    }
}
