import AppKit
import SwiftUI

/// Calm, high-contrast palette with explicit light and dark values.
/// Text colors keep at least 7:1 contrast on their surfaces; accents at least 4.5:1.
public enum Theme {
    static func dynamic(light: UInt32, dark: UInt32) -> Color {
        Color(nsColor: NSColor(name: nil) { appearance in
            let isDark = appearance.bestMatch(from: [.darkAqua, .aqua]) == .darkAqua
            return NSColor(hex: isDark ? dark : light)
        })
    }

    public static let background = dynamic(light: 0xF2F1EC, dark: 0x0D1014)
    public static let surface = dynamic(light: 0xFFFFFF, dark: 0x161A20)
    public static let surfaceSunken = dynamic(light: 0xE9E7E0, dark: 0x11151A)
    public static let border = dynamic(light: 0xCFCCC2, dark: 0x2A313B)
    public static let textPrimary = dynamic(light: 0x13161B, dark: 0xF3F4F6)
    public static let textSecondary = dynamic(light: 0x474E5A, dark: 0xA8B0BC)
    /// The target (amber).
    public static let target = dynamic(light: 0x8F5400, dark: 0xFFB547)
    /// The head and its direction cone (blue).
    public static let head = dynamic(light: 0x0A5FA0, dark: 0x63C7FF)
    public static let ok = dynamic(light: 0x166534, dark: 0x4ADE80)
    public static let warn = dynamic(light: 0x92400E, dark: 0xFBBF24)
    public static let bad = dynamic(light: 0xB91C1C, dark: 0xF87171)
    public static let grid = dynamic(light: 0xD9D6CC, dark: 0x232A33)

    public static let corner: CGFloat = 14
}

extension NSColor {
    convenience init(hex: UInt32) {
        self.init(srgbRed: CGFloat((hex >> 16) & 0xFF) / 255, green: CGFloat((hex >> 8) & 0xFF) / 255,
                  blue: CGFloat(hex & 0xFF) / 255, alpha: 1)
    }
}

public enum Severity: Sendable {
    case ok, warn, bad, neutral

    public var color: Color {
        switch self {
        case .ok: Theme.ok
        case .warn: Theme.warn
        case .bad: Theme.bad
        case .neutral: Theme.textSecondary
        }
    }

    /// A distinct shape per severity, so state is never conveyed by color alone.
    public var symbol: String {
        switch self {
        case .ok: "checkmark.circle.fill"
        case .warn: "exclamationmark.triangle.fill"
        case .bad: "xmark.octagon.fill"
        case .neutral: "circle.dashed"
        }
    }

    public var spoken: String {
        switch self {
        case .ok: "OK"
        case .warn: "Warning"
        case .bad: "Problem"
        case .neutral: "Inactive"
        }
    }
}

/// A card surface used for every panel.
public struct Card<Content: View>: View {
    let title: String?
    let fillHeight: Bool
    let content: Content

    public init(_ title: String? = nil, fillHeight: Bool = false, @ViewBuilder content: () -> Content) {
        self.title = title
        self.fillHeight = fillHeight
        self.content = content()
    }

    public var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            if let title {
                Text(title.uppercased())
                    .font(.system(size: 12, weight: .semibold))
                    .tracking(1.1)
                    .foregroundStyle(Theme.textSecondary)
                    .accessibilityAddTraits(.isHeader)
            }
            content
        }
        .padding(18)
        .frame(maxWidth: .infinity, maxHeight: fillHeight ? .infinity : nil, alignment: .topLeading)
        .background(Theme.surface, in: RoundedRectangle(cornerRadius: Theme.corner, style: .continuous))
        .overlay(RoundedRectangle(cornerRadius: Theme.corner, style: .continuous).strokeBorder(Theme.border, lineWidth: 1))
    }
}

/// One status item: icon, label, value, and a severity shape.
public struct StatusPill: View {
    let icon: String
    let label: String
    let value: String
    let severity: Severity

    public init(icon: String, label: String, value: String, severity: Severity) {
        self.icon = icon; self.label = label; self.value = value; self.severity = severity
    }

    public var body: some View {
        HStack(spacing: 10) {
            Image(systemName: icon)
                .font(.system(size: 17, weight: .medium))
                .foregroundStyle(Theme.textSecondary)
                .frame(width: 22)
            VStack(alignment: .leading, spacing: 2) {
                Text(label)
                    .font(.system(size: 11, weight: .semibold))
                    .tracking(0.6)
                    .foregroundStyle(Theme.textSecondary)
                HStack(spacing: 6) {
                    Image(systemName: severity.symbol)
                        .font(.system(size: 12, weight: .bold))
                        .foregroundStyle(severity.color)
                    Text(value)
                        .font(.system(size: 14, weight: .semibold))
                        .foregroundStyle(Theme.textPrimary)
                        .lineLimit(1)
                        .truncationMode(.middle)
                }
            }
        }
        .padding(.horizontal, 12)
        .padding(.vertical, 7)
        .frame(minWidth: 120, maxWidth: .infinity, alignment: .leading)
        .background(Theme.surfaceSunken, in: RoundedRectangle(cornerRadius: 10, style: .continuous))
        .accessibilityElement(children: .ignore)
        .accessibilityLabel("\(label): \(value). \(severity.spoken).")
    }
}

/// Large primary action button (Recenter).
public struct BigButtonStyle: ButtonStyle {
    let tint: Color
    public init(tint: Color = Theme.head) { self.tint = tint }

    public func makeBody(configuration: Configuration) -> some View {
        configuration.label
            .font(.system(size: 17, weight: .semibold))
            .foregroundStyle(Theme.background)
            .padding(.vertical, 14)
            .padding(.horizontal, 18)
            .frame(maxWidth: .infinity)
            .background(tint.opacity(configuration.isPressed ? 0.75 : 1), in: RoundedRectangle(cornerRadius: 12, style: .continuous))
            .contentShape(RoundedRectangle(cornerRadius: 12))
    }
}

/// Secondary button: outlined.
public struct QuietButtonStyle: ButtonStyle {
    var selected: Bool
    public init(selected: Bool = false) { self.selected = selected }

    public func makeBody(configuration: Configuration) -> some View {
        configuration.label
            .font(.system(size: 14, weight: .semibold))
            .foregroundStyle(selected ? Theme.background : Theme.textPrimary)
            .padding(.vertical, 9)
            .padding(.horizontal, 12)
            .frame(maxWidth: .infinity)
            .background(selected ? Theme.textPrimary : Theme.surfaceSunken.opacity(configuration.isPressed ? 0.6 : 1),
                        in: RoundedRectangle(cornerRadius: 9, style: .continuous))
            .overlay(RoundedRectangle(cornerRadius: 9, style: .continuous).strokeBorder(Theme.border, lineWidth: 1))
            .contentShape(RoundedRectangle(cornerRadius: 9))
    }
}

/// Formats degrees with an explicit sign and the word for the side.
public func signedDegrees(_ d: Double, decimals: Int = 0) -> String {
    let v = decimals == 0 ? String(format: "%+.0f", d) : String(format: "%+.\(decimals)f", d)
    return v + "\u{00B0}"
}
