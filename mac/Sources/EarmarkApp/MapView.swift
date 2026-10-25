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
    /// UWB walking guidance: anchors (space.json + hub health), the pose mode, and text lines for the list.
    var anchors: [UWBText.AnchorLine] = []
    var listenerPose: ListenerPose?
    var wearerLine = ""
    /// Show the walking layer (anchors, wearer badge, wider bounds) only when UWB is configured or reporting.
    var showsWalking: Bool { !anchors.isEmpty || listenerPose != nil }
    var modeBadge: String { UWBText.mode(listenerPose?.mode) }

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
        listenerPose = core.listenerPose
        anchors = UWBText.anchors(space: core.space, pose: core.listenerPose, listener: core.listenerPosition)
        wearerLine = UWBText.wearerLine(pose: core.listenerPose, listener: core.listenerPosition)
    }

    /// Text equivalent of the map, for VoiceOver and the list under it.
    var spokenSummary: String {
        var parts: [String] = []
        for s in spots {
            let what = s.objects.isEmpty ? "empty" : s.objects.joined(separator: " and ")
            parts.append("Spot \(s.spot.spot), \(s.spot.label): \(what)\(s.isTarget ? ", the target" : "")")
        }
        for l in loose { parts.append("\(l.name): \(l.detail)\(l.isTarget ? ", the target" : "")") }
        if showsWalking {
            parts.append(wearerLine)
            parts += anchors.map(\.text)
        }
        return parts.joined(separator: ". ")
    }
}

/// Large live top-down map: forward up, spots, object chips, target, the listener (at the origin when seated,
/// or wherever UWB puts the wearer) with the head cone, and the UWB anchors.
struct MapView: View {
    let scene: MapScene
    @ObservedObject var pose: PoseModel

