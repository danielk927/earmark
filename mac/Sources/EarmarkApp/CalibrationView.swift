import EarmarkAudio
import EarmarkContracts
import EarmarkUI
import Foundation
import SwiftUI

/// State behind the UWB calibration sheet (PRD 10.6). Owned by AppModel so results survive closing the sheet;
/// `reload()` re-reads config/space.json every time the sheet opens.
@MainActor
final class CalibrationModel: ObservableObject {
    struct AnchorRow: Identifiable, Equatable {
        var id: String
        var label: String
        var forwardCm: Double
        var sideCm: Double
        var heightCm: Double
    }

    struct MarkResult: Equatable {
        var solved: EarmarkPoint
        var errorM: Double
        var samples: Int
    }

    let core: EarmarkCore
    let fileURL: URL?

    @Published var anchors: [AnchorRow] = []
    @Published var phoneZCm = Calibration.defaultPhoneZ * 100
    @Published var headOffsetCm = Calibration.defaultHeadOffsetM * 100
    @Published private(set) var results: [String: MarkResult] = [:]
    @Published private(set) var measuring: String?
    @Published private(set) var message: String?
    @Published private(set) var saveMessage: String?
    @Published private(set) var loadError: String?
    @Published private(set) var recentered = false
    private var samples: [EarmarkPoint] = []

    init(core: EarmarkCore, fileURL: URL?) {
        self.core = core
        self.fileURL = fileURL
        reload()
    }

    /// Fills the form from config/space.json (falling back to the hub's snapshot, then the PRD placeholders).
    func reload() {
        var space = core.space
        loadError = nil
        if let fileURL {
            do { space = try Calibration.read(fileURL) } catch {
                loadError = "Could not read \(fileURL.path): \(error.localizedDescription)"
            }
        } else {
            loadError = "Could not find the Earmark repo, so Save is off. Set EARMARK_REPO_ROOT to the repo folder (or build with build_app.sh), then reopen this screen."
        }
        let list = (space?.anchors).flatMap { $0.isEmpty ? nil : $0 } ?? Calibration.defaultAnchors()
        anchors = list.map { a in
            let p = Geometry.point(a.position) ?? .zero
            return AnchorRow(id: a.anchor, label: a.label, forwardCm: Self.cm(p.y), sideCm: Self.cm(p.x), heightCm: Self.cm(p.z))
        }
        phoneZCm = Self.cm(space?.tracking?.phoneZ ?? Calibration.defaultPhoneZ)
        headOffsetCm = Self.cm(space?.tracking?.headOffsetM ?? Calibration.defaultHeadOffsetM)
        saveMessage = nil
    }

    private static func cm(_ m: Double) -> Double { (m * 1000).rounded() / 10 }

    // MARK: Verify

    /// The first mark without a result, nil when all five are measured.
    var currentMark: Calibration.Mark? { Calibration.marks.first { results[$0.id] == nil } }

    var verdict: Calibration.Verdict? { Calibration.verdict(errorsM: results.values.map(\.errorM)) }

    /// Averages listener_pose (tracked or frozen only) over `Calibration.verifySeconds`.
    func verify(_ mark: Calibration.Mark) {
        guard measuring == nil else { return }
        measuring = mark.id
        samples = []
        say("Measuring \(mark.name) for \(Int(Calibration.verifySeconds)) seconds. Hold still.")
        core.onListenerPose = { [weak self] p in self?.collect(p) }
        Task { [weak self] in
            try? await Task.sleep(nanoseconds: UInt64(Calibration.verifySeconds * 1_000_000_000))
            self?.finish(mark)
        }
    }

    func redo(_ mark: Calibration.Mark) {
        results[mark.id] = nil
        recentered = false
    }

    func cancelMeasuring() {
        core.onListenerPose = nil
        measuring = nil
    }

