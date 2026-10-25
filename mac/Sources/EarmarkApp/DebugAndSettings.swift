import EarmarkAudio
import EarmarkContracts
import EarmarkUI
import SwiftUI

/// Collapsible debug panel: head numbers, guidance math, latency, concierge (Moss/LLM) status, last bus messages.
struct DebugPanel: View {
    @ObservedObject var m: AppModel
    @ObservedObject var pose: PoseModel

    var body: some View {
        let core = m.core
        let g = pose.guidance
        ScrollView {
            VStack(alignment: .leading, spacing: 16) {
                Card("Head and guidance") {
                    Grid(alignment: .leading, horizontalSpacing: 18, verticalSpacing: 5) {
                        row("Yaw / pitch", "\(signedDegrees(pose.yaw, decimals: 1)) / \(signedDegrees(pose.pitch, decimals: 1))")
                        row("Motion rate", String(format: "%.0f Hz (%@)", pose.rateHz, core.head.state.rawValue))
                        row("Target az / el", g.map { "\(signedDegrees($0.targetAzimuthDeg, decimals: 1)) / \(signedDegrees($0.targetElevationDeg, decimals: 1))" } ?? "-")
                        row("Angle error", g.map { signedDegrees($0.errorDeg, decimals: 1) } ?? "-")
                        row("Ping interval", g.map { String(format: "%.0f ms", $0.pingIntervalSec * 1000) } ?? "-")
                        row("Zone / locked", g.map { "\($0.zone.rawValue) / \($0.locked ? "yes" : "no")" } ?? "-")
                        row("Last feedback", core.lastFeedback.map { "\($0.event.rawValue)\($0.turn.map { " " + $0.rawValue } ?? "")" } ?? "-")
                        row("Listener x / y", String(format: "%+.2f / %+.2f m", pose.listener.x, pose.listener.y))
                        row("Listener pose", core.listenerPose.map { p in
                            "\(p.mode.rawValue), \(p.source.rawValue), \(p.anchorsUsed) anchors" + (p.residualM.map { String(format: ", res %.2f m", $0) } ?? "")
                        } ?? "none (origin)")
                        row("Target distance", g.map { String(format: "%.2f m", $0.distanceM) } ?? "-")
                    }
                }
                Card("Audio") {
                    Grid(alignment: .leading, horizontalSpacing: 18, verticalSpacing: 5) {
                        row("Renderer", core.renderer?.kind.rawValue ?? "none")
                        row("Output latency", String(format: "%.0f ms", (core.renderer?.presentationLatency ?? 0) * 1000))
                        row("Output rate", kHz(core.devices.outputSampleRate))
                        row("Ducked", core.isSpeaking ? "yes (speech playing)" : "no")
                        row("Mic level", m.flags.noMic ? "off" : String(format: "%.0f dBFS (open at %.0f)", m.micLevelDb, m.micThresholdDb))
                        row("STT", "\(core.effectiveSttEngine) (\(core.sttReason))")
                        row("Apple Speech", m.appleStatus ?? "idle")
                    }
                }
                Card("Concierge and bus") {
                    VStack(alignment: .leading, spacing: 6) {
                        ForEach(core.componentStatus.keys.sorted(), id: \.self) { k in
                            let s = core.componentStatus[k]!
                            Text("\(k): \(s.ok ? "ok" : "NOT OK") - \(s.detail)\(infoText(s))")
                                .font(.system(size: 12).monospaced())
                                .foregroundStyle(s.ok ? Theme.textPrimary : Theme.bad)
                                .lineLimit(2)
                        }
                        if core.componentStatus.isEmpty {
                            Text("No status from the concierge or hub yet")
                                .font(.system(size: 12))
                                .foregroundStyle(Theme.textSecondary)
                        }
                        Divider().overlay(Theme.border)
                        ForEach(Array(core.recentMessages.suffix(9).enumerated()), id: \.offset) { _, line in
                            Text(line)
                                .font(.system(size: 12).monospaced())
                                .foregroundStyle(Theme.textSecondary)
                                .lineLimit(1)
                        }
                    }
                }
            }
        }
        .scrollIndicators(.never)
        .accessibilityElement(children: .contain)
        .accessibilityLabel("Debug panel")
    }

    private func infoText(_ s: Status) -> String {
        guard let info = s.info, !info.isEmpty else { return "" }
        let pairs = info.keys.sorted().prefix(4).map { k -> String in
            switch info[k]! {
            case .string(let v): "\(k)=\(v)"
            case .number(let v): "\(k)=\(v)"
            case .bool(let v): "\(k)=\(v)"
            case .null: "\(k)=null"
            }
        }
        return " [" + pairs.joined(separator: ", ") + "]"
    }

