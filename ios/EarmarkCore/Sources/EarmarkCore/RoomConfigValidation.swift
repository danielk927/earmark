import Foundation
import simd

public struct RoomConfigError: Error, CustomStringConvertible {
    public let description: String
}

extension RoomConfig {
    func validate() throws {
        func fail(_ message: String) -> RoomConfigError { RoomConfigError(description: "scene.json: " + message) }
        func close(_ a: Double, _ b: Double) -> Bool { abs(a - b) <= 1e-9 * max(1, abs(b)) }

        // The detector is built for exactly one chirp shape and schedule (C3).
        guard close(chirp.f0, Parameters.f0), close(chirp.f1, Parameters.f1), close(chirp.duration, Parameters.chirpDuration) else {
            throw fail("chirp must be \(Parameters.f0)–\(Parameters.f1) Hz, \(Parameters.chirpDuration) s")
        }
        guard close(cycleSeconds, Parameters.cycle), close(slotSeconds, Parameters.slotSpacing) else {
            throw fail("cycleSeconds must be \(Parameters.cycle) and slotSeconds \(Parameters.slotSpacing)")
        }
        guard (1...Parameters.maxBeacons).contains(beacons.count) else {
            throw fail("needs 1 to \(Parameters.maxBeacons) beacons, found \(beacons.count)")
        }
        guard Set(beacons.map(\.id)).count == beacons.count else { throw fail("beacon ids must be unique") }
        guard Set(beacons.map(\.slot)).count == beacons.count else { throw fail("beacon slots must be unique") }
        for beacon in beacons {
            guard (0..<Parameters.maxBeacons).contains(beacon.slot) else { throw fail("\(beacon.id): slot must be 0...3") }
            guard beacon.position.count == 3 else { throw fail("\(beacon.id): position needs 3 numbers") }
        }
        guard calibrationPoint.count == 3 else { throw fail("calibrationPoint needs 3 numbers") }
        for destination in destinations where destination.position.count != 3 {
            throw fail("\(destination.name): position needs 3 numbers")
        }
    }

    var beaconPositions: [SIMD3<Double>] { beacons.map { SIMD3($0.position[0], $0.position[1], $0.position[2]) } }
    var calibrationPosition: SIMD3<Double> { SIMD3(calibrationPoint[0], calibrationPoint[1], calibrationPoint[2]) }
    var speedOfSound: Double { Parameters.speedOfSound(temperatureC: temperatureC) }
}