    var body: some View {
        Canvas { ctx, size in draw(ctx, size) }
            .accessibilityElement(children: .ignore)
            .accessibilityLabel(scene.showsWalking
                ? "Room map, seen from above. The counter is up. Walking guidance: \(scene.modeBadge)."
                : "Room map, seen from above. You are at the center, facing up.")
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
    /// Walking area kept in view when UWB is on: the start mark is 2-4 m behind the origin (PRD 4.2).
    static let walkingArea: [EarmarkPoint] = [[0, -2.5, 0], [-0.8, -2.5, 0], [0.8, -2.5, 0]]

    /// Radius of the "somewhere around here" circle for proximity-only objects.
    static func proximityRadius(_ detail: String) -> Double {
        detail.hasSuffix("close by") ? 0.10 : (detail.hasSuffix("far") ? 0.30 : 0.18)
    }

    private func frame(_ size: CGSize) -> Frame {
        var pts = scene.spots.compactMap { Geometry.point($0.spot.position) }
        if let t = scene.target { pts.append(t) }
        if scene.showsWalking {
            pts += scene.anchors.compactMap(\.position).map { EarmarkPoint($0.x, $0.y, 0) }
            pts += Self.walkingArea
            pts.append(pose.listener)
        }
        var top = pts.map(\.y).max() ?? 0.6
        for l in scene.loose { if let p = l.position { pts.append(p); top = max(top, p.y + Self.proximityRadius(l.detail) + 0.08) } }
        // Anchors carry two lines of text, so the walking layer gets extra margin on every side.
        let maxX = max(0.45, pts.map { abs($0.x) }.max() ?? 0) + (scene.showsWalking ? 0.35 : 0)
        let minY = pts.map(\.y).min() ?? 0
        // Room behind the listener: enough for a target back there, or for the head cone when facing backward.
        let back = max(minY < -0.1 ? -minY + (scene.showsWalking ? 0.3 : 0.1) : 0, pose.facingBack ? Self.backConeLength + 0.05 : 0)
        let bottomPad: CGFloat = back > 0 ? 10 : 38, topPad: CGFloat = 30
        let spanY = top + 0.12 + back
        let scale = min((size.width - 40) / CGFloat(2 * maxX + 0.36), (size.height - bottomPad - topPad) / CGFloat(spanY))
        let originY = size.height - bottomPad - CGFloat(back) * scale
        return Frame(origin: CGPoint(x: size.width / 2, y: originY), scale: scale)
    }

    private func draw(_ ctx: GraphicsContext, _ size: CGSize) {
        let f = frame(size)

        // Range rings around the origin mark, labeled on the right at ear level (away from the forward axis):
        // every 25 cm seated, out to 3 m when walking.
        let rings = scene.showsWalking ? [0.5, 1.0, 2.0, 3.0] : [0.25, 0.5, 0.75, 1.0]
        for r in rings {
            let rad = CGFloat(r) * f.scale
            let rect = CGRect(x: f.origin.x - rad, y: f.origin.y - rad, width: 2 * rad, height: 2 * rad)
            ctx.stroke(Path(ellipseIn: rect), with: .color(Theme.grid), style: StrokeStyle(lineWidth: 1, dash: [3, 5]))
            if f.origin.x + rad + 40 < size.width {
                ctx.draw(Text(verbatim: r < 1 ? "\(Int(r * 100)) cm" : "\(Int(r)) m").font(.system(size: 11)).foregroundColor(Theme.textSecondary),
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

        let you = f.pt(pose.listener)

        if let t = scene.target {
            var line = Path()
            line.move(to: you); line.addLine(to: f.pt(t))
            ctx.stroke(line, with: .color(Theme.target.opacity(0.85)), style: StrokeStyle(lineWidth: 2.5, dash: [8, 6]))
        }

        if scene.showsWalking {
            for a in scene.anchors { drawAnchor(ctx, f, a) }
            if simd_length(pose.listener) > 0.05 { drawOriginMark(ctx, f) }
        }

        drawHead(ctx, f, at: you)

        // Box width from the closest pair of spots in the same row, so neighbors never overlap.
        let pts = scene.spots.compactMap { Geometry.point($0.spot.position) }
        var minGap = 1.0
        for (i, a) in pts.enumerated() { for b in pts.dropFirst(i + 1) where abs(a.y - b.y) < 0.12 { minGap = min(minGap, abs(a.x - b.x)) } }
        // Zoomed out for walking, the counter is small: let the boxes shrink rather than overlap.
        let boxW = max(scene.showsWalking ? 44 : 76, min(150, 0.34 * f.scale, CGFloat(minGap) * f.scale - 10))
        for item in scene.spots { drawSpot(ctx, f, item, boxW: boxW) }

        // A target that is not on a spot.
        if let t = scene.target, !scene.spots.contains(where: \.isTarget), !scene.loose.contains(where: { $0.isTarget && $0.position != nil }) {
            let c = f.pt(t)
            ctx.fill(Path(ellipseIn: CGRect(x: c.x - 11, y: c.y - 11, width: 22, height: 22)), with: .color(Theme.target))
            ctx.draw(Text(scene.targetName ?? "target").font(.system(size: 15, weight: .bold)).foregroundColor(Theme.target),
                     at: CGPoint(x: c.x, y: c.y + 24))
        }

        ctx.fill(Path(ellipseIn: CGRect(x: you.x - 17, y: you.y - 17, width: 34, height: 34)), with: .color(Theme.head))
        ctx.draw(Text("You").font(.system(size: 13, weight: .bold)).foregroundColor(Theme.background), at: you)
        if scene.showsWalking { drawModeBadge(ctx, at: you) }
    }

    private func drawHead(_ ctx: GraphicsContext, _ f: Frame, at c: CGPoint) {
        let r = CGFloat(pose.facingBack ? Self.backConeLength : 0.8) * f.scale
        let yaw = pose.yaw
        var cone = Path()
        cone.move(to: c)
        cone.addArc(center: c, radius: r, startAngle: .degrees(yaw - 28 - 90), endAngle: .degrees(yaw + 28 - 90), clockwise: false)
        cone.closeSubpath()
        let a = yaw * .pi / 180
        let tip = CGPoint(x: c.x + r * CGFloat(sin(a)), y: c.y - r * CGFloat(cos(a)))
        ctx.fill(cone, with: .linearGradient(Gradient(colors: [Theme.head.opacity(pose.tracking ? 0.30 : 0.12), Theme.head.opacity(0.03)]),
                                             startPoint: c, endPoint: tip))
        ctx.stroke(cone, with: .color(Theme.head.opacity(0.5)), style: StrokeStyle(lineWidth: 1.2, dash: pose.tracking ? [] : [5, 5]))
        var nose = Path()
        nose.move(to: c)
        nose.addLine(to: CGPoint(x: c.x + r * 0.9 * CGFloat(sin(a)), y: c.y - r * 0.9 * CGFloat(cos(a))))
        ctx.stroke(nose, with: .color(Theme.head), style: StrokeStyle(lineWidth: 3, lineCap: .round))
    }

    /// Mode badge under the wearer dot: an icon plus the words, never color alone.
    private func drawModeBadge(_ ctx: GraphicsContext, at c: CGPoint) {
        let icon: String
        switch scene.listenerPose?.mode {
        case .tracked?: icon = "figure.walk"
        case .frozen?: icon = "pin.fill"
        case .lost?: icon = "questionmark.circle"
        case .fixed?, nil: icon = "lock.fill"
        }
        let text = (Text(Image(systemName: icon)) + Text(" " + scene.modeBadge))
            .font(.system(size: 12, weight: .bold))
            .foregroundColor(Theme.textPrimary)
        let resolved = ctx.resolve(text)
        let size = resolved.measure(in: CGSize(width: 240, height: 40))
        let rect = CGRect(x: c.x - size.width / 2 - 8, y: c.y + 22, width: size.width + 16, height: size.height + 6)
        let shape = Path(roundedRect: rect, cornerRadius: rect.height / 2)
        ctx.fill(shape, with: .color(Theme.surface))
        ctx.stroke(shape, with: .color(Theme.head), style: StrokeStyle(lineWidth: 1.5))
        ctx.draw(resolved, in: rect.insetBy(dx: 8, dy: 3))
    }

    /// The origin floor mark, drawn once the wearer has walked away from it.
    private func drawOriginMark(_ ctx: GraphicsContext, _ f: Frame) {
        let o = f.origin
        var plus = Path()
        plus.move(to: CGPoint(x: o.x - 9, y: o.y)); plus.addLine(to: CGPoint(x: o.x + 9, y: o.y))
        plus.move(to: CGPoint(x: o.x, y: o.y - 9)); plus.addLine(to: CGPoint(x: o.x, y: o.y + 9))
        ctx.stroke(plus, with: .color(Theme.textSecondary), style: StrokeStyle(lineWidth: 2, lineCap: .round))
        ctx.draw(Text("Counter mark").font(.system(size: 11, weight: .medium)).foregroundColor(Theme.textSecondary),
                 at: CGPoint(x: o.x + 12, y: o.y + 10), anchor: .leading)
    }

    /// An anchor: a triangle (filled = online, filled and struck through = blocked, dashed outline = offline or
    /// no report), its label, and its state spelled out with an icon and words.
    private func drawAnchor(_ ctx: GraphicsContext, _ f: Frame, _ a: UWBText.AnchorLine) {
        guard let p = a.position else { return }
        let c = f.pt(p)
        let s: CGFloat = 13
        var tri = Path()
        tri.move(to: CGPoint(x: c.x, y: c.y - s))
        tri.addLine(to: CGPoint(x: c.x + s, y: c.y + s * 0.75))
        tri.addLine(to: CGPoint(x: c.x - s, y: c.y + s * 0.75))
        tri.closeSubpath()
        let severity = MapList.anchorSeverity(a.state)
        switch a.state {
        case .online, .blocked:
            ctx.fill(tri, with: .color(Theme.textPrimary))
        case .offline, .unknown:
            ctx.fill(tri, with: .color(Theme.surface))
            ctx.stroke(tri, with: .color(Theme.textPrimary), style: StrokeStyle(lineWidth: 2, dash: [4, 3]))
        }
        if a.state == .blocked {
            var slash = Path()
            slash.move(to: CGPoint(x: c.x - s - 3, y: c.y + s + 2)); slash.addLine(to: CGPoint(x: c.x + s + 3, y: c.y - s - 2))
            ctx.stroke(slash, with: .color(severity.color), style: StrokeStyle(lineWidth: 3, lineCap: .round))
        }
        ctx.draw(Text(a.label).font(.system(size: 12, weight: .semibold)).foregroundColor(Theme.textPrimary),
                 at: CGPoint(x: c.x, y: c.y + s + 10))
        let dist = a.distanceM.map { String(format: ", %.1f m", $0) } ?? ""
        let status = (Text(Image(systemName: severity.symbol)).foregroundColor(severity.color)
                      + Text(" " + MapList.anchorWord(a.state) + dist).foregroundColor(Theme.textSecondary))
            .font(.system(size: 11, weight: .medium))
        ctx.draw(status, at: CGPoint(x: c.x, y: c.y + s + 25))
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
            if scene.showsWalking {
                VStack(alignment: .leading, spacing: 3) {
                    Text("WALKING - \(scene.modeBadge.uppercased())")
                        .font(.system(size: 10, weight: .semibold))
                        .tracking(0.5)
                        .foregroundStyle(Theme.textSecondary)
                    Text(scene.wearerLine)
                        .font(.system(size: 14, weight: .semibold))
                        .foregroundStyle(Theme.textPrimary)
                        .fixedSize(horizontal: false, vertical: true)
                }
                .frame(maxWidth: .infinity, alignment: .leading)
                .accessibilityElement(children: .combine)
                ForEach(scene.anchors) { a in
                    VStack(alignment: .leading, spacing: 3) {
                        Text(a.label.uppercased())
                            .font(.system(size: 10, weight: .semibold))
                            .tracking(0.5)
                            .foregroundStyle(Theme.textSecondary)
                        HStack(spacing: 4) {
                            Image(systemName: Self.anchorSeverity(a.state).symbol)
                                .foregroundStyle(Self.anchorSeverity(a.state).color)
                                .accessibilityHidden(true)
                            Text(Self.anchorWord(a.state) + (a.distanceM.map { String(format: ", %.1f m from you", $0) } ?? ""))
                                .font(.system(size: 14, weight: .semibold))
                                .foregroundStyle(Theme.textPrimary)
                                .fixedSize(horizontal: false, vertical: true)
                        }
                    }
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .accessibilityElement(children: .ignore)
                    .accessibilityLabel(a.text)
                }
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

    /// Anchor state as a severity shape (paired with words wherever it is shown).
    static func anchorSeverity(_ s: UWBText.AnchorState) -> Severity {
        switch s {
        case .online: .ok
        case .blocked: .warn
        case .offline: .bad
        case .unknown: .neutral
        }
    }

    static func anchorWord(_ s: UWBText.AnchorState) -> String {
        switch s {
        case .online: "online"
        case .blocked: "blocked"
        case .offline: "offline"
        case .unknown: "no report yet"
        }
    }
}
