import EarmarkAudio
import EarmarkContracts
import EarmarkUI
import simd
import SwiftUI

/// What the map draws, derived from the snapshot and state updates.
struct MapScene {
    struct SpotItem { var spot: Spot; var objects: [String]; var isTarget: Bool }
    struct LooseItem { var name: String; var detail: String; var position: EarmarkPoint?; var isTarget: Bool }

    var spots: [SpotItem] = []
    var loose: [LooseItem] = []
    var target: EarmarkPoint?
    var targetName: String?

    init(core: EarmarkCore) {
        let names = Dictionary(core.objects.map { ($0.objectId, $0.name) }, uniquingKeysWith: { a, _ in a })
        let targetID = core.guide?.objectId
        target = core.guideTarget
        targetName = core.guide?.name
        var bySpot: [Int: [String]] = [:]
        var looseItems: [LooseItem] = []
        for (id, st) in core.states.sorted(by: { $0.key < $1.key }) {
            let name = names[id] ?? id
            if st.status == .onSpot, let s = st.location.spot {
                bySpot[s, default: []].append(name)
                continue
            }
            let pos = st.location.position.flatMap(Geometry.point)
            let detail: String
            switch st.status {
            case .held: detail = "held"
            case .missing: detail = "missing"
            case .roaming:
                if let near = st.location.near {
                    let rx = core.space?.receivers.first { $0.receiver == near }?.label ?? near
                    let range: [DistanceClass: String] = [.near: "close by", .mid: "a few steps away", .far: "far"]
                    detail = "near \(rx)" + (st.location.distanceClass.map { ", " + (range[$0] ?? $0.rawValue) } ?? "")
                } else if let a = st.location.area {
                    detail = "in " + (core.space?.areas.first { $0.area == a }?.label ?? a)
                } else { detail = "roaming" }
            case .onSpot: detail = "on a spot"
            }
            looseItems.append(LooseItem(name: name, detail: detail, position: st.status == .roaming ? pos : nil, isTarget: id == targetID))
        }
        let targetSpot: Int? = targetID.flatMap { core.states[$0]?.location.spot }
        spots = (core.space?.spots ?? []).sorted { $0.spot < $1.spot }.map { s in
            let isTarget = targetSpot == s.spot ||
                (target.map { t in Geometry.point(s.position).map { simd_distance($0, t) < 0.05 } ?? false } ?? false)
            return SpotItem(spot: s, objects: bySpot[s.spot] ?? [], isTarget: isTarget)
        }
        loose = looseItems
    }

    /// Text equivalent of the map, for VoiceOver and the list under it.
    var spokenSummary: String {
        var parts: [String] = []
        for s in spots {
            let what = s.objects.isEmpty ? "empty" : s.objects.joined(separator: " and ")
            parts.append("Spot \(s.spot.spot), \(s.spot.label): \(what)\(s.isTarget ? ", the target" : "")")
        }
        for l in loose { parts.append("\(l.name): \(l.detail)\(l.isTarget ? ", the target" : "")") }
        return parts.joined(separator: ". ")
    }
}

/// Large live top-down map: listener at the origin, forward up, spots, object chips, target, head cone.
struct MapView: View {
    let scene: MapScene
    @ObservedObject var pose: PoseModel

    var body: some View {
        Canvas { ctx, size in draw(ctx, size) }
            .accessibilityElement(children: .ignore)
            .accessibilityLabel("Room map, seen from above. You are at the center, facing up.")
            .accessibilityValue("Head turned \(Int(pose.yaw.rounded())) degrees. " + scene.spokenSummary)
    }

    // World (meters, +x right, +y forward) -> screen.
    private struct Frame {
        var origin: CGPoint
        var scale: CGFloat
        func pt(_ p: EarmarkPoint) -> CGPoint { CGPoint(x: origin.x + CGFloat(p.x) * scale, y: origin.y - CGFloat(p.y) * scale) }
        func pt(_ v: [Double]) -> CGPoint { pt(Geometry.point(v) ?? .zero) }
    }

