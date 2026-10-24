import EarmarkAudio
import EarmarkUI
import SwiftUI

struct SpikeView: View {
    @ObservedObject var m: SpikeModel

    var body: some View {
        VStack(spacing: 16) {
            header
            if m.hfp || m.routingNotice != nil || m.rendererError != nil { banners }
            HStack(alignment: .top, spacing: 16) {
                headColumn.frame(width: 330)
                soundColumn.frame(maxWidth: .infinity)
                testColumn.frame(width: 400)
            }
            Spacer(minLength: 0)
        }
        .padding(20)
        .frame(minWidth: 1180, minHeight: 820)
        .background(Theme.background)
    }

    // MARK: Header

    private var header: some View {
        HStack(alignment: .center, spacing: 14) {
            VStack(alignment: .leading, spacing: 3) {
                Text("Earmark Spatial Spike")
                    .font(.system(size: 26, weight: .bold))
                    .foregroundStyle(Theme.textPrimary)
                Text("Phase 0.5 gate - no bus, no network")
                    .font(.system(size: 14))
                    .foregroundStyle(Theme.textSecondary)
            }
            Spacer()
            StatusPill(icon: "airpodspro", label: "HEAD TRACKING", value: headValue, severity: headSeverity).fixedSize()
            StatusPill(icon: "speaker.wave.2", label: "OUTPUT", value: "\(m.outputDevice) - \(rate(m.outputRate))",
                       severity: m.hfp ? .bad : (m.outputTransport.isBluetooth ? .ok : .warn)).fixedSize()
            StatusPill(icon: "timer", label: "LATENCY", value: String(format: "%.0f ms", m.latencyMs), severity: .neutral).fixedSize()
        }
    }

    private var headValue: String {
        m.headState == .connected ? String(format: "Tracking %.0f Hz", m.rateHz) : m.headState.displayName
    }

    private var headSeverity: Severity {
        switch m.headState {
        case .connected: .ok
        case .mock, .waiting: .warn
        default: .bad
        }
    }

    private var banners: some View {
        VStack(alignment: .leading, spacing: 8) {
            if m.hfp {
                Banner(severity: .bad, text: "\(m.outputDevice) is at \(rate(m.outputRate)): hands-free mode. Spatial cues are destroyed. Quit apps using the AirPods mic and reselect the AirPods as output.")
            }
            if let r = m.rendererError { Banner(severity: .bad, text: r) }
            if let n = m.routingNotice { Banner(severity: .warn, text: n) }
        }
    }

    // MARK: Head column

    private var headColumn: some View {
        VStack(spacing: 16) {
            Card("Head") {
                AngleDial(headYaw: m.yaw, target: m.testRunning ? nil : m.targetAzimuth, label: "Head direction")
                    .frame(height: 230)
                    .frame(maxWidth: .infinity)
                HStack(spacing: 0) {
                    Readout(label: "YAW", value: signedDegrees(m.yaw, decimals: 1))
                    Readout(label: "PITCH", value: signedDegrees(m.pitch, decimals: 1))
                    Readout(label: "ROLL", value: signedDegrees(m.roll, decimals: 1))
                }
                Text(m.headMessage)
                    .font(.system(size: 13))
                    .foregroundStyle(Theme.textSecondary)
                    .fixedSize(horizontal: false, vertical: true)
                Button { m.recenter() } label: {
                    Label("Recenter  (R)", systemImage: "scope")
                }
                .buttonStyle(BigButtonStyle())
                .accessibilityHint("Sets the current head direction as straight ahead")
            }
            Card("Virtual head") {
                Toggle("Mock head (no AirPods)", isOn: $m.mockHead)
                    .toggleStyle(.switch)
                    .font(.system(size: 14, weight: .medium))
                if let mock = m.mock {
                    MockHeadControls(mock: mock)
                } else {
                    Text("Real AirPods tracking. Turn on the mock head to test without AirPods.")
                        .font(.system(size: 13))
                        .foregroundStyle(Theme.textSecondary)
                }
            }
        }
    }

    // MARK: Sound column

    private let presets: [Double] = [-90, -45, 0, 45, 90, 180]

