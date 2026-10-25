import Foundation

/// The ONLY place where CoreMotion head angles are mapped to Earmark head angles.
///
/// Earmark convention (brief 4.1, contracts/README.md): yaw is degrees from the calibrated forward
/// direction, positive when the head turns RIGHT; pitch is positive when looking UP.
///
/// Everything downstream (renderers, guidance, bus `head_pose`) uses Earmark angles, so flipping a
/// sign here is a one-line change that fixes the whole app.
public enum HeadSigns {
    /// CoreMotion attitude yaw follows the right-hand rule about the vertical +Z axis, so it is positive
    /// when the head turns LEFT (counterclockwise seen from above). Earmark wants positive = RIGHT, hence -1.
    /// Derived from Apple's axis figures, UNVERIFIED on hardware (docs/sponsors/vendor-notes/apple-spatial-audio.md section 1).
    ///
    /// On-device sign check (mac/README.md, gate step 1): open SpatialSpike, press Recenter facing forward,
    /// then turn your head to the RIGHT. The yaw readout must go POSITIVE, and a ping placed at 0 deg must
    /// move into your LEFT ear. If the readout goes negative (or the ping moves the wrong way), change this
    /// value to +1, run `mac/build_app.sh`, and repeat the check.
    public static let yawSign: Double = -1

    /// CoreMotion attitude pitch is rotation about the headphone X axis. If X points out of the right ear,
    /// looking up is positive, hence +1. UNVERIFIED on hardware.
    ///
    /// On-device check: face forward, press Recenter, then look UP. The pitch readout must go POSITIVE.
    /// If it goes negative, change this value to -1 and rebuild. If nodding moves the roll readout instead
    /// of pitch, the axes are swapped on that AirPods model: note it in docs/project/STATUS.md (elevation is a weak
    /// cue anyway, and guidance uses azimuth only).
    public static let pitchSign: Double = 1

    /// Earmark yaw in degrees from a CoreMotion relative yaw in radians.
    public static func earmarkYawDeg(coreMotionYawRad: Double) -> Double {
        Angles.wrapDeg(yawSign * coreMotionYawRad * 180 / .pi)
    }

    /// Earmark pitch in degrees from a CoreMotion relative pitch in radians.
    public static func earmarkPitchDeg(coreMotionPitchRad: Double) -> Double {
        pitchSign * coreMotionPitchRad * 180 / .pi
    }
}