    static let backConeLength = 0.45

    /// Radius of the "somewhere around here" circle for proximity-only objects.
    static func proximityRadius(_ detail: String) -> Double {
        detail.hasSuffix("close by") ? 0.10 : (detail.hasSuffix("far") ? 0.30 : 0.18)
    }

    private func frame(_ size: CGSize) -> Frame {
        var pts = scene.spots.compactMap { Geometry.point($0.spot.position) }
        if let t = scene.target { pts.append(t) }
        var top = pts.map(\.y).max() ?? 0.6
        for l in scene.loose { if let p = l.position { pts.append(p); top = max(top, p.y + Self.proximityRadius(l.detail) + 0.08) } }
        let maxX = max(0.45, pts.map { abs($0.x) }.max() ?? 0)
        let minY = pts.map(\.y).min() ?? 0
        // Room behind the listener: enough for a target back there, or for the head cone when facing backward.
        let back = max(minY < -0.1 ? -minY + 0.1 : 0, pose.facingBack ? Self.backConeLength + 0.05 : 0)
        let bottomPad: CGFloat = back > 0 ? 10 : 38, topPad: CGFloat = 30
        let spanY = top + 0.12 + back
        let scale = min((size.width - 40) / CGFloat(2 * maxX + 0.36), (size.height - bottomPad - topPad) / CGFloat(spanY))
        let originY = size.height - bottomPad - CGFloat(back) * scale
        return Frame(origin: CGPoint(x: size.width / 2, y: originY), scale: scale)
    }

    private func draw(_ ctx: GraphicsContext, _ size: CGSize) {
        let f = frame(size)

        // Range rings every 25 cm, labeled on the right at ear level (away from the forward axis).
        for r in [0.25, 0.5, 0.75, 1.0] {
            let rad = CGFloat(r) * f.scale
            let rect = CGRect(x: f.origin.x - rad, y: f.origin.y - rad, width: 2 * rad, height: 2 * rad)
            ctx.stroke(Path(ellipseIn: rect), with: .color(Theme.grid), style: StrokeStyle(lineWidth: 1, dash: [3, 5]))
            if f.origin.x + rad + 40 < size.width {
                ctx.draw(Text("\(Int(r * 100)) cm").font(.system(size: 11)).foregroundColor(Theme.textSecondary),
                         at: CGPoint(x: f.origin.x + rad + 4, y: f.origin.y - 8), anchor: .leading)
            }
        }
        var axis = Path()
        axis.move(to: f.origin); axis.addLine(to: CGPoint(x: f.origin.x, y: 30))
        ctx.stroke(axis, with: .color(Theme.grid), style: StrokeStyle(lineWidth: 1.5, dash: [2, 4]))
        ctx.draw(Text("Calibrated forward").font(.system(size: 12, weight: .semibold)).foregroundColor(Theme.textSecondary),
                 at: CGPoint(x: f.origin.x, y: 14))

        // Proximity-only objects: a soft circle under everything else, labeled at its top.
        for l in scene.loose { if let p = l.position { drawRoaming(ctx, f, l, p) } }

        if let t = scene.target {
            var line = Path()
            line.move(to: f.origin); line.addLine(to: f.pt(t))
            ctx.stroke(line, with: .color(Theme.target.opacity(0.85)), style: StrokeStyle(lineWidth: 2.5, dash: [8, 6]))
        }

        drawHead(ctx, f)

        // Box width from the closest pair of spots in the same row, so neighbors never overlap.
        let pts = scene.spots.compactMap { Geometry.point($0.spot.position) }
        var minGap = 1.0
        for (i, a) in pts.enumerated() { for b in pts.dropFirst(i + 1) where abs(a.y - b.y) < 0.12 { minGap = min(minGap, abs(a.x - b.x)) } }
        let boxW = max(76, min(150, 0.34 * f.scale, CGFloat(minGap) * f.scale - 10))
        for item in scene.spots { drawSpot(ctx, f, item, boxW: boxW) }

        // A target that is not on a spot.
        if let t = scene.target, !scene.spots.contains(where: \.isTarget), !scene.loose.contains(where: { $0.isTarget && $0.position != nil }) {
            let c = f.pt(t)
            ctx.fill(Path(ellipseIn: CGRect(x: c.x - 11, y: c.y - 11, width: 22, height: 22)), with: .color(Theme.target))
            ctx.draw(Text(scene.targetName ?? "target").font(.system(size: 15, weight: .bold)).foregroundColor(Theme.target),
                     at: CGPoint(x: c.x, y: c.y + 24))
        }

        ctx.fill(Path(ellipseIn: CGRect(x: f.origin.x - 17, y: f.origin.y - 17, width: 34, height: 34)), with: .color(Theme.head))
        ctx.draw(Text("You").font(.system(size: 13, weight: .bold)).foregroundColor(Theme.background), at: f.origin)
    }

