import SwiftUI

/// Top-down dial: forward is up, positive angles are clockwise (to the right), matching Earmark yaw.
/// Shows the head direction cone, an optional target, and an optional response marker the operator
/// can set by clicking or dragging (the pointing test).
public struct AngleDial: View {
    let headYaw: Double
    let target: Double?
    let response: Binding<Double?>?
    let label: String

    public init(headYaw: Double, target: Double?, response: Binding<Double?>? = nil, label: String) {
        self.headYaw = headYaw
        self.target = target
        self.response = response
        self.label = label
    }

    private static let cardinal: [(Double, String)] = [(0, "Front"), (90, "Right"), (180, "Back"), (-90, "Left")]

    public var body: some View {
        GeometryReader { geo in
            dial(size: geo.size)
        }
        .aspectRatio(1, contentMode: .fit)
        .accessibilityElement(children: .ignore)
        .accessibilityLabel(label)
        .accessibilityValue(accessibilityValue)
    }

    private func dial(size: CGSize) -> some View {
        let center = CGPoint(x: size.width / 2, y: size.height / 2)
        let radius: CGFloat = min(size.width, size.height) / 2 - 34
        return ZStack {
            Canvas { ctx, _ in draw(ctx, center: center, radius: radius) }
            ForEach(0..<4, id: \.self) { i in
                cardinalLabel(i, center: center, radius: radius)
            }
        }
        .contentShape(Rectangle())
        .gesture(DragGesture(minimumDistance: 0).onChanged { v in setResponse(v.location, center: center) })
    }

    private func cardinalLabel(_ i: Int, center: CGPoint, radius: CGFloat) -> some View {
        let (angle, name) = Self.cardinal[i]
        return Text(name)
            .font(.system(size: 11, weight: .semibold))
            .foregroundStyle(Theme.textSecondary)
            .position(point(center, radius + 21, angle))
            .accessibilityHidden(true)
    }

    private func setResponse(_ loc: CGPoint, center: CGPoint) {
        guard let response else { return }
        let dx = Double(loc.x - center.x), dy = Double(loc.y - center.y)
        guard (dx * dx + dy * dy).squareRoot() > 12 else { return }
        let a = atan2(dx, -dy) * 180 / .pi
        response.wrappedValue = (a / 5).rounded() * 5
    }

    private var accessibilityValue: String {
        var parts = ["Head \(Int(headYaw.rounded())) degrees"]
        if let target { parts.append("target \(Int(target.rounded())) degrees") }
        if let r = response?.wrappedValue { parts.append("response \(Int(r.rounded())) degrees") }
        return parts.joined(separator: ", ")
    }

    private func point(_ c: CGPoint, _ r: CGFloat, _ deg: Double) -> CGPoint {
        let a = deg * .pi / 180
        return CGPoint(x: c.x + r * CGFloat(sin(a)), y: c.y - r * CGFloat(cos(a)))
    }

    private func draw(_ ctx: GraphicsContext, center c: CGPoint, radius r: CGFloat) {
        // Rings and ticks every 15 degrees.
        let ring = Path(ellipseIn: CGRect(x: c.x - r, y: c.y - r, width: 2 * r, height: 2 * r))
        ctx.stroke(ring, with: .color(Theme.border), lineWidth: 1.5)
        for k in 0..<24 {
            let a = Double(k) * 15
            var tick = Path()
            let inner: CGFloat = k % 6 == 0 ? r - 14 : (k % 2 == 0 ? r - 9 : r - 5)
            tick.move(to: point(c, inner, a)); tick.addLine(to: point(c, r, a))
            ctx.stroke(tick, with: .color(Theme.textSecondary.opacity(k % 6 == 0 ? 0.9 : 0.5)), lineWidth: k % 6 == 0 ? 2 : 1)
        }
        // Head cone (+-25 deg).
        var cone = Path()
        cone.move(to: c)
        cone.addArc(center: c, radius: r * 0.82, startAngle: .degrees(headYaw - 25 - 90), endAngle: .degrees(headYaw + 25 - 90), clockwise: false)
        cone.closeSubpath()
        ctx.fill(cone, with: .color(Theme.head.opacity(0.22)))
        var nose = Path()
        nose.move(to: c); nose.addLine(to: point(c, r * 0.82, headYaw))
        ctx.stroke(nose, with: .color(Theme.head), style: StrokeStyle(lineWidth: 3, lineCap: .round))
        ctx.fill(Path(ellipseIn: CGRect(x: c.x - 9, y: c.y - 9, width: 18, height: 18)), with: .color(Theme.head))

        if let target {
            let p = point(c, r * 0.68, target)
            ctx.fill(Path(ellipseIn: CGRect(x: p.x - 10, y: p.y - 10, width: 20, height: 20)), with: .color(Theme.target))
            ctx.stroke(Path(ellipseIn: CGRect(x: p.x - 16, y: p.y - 16, width: 32, height: 32)), with: .color(Theme.target), lineWidth: 2)
        }
        if let resp = response?.wrappedValue {
            let p = point(c, r * 0.68, resp)
            var x = Path()
            x.move(to: CGPoint(x: p.x - 9, y: p.y - 9)); x.addLine(to: CGPoint(x: p.x + 9, y: p.y + 9))
            x.move(to: CGPoint(x: p.x + 9, y: p.y - 9)); x.addLine(to: CGPoint(x: p.x - 9, y: p.y + 9))
            ctx.stroke(x, with: .color(Theme.textPrimary), style: StrokeStyle(lineWidth: 3.5, lineCap: .round))
            var ray = Path()
            ray.move(to: c); ray.addLine(to: point(c, r * 0.6, resp))
            ctx.stroke(ray, with: .color(Theme.textPrimary.opacity(0.5)), style: StrokeStyle(lineWidth: 1.5, dash: [4, 4]))
        }
    }
}