    private func collect(_ p: ListenerPose) {
        guard p.mode == .tracked || p.mode == .frozen, let pt = Geometry.point(p.position) else { return }
        samples.append(pt)
    }

    private func finish(_ mark: Calibration.Mark) {
        guard measuring == mark.id else { return }   // cancelled (sheet closed)
        core.onListenerPose = nil
        measuring = nil
        guard let solved = Calibration.mean(samples) else {
            say("No position from the hub in \(Int(Calibration.verifySeconds)) seconds. Check that the wearer app is running and at least two anchors are online, then press Verify again.")
            return
        }
        let error = Geometry.horizontalDistance(solved, from: mark.expected)
        results[mark.id] = MarkResult(solved: solved, errorM: error, samples: samples.count)
        var text = String(format: "%@: you are at x %+.2f, y %+.2f meters, %.2f meters from the mark. ", mark.name, solved.x, solved.y, error)
        if let next = currentMark {
            text += "Next: " + next.instruction
        } else if let v = verdict {
            text += String(format: "All marks done. Median error %.2f meters, max %.2f meters: %@. Now recenter the AirPods.",
                           v.medianM, v.maxM, v.passed ? "pass" : "fail")
        }
        say(text)
    }

    // MARK: Recenter and save

    func recenter() {
        core.recenter()
        recentered = true
        say("Recentered. The AirPods' straight ahead is now the counter.")
    }

    /// Writes anchors and tracking into config/space.json (other fields untouched, old file kept as .bak),
    /// then sends `reset` so the hub reloads it and pushes the anchors to Convex.
    func save() {
        guard let fileURL else {
            say(loadError ?? "No space.json to save to.")
            return
        }
        do {
            var space = try Calibration.read(fileURL)
            space.anchors = anchors.map {
                Anchor(anchor: $0.id, label: $0.label,
                       position: Calibration.position(forwardCm: $0.forwardCm, sideCm: $0.sideCm, heightCm: $0.heightCm))
            }
            // earZM / markZM are set elsewhere (hub config); keep whatever space.json already has.
            space.tracking = Tracking(phoneZ: (phoneZCm * 10).rounded() / 1000, headOffsetM: (headOffsetCm * 10).rounded() / 1000,
                                      earZM: space.tracking?.earZM, markZM: space.tracking?.markZM)
            try Calibration.write(space, to: fileURL)
            if core.busConnected {
                core.sendReset()
                saveMessage = "Saved \(fileURL.path) (previous file kept as space.json.bak) and asked the hub to reload it."
            } else {
                saveMessage = "Saved \(fileURL.path) (previous file kept as space.json.bak). The bus is not connected: restart the hub so it reads the new file."
            }
        } catch {
            saveMessage = "Could not save: \(error.localizedDescription)"
        }
        say(saveMessage ?? "")
    }

    private func say(_ text: String) {
        message = text
        AccessibilityNotification.Announcement(text).post()
    }
}

/// UWB calibration sheet: anchor positions, wearer geometry, a five-mark position check, recenter, save.
/// Every control is a standard focusable control with a spoken label, so it works with Tab and VoiceOver.
@MainActor
struct CalibrationView: View {
    @ObservedObject var m: AppModel
    @ObservedObject var cal: CalibrationModel
    @Environment(\.dismiss) private var dismiss

    private static let cmFormat = FloatingPointFormatStyle<Double>().precision(.fractionLength(0...1))