    private func drawHead(_ ctx: GraphicsContext, _ f: Frame) {
        let r = CGFloat(pose.facingBack ? Self.backConeLength : 0.8) * f.scale
        let yaw = pose.yaw
        var cone = Path()
        cone.move(to: f.origin)
        cone.addArc(center: f.origin, radius: r, startAngle: .degrees(yaw - 28 - 90), endAngle: .degrees(yaw + 28 - 90), clockwise: false)
        cone.closeSubpath()
        let a = yaw * .pi / 180
        let tip = CGPoint(x: f.origin.x + r * CGFloat(sin(a)), y: f.origin.y - r * CGFloat(cos(a)))
        ctx.fill(cone, with: .linearGradient(Gradient(colors: [Theme.head.opacity(pose.tracking ? 0.30 : 0.12), Theme.head.opacity(0.03)]),
                                             startPoint: f.origin, endPoint: tip))
        ctx.stroke(cone, with: .color(Theme.head.opacity(0.5)), style: StrokeStyle(lineWidth: 1.2, dash: pose.tracking ? [] : [5, 5]))
        var nose = Path()
        nose.move(to: f.origin)
        nose.addLine(to: CGPoint(x: f.origin.x + r * 0.9 * CGFloat(sin(a)), y: f.origin.y - r * 0.9 * CGFloat(cos(a))))
        ctx.stroke(nose, with: .color(Theme.head), style: StrokeStyle(lineWidth: 3, lineCap: .round))
    }

    private func drawSpot(_ ctx: GraphicsContext, _ f: Frame, _ item: MapScene.SpotItem, boxW w: CGFloat) {
        let c = f.pt(item.spot.position)
        let h: CGFloat = 64
        let rect = CGRect(x: c.x - w / 2, y: c.y - h / 2, width: w, height: h)
        let shape = Path(roundedRect: rect, cornerRadius: 12)
        if item.isTarget {
            let glow = Path(roundedRect: rect.insetBy(dx: -8, dy: -8), cornerRadius: 17)
            ctx.fill(glow, with: .color(Theme.target.opacity(0.22)))
        }
        ctx.fill(shape, with: .color(item.objects.isEmpty ? Theme.surfaceSunken : Theme.surface))
        ctx.stroke(shape, with: .color(item.isTarget ? Theme.target : Theme.border),
                   style: StrokeStyle(lineWidth: item.isTarget ? 3.5 : 1.5, dash: item.objects.isEmpty ? [5, 4] : []))
        let name = item.objects.isEmpty ? "empty" : item.objects.joined(separator: ", ")
        let narrow = w < 112
        let long = name.count > 9 || narrow
        let nameText = Text(name)
            .font(.system(size: item.objects.isEmpty ? 13 : (long ? (narrow ? 12 : 13) : 17), weight: item.objects.isEmpty ? .regular : .bold))
            .foregroundColor(item.objects.isEmpty ? Theme.textSecondary : (item.isTarget ? Theme.target : Theme.textPrimary))
        let nameRect = CGRect(x: rect.minX + 6, y: rect.minY + 6, width: rect.width - 12, height: rect.height - 26)
        let resolved = ctx.resolve(nameText)
        let fit = resolved.measure(in: nameRect.size)
        ctx.draw(resolved, in: CGRect(x: nameRect.midX - fit.width / 2, y: nameRect.midY - fit.height / 2, width: fit.width, height: fit.height))
        let label = narrow ? "Spot \(item.spot.spot)" : "\(item.spot.spot) - \(item.spot.label)"
        ctx.draw(Text(label).font(.system(size: 11, weight: .medium)).foregroundColor(Theme.textSecondary),
                 at: CGPoint(x: c.x, y: rect.maxY - 11))
    }