    private func row(_ k: String, _ v: String) -> some View {
        GridRow {
            Text(k)
                .font(.system(size: 12, weight: .medium))
                .foregroundStyle(Theme.textSecondary)
            Text(v)
                .font(.system(size: 13, weight: .semibold).monospacedDigit())
                .foregroundStyle(Theme.textPrimary)
                .lineLimit(1)
        }
        .accessibilityElement(children: .combine)
    }
}

struct SettingsView: View {
    @ObservedObject var m: AppModel
    @Environment(\.dismiss) private var dismiss
    @State private var showCalibration = false

    var body: some View {
        VStack(alignment: .leading, spacing: 18) {
            Text("Settings")
                .font(.system(size: 24, weight: .bold))
                .foregroundStyle(Theme.textPrimary)
            Form {
                Section("Listening") {
                    Picker("Mode", selection: $m.listenMode) {
                        ForEach(ListenMode.allCases) { Text($0.displayName).tag($0) }
                    }
                    .pickerStyle(.radioGroup)
                    Text("Push to talk is the default: the judging hall is loud, and Cartesia bills every second of streamed audio. Always listening streams only while the voice detector hears speech, plus 1 s.")
                        .font(.system(size: 12))
                        .foregroundStyle(Theme.textSecondary)
                        .fixedSize(horizontal: false, vertical: true)
                }
                Section("Audio routing") {
                    Toggle("Keep the system input on the built-in microphone", isOn: $m.enforceBuiltInMic)
                    Text("If the system input is the AirPods microphone, macOS drops the AirPods into hands-free mode, which destroys spatial audio. With this on, Earmark switches the system input back to the built-in mic whenever that happens, and says so on screen.")
                        .font(.system(size: 12))
                        .foregroundStyle(Theme.textSecondary)
                        .fixedSize(horizontal: false, vertical: true)
                }
                Section("Spatial renderer") {
                    Picker("Renderer", selection: $m.rendererChoice) {
                        ForEach(RendererKind.selectable) { Text($0.displayName).tag($0) }
                    }
                    Picker("Ping timbre", selection: $m.timbre) {
                        ForEach(PingTimbre.allCases) { Text($0.displayName).tag($0) }
                    }
                    Text("If the chosen renderer cannot start, Earmark falls back to stereo panning, then to speech only.")
                        .font(.system(size: 12))
                        .foregroundStyle(Theme.textSecondary)
                }
                Section("Head tracking") {
                    Toggle("Mock head (no AirPods)", isOn: $m.mockHead)
                    Text("Bus: \(m.busURL)")
                        .font(.system(size: 12).monospaced())
                        .foregroundStyle(Theme.textSecondary)
                }
                Section("Walking guidance (UWB)") {
                    Button("Calibrate UWB anchors...") { showCalibration = true }
                        .accessibilityHint("Opens the anchor measurements, position check, and save to space.json")
                    tuning("Listener glide", value: $m.listenerGlideSec, range: 0...1, step: 0.05, unit: "s",
                           help: "How long the sound glides to each new position (hub blend_s, default 0.4 s). Lower follows a walk more tightly.")
                    tuning("Full volume within", value: $m.attenuation.referenceDistance, range: 0.2...2, step: 0.1, unit: "m",
                           help: "Cues closer than this are not attenuated (default 0.6 m, so the seated demo sounds the same).")
                    tuning("No quieter beyond", value: $m.attenuation.maximumDistance, range: 2...20, step: 0.5, unit: "m",
                           help: "Default 8 m.")
                    tuning("Rolloff", value: $m.attenuation.rolloffFactor, range: 0...3, step: 0.1, unit: "",
                           help: "How fast the cue gets quieter with distance (default 1, 0 = no distance cue). PHASE applies a change when the renderer is next built.")
                }
            }
            .formStyle(.grouped)
            HStack {
                Spacer()
                Button("Done") { dismiss() }
                    .keyboardShortcut(.defaultAction)
            }
        }
        .padding(24)
        .frame(width: 560, height: 720)
        .background(Theme.background)
        .sheet(isPresented: $showCalibration) { CalibrationView(m: m, cal: m.calibration) }
    }

    /// A labeled slider with its value in words for VoiceOver.
    private func tuning(_ title: String, value: Binding<Double>, range: ClosedRange<Double>, step: Double,
                        unit: String, help: String) -> some View {
        VStack(alignment: .leading, spacing: 4) {
            HStack {
                Text(title)
                Spacer()
                Text(String(format: "%.2f", value.wrappedValue) + (unit.isEmpty ? "" : " " + unit))
                    .font(.system(size: 13).monospacedDigit())
                    .foregroundStyle(Theme.textSecondary)
                    .accessibilityHidden(true)
            }
            Slider(value: value, in: range, step: step)
                .accessibilityLabel(title)
                .accessibilityValue(String(format: "%.2f", value.wrappedValue) + (unit.isEmpty ? "" : " " + unit))
            Text(help)
                .font(.system(size: 12))
                .foregroundStyle(Theme.textSecondary)
                .fixedSize(horizontal: false, vertical: true)
        }
    }
}
