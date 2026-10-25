import EarmarkAudio
import EarmarkContracts
import EarmarkUI
import SwiftUI

/// Where each known item is in the room (meters), from its state: exact position, spot, or area.
struct RoomItem: Identifiable {
    var id: String
    var name: String
    var position: EarmarkPoint
    var isTarget: Bool
}

@MainActor
func roomItems(_ core: EarmarkCore) -> [RoomItem] {
    let names = Dictionary(core.objects.map { ($0.objectId, $0.name) }, uniquingKeysWith: { a, _ in a })
    let spots = Dictionary((core.space?.spots ?? []).map { ($0.spot, $0.position) }, uniquingKeysWith: { a, _ in a })
    let areas = Dictionary((core.space?.areas ?? []).map { ($0.area, $0.position) }, uniquingKeysWith: { a, _ in a })
    return core.states.sorted { $0.key < $1.key }.compactMap { id, st in
        guard st.status != .held, st.status != .missing else { return nil }
        let raw = st.location.position ?? st.location.spot.flatMap { spots[$0] } ?? st.location.area.flatMap { areas[$0] }
        guard let p = raw.flatMap(Geometry.point) else { return nil }
        return RoomItem(id: id, name: names[id] ?? id, position: p, isTarget: core.guide?.objectId == id)
    }
}

/// 360-degree top-down room around the mat: items stay where they are, and the judge can be dragged
/// around them (operator mode) or follows the phones. Forward (+y) is up.
struct RoomCircle: View {
    let core: EarmarkCore
    @ObservedObject var pose: PoseModel
    let manual: Bool
    let onMoveJudge: (EarmarkPoint) -> Void

    static let radiusM = 4.0

    private struct Frame {
        var c: CGPoint
        var s: CGFloat
        func pt(_ p: EarmarkPoint) -> CGPoint { CGPoint(x: c.x + CGFloat(p.x) * s, y: c.y - CGFloat(p.y) * s) }
        func meters(_ q: CGPoint) -> (Double, Double) { (Double((q.x - c.x) / s), Double((c.y - q.y) / s)) }
    }

    /// How far the view reaches: everything known plus room to move, in half-meter steps (1.5 to 4 m).
    private var reachM: Double {
        var far = 1.0
        for a in core.space?.areas ?? [] { if let p = Geometry.point(a.position) { far = max(far, (p.x * p.x + p.y * p.y).squareRoot()) } }
        for it in roomItems(core) { far = max(far, (it.position.x * it.position.x + it.position.y * it.position.y).squareRoot()) }
        let j = core.listenerPosition
        far = max(far, (j.x * j.x + j.y * j.y).squareRoot())
        return min(Self.radiusM, max(1.5, ((far + 0.3) * 2).rounded(.up) / 2))
    }

    private func frame(_ size: CGSize) -> Frame {
        Frame(c: CGPoint(x: size.width / 2, y: size.height / 2), s: min(size.width, size.height) / 2 / CGFloat(reachM + 0.3))
    }

    var body: some View {
        GeometryReader { geo in
            let f = frame(geo.size)
            Canvas { ctx, size in draw(ctx, frame(size)) }
                .contentShape(Rectangle())
                .gesture(DragGesture(minimumDistance: 0).onChanged { v in
                    guard manual else { return }
                    let (x, y) = f.meters(v.location)
                    let r = Self.radiusM
                    onMoveJudge(EarmarkPoint(max(-r, min(r, x)), max(-r, min(r, y)), EarmarkCore.manualEarHeight))
                })
        }
        .accessibilityElement(children: .ignore)
        .accessibilityLabel(manual ? "Room seen from above. Drag to move the judge; arrow keys move them 10 centimeters." : "Room seen from above.")
        .accessibilityValue(roomItems(core).map { "\($0.name)\($0.isTarget ? ", the target" : "")" }.joined(separator: ", "))
    }

    private func label(_ ctx: GraphicsContext, _ s: String, at p: CGPoint, size: CGFloat = 12, color: Color = Theme.textSecondary, weight: Font.Weight = .regular) {
        ctx.draw(Text(s).font(.system(size: size, weight: weight)).foregroundColor(color), at: p)
    }

