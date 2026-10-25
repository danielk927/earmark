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
    /// With a locator fix: the ping speeds up to this share of its interval when the target is at your feet, and is full speed from `proximityFarM` away.
    public var proximityMinScale: Double = 0.4
    public var proximityFarM: Double = 3
    /// Ping loudness runs from full at `gainNearM` to `gainFarGain` at `gainFarM` and beyond.
    public var gainNearM: Double = 0.5
    public var gainFarM: Double = 4
    public var gainFarGain: Float = 0.25
    /// Within this horizontal distance the user has arrived.
    public var arriveM: Double = 0.5

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

/// Pure guidance math: head yaw vs the target's azimuth. The target is stored relative to the listener
/// (the app calls `retarget` as the user walks), so the listener is always the origin.
///
/// Azimuth only (orchestrator decision): spots sit 30-45 cm below ear level and blind users orient
/// horizontally before reaching down, so a user facing the jar with a level head must reach "locked".
/// Rendering still uses the full 3D position with head yaw and pitch.
public struct Guidance: Sendable {
    public let config: GuidanceConfig
    public private(set) var target: EarmarkPoint
    public private(set) var zone: GuidanceZone?
    public private(set) var locked = false
    private var lockCandidateSince: Double?

    public init(target: EarmarkPoint, config: GuidanceConfig = GuidanceConfig()) {
        self.target = target
        self.config = config
    }

    /// The target moved relative to the listener (the locator says the user walked). Lock and zone carry over.
    public mutating func retarget(_ p: EarmarkPoint) { target = p }

    /// Ping interval multiplier for a locator distance: 1 far away, `proximityMinScale` at your feet.
    public static func proximityScale(distanceM: Double?, config: GuidanceConfig = GuidanceConfig()) -> Double {
        guard let d = distanceM else { return 1 }
        let x = min(max(d / config.proximityFarM, 0), 1)
        return config.proximityMinScale + (1 - config.proximityMinScale) * x
    }

    /// Loudness for a locator distance: louder as the user walks toward the target.
    public static func proximityGain(distanceM: Double?, config: GuidanceConfig = GuidanceConfig()) -> Float {
        guard let d = distanceM else { return 1 }
        let x = min(max((d - config.gainNearM) / (config.gainFarM - config.gainNearM), 0), 1)
        return 1 - (1 - config.gainFarGain) * Float(x)
    }

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

    /// Advances the state machine. Call at a steady rate (the app ticks at 50 Hz).
    /// `distanceM` is the locator's distance (nil without a fix); the target vector is already relative to the listener.
    public mutating func update(headYawDeg: Double, now: Double, distanceM: Double? = nil) -> (state: GuidanceState, events: [GuidanceEvent]) {
        let az = targetAzimuthDeg
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
            targetElevationDeg: targetElevationDeg,
            distanceM: Geometry.horizontalDistance(target),
            pingIntervalSec: Self.pingInterval(errorDeg: e, config: config) * Self.proximityScale(distanceM: distanceM, config: config),
            zone: zone ?? .front,
            locked: locked,
            turn: Self.turn(forErrorDeg: e)
        )
        return (state, events)
    }
}
