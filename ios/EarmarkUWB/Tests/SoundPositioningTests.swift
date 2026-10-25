import XCTest

final class SoundPositioningTests: XCTestCase {
    func testRangingDefaultIsHubHostOnPort8766() {
        XCTAssertEqual(RangingAddress.derived(fromHub: "ws://192.168.8.10:8765"), "ws://192.168.8.10:8766")
        XCTAssertEqual(RangingAddress.derived(fromHub: "192.168.8.10"), "ws://192.168.8.10:8766")
        XCTAssertEqual(RangingAddress.derived(fromHub: "wss://mac.local:9000"), "ws://mac.local:8766")
        XCTAssertNil(RangingAddress.derived(fromHub: ""))
        XCTAssertNil(RangingAddress.derived(fromHub: "http://x"))
    }

    func testRangingResolve() {
        let hub = "ws://10.0.0.5:8765"
        XCTAssertEqual(RangingAddress.resolve(typed: "", hubText: hub)?.absoluteString, "ws://10.0.0.5:8766")
        XCTAssertEqual(RangingAddress.resolve(typed: "  ", hubText: hub)?.absoluteString, "ws://10.0.0.5:8766")
        XCTAssertEqual(RangingAddress.resolve(typed: "10.0.0.9", hubText: hub)?.absoluteString, "ws://10.0.0.9:8766")
        XCTAssertEqual(RangingAddress.resolve(typed: "10.0.0.9:7000", hubText: hub)?.absoluteString, "ws://10.0.0.9:7000")
        XCTAssertEqual(RangingAddress.resolve(typed: "ws://mac.local:8766", hubText: hub)?.absoluteString, "ws://mac.local:8766")
        XCTAssertNil(RangingAddress.resolve(typed: "http://10.0.0.9", hubText: hub))
        XCTAssertNil(RangingAddress.resolve(typed: "", hubText: "not a url ://"))
    }

    func testBeaconNumberFromDeviceId() {
        XCTAssertEqual(BeaconNumber.forDevice("uwb_1"), 1)
        XCTAssertEqual(BeaconNumber.forDevice("uwb_2"), 2)
        XCTAssertEqual(BeaconNumber.forDevice("uwb_3"), 3)
        XCTAssertNil(BeaconNumber.forDevice("wearer"))
        XCTAssertNil(BeaconNumber.forDevice("uwb_0"))
        XCTAssertNil(BeaconNumber.forDevice("uwb_5"))
        XCTAssertNil(BeaconNumber.forDevice("uwb_x"))
    }

    func testStatusTexts() {
        XCTAssertEqual(SoundStatusText.listener(enabled: false, connected: true, fixAge: 1, error: nil), "Sound positioning: off")
        XCTAssertEqual(SoundStatusText.listener(enabled: true, connected: false, fixAge: nil, error: nil), "Sound positioning: connecting")
        XCTAssertEqual(SoundStatusText.listener(enabled: true, connected: false, fixAge: nil, error: "refused"), "Sound positioning: refused")
        XCTAssertEqual(SoundStatusText.listener(enabled: true, connected: true, fixAge: nil, error: nil), "Sound positioning: connected, no fix yet")
        XCTAssertEqual(SoundStatusText.listener(enabled: true, connected: true, fixAge: 0.4, error: nil), "Sound positioning: connected, last fix 0.4 s ago")
        XCTAssertEqual(SoundStatusText.listener(enabled: true, connected: true, fixAge: 42.3, error: nil), "Sound positioning: connected, last fix 42 s ago")
        XCTAssertEqual(SoundStatusText.beacon(number: 2, enabled: true, chirping: true, played: 7, error: nil), "Sound beacon 2: chirping, 7 chirps played")
        XCTAssertEqual(SoundStatusText.beacon(number: 2, enabled: true, chirping: false, played: 0, error: "boom"), "Sound beacon 2: boom")
        XCTAssertEqual(SoundStatusText.beacon(number: 1, enabled: false, chirping: false, played: 0, error: nil), "Sound beacon 1: off")
        XCTAssertEqual(SoundStatusText.audioFollows("uwb"), "Audio follows: UWB")
        XCTAssertEqual(SoundStatusText.audioFollows("sound"), "Audio follows: Sound")
        XCTAssertEqual(SoundStatusText.audioFollows(nil), "Audio follows: waiting for the hub")
    }
}