    private func draw(_ ctx: GraphicsContext, _ f: Frame) {
        let reach = reachM
        for k in 1...Int(reach * 2) {
            let r = Double(k) / 2
            let rad = CGFloat(r) * f.s
            ctx.stroke(Path(ellipseIn: CGRect(x: f.c.x - rad, y: f.c.y - rad, width: 2 * rad, height: 2 * rad)),
                       with: .color(Theme.grid), style: StrokeStyle(lineWidth: 1, dash: [3, 5]))
            label(ctx, k % 2 == 0 ? "\(k / 2) m" : String(format: "%.1f m", r), at: CGPoint(x: f.c.x + rad * 0.72, y: f.c.y + rad * 0.70), size: 11)
        }
        let edge = CGFloat(reach + 0.15) * f.s
        label(ctx, "forward", at: CGPoint(x: f.c.x, y: f.c.y - edge), weight: .semibold)
        label(ctx, "behind", at: CGPoint(x: f.c.x, y: f.c.y + edge), weight: .semibold)
        // The mat: where the judge starts.
        ctx.stroke(Path(ellipseIn: CGRect(x: f.c.x - 5, y: f.c.y - 5, width: 10, height: 10)), with: .color(Theme.textSecondary), lineWidth: 1.5)

        for a in core.space?.areas ?? [] {
            guard let p = Geometry.point(a.position) else { continue }
            let q = f.pt(p)
            ctx.fill(Path(ellipseIn: CGRect(x: q.x - 3, y: q.y - 3, width: 6, height: 6)), with: .color(Theme.textSecondary.opacity(0.6)))
            label(ctx, a.label ?? a.area, at: CGPoint(x: q.x, y: q.y - 12), size: 11)
        }

        let items = roomItems(core)
        let judge = core.listenerPosition
        let j = f.pt(judge)
        if let t = core.guideTarget {
            let q = f.pt(t)
            // Arrival ring: half a meter around the target.
            let ar = 0.5 * f.s
            ctx.stroke(Path(ellipseIn: CGRect(x: q.x - ar, y: q.y - ar, width: 2 * ar, height: 2 * ar)),
                       with: .color(Theme.target.opacity(0.7)), style: StrokeStyle(lineWidth: 1.5, dash: [5, 5]))
            var line = Path()
            line.move(to: j); line.addLine(to: q)
            ctx.stroke(line, with: .color(Theme.target.opacity(0.85)), style: StrokeStyle(lineWidth: 2.5, dash: [8, 6]))
        }
        // Items sharing a place get one dot and one label ("sugar, pepper").
        var groups: [(p: EarmarkPoint, names: [String], target: Bool)] = []
        for it in items {
            if let i = groups.firstIndex(where: { abs($0.p.x - it.position.x) < 0.05 && abs($0.p.y - it.position.y) < 0.05 }) {
                groups[i].names.append(it.name); groups[i].target = groups[i].target || it.isTarget
            } else { groups.append((it.position, [it.name], it.isTarget)) }
        }
        for g in groups {
            let q = f.pt(g.p)
            let r: CGFloat = g.target ? 11 : 7
            ctx.fill(Path(ellipseIn: CGRect(x: q.x - r, y: q.y - r, width: 2 * r, height: 2 * r)),
                     with: .color(g.target ? Theme.target : Theme.textPrimary.opacity(0.75)))
            label(ctx, g.names.joined(separator: ", "), at: CGPoint(x: q.x, y: q.y + r + 11), size: g.target ? 15 : 13,
                  color: g.target ? Theme.target : Theme.textPrimary, weight: g.target ? .bold : .semibold)
        }
        if let t = core.guideTarget, !items.contains(where: \.isTarget) {
            let q = f.pt(t)
            ctx.fill(Path(ellipseIn: CGRect(x: q.x - 11, y: q.y - 11, width: 22, height: 22)), with: .color(Theme.target))
            label(ctx, core.guide?.name ?? "ping", at: CGPoint(x: q.x, y: q.y + 24), size: 15, color: Theme.target, weight: .bold)
        }

        // The judge, with the AirPods head direction.
        let coneR = 0.9 * f.s
        let a = pose.yaw * .pi / 180
        var cone = Path()
        cone.move(to: j)
        cone.addArc(center: j, radius: coneR, startAngle: .degrees(pose.yaw - 28 - 90), endAngle: .degrees(pose.yaw + 28 - 90), clockwise: false)
        cone.closeSubpath()
        let tip = CGPoint(x: j.x + coneR * CGFloat(sin(a)), y: j.y - coneR * CGFloat(cos(a)))
        ctx.fill(cone, with: .linearGradient(Gradient(colors: [Theme.head.opacity(pose.tracking ? 0.30 : 0.12), Theme.head.opacity(0.03)]),
                                             startPoint: j, endPoint: tip))
        ctx.stroke(cone, with: .color(Theme.head.opacity(0.5)), style: StrokeStyle(lineWidth: 1.2, dash: pose.tracking ? [] : [5, 5]))
        if manual {
            ctx.stroke(Path(ellipseIn: CGRect(x: j.x - 24, y: j.y - 24, width: 48, height: 48)), with: .color(Theme.head.opacity(0.6)),
                       style: StrokeStyle(lineWidth: 1.5, dash: [3, 3]))
        }
        ctx.fill(Path(ellipseIn: CGRect(x: j.x - 17, y: j.y - 17, width: 34, height: 34)), with: .color(Theme.head))
        label(ctx, "Judge", at: j, size: 11, color: Theme.background, weight: .bold)
    }
}

/// Operator controls under the room: hand positioning, a readout, and ping start/stop.
struct RoomControls: View {
    @ObservedObject var m: AppModel

    var body: some View {
        let core = m.core
        let p = core.listenerPosition
        HStack(spacing: 12) {
            Toggle("Move the judge by hand", isOn: $m.manualJudge)
                .toggleStyle(.switch)
                .font(.system(size: 14, weight: .semibold))
                .fixedSize()
            Text(String(format: "%.1f m %@, %.1f m %@", abs(p.x), p.x >= 0 ? "right" : "left", abs(p.y), p.y >= 0 ? "forward" : "back"))
                .font(.system(size: 13))
                .foregroundStyle(Theme.textSecondary)
                .monospacedDigit()
            Spacer()
            if core.guide != nil {
                Button { core.stopPing() } label: { Label("Stop ping", systemImage: "stop.fill") }
                    .buttonStyle(QuietButtonStyle())
                    .fixedSize()
            } else {
                Menu {
                    ForEach(roomItems(core)) { it in
                        Button(it.name.capitalized) { core.startManualPing(objectId: it.id, name: it.name, at: it.position) }
                    }
                } label: { Label("Ping an item", systemImage: "dot.radiowaves.left.and.right") }
                    .menuStyle(.borderlessButton)
                    .fixedSize()
                    .disabled(roomItems(core).isEmpty)
            }
        }
    }
}
