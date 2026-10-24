import SwiftUI

struct ContentView: View {
    @StateObject private var model = PhoneModel()

    var body: some View {
        NavigationStack {
            Group {
                if model.running { runningView } else { setupView }
            }
            .padding(20)
            .navigationTitle("Earmark Phone")
        }
    }

    private var setupView: some View {
        Form {
            Section("What is this phone?") {
                Picker("Role", selection: $model.isUser) {
                    Text("The user's phone").tag(true)
                    Text("A beacon").tag(false)
                }
                .pickerStyle(.segmented)
                if !model.isUser {
                    Stepper("Beacon number \(model.beaconNumber)", value: $model.beaconNumber, in: 1...5)
                }
            }
            Section("The Mac") {
                TextField("192.168.1.20:8766", text: $model.server)
                    #if os(iOS)
                    .keyboardType(.numbersAndPunctuation)
                    .textInputAutocapitalization(.never)
                    #endif
                    .autocorrectionDisabled()
                Text("The Mac shows this address when you run make ranging.")
                    .font(.footnote).foregroundStyle(.secondary)
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
}
