import EarmarkAudio
import EarmarkContracts
import EarmarkUI
import SwiftUI

struct AppView: View {
    @ObservedObject var m: AppModel

    var body: some View {
        let core = m.core
        let _ = m.revision
        VStack(spacing: 14) {
            TopBar(m: m)
            StatusBar(m: m)
            BannerStack(m: m)
            HStack(alignment: .top, spacing: 16) {
                Card("Room", fillHeight: true) {
                    let scene = MapScene(core: core)
                    MapView(scene: scene, pose: m.pose)
                        .frame(maxWidth: .infinity, maxHeight: .infinity)
                        .frame(minHeight: 300)
                    Divider().overlay(Theme.border)
                    MapList(scene: scene)
                }
                .frame(maxWidth: .infinity, maxHeight: .infinity)
                if m.showDebug {
                    DebugPanel(m: m, pose: m.pose)
                        .frame(width: 330)
                        .frame(maxHeight: .infinity)
                }
                VStack(spacing: 16) {
                    GuidanceCard(core: core, pose: m.pose)
                    CaptionsCard(m: m)
                    ActionButtons(m: m)
                    Spacer(minLength: 0)
                }
                .frame(width: 440)
                .frame(maxHeight: .infinity)
            }
            .frame(maxHeight: .infinity)
        }
        .padding(20)
        .frame(minWidth: 1240, minHeight: 820)
        .background(Theme.background)
        .sheet(isPresented: $m.showSettings) { SettingsView(m: m) }
    }
}

// MARK: Top bar

private struct TopBar: View {
    @ObservedObject var m: AppModel

    var body: some View {
        HStack(alignment: .center, spacing: 14) {
            ZStack {
                Circle().fill(Theme.target).frame(width: 34, height: 34)
                Image(systemName: "dot.radiowaves.left.and.right")
                    .font(.system(size: 16, weight: .bold))
                    .foregroundStyle(Theme.background)
            }
            .accessibilityHidden(true)
            VStack(alignment: .leading, spacing: 1) {
                Text("Earmark")
                    .font(.system(size: 26, weight: .bold))
                    .foregroundStyle(Theme.textPrimary)
                Text("Find things by sound")
                    .font(.system(size: 13))
                    .foregroundStyle(Theme.textSecondary)
            }
            .accessibilityElement(children: .combine)
            Spacer()
            Button { m.showDebug.toggle() } label: {
                Label(m.showDebug ? "Hide debug" : "Show debug", systemImage: "ladybug")
            }
            .buttonStyle(QuietButtonStyle())
            .fixedSize()
            Button { m.showSettings = true } label: { Label("Settings", systemImage: "gearshape") }
                .buttonStyle(QuietButtonStyle())
                .fixedSize()
                .keyboardShortcut(",", modifiers: .command)
        }
    }
}

// MARK: Status bar

private struct StatusBar: View {
    @ObservedObject var m: AppModel

    var body: some View {
        let core = m.core
        let d = core.devices
        let mode = core.guidanceMode
        let latency = (core.renderer?.presentationLatency ?? 0) * 1000
        Grid(horizontalSpacing: 8, verticalSpacing: 8) {
            GridRow {
                StatusPill(icon: "network", label: "BUS", value: m.busState.displayName,
                           severity: m.busState == .connected ? .ok : (m.busState == .connecting ? .warn : .bad))
                StatusPill(icon: "airpodspro", label: "HEAD TRACKING", value: headValue(core), severity: headSeverity(core.head.state))
                StatusPill(icon: "mic", label: micLabel, value: m.micStatus, severity: m.micSeverity)
                StatusPill(icon: "speaker.wave.2", label: "OUTPUT", value: "\(d.outputDevice) - \(kHz(d.outputSampleRate))",
                           severity: d.hfpSuspected ? .bad : (d.outputTransport.isBluetooth ? .ok : .warn))
            }
            GridRow {
                StatusPill(icon: "waveform", label: "SPEECH TO TEXT", value: sttValue(core), severity: core.micEnabled ? .ok : .neutral)
                StatusPill(icon: "point.3.connected.trianglepath.dotted", label: "GUIDANCE - LEVEL \(mode.level) OF 4",
                           value: mode.displayName, severity: mode.level == 1 ? .ok : (mode.level <= 3 ? .warn : .bad))
                StatusPill(icon: "cube.transparent", label: "RENDERER", value: core.renderer?.kind.displayName ?? "None",
                           severity: core.renderer == nil ? .bad : .ok)
                StatusPill(icon: "timer", label: "OUTPUT LATENCY", value: String(format: "%.0f ms", latency),
                           severity: latency > 300 ? .warn : .neutral)
            }
            GridRow {
                StatusPill(icon: "figure.walk", label: "UWB WALKING",
                           value: UWBText.statusValue(pose: core.listenerPose, anchorCount: core.space?.anchors?.count ?? 0),
                           severity: uwbSeverity(core))
                    .gridCellColumns(4)
            }
        }
    }

