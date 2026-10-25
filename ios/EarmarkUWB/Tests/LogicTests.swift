import EarmarkContracts
import XCTest

// The Logic/ sources are compiled straight into this test bundle (no host app), so these run on any simulator.
final class LogicTests: XCTestCase {
    func testMotionHysteresis() {
        var classifier = MotionClassifier(windowSize: 25)
        var changes: [MotionState.State] = []
        func feed(_ g: Double, _ count: Int) {
            for _ in 0..<count {
                if let state = classifier.push(g) { changes.append(state) }
            }
        }

        feed(0.01, 24)
        XCTAssertTrue(changes.isEmpty, "no decision before the 0.5 s window is full")
        feed(0.01, 1)
        XCTAssertEqual(changes, [.still])

        feed(0.10, 25)
        XCTAssertEqual(changes.last, .moving)

        feed(0.045, 50)   // between 0.03 and 0.06: hysteresis keeps "moving"
        XCTAssertEqual(classifier.state, .moving)

        feed(0.01, 25)
        XCTAssertEqual(changes.last, .still)

        feed(0.045, 50)   // and keeps "still"
        XCTAssertEqual(classifier.state, .still)
        XCTAssertEqual(changes, [.still, .moving, .still])
    }

    func testMotionFirstDecisionCanBeMoving() {
        var classifier = MotionClassifier(windowSize: 25)
        var first: MotionState.State?
        for _ in 0..<25 { first = classifier.push(0.2) ?? first }
        XCTAssertEqual(first, .moving)
    }

    func testDecimatorCapsAt20Hz() {
        for inputHz in [30.0, 60.0, 100.0] {
            var decimator = RangeDecimator(maxHz: 20)
            var sent = 0
            for i in 0..<Int(inputHz * 10) {
                if decimator.shouldSend(at: Double(i) / inputHz) { sent += 1 }
            }
            XCTAssertGreaterThanOrEqual(sent, 195, "\(inputHz) Hz in should give ~20 Hz out over 10 s")
            XCTAssertLessThanOrEqual(sent, 202, "\(inputHz) Hz in should give ~20 Hz out over 10 s")
        }
    }

    func testDecimatorPassesSlowStreams() {
        var decimator = RangeDecimator(maxHz: 20)
        var sent = 0
        for i in 0..<100 {
            if decimator.shouldSend(at: Double(i) / 10) { sent += 1 }
        }
        XCTAssertEqual(sent, 100)
    }

    func testRateMeter() {
        var meter = RateMeter(window: 2)
        for i in 0..<40 { meter.record(Double(i) * 0.05) }
        XCTAssertEqual(meter.rate(at: 1.95), 20, accuracy: 0.01)
        XCTAssertEqual(meter.rate(at: 10), 0)
    }

    func testBackoff() {
        var backoff = Backoff()
        XCTAssertEqual((0..<6).map { _ in backoff.next() }, [0.5, 1, 2, 4, 5, 5])
        backoff.reset()
        XCTAssertEqual(backoff.next(), 0.5)
    }

    func testHubAddress() {
        XCTAssertEqual(HubAddress.parse("ws://192.168.8.10:8765")?.absoluteString, "ws://192.168.8.10:8765")
        XCTAssertEqual(HubAddress.parse("  192.168.8.10 ")?.absoluteString, "ws://192.168.8.10:8765")
        XCTAssertEqual(HubAddress.parse("192.168.8.10:9000")?.absoluteString, "ws://192.168.8.10:9000")
        XCTAssertEqual(HubAddress.parse("WS://mac.local")?.absoluteString, "ws://mac.local:8765")
        XCTAssertNil(HubAddress.parse("http://192.168.8.10:8765"))
        XCTAssertNil(HubAddress.parse(""))
        XCTAssertNil(HubAddress.parse("ws://"))
    }
}
