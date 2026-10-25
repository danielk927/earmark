import Foundation

/// Tunables for guidance. Defaults follow brief 5.E and the guide_feedback schema description.
public struct GuidanceConfig: Sendable, Equatable {
    /// Ping interval at or beyond `farAngleDeg` of error.
    public var farIntervalSec: Double = 0.9
    /// Ping interval at or under `nearAngleDeg` of error.
    public var nearIntervalSec: Double = 0.15
    public var farAngleDeg: Double = 90
    public var nearAngleDeg: Double = 10
    /// Locked when |error| < lockEnterDeg continuously for more than lockDwellSec; unlocked when |error| > lockExitDeg.
    public var lockEnterDeg: Double = 8
    public var lockExitDeg: Double = 12
    public var lockDwellSec: Double = 0.3
    /// Behind when |error| > behindEnterDeg; back in front when |error| < behindExitDeg.
    public var behindEnterDeg: Double = 100
    public var behindExitDeg: Double = 95
    /// Walking guidance (PRD 10.2): the ping interval is multiplied by 1.0 within `nearDistanceM` of the target,
    /// rising linearly to `farDistanceFactor` at `farDistanceM` and beyond. Far = slower, close = faster.
    public var nearDistanceM: Double = 1.0
    public var farDistanceM: Double = 4.0
    public var farDistanceFactor: Double = 1.6

    public init() {}
}

public enum GuidanceZone: String, Sendable { case front, behind }
public enum TurnDirection: String, Sendable { case left, right }

/// Transitions only; the app maps behind/front/locked to bus `guide_feedback`.
public enum GuidanceEvent: Equatable, Sendable {
    case behind(turn: TurnDirection, errorDeg: Double)
    case front(errorDeg: Double)
    case locked(errorDeg: Double)
    case unlocked(errorDeg: Double)
}

public struct GuidanceState: Equatable, Sendable {
    /// Signed horizontal angle from the head direction to the target, degrees, positive = target to the right.
    public var errorDeg: Double
    public var targetAzimuthDeg: Double
    /// Shown in the debug panel only; it never affects ping rate, lock, or behind.
    public var targetElevationDeg: Double
    /// Horizontal distance from the listener to the target, meters.
    public var distanceM: Double
    public var pingIntervalSec: Double
    public var zone: GuidanceZone
    public var locked: Bool
    /// The shorter way to turn toward the target.
    public var turn: TurnDirection
}

/// Pure guidance math: head yaw vs the target's azimuth seen from the listener (target - listener).
/// With the listener at the origin (seated demo, UWB off) this is exactly the original origin-relative math.
///
/// Azimuth only (orchestrator decision): spots sit 30-45 cm below ear level and blind users orient
/// horizontally before reaching down, so a user facing the jar with a level head must reach "locked".
/// Rendering still uses the full 3D position with head yaw and pitch.
public struct Guidance: Sendable {
    public let config: GuidanceConfig
    public let target: EarmarkPoint
    public private(set) var zone: GuidanceZone?
    public private(set) var locked = false
    private var lockCandidateSince: Double?

    public init(target: EarmarkPoint, config: GuidanceConfig = GuidanceConfig()) {
        self.target = target
        self.config = config
    }

    /// Origin-relative (listener at the calibrated position).
    public var targetAzimuthDeg: Double { Geometry.azimuthDeg(target) }
    public var targetElevationDeg: Double { Geometry.elevationDeg(target) }

    public static func signedErrorDeg(targetAzimuthDeg: Double, headYawDeg: Double) -> Double {
        Angles.wrapDeg(targetAzimuthDeg - headYawDeg)
    }

    /// Shorter turn toward the target; exactly behind (180) resolves to right.
    public static func turn(forErrorDeg e: Double) -> TurnDirection {
        Angles.wrapDeg(e) >= 0 ? .right : .left
    }

    /// Smooth, monotonic curve from nearIntervalSec (|e| <= near) to farIntervalSec (|e| >= far), smoothstep in between.
    public static func pingInterval(errorDeg: Double, config: GuidanceConfig = GuidanceConfig()) -> Double {
        let a = abs(Angles.wrapDeg(errorDeg))
        let span = config.farAngleDeg - config.nearAngleDeg
        let x = span > 0 ? min(max((a - config.nearAngleDeg) / span, 0), 1) : (a > config.nearAngleDeg ? 1 : 0)
        let s = x * x * (3 - 2 * x)
        return config.nearIntervalSec + (config.farIntervalSec - config.nearIntervalSec) * s
    }

    /// 1.0 within `nearDistanceM`, linear to `farDistanceFactor` at `farDistanceM`, clamped beyond.
    public static func distanceFactor(distanceM d: Double, config: GuidanceConfig = GuidanceConfig()) -> Double {
        let span = config.farDistanceM - config.nearDistanceM
        let x = span > 0 ? min(max((d - config.nearDistanceM) / span, 0), 1) : (d > config.nearDistanceM ? 1 : 0)
        return 1 + (config.farDistanceFactor - 1) * x
    }

    /// Angle curve times the distance factor.
    public static func pingInterval(errorDeg: Double, distanceM: Double, config: GuidanceConfig = GuidanceConfig()) -> Double {
        pingInterval(errorDeg: errorDeg, config: config) * distanceFactor(distanceM: distanceM, config: config)
    }

    /// Seated (listener at the origin). Kept so existing callers and tests compile unchanged.
    public mutating func update(headYawDeg: Double, now: Double) -> (state: GuidanceState, events: [GuidanceEvent]) {
        update(headYawDeg: headYawDeg, listener: .zero, now: now)
    }

    /// Advances the state machine. Call at a steady rate (the app ticks at 50 Hz).
    /// Behind, locked, and the ping rate all come from the vector target - listener.
    public mutating func update(headYawDeg: Double, listener: EarmarkPoint, now: Double) -> (state: GuidanceState, events: [GuidanceEvent]) {
        let az = Geometry.azimuthDeg(target, from: listener)
        let dist = Geometry.horizontalDistance(target, from: listener)
        let e = Self.signedErrorDeg(targetAzimuthDeg: az, headYawDeg: headYawDeg)
        let a = abs(e)
        var events: [GuidanceEvent] = []

        switch zone {
        case nil:
            if a > config.behindEnterDeg {
                zone = .behind
                events.append(.behind(turn: Self.turn(forErrorDeg: e), errorDeg: e))
            } else {
                zone = .front
            }
        case .front?:
            if a > config.behindEnterDeg {
                zone = .behind
                events.append(.behind(turn: Self.turn(forErrorDeg: e), errorDeg: e))
            }
        case .behind?:
            if a < config.behindExitDeg {
                zone = .front
                events.append(.front(errorDeg: e))
            }
        }

        if locked {
            if a > config.lockExitDeg {
                locked = false
                lockCandidateSince = nil
                events.append(.unlocked(errorDeg: e))
            }
        } else if a < config.lockEnterDeg {
            if let since = lockCandidateSince {
                if now - since > config.lockDwellSec {
                    locked = true
                    events.append(.locked(errorDeg: e))
                }
            } else {
                lockCandidateSince = now
            }
        } else {
            lockCandidateSince = nil
        }

        let state = GuidanceState(
            errorDeg: e,
            targetAzimuthDeg: az,
            targetElevationDeg: Geometry.elevationDeg(target, from: listener),
            distanceM: dist,
            pingIntervalSec: Self.pingInterval(errorDeg: e, distanceM: dist, config: config),
            zone: zone ?? .front,
            locked: locked,
            turn: Self.turn(forErrorDeg: e)
        )
        return (state, events)
    }
}