    private var micLabel: String {
        m.flags.noMic ? "MIC" : (m.listenMode == .pushToTalk ? "MIC - HOLD SPACE" : "MIC - ALWAYS ON")
    }

    private func headValue(_ core: EarmarkCore) -> String {
        core.head.state == .connected ? String(format: "Tracking %.0f Hz", core.head.updateRateHz) : core.head.state.displayName
    }

    private func headSeverity(_ s: HeadTrackingState) -> Severity {
        switch s {
        case .connected: .ok
        case .mock, .waiting: .warn
        default: .bad
        }
    }

    /// Off or fixed is the normal seated demo (neutral); lost is a problem; fewer anchors than configured warns.
    private func uwbSeverity(_ core: EarmarkCore) -> Severity {
        guard let p = core.listenerPose else { return .neutral }
        switch p.mode {
        case .fixed?: return .neutral
        case .lost?: return .bad
        case .tracked?, .frozen?:
            let used = p.anchorsUsed ?? 0
            let total = max(core.space?.anchors?.count ?? 0, used)
            return used < total || !(p.blocked ?? []).isEmpty ? .warn : .ok
        case nil:   // beacon / sound locator: no anchors to count
            return p.quality == .lost ? .bad : .ok
        }
    }

    private func sttValue(_ core: EarmarkCore) -> String {
        switch core.effectiveSttEngine {
        case "cartesia": "Cartesia Ink"
        default: "Apple Speech"
        }
    }
}

func kHz(_ hz: Double) -> String {
    hz <= 0 ? "-" : (hz.truncatingRemainder(dividingBy: 1000) == 0 ? "\(Int(hz / 1000)) kHz" : String(format: "%.1f kHz", hz / 1000))
}

private struct BannerStack: View {
    @ObservedObject var m: AppModel

    var body: some View {
        let d = m.core.devices
        VStack(spacing: 8) {
            if d.hfpSuspected {
                AppBanner(severity: .bad, text: "\(d.outputDevice) is in hands-free mode (\(kHz(d.outputSampleRate))). Spatial cues are destroyed: quit apps using the AirPods microphone, then reselect the AirPods as output.")
            }
            if m.core.renderer == nil {
                AppBanner(severity: .bad, text: "No renderer could start, so Earmark guides with speech only. " + m.core.rendererFailures.joined(separator: " "))
            } else if !m.core.rendererFailures.isEmpty {
                AppBanner(severity: .warn, text: "Fell back to \(m.core.renderer!.kind.displayName): " + m.core.rendererFailures.joined(separator: " "))
            }
            if let n = m.routingNotice { AppBanner(severity: .warn, text: n) }
        }
    }
}

struct AppBanner: View {
    let severity: Severity
    let text: String

