import AVFAudio
import Foundation
import simd

/// A point in Earmark coordinates: meters, +x right, +y forward, +z up, origin = calibrated head position.
public typealias EarmarkPoint = SIMD3<Double>

public enum Angles {
    /// Wraps an angle in degrees into (-180, 180].
    public static func wrapDeg(_ a: Double) -> Double {
        guard a.isFinite else { return 0 }
        var r = a.truncatingRemainder(dividingBy: 360)
        if r <= -180 { r += 360 }
        if r > 180 { r -= 360 }
        return r
    }
}

public enum Geometry {
    /// Earmark world point -> AVAudio3DPoint (and PHASE): +x right, +y up, -z forward.
    /// The matrix [[1,0,0],[0,0,1],[0,-1,0]] has determinant +1 (a rotation, no mirror).
    /// VERIFIED LOCALLY by offline rendering (docs/vendor-notes/apple-spatial-audio.md section 2).
    public static func avPoint(_ p: EarmarkPoint) -> AVAudio3DPoint {
        AVAudio3DPoint(x: Float(p.x), y: Float(p.z), z: Float(-p.y))
    }

    /// Azimuth in degrees from forward (+y), positive to the right (+x). atan2(x, y).
    public static func azimuthDeg(_ p: EarmarkPoint) -> Double {
        if p.x == 0 && p.y == 0 { return 0 }
        return atan2(p.x, p.y) * 180 / .pi
    }

    /// Elevation in degrees above the horizontal plane, positive up.
    public static func elevationDeg(_ p: EarmarkPoint) -> Double {
        let h = (p.x * p.x + p.y * p.y).squareRoot()
        if h == 0 && p.z == 0 { return 0 }
        return atan2(p.z, h) * 180 / .pi
    }

    /// Horizontal distance from the listener in meters.
    public static func horizontalDistance(_ p: EarmarkPoint) -> Double {
        (p.x * p.x + p.y * p.y).squareRoot()
    }

    // Listener-relative versions (UWB walking guidance, PRD 10.2): everything is computed from the vector
    // target - listener, so a listener at the origin gives exactly the origin-relative values above.

    /// Azimuth of `target` seen from `listener`, degrees from forward (+y), positive to the right.
    public static func azimuthDeg(_ target: EarmarkPoint, from listener: EarmarkPoint) -> Double {
        azimuthDeg(target - listener)
    }

    /// Elevation of `target` seen from `listener`, degrees, positive up.
    public static func elevationDeg(_ target: EarmarkPoint, from listener: EarmarkPoint) -> Double {
        elevationDeg(target - listener)
    }

    /// Horizontal distance from `listener` to `target` in meters.
    public static func horizontalDistance(_ target: EarmarkPoint, from listener: EarmarkPoint) -> Double {
        horizontalDistance(target - listener)
    }

    /// A point at the given azimuth (deg, + right), elevation (deg, + up), and distance (m).
    public static func point(azimuthDeg az: Double, elevationDeg el: Double = 0, distance d: Double = 1) -> EarmarkPoint {
        let a = az * .pi / 180, e = el * .pi / 180
        return EarmarkPoint(d * cos(e) * sin(a), d * cos(e) * cos(a), d * sin(e))
    }

    /// Contract `Vec3` ([Double] with 3 items) to a point.
    public static func point(_ v: [Double]) -> EarmarkPoint? {
        guard v.count == 3, v.allSatisfy(\.isFinite) else { return nil }
        return EarmarkPoint(v[0], v[1], v[2])
    }

    /// Clock-face hour (1...12) for an azimuth relative to the head, 12 = straight ahead, 3 = right.
    public static func clockHour(azimuthDeg az: Double) -> Int {
        let h = Int((Angles.wrapDeg(az) / 30).rounded())
        let r = ((h % 12) + 12) % 12
        return r == 0 ? 12 : r
    }
}

/// Glides the listener position to each new target in a straight line over `duration` seconds
/// (PRD 10.1, hub `uwb.blend_s`, default 0.4 s), so the audio never jumps. Pure; EarmarkCore samples it every tick
/// and hands the result to the renderer, so every renderer (and guidance) gets the same smooth path.
/// A new target restarts the glide from wherever the listener is now; the same target again is ignored.
/// ponytail: linear restart-per-update; at a steady walk it trails by about `duration` x speed. Lower the
/// glide in Settings if that lag is audible.
public struct ListenerGlide: Sendable, Equatable {
    public var duration: Double
    public private(set) var from: EarmarkPoint
    public private(set) var to: EarmarkPoint
    private var startT = -Double.infinity

    public init(duration: Double = 0.4, position: EarmarkPoint = .zero) {
        self.duration = duration
        self.from = position
        self.to = position
    }

    public mutating func setTarget(_ p: EarmarkPoint, now: Double) {
        guard p != to else { return }
        from = position(at: now)
        to = p
        startT = now
    }

    public func position(at now: Double) -> EarmarkPoint {
        guard duration > 0 else { return to }
        let u = min(max((now - startT) / duration, 0), 1)
        return from + (to - from) * u
    }

    /// Meters per second on the current leg: the most the listener can move in `dt` is `speed * dt`.
    public var speed: Double { duration > 0 ? simd_distance(from, to) / duration : .infinity }
}

/// Wrap-aware exponential smoothing for angles in degrees.
/// alpha = 1 - exp(-dt / tau); with tau <= 40 ms the added lag is under one AirPods motion sample.
public struct AngleSmoother: Sendable {
    public var timeConstant: Double
    public private(set) var value: Double?
    private var lastT: Double?

    public init(timeConstant: Double = 0.03) { self.timeConstant = timeConstant }

    public mutating func reset() { value = nil; lastT = nil }

    public mutating func update(_ angleDeg: Double, t: Double) -> Double {
        guard let v = value, let lt = lastT, timeConstant > 0 else {
            value = Angles.wrapDeg(angleDeg); lastT = t
            return value!
        }
        let dt = max(0, t - lt)
        let alpha = 1 - exp(-dt / timeConstant)
        let next = Angles.wrapDeg(v + alpha * Angles.wrapDeg(angleDeg - v))
        value = next; lastT = t
        return next
    }
}

/// Measures an event rate over a sliding window.
public struct RateMeter: Sendable {
    public let window: Double
    private var stamps: [Double] = []

    public init(window: Double = 1.0) { self.window = window }

    public mutating func record(_ t: Double) {
        stamps.append(t)
        prune(now: t)
    }

    public mutating func prune(now: Double) {
        let cutoff = now - window
        if let i = stamps.firstIndex(where: { $0 > cutoff }) {
            if i > 0 { stamps.removeFirst(i) }
        } else {
            stamps.removeAll()
        }
    }

    /// Events per second over the window, computed from the span of the recorded stamps.
    public func rate(now: Double) -> Double {
        let live = stamps.filter { $0 > now - window }
        guard live.count >= 2, let first = live.first, let last = live.last, last > first else { return 0 }
        return Double(live.count - 1) / (last - first)
    }
}