    var body: some View {
        let _ = m.revision   // live anchor status
        VStack(alignment: .leading, spacing: 16) {
            Text("UWB calibration")
                .font(.system(size: 24, weight: .bold))
                .foregroundStyle(Theme.textPrimary)
                .accessibilityAddTraits(.isHeader)
            if let e = cal.loadError { AppBanner(severity: .warn, text: e) }
            ScrollView {
                VStack(alignment: .leading, spacing: 16) {
                    anchorsCard
                    wearerCard
                    verifyCard
                    recenterCard
                }
            }
            HStack(spacing: 12) {
                if let s = cal.saveMessage {
                    Text(s)
                        .font(.system(size: 12))
                        .foregroundStyle(Theme.textSecondary)
                        .fixedSize(horizontal: false, vertical: true)
                }
                Spacer()
                Button("Close") { dismiss() }
                    .keyboardShortcut(.cancelAction)
                Button("Save to space.json") { cal.save() }
                    .keyboardShortcut("s", modifiers: .command)
                    .disabled(cal.fileURL == nil)
                    .accessibilityHint("Writes the anchor positions and wearer settings, keeps a backup, and reloads the hub. Command S.")
            }
        }
        .padding(24)
        .frame(width: 720, height: 800)
        .background(Theme.background)
        .onAppear { cal.reload() }
        .onDisappear { cal.cancelMeasuring() }
    }

    // MARK: 1. Anchors

    private var anchorsCard: some View {
        Card("1. Anchor positions") {
            Text("Measure each UWB Reader/Emitter from the origin floor mark, in centimeters: forward toward the counter (behind is negative), side to the right (left is negative), height relative to ear level (below is negative).")
                .font(.system(size: 13))
                .foregroundStyle(Theme.textSecondary)
                .fixedSize(horizontal: false, vertical: true)
            ForEach($cal.anchors) { $row in
                VStack(alignment: .leading, spacing: 6) {
                    HStack(spacing: 8) {
                        Text(row.label)
                            .font(.system(size: 15, weight: .semibold))
                            .foregroundStyle(Theme.textPrimary)
                        Spacer()
                        anchorStatus(row)
                    }
                    HStack(spacing: 12) {
                        field("Forward cm", value: $row.forwardCm, spoken: "\(row.label) forward, centimeters")
                        field("Side cm", value: $row.sideCm, spoken: "\(row.label) side, centimeters, right is positive")
                        field("Height cm", value: $row.heightCm, spoken: "\(row.label) height versus ear level, centimeters")
                    }
                }
                .padding(.vertical, 4)
            }
        }
    }

    /// Live state from the latest listener_pose: icon plus words, and the last measured range.
    private func anchorStatus(_ row: CalibrationModel.AnchorRow) -> some View {
        let pose = m.core.listenerPose
        let health = pose?.anchors?.first { $0.anchor == row.id }
        let state: UWBText.AnchorState
        if pose?.blocked?.contains(row.id) == true { state = .blocked }
        else if let health { state = health.online ? .online : .offline }
        else { state = .unknown }
        let severity = MapList.anchorSeverity(state)
        let dist = health?.distanceM.map { String(format: ", last distance %.2f m", $0) } ?? ""
        let text = MapList.anchorWord(state) + dist
        return HStack(spacing: 5) {
            Image(systemName: severity.symbol)
                .foregroundStyle(severity.color)
                .accessibilityHidden(true)
            Text(text)
                .font(.system(size: 13, weight: .medium).monospacedDigit())
                .foregroundStyle(Theme.textSecondary)
        }
        .accessibilityElement(children: .ignore)
        .accessibilityLabel("\(row.label): \(text)")
    }

    private func field(_ title: String, value: Binding<Double>, spoken: String) -> some View {
        VStack(alignment: .leading, spacing: 2) {
            Text(title)
                .font(.system(size: 11, weight: .semibold))
                .foregroundStyle(Theme.textSecondary)
                .accessibilityHidden(true)
            TextField(title, value: value, format: Self.cmFormat)
                .textFieldStyle(.roundedBorder)
                .frame(width: 110)
                .accessibilityLabel(spoken)
        }
    }

    // MARK: 2. Wearer