    var body: some View {
        HStack(alignment: .top, spacing: 10) {
            Image(systemName: severity.symbol)
                .font(.system(size: 15, weight: .bold))
                .foregroundStyle(severity.color)
            Text(text)
                .font(.system(size: 14, weight: .medium))
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

// MARK: Guidance

private struct GuidanceCard: View {
    let core: EarmarkCore
    @ObservedObject var pose: PoseModel

    var body: some View {
        Card("Guidance") {
            if let g = core.guide, let s = pose.guidance {
                HStack(alignment: .center, spacing: 18) {
                    indicator(s)
                    VStack(alignment: .leading, spacing: 6) {
                        Text(g.name.capitalized)
                            .font(.system(size: 34, weight: .bold))
                            .foregroundStyle(Theme.target)
                            .lineLimit(1)
                            .minimumScaleFactor(0.6)
                        Text(direction(s))
                            .font(.system(size: 22, weight: .semibold))
                            .foregroundStyle(Theme.textPrimary)
                            .fixedSize(horizontal: false, vertical: true)
                        Text(detail(s))
                            .font(.system(size: 14))
                            .foregroundStyle(Theme.textSecondary)
                            .fixedSize(horizontal: false, vertical: true)
                    }
                    Spacer(minLength: 0)
                }
                .accessibilityElement(children: .combine)
                .accessibilityLabel("Guiding to \(g.name). \(direction(s)). \(detail(s)).")
            } else {
                HStack(spacing: 14) {
                    Image(systemName: "ear")
                        .font(.system(size: 40, weight: .light))
                        .foregroundStyle(Theme.textSecondary)
                        .frame(width: 72)
                        .accessibilityHidden(true)
                    VStack(alignment: .leading, spacing: 4) {
                        Text("Ready")
                            .font(.system(size: 28, weight: .bold))
                            .foregroundStyle(Theme.textPrimary)
                        Text("Ask \"Where's the sugar?\" and follow the sound.")
                            .font(.system(size: 16))
                            .foregroundStyle(Theme.textSecondary)
                            .fixedSize(horizontal: false, vertical: true)
                    }
                }
                .accessibilityElement(children: .combine)
            }
        }
    }

    @ViewBuilder private func indicator(_ s: GuidanceState) -> some View {
        ZStack {
            Circle().fill(Theme.target.opacity(0.14)).frame(width: 84, height: 84)
            Circle().strokeBorder(Theme.target, lineWidth: 2.5).frame(width: 84, height: 84)
            if s.locked {
                Image(systemName: "checkmark").font(.system(size: 38, weight: .bold)).foregroundStyle(Theme.target)
            } else if s.zone == .behind {
                Image(systemName: s.turn == .right ? "arrow.uturn.right" : "arrow.uturn.left")
                    .font(.system(size: 34, weight: .bold)).foregroundStyle(Theme.target)
            } else {
                Image(systemName: "arrow.up")
                    .font(.system(size: 38, weight: .bold))
                    .foregroundStyle(Theme.target)
                    .rotationEffect(.degrees(s.errorDeg))
            }
        }
        .accessibilityHidden(true)
    }

    private func direction(_ s: GuidanceState) -> String {
        if s.locked { return "Locked on - reach ahead" }
        if s.zone == .behind { return "Behind you - turn \(s.turn.rawValue)" }
        let a = abs(s.errorDeg)
        if a < 8 { return "Straight ahead" }
        return "Turn \(s.turn.rawValue) \(Int(a.rounded()))\u{00B0}"
    }

    private func detail(_ s: GuidanceState) -> String {
        // Clock face and distance are from where the listener is now (UWB), not from the counter mark.
        let hour = Geometry.clockHour(azimuthDeg: s.errorDeg)
        let dist = s.distanceM < 1 ? "\(Int((s.distanceM * 100).rounded())) cm" : String(format: "%.1f m", s.distanceM)
        return "At your \(hour) o'clock, about \(dist) away\nPing every \(Int((s.pingIntervalSec * 1000).rounded())) ms"
    }
}

// MARK: Captions

private struct CaptionsCard: View {
    @ObservedObject var m: AppModel

    var body: some View {
        let caps = m.core.captions
        let said = caps.last { $0.speaker == .earmark || $0.speaker == .system }
        let heard = caps.last { $0.speaker == .user }
        Card("Conversation") {
            VStack(alignment: .leading, spacing: 14) {
                captionBlock(title: "EARMARK SAID", icon: "speaker.wave.2.fill",
                             text: said?.text, placeholder: "Nothing yet", active: m.core.isSpeaking, tag: said?.source)
                captionBlock(title: "HEARD", icon: "waveform",
                             text: heard?.text, placeholder: listeningHint, active: m.core.userSpeaking,
                             tag: heard.map { $0.isFinal ? $0.source : "\($0.source), listening" })
            }
        }
    }

    private var listeningHint: String {
        if m.flags.noMic { return "Microphone off" }
        return m.listenMode == .pushToTalk ? "Hold Space and speak" : "Listening for speech"
    }

    private func captionBlock(title: String, icon: String, text: String?, placeholder: String, active: Bool, tag: String?) -> some View {
        VStack(alignment: .leading, spacing: 6) {
            HStack(spacing: 6) {
                Image(systemName: icon)
                    .font(.system(size: 12, weight: .bold))
                    .foregroundStyle(active ? Theme.target : Theme.textSecondary)
                Text(title)
                    .font(.system(size: 11, weight: .semibold))
                    .tracking(1)
                    .foregroundStyle(Theme.textSecondary)
                if active {
                    Text("LIVE")
                        .font(.system(size: 10, weight: .heavy))
                        .foregroundStyle(Theme.background)
                        .padding(.horizontal, 5).padding(.vertical, 1)
                        .background(Theme.target, in: Capsule())
                }
                Spacer()
                if let tag, text != nil {
                    Text(tag)
                        .font(.system(size: 11))
                        .foregroundStyle(Theme.textSecondary)
                }
            }
            Text(text ?? placeholder)
                .font(.system(size: 22, weight: text == nil ? .regular : .semibold))
                .foregroundStyle(text == nil ? Theme.textSecondary : Theme.textPrimary)
                .lineLimit(4)
                .fixedSize(horizontal: false, vertical: true)
                .frame(maxWidth: .infinity, minHeight: 56, alignment: .topLeading)
        }
        .accessibilityElement(children: .combine)
    }
}

// MARK: Actions

private struct ActionButtons: View {
    @ObservedObject var m: AppModel

    var body: some View {
        VStack(spacing: 10) {
            PositioningPicker(m: m)
            Button { m.recenter() } label: {
                Label("Recenter  (R)", systemImage: "scope")
                    .font(.system(size: 20, weight: .bold))
                    .padding(.vertical, 6)
            }
            .buttonStyle(BigButtonStyle())
            .accessibilityLabel("Recenter")
            .accessibilityHint("Makes the direction you face now straight ahead. Keyboard shortcut R.")
            if !m.flags.noMic && m.listenMode == .pushToTalk {
                TalkButton(m: m)
            }
            if let mock = m.mockTracker {
                MockHeadStrip(mock: mock)
            }
        }
    }
}

/// Which positioning system drives the audio (UWB or sound chirps); both keep running. Follows the hub's answer.
private struct PositioningPicker: View {
    @ObservedObject var m: AppModel

    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            Text("POSITIONING  (P)")
                .font(.system(size: 10, weight: .semibold))
                .tracking(0.5)
                .foregroundStyle(Theme.textSecondary)
            Picker("Positioning", selection: Binding(get: { m.activePositioning }, set: { m.selectPositioning($0) })) {
                Text("UWB").tag(PositioningSystem.uwb)
                Text("Sound").tag(PositioningSystem.sound)
            }
            .pickerStyle(.segmented)
            .labelsHidden()
            .accessibilityLabel("Positioning system")
            .accessibilityValue(PositioningText.name(m.activePositioning))
            .accessibilityHint("Chooses whether UWB or sound chirps drive the audio. Keyboard shortcut P.")
            if let p = m.core.agedPositioning {
                Text(PositioningText.inactiveLine(p))
                    .font(.system(size: 13))
                    .foregroundStyle(Theme.textSecondary)
            }
        }
    }
}

private struct TalkButton: View {
    @ObservedObject var m: AppModel

