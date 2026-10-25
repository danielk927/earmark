import Foundation
import simd

/// One beacon's clock model on the receiver's audio clock (B4): arrival ≈ a + b·n at the calibration point.
struct BeaconTiming {
    let a: Double           // s, audio clock
    let b: Double           // s, cycle length on the receiver's clock
    let d: Double           // m, distance from the calibration point
    let sigma: Double       // s, timing noise
    let phase: Double       // s, wall-clock phase of a within the cycle
    let kept: Int

    /// The measured range for an arrival at audio time t (B5).
    func range(arrival t: Double, speedOfSound c: Double) -> Double {
        let n = ((t - a) / b).rounded()
        return c * (t - a - b * n) + d
    }
}

struct Calibration {
    let beacons: [BeaconTiming]
}

enum Calibrator {
    /// Fits every beacon from the detections collected during calibration.
    static func fit(config: RoomConfig, detections: [Detection], elapsed: Double) -> (CalibrationReport, Calibration?) {
        let c = config.speedOfSound
        let center = config.calibrationPosition
        let positions = config.beaconPositions
        var problems: [String] = []
        if elapsed < Parameters.calibrationDuration {
            problems.append(String(format: "Calibration ran %.1f s; it needs %.0f s.", elapsed, Parameters.calibrationDuration))
        }

        var timings: [BeaconTiming?] = []
        var reports: [BeaconCalibration] = []
        for (k, beacon) in config.beacons.enumerated() {
            let own = detections.filter { $0.beacon == k }.sorted { $0.arrivalTime < $1.arrivalTime }
            guard let first = own.first, let fit = robustFit(own.map(\.arrivalTime)) else {
                problems.append("\(beacon.id): only \(own.count) detections; it needs \(Parameters.minCalibrationDetections).")
                timings.append(nil)
                reports.append(BeaconCalibration(id: beacon.id, detections: own.count, residualCm: 0, phaseSeconds: 0))
                continue
            }
            let wallOffset = first.wallClock - first.arrivalTime
            let phase = positiveRemainder(fit.a + wallOffset, Parameters.cycle)
            let timing = BeaconTiming(a: fit.a, b: fit.b, d: simd_distance(center, positions[k]), sigma: fit.sigma, phase: phase, kept: fit.kept)
            timings.append(timing)
            reports.append(BeaconCalibration(id: beacon.id, detections: fit.kept, residualCm: fit.sigma * c * 100, phaseSeconds: phase))

            if fit.kept < Parameters.minCalibrationDetections {
                problems.append("\(beacon.id): only \(fit.kept) good detections; it needs \(Parameters.minCalibrationDetections).")
            }
            if fit.sigma * c > Parameters.maxCalibrationResidual {
                problems.append(String(format: "%@: timing noise is %.1f cm; the limit is %.0f cm.",
                                       beacon.id, fit.sigma * c * 100, Parameters.maxCalibrationResidual * 100))
            }
        }

        for i in 0..<timings.count {
            for j in (i + 1)..<timings.count {
                guard let ti = timings[i], let tj = timings[j] else { continue }
                let gap = abs(ti.phase - tj.phase)
                let circular = min(gap, Parameters.cycle - gap)
                if circular < Parameters.minSlotGap {
                    problems.append(String(format: "%@ and %@ arrive %.0f ms apart; they need %.0f ms.",
                                           config.beacons[i].id, config.beacons[j].id, circular * 1000, Parameters.minSlotGap * 1000))
                }
            }
        }

        let report = CalibrationReport(ok: problems.isEmpty, beacons: reports, problems: problems)
        guard problems.isEmpty else { return (report, nil) }
        return (report, Calibration(beacons: timings.map { $0! }))
    }

    struct Fit { let a: Double; let b: Double; let sigma: Double; let kept: Int }

    /// Fit t ≈ a + b·n (B4 steps 1–4). It starts from a Theil–Sen line (median of pairwise slopes),
    /// which a clump of echo detections can't tilt, then trims points more than
    /// max(3·MAD, 30 µs) from the median residual and refits by least squares, three times.
    static func robustFit(_ times: [Double]) -> Fit? {
        guard let t1 = times.first, times.count >= 2 else { return nil }
        let n = times.map { (($0 - t1) / Parameters.cycle).rounded() }
        var slopes: [Double] = []
        for i in n.indices { for j in (i + 1)..<n.count where n[j] != n[i] { slopes.append((times[j] - times[i]) / (n[j] - n[i])) } }
        guard !slopes.isEmpty else { return nil }
        let b0 = median(slopes)
        var line = (a: median(zip(n, times).map { $1 - b0 * $0 }), b: b0)
        var keep = Array(repeating: true, count: times.count)
        for _ in 0..<Parameters.robustFitPasses {
            let residuals = zip(n, times).map { $1 - (line.a + line.b * $0) }
            let med = median(residuals)
            let mad = 1.4826 * median(residuals.map { abs($0 - med) })
            let limit = max(Parameters.madMultiplier * mad, Parameters.residualFloor)
            keep = residuals.map { abs($0 - med) < limit }
            guard let refit = leastSquares(n, times, keep) else { return nil }
            line = refit
        }
        let kept = zip(n, times).enumerated().filter { keep[$0.offset] }.map { $0.element.1 - (line.a + line.b * $0.element.0) }
        let mean = kept.reduce(0, +) / Double(kept.count)
        let variance = kept.reduce(0) { $0 + ($1 - mean) * ($1 - mean) } / Double(max(kept.count - 1, 1))
        return Fit(a: line.a, b: line.b, sigma: max(variance.squareRoot(), Parameters.timingNoiseFloor), kept: kept.count)
    }

    private static func leastSquares(_ x: [Double], _ y: [Double], _ use: [Bool]) -> (a: Double, b: Double)? {
        var count = 0.0, sx = 0.0, sy = 0.0, sxx = 0.0, sxy = 0.0
        for i in x.indices where use[i] {
            count += 1; sx += x[i]; sy += y[i]; sxx += x[i] * x[i]; sxy += x[i] * y[i]
        }
        let det = count * sxx - sx * sx
        guard count >= 2, det > 0 else { return nil }
        let b = (count * sxy - sx * sy) / det
        return ((sy - b * sx) / count, b)
    }

    private static func median(_ values: [Double]) -> Double {
        let s = values.sorted()
        return s.count % 2 == 1 ? s[s.count / 2] : 0.5 * (s[s.count / 2 - 1] + s[s.count / 2])
    }
}

func positiveRemainder(_ x: Double, _ m: Double) -> Double {
    let r = x.truncatingRemainder(dividingBy: m)
    return r < 0 ? r + m : r
}