    private var soundColumn: some View {
        VStack(spacing: 16) {
            Card("Renderer") {
                Grid(horizontalSpacing: 8, verticalSpacing: 8) {
                    GridRow {
                        ForEach(RendererKind.selectable.prefix(2)) { k in rendererButton(k) }
                    }
                    GridRow {
                        ForEach(RendererKind.selectable.suffix(2)) { k in rendererButton(k) }
                    }
                }
                HStack(spacing: 8) {
                    Text("Ping timbre")
                        .font(.system(size: 14, weight: .medium))
                        .foregroundStyle(Theme.textSecondary)
                    ForEach(PingTimbre.allCases) { t in
                        Button(t.displayName) { m.timbre = t }
                            .buttonStyle(QuietButtonStyle(selected: m.timbre == t))
                            .accessibilityAddTraits(m.timbre == t ? .isSelected : [])
                    }
                }
            }
            Card("Place the ping (fixed in the room)") {
                HStack(spacing: 8) {
                    ForEach(presets, id: \.self) { a in
                        Button(a == 0 ? "0\u{00B0}" : signedDegrees(a)) { m.place(a) }
                            .buttonStyle(QuietButtonStyle(selected: !m.testRunning && m.targetAzimuth == a))
                            .disabled(m.testRunning)
                            .accessibilityLabel(presetLabel(a))
                    }
                }
                HStack(spacing: 8) {
                    Text("Height")
                        .font(.system(size: 14, weight: .medium))
                        .foregroundStyle(Theme.textSecondary)
                        .frame(width: 70, alignment: .leading)
                    ForEach([(0.0, "Ear level"), (-20.0, "-20\u{00B0}"), (-35.0, "Table, -35\u{00B0}")], id: \.0) { el, name in
                        Button(name) { m.elevation = el }
                            .buttonStyle(QuietButtonStyle(selected: m.elevation == el))
                            .accessibilityLabel("Height \(name)")
                    }
                }
                HStack(spacing: 12) {
                    Text("Interval")
                        .font(.system(size: 14, weight: .medium))
                        .foregroundStyle(Theme.textSecondary)
                        .frame(width: 70, alignment: .leading)
                    Slider(value: $m.intervalMs, in: 150...1_000, step: 50)
                        .disabled(m.guidanceRate)
                        .accessibilityLabel("Ping interval")
                        .accessibilityValue("\(Int(m.intervalMs)) milliseconds")
                    Text("\(Int(m.intervalMs)) ms")
                        .font(.system(size: 14, weight: .semibold).monospacedDigit())
                        .foregroundStyle(Theme.textPrimary)
                        .frame(width: 64, alignment: .trailing)
                }
                Toggle("Guidance rate: interval follows the angle error", isOn: $m.guidanceRate)
                    .toggleStyle(.switch)
                    .font(.system(size: 13))
                    .accessibilityHint("Always off during blind trials, where a fixed rate keeps the answer hidden")
                HStack(spacing: 8) {
                    Button { m.stopPing() } label: { Label("Stop", systemImage: "stop.fill") }
                        .buttonStyle(QuietButtonStyle())
                    Button { m.playOnce(.locked) } label: { Label("Locked tone", systemImage: "checkmark.seal") }
                        .buttonStyle(QuietButtonStyle())
                    Button { m.playOnce(.behind) } label: { Label("Behind cue", systemImage: "arrow.uturn.backward") }
                        .buttonStyle(QuietButtonStyle())
                }
                .disabled(m.testRunning)
                Text(pingStatus)
                    .font(.system(size: 15, weight: .semibold))
                    .foregroundStyle(m.pinging ? Theme.target : Theme.textSecondary)
                    .accessibilityLabel(pingStatus)
            }
            Card("Gate checks") {
                VStack(alignment: .leading, spacing: 8) {
                    Step(n: 1, text: "Sign check: place the ping at 0\u{00B0}, press R facing forward, turn your head LEFT. The ping must move to your RIGHT ear, and the yaw readout must go negative. Look up: pitch goes positive. If not, flip yawSign or pitchSign in HeadSigns.swift.")
                    Step(n: 2, text: "Fixed in room: ping at 0\u{00B0}, turn slowly 90\u{00B0} left and right. The ping must stay put in the room.")
                    Step(n: 3, text: "Pointing: run the blind test, 10 front trials per renderer (pass: 8 of 10 within 20\u{00B0}), plus 4 behind trials.")
                }
            }
        }
    }

    private func rendererButton(_ k: RendererKind) -> some View {
        Button(k.displayName) { m.rendererKind = k }
            .buttonStyle(QuietButtonStyle(selected: m.rendererKind == k))
            .accessibilityAddTraits(m.rendererKind == k ? .isSelected : [])
            .accessibilityHint("Switches the spatial renderer")
    }

    private func presetLabel(_ a: Double) -> String {
        switch a {
        case 0: "Place ping straight ahead"
        case 180: "Place ping behind"
        default: "Place ping \(Int(abs(a))) degrees \(a < 0 ? "left" : "right")"
        }
    }