    var body: some View {
        Label(m.pttHeld ? "Listening..." : "Hold to talk  (Space)", systemImage: m.pttHeld ? "mic.fill" : "mic")
            .font(.system(size: 17, weight: .semibold))
            .foregroundStyle(m.pttHeld ? Theme.background : Theme.textPrimary)
            .frame(maxWidth: .infinity)
            .padding(.vertical, 13)
            .background(m.pttHeld ? Theme.target : Theme.surfaceSunken, in: RoundedRectangle(cornerRadius: 12, style: .continuous))
            .overlay(RoundedRectangle(cornerRadius: 12, style: .continuous).strokeBorder(Theme.border, lineWidth: 1))
            .contentShape(Rectangle())
            .gesture(DragGesture(minimumDistance: 0).onChanged { _ in m.setPTT(true) }.onEnded { _ in m.setPTT(false) })
            .accessibilityElement()
            .accessibilityLabel("Hold to talk")
            .accessibilityHint("Hold the Space bar while you speak")
            .accessibilityAddTraits(.isButton)
    }
}

private struct MockHeadStrip: View {
    let mock: MockHeadTracker
    @State private var sweeping = false

    var body: some View {
        HStack(spacing: 8) {
            Text("Virtual head")
                .font(.system(size: 13, weight: .semibold))
                .foregroundStyle(Theme.textSecondary)
            Button { mock.turn(byDeg: -15) } label: { Label("Left", systemImage: "arrow.left") }
                .buttonStyle(QuietButtonStyle())
                .accessibilityLabel("Turn virtual head left 15 degrees")
            Button { mock.turn(byDeg: 15) } label: { Label("Right", systemImage: "arrow.right") }
                .buttonStyle(QuietButtonStyle())
                .accessibilityLabel("Turn virtual head right 15 degrees")
            Toggle("Sweep", isOn: $sweeping)
                .toggleStyle(.switch)
                .font(.system(size: 13))
                .fixedSize()
                .onChange(of: sweeping) { _, on in mock.setSweeping(on) }
        }
        .padding(10)
        .background(Theme.surface, in: RoundedRectangle(cornerRadius: 12, style: .continuous))
        .overlay(RoundedRectangle(cornerRadius: 12, style: .continuous).strokeBorder(Theme.border, lineWidth: 1))
    }
}