    private func drawRoaming(_ ctx: GraphicsContext, _ f: Frame, _ l: MapScene.LooseItem, _ p: EarmarkPoint) {
        let c = f.pt(p)
        let r = CGFloat(Self.proximityRadius(l.detail)) * f.scale
        let circle = Path(ellipseIn: CGRect(x: c.x - r, y: c.y - r, width: 2 * r, height: 2 * r))
        let color = l.isTarget ? Theme.target : Theme.textSecondary
        ctx.fill(circle, with: .color(color.opacity(0.08)))
        ctx.stroke(circle, with: .color(color.opacity(0.7)), style: StrokeStyle(lineWidth: 1.5, dash: [4, 4]))
        ctx.draw(Text("\(l.name) - \(l.detail)").font(.system(size: 13, weight: .semibold)).foregroundColor(l.isTarget ? Theme.target : Theme.textPrimary),
                 at: CGPoint(x: c.x, y: c.y - r - 11))
    }
}

/// Visible text-list equivalent of the map.
struct MapList: View {
    let scene: MapScene

    var body: some View {
        LazyVGrid(columns: [GridItem(.adaptive(minimum: 150), spacing: 12, alignment: .topLeading)], alignment: .leading, spacing: 10) {
            ForEach(scene.spots, id: \.spot.spot) { s in
                VStack(alignment: .leading, spacing: 3) {
                    Text("SPOT \(s.spot.spot) - \(s.spot.label.uppercased())")
                        .fixedSize(horizontal: false, vertical: true)
                        .font(.system(size: 10, weight: .semibold))
                        .tracking(0.5)
                        .foregroundStyle(Theme.textSecondary)
                    HStack(spacing: 4) {
                        if s.isTarget { Image(systemName: "scope").foregroundStyle(Theme.target).accessibilityHidden(true) }
                        Text(s.objects.isEmpty ? "empty" : s.objects.joined(separator: ", "))
                            .font(.system(size: 14, weight: .semibold))
                            .foregroundStyle(s.objects.isEmpty ? Theme.textSecondary : (s.isTarget ? Theme.target : Theme.textPrimary))
                            .fixedSize(horizontal: false, vertical: true)
                    }
                }
                .frame(maxWidth: .infinity, alignment: .leading)
                .accessibilityElement(children: .combine)
                .accessibilityLabel("Spot \(s.spot.spot), \(s.spot.label): \(s.objects.isEmpty ? "empty" : s.objects.joined(separator: " and "))\(s.isTarget ? ", target" : "")")
            }
            VStack(alignment: .leading, spacing: 3) {
                Text("OFF THE SPOTS")
                    .font(.system(size: 10, weight: .semibold))
                    .tracking(0.5)
                    .foregroundStyle(Theme.textSecondary)
                Text(scene.loose.isEmpty ? "nothing" : scene.loose.map { "\($0.name), \($0.detail)" }.joined(separator: "; "))
                    .font(.system(size: 14, weight: .semibold))
                    .foregroundStyle(scene.loose.isEmpty ? Theme.textSecondary : Theme.textPrimary)
                    .fixedSize(horizontal: false, vertical: true)
            }
            .frame(maxWidth: .infinity, alignment: .leading)
            .accessibilityElement(children: .combine)
        }
    }
}