    private var pingStatus: String {
        if m.testRunning { return "Blind trial running - target hidden" }
        guard m.pinging, let a = m.targetAzimuth else { return "Not pinging" }
        return "Pinging at \(signedDegrees(a)), height \(signedDegrees(m.elevation))"
    }

    // MARK: Test column

    private var testColumn: some View {
        VStack(spacing: 16) {
            Card("Blind pointing test") {
                HStack(spacing: 8) {
                    ForEach(TrialSet.allCases) { s in
                        Button(s == .front ? "Front half" : "Behind") { m.trialSet = s }
                            .buttonStyle(QuietButtonStyle(selected: m.trialSet == s))
                            .disabled(m.testRunning)
                    }
                }
                HStack {
                    Text("Tester")
                        .font(.system(size: 14, weight: .medium))
                        .foregroundStyle(Theme.textSecondary)
                    TextField("Pseudonym", text: $m.tester)
                        .textFieldStyle(.roundedBorder)
                        .frame(width: 110)
                        .accessibilityLabel("Tester pseudonym")
                    Spacer()
                    Text(m.sessionId.map { "Session \($0)" } ?? "No session")
                        .font(.system(size: 12).monospacedDigit())
                        .foregroundStyle(Theme.textSecondary)
                }
                AngleDial(headYaw: m.yaw, target: m.lastResult?.targetDeg, response: $m.response,
                          label: "Pointing dial. Click where the tester points.")
                    .frame(height: 210)
                    .frame(maxWidth: .infinity)
                HStack(spacing: 8) {
                    Text("Pointed at")
                        .font(.system(size: 14, weight: .medium))
                        .foregroundStyle(Theme.textSecondary)
                    Text(m.response.map { signedDegrees($0) } ?? "-")
                        .font(.system(size: 22, weight: .bold).monospacedDigit())
                        .foregroundStyle(Theme.textPrimary)
                        .frame(width: 70)
                    Stepper("Adjust response", value: Binding(get: { m.response ?? 0 }, set: { m.response = Angles.wrapDeg($0) }), step: 5)
                        .labelsHidden()
                        .accessibilityLabel("Adjust pointed angle by 5 degrees")
                    Spacer()
                }
                HStack(spacing: 8) {
                    Button(m.testRunning ? "Trial \(m.trialNumber) running" : "Next trial") { m.nextTrial() }
                        .buttonStyle(QuietButtonStyle(selected: !m.testRunning))
                        .disabled(m.testRunning)
                    Button("Record response") { m.recordResponse() }
                        .buttonStyle(QuietButtonStyle(selected: m.testRunning && m.response != nil))
                        .disabled(!m.testRunning || m.response == nil)
                }
                if let r = m.lastResult { ResultLine(trial: r) }
            }
            Card("Tally - \(m.rendererKind.displayName), \(m.timbre.rawValue)") {
                let t = m.tally
                Text(t.verdict)
                    .font(.system(size: 18, weight: .bold))
                    .foregroundStyle(t.passed == true ? Theme.ok : (t.passed == false ? Theme.bad : Theme.textPrimary))
                    .accessibilityLabel("Gate tally: \(t.verdict)")
                Text("Front trials \(t.frontTrials) - mean error \(t.meanAbsErrorDeg.map { String(format: "%.0f\u{00B0}", $0) } ?? "-") - behind trials \(t.behindTrials) - front/back confusions \(t.confusions)")
                    .font(.system(size: 13))
                    .foregroundStyle(Theme.textSecondary)
                    .fixedSize(horizontal: false, vertical: true)
                HStack {
                    Text("Log")
                        .font(.system(size: 13, weight: .medium))
                        .foregroundStyle(Theme.textSecondary)
                    TextField("logs/spatial_gate.jsonl", text: $m.logPath)
                        .textFieldStyle(.roundedBorder)
                        .font(.system(size: 12).monospaced())
                        .accessibilityLabel("Results log path, relative to the repo")
                }
                Text(m.resolvedLogURL.path)
                    .font(.system(size: 11).monospaced())
                    .foregroundStyle(Theme.textSecondary)
                    .lineLimit(1)
                    .truncationMode(.head)
                if let e = m.logError { Banner(severity: .bad, text: e) }
                Button("New session") { m.startSession() }
                    .buttonStyle(QuietButtonStyle())
                    .disabled(m.testRunning)
            }
        }
    }
}

