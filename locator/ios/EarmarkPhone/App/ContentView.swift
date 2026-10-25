import SwiftUI

struct ContentView: View {
    @StateObject private var model = PhoneModel()

    var body: some View {
        NavigationStack {
            Group {
                if model.running {
                    if model.role == .selfTimed { selfTimedRunningView } else { runningView }
                } else {
                    setupView
                }
            }
            .padding(20)
            .navigationTitle("Earmark Phone")
        }
    }

    private var setupView: some View {
        Form {
            Section("What is this phone?") {
                Picker("Role", selection: $model.role) {
                    Text("The user's phone").tag(PhoneRole.user)
                    Text("A beacon").tag(PhoneRole.beacon)
                    Text("Beacon (no Mac)").tag(PhoneRole.selfTimed)
                }
                .pickerStyle(.inline)
                .labelsHidden()
                if model.role == .beacon {
                    Stepper("Beacon number \(model.beaconNumber)", value: $model.beaconNumber, in: 1...5)
                }
                if model.role == .selfTimed {
                    Stepper("Beacon number \(model.beaconNumber)", value: $model.beaconNumber, in: 1...4)
                }
            }
            if model.role == .selfTimed {
                Section("Chirp") {
                    Picker("Band", selection: $model.bandPreset) {
                        ForEach(bandPresets.indices, id: \.self) { i in Text(bandPresets[i].name).tag(i) }
                    }
                    VStack(alignment: .leading) {
                        Text("Volume \(String(format: "%.2f", model.volume))")
                        Slider(value: $model.volume, in: 0.1...1.0, step: 0.05) { Text("Volume") }
                    }
                    Text("Chirps every 0.5 s on this phone's own clock, in slot \(model.beaconNumber) (\(String(format: "%.3f", model.slotPhase)) s into each cycle). No Mac address or Wi-Fi needed.")
                        .font(.footnote).foregroundStyle(.secondary)
                }
            } else {
                Section("The Mac") {
                    TextField("some-words.trycloudflare.com", text: $model.server)
                        #if os(iOS)
                        .keyboardType(.URL)
                        .textInputAutocapitalization(.never)
                        #endif
                        .autocorrectionDisabled()
                    Text("Type the name the Mac prints when you run make session TUNNEL=1. On a Wi-Fi that lets phones reach the Mac, its address like 192.168.1.20:8766 works too.")
                        .font(.footnote).foregroundStyle(.secondary)
                }
            }
            Section {
                Button("Start") { model.start() }
                    .font(.title2.bold())
                if let p = model.problem { Text(p).foregroundStyle(.red) }
            } footer: {
                Text("Turn the volume all the way up and leave the screen on. Beacon phones should lie flat or stand up with the speaker facing the room.")
            }
        }
    }

    private var runningView: some View {
        VStack(alignment: .leading, spacing: 18) {
            Text(model.roleName).font(.largeTitle.bold())
            Label(model.status, systemImage: model.status == "Connected" ? "checkmark.circle.fill" : "arrow.triangle.2.circlepath")
                .font(.title3)
                .foregroundStyle(model.status == "Connected" ? .green : .orange)
            if !model.chirpBand.isEmpty { Text("Chirp band: \(model.chirpBand)").foregroundStyle(.secondary) }
            Text("Chirps played: \(model.chirps)")
            VStack(alignment: .leading) {
                Text("Microphone")
                ProgressView(value: Double(min(model.level * 8, 1)))
            }
            if model.isUser {
                if let f = model.fix {
                    VStack(alignment: .leading, spacing: 4) {
                        Text("You are at").font(.headline)
                        Text(String(format: "x %.2f   y %.2f   z %.2f meters", f.x, f.y, f.z)).font(.title3.monospaced())
                        Text("\(f.quality), using \(f.used) beacons").foregroundStyle(f.quality == "ok" ? .green : .orange)
                    }
                } else {
                    Text("Waiting for the first position...").foregroundStyle(.secondary)
                }
            }
            if let p = model.problem { Text(p).foregroundStyle(.red) }
            Spacer()
            Button("Play test sweep") { model.testSweep() }.buttonStyle(.bordered)
            Button("Stop", role: .destructive) { model.stop() }.buttonStyle(.borderedProminent)
        }
    }

    private var selfTimedRunningView: some View {
        VStack(alignment: .leading, spacing: 18) {
            Text("Beacon \(model.beaconNumber)").font(.largeTitle.bold())
            Label(model.status, systemImage: model.status == "Chirping" ? "speaker.wave.3.fill" : "arrow.triangle.2.circlepath")
                .font(.title3)
                .foregroundStyle(model.status == "Chirping" ? .green : .orange)
            Text("Chirping every 0.5 s, slot \(String(format: "%.3f", model.slotPhase)) s")
            if let t = model.firstChirpAt {
                Text("First chirp at \(t.formatted(date: .omitted, time: .standard))").foregroundStyle(.secondary)
            }
            Text("Chirps played: \(model.chirps)").font(.title2.monospacedDigit())
            Text("Band: \(model.chirpBand)").foregroundStyle(.secondary)
            Text("Volume \(String(format: "%.2f", model.volume))").foregroundStyle(.secondary)
            GroupBox {
                VStack(alignment: .leading, spacing: 6) {
                    Label("Volume all the way up", systemImage: "speaker.plus")
                    Label("Bottom edge toward the room", systemImage: "iphone")
                    Label("Screen on; do not lock the phone", systemImage: "sun.max")
                    Label("No Wi-Fi or Mac needed", systemImage: "wifi.slash")
                }
                .font(.callout)
            }
            if let p = model.problem { Text(p).foregroundStyle(.red) }
            Spacer()
            Button("Stop", role: .destructive) { model.stop() }.buttonStyle(.borderedProminent)
        }
    }
}
