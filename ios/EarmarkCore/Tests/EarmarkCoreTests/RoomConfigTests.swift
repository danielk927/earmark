import Foundation
import Testing
@testable import EarmarkCore

struct RoomConfigTests {
    @Test func parsesC4Example() throws {
        let config = try RoomConfig.load(from: Data(TestScene.c4Example.utf8))
        #expect(config.version == 1)
        #expect(config.temperatureC == 21.0)
        #expect(config.beacons.map(\.id) == ["B1", "B2", "B3", "B4"])
        #expect(config.beacons.map(\.slot) == [0, 1, 2, 3])
        #expect(config.beacons[3].position == [-1.70, -0.30, 1.00])
        #expect(config.beacons[3].device == "MacBook")
        #expect(config.calibrationPoint == [0.0, 0.0, 1.45])
        #expect(config.receiverHeight == 1.45)
        #expect(config.earHeight == 1.62)
        #expect(config.destinations.map(\.name) == ["sugar jar", "keys", "spice jar", "pill bottle"])
        #expect(config.chirp.f1 == 20000)
    }

    @Test func nullReceiverHeightMeansFree3D() throws {
        let json = TestScene.c4Example.replacingOccurrences(of: "\"receiverHeight\": 1.45", with: "\"receiverHeight\": null")
        #expect(try RoomConfig.load(from: Data(json.utf8)).receiverHeight == nil)
    }

    @Test(arguments: [
        ("\"slot\": 3", "\"slot\": 2"),                      // duplicate slot
        ("\"f1\": 20000", "\"f1\": 21000"),                  // wrong chirp
        ("[-1.70, -0.30, 1.00]", "[-1.70, -0.30]"),          // 2D position
    ])
    func rejectsBadScene(from: String, to: String) {
        let json = TestScene.c4Example.replacingOccurrences(of: from, with: to)
        #expect(throws: RoomConfigError.self) { try RoomConfig.load(from: Data(json.utf8)) }
    }

    @Test func repoSceneLoads() throws {
        _ = try TestScene.load()
    }

    @Test func stubEngineBuildsFromScene() throws {
        let engine = try EarmarkEngine(config: TestScene.load())
        #expect(engine.state(at: 0).status == .notCalibrated)
        #expect(engine.guidance(at: 0, headYaw: 0, destination: "keys").valid == false)
    }
}