private struct Readout: View {
    let label: String
    let value: String
    var body: some View {
        VStack(spacing: 2) {
            Text(label)
                .font(.system(size: 11, weight: .semibold))
                .tracking(0.8)
                .foregroundStyle(Theme.textSecondary)
            Text(value)
                .font(.system(size: 22, weight: .bold).monospacedDigit())
                .foregroundStyle(Theme.textPrimary)
        }
        .frame(maxWidth: .infinity)
        .accessibilityElement(children: .combine)
    }
}

private struct Step: View {
    let n: Int
    let text: String
    var body: some View {
        HStack(alignment: .firstTextBaseline, spacing: 10) {
            Text("\(n)")
                .font(.system(size: 13, weight: .bold))
                .foregroundStyle(Theme.background)
                .frame(width: 22, height: 22)
                .background(Theme.textSecondary, in: Circle())
            Text(text)
                .font(.system(size: 13))
                .foregroundStyle(Theme.textPrimary)
                .fixedSize(horizontal: false, vertical: true)
        }
        .accessibilityElement(children: .combine)
    }
}

private struct ResultLine: View {
    let trial: GateTrial
    var body: some View {
        let sev: Severity = trial.frontBackConfusion ? .bad : (trial.within20 ? .ok : .warn)
        HStack(alignment: .top, spacing: 8) {
            Image(systemName: sev.symbol).foregroundStyle(sev.color)
            VStack(alignment: .leading, spacing: 2) {
                Text("Target \(signedDegrees(trial.targetDeg)), pointed \(signedDegrees(trial.responseDeg)), error \(signedDegrees(trial.errorDeg))")
                    .font(.system(size: 14, weight: .semibold))
                    .foregroundStyle(Theme.textPrimary)
                Text(trial.frontBackConfusion ? "Front/back confusion" : (trial.within20 ? "Within 20\u{00B0}" : "Outside 20\u{00B0}"))
                    .font(.system(size: 13))
                    .foregroundStyle(Theme.textSecondary)
            }
        }
        .accessibilityElement(children: .combine)
    }
}

struct Banner: View {
    let severity: Severity
    let text: String
    var body: some View {
        HStack(alignment: .top, spacing: 10) {
            Image(systemName: severity.symbol).foregroundStyle(severity.color).font(.system(size: 15, weight: .bold))
            Text(text)
                .font(.system(size: 13, weight: .medium))
                .foregroundStyle(Theme.textPrimary)
                .fixedSize(horizontal: false, vertical: true)
            Spacer(minLength: 0)
        }
        .padding(12)
        .background(severity.color.opacity(0.12), in: RoundedRectangle(cornerRadius: 10, style: .continuous))
        .overlay(RoundedRectangle(cornerRadius: 10, style: .continuous).strokeBorder(severity.color.opacity(0.6), lineWidth: 1))
        .accessibilityElement(children: .combine)
        .accessibilityLabel("\(severity.spoken): \(text)")
    }
}

/// Slider, step buttons, and sweep for the virtual head.
struct MockHeadControls: View {
    let mock: MockHeadTracker
    @State private var yaw = 0.0
    @State private var sweeping = false

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            HStack {
                Text("Yaw")
                    .font(.system(size: 14, weight: .medium))
                    .foregroundStyle(Theme.textSecondary)
                Slider(value: $yaw, in: -180...180, step: 1)
                    .onChange(of: yaw) { _, v in if !sweeping { mock.setRawPose(yawDeg: v) } }
                    .accessibilityLabel("Virtual head yaw")
                    .accessibilityValue("\(Int(yaw)) degrees")
            }
            HStack(spacing: 8) {
                Button("Turn left 15\u{00B0}") { mock.turn(byDeg: -15); yaw = mock.rawYawDeg }
                    .buttonStyle(QuietButtonStyle())
                Button("Turn right 15\u{00B0}") { mock.turn(byDeg: 15); yaw = mock.rawYawDeg }
                    .buttonStyle(QuietButtonStyle())
            }
            Toggle("Sweep +-60\u{00B0}", isOn: $sweeping)
                .toggleStyle(.switch)
                .font(.system(size: 13))
                .onChange(of: sweeping) { _, on in mock.setSweeping(on) }
            Text("Arrow keys turn 15\u{00B0} (Shift: 5\u{00B0}).")
                .font(.system(size: 12))
                .foregroundStyle(Theme.textSecondary)
        }
    }
}

func rate(_ hz: Double) -> String {
    hz <= 0 ? "-" : (hz.truncatingRemainder(dividingBy: 1000) == 0 ? "\(Int(hz / 1000)) kHz" : String(format: "%.1f kHz", hz / 1000))
}