    private var wearerCard: some View {
        Card("2. Wearer phone") {
            HStack(spacing: 16) {
                field("Phone height cm", value: $cal.phoneZCm, spoken: "Phone height versus ear level, centimeters, below is negative")
                field("Head offset cm", value: $cal.headOffsetCm, spoken: "Head offset behind the phone, centimeters")
                Spacer()
            }
            Text(String(format: "Defaults: phone %.0f cm (chest height, below the ears), head %.0f cm behind the phone.",
                        Calibration.defaultPhoneZ * 100, Calibration.defaultHeadOffsetM * 100))
                .font(.system(size: 12))
                .foregroundStyle(Theme.textSecondary)
        }
    }

    // MARK: 3. Verify

    private var verifyCard: some View {
        Card("3. Verify") {
            Text("Save first if you changed the anchors, so the hub solves with the new positions.")
                .font(.system(size: 12))
                .foregroundStyle(Theme.textSecondary)
            if let mark = cal.currentMark {
                HStack(spacing: 12) {
                    Text(mark.instruction)
                        .font(.system(size: 16, weight: .semibold))
                        .foregroundStyle(Theme.textPrimary)
                        .fixedSize(horizontal: false, vertical: true)
                    Spacer()
                    Button { cal.verify(mark) } label: { Text(verbatim: cal.measuring == nil ? "Verify" : "Measuring...") }
                        .keyboardShortcut(.defaultAction)
                        .disabled(cal.measuring != nil)
                        .accessibilityHint("Averages the solved position for \(Int(Calibration.verifySeconds)) seconds. Return key.")
                }
            }
            if let msg = cal.message {
                Text(msg)
                    .font(.system(size: 13))
                    .foregroundStyle(Theme.textPrimary)
                    .fixedSize(horizontal: false, vertical: true)
                    .accessibilityAddTraits(.updatesFrequently)
            }
            ForEach(Calibration.marks) { mark in
                if let r = cal.results[mark.id] { resultRow(mark, r) }
            }
            if let v = cal.verdict {
                let n = cal.results.count
                let total = Calibration.marks.count
                AppBanner(severity: v.passed ? .ok : .bad,
                          text: String(format: "%@ (%ld of %ld marks): median error %.2f m (target %.2f), max %.2f m (target %.2f).",
                                       v.passed ? "Pass" : "Fail", n, total, v.medianM, Calibration.medianTargetM,
                                       v.maxM, Calibration.maxTargetM))
            }
        }
    }

    private func resultRow(_ mark: Calibration.Mark, _ r: CalibrationModel.MarkResult) -> some View {
        let ok = r.errorM <= Calibration.maxTargetM
        let severity: Severity = ok ? .ok : .bad
        let text = String(format: "%@: solved (%+.2f, %+.2f) m, error %.2f m, %ld samples, %@", mark.name, r.solved.x, r.solved.y,
                          r.errorM, r.samples, ok ? "within 0.35 m" : "over 0.35 m")
        return HStack(spacing: 8) {
            Image(systemName: severity.symbol)
                .foregroundStyle(severity.color)
                .accessibilityHidden(true)
            Text(text)
                .font(.system(size: 13).monospacedDigit())
                .foregroundStyle(Theme.textPrimary)
            Spacer()
            Button("Redo") { cal.redo(mark) }
                .disabled(cal.measuring != nil)
                .accessibilityLabel("Redo \(mark.name)")
        }
        .accessibilityElement(children: .contain)
    }

    // MARK: 4. Recenter

    private var recenterCard: some View {
        Card("4. Recenter") {
            HStack(spacing: 12) {
                Text(cal.recentered
                     ? "Recentered: the AirPods' straight ahead is the counter."
                     : "Last step: stand on the origin mark facing the counter and press Recenter, so the room and the AirPods agree on forward.")
                    .font(.system(size: 14))
                    .foregroundStyle(Theme.textPrimary)
                    .fixedSize(horizontal: false, vertical: true)
                Spacer()
                Button("Recenter AirPods") { cal.recenter() }
                    .accessibilityHint("Makes the direction the AirPods face now straight ahead")
            }
        }
    }
}
