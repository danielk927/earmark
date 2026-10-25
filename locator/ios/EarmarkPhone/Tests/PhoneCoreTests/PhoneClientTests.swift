import Foundation
import Network
import Testing
@testable import PhoneCore

/// Stands in for the microphone: a 50 ms chunk every 20 ms (faster than real time keeps the test short).
private final class FakeMic: AudioSource, @unchecked Sendable {
    private(set) var runningChirp: ChirpSpec?
    private(set) var starts = 0
    private var timer: DispatchSourceTimer?
    private var counter = 777_000  // a real phone's counter does not start at zero either

    var isRunning: Bool { runningChirp != nil }

    func start(chirp: ChirpSpec, onChunk: @escaping (Int, Data) -> Void, onLevel: @escaping (Float) -> Void) throws {
        starts += 1
        runningChirp = chirp
        let t = DispatchSource.makeTimerSource(queue: DispatchQueue(label: "fake-mic"))
        t.schedule(deadline: .now(), repeating: .milliseconds(20))
        t.setEventHandler { [weak self] in
            guard let self else { return }
            onChunk(self.counter, Data(count: chunkSamples * 2))
            self.counter += chunkSamples
        }
        t.resume()
        timer = t
    }

    func stop() { timer?.cancel(); timer = nil; runningChirp = nil }
    func playChirp() {}
    func playTestSweep() {}
}

/// The Mac's ranging service as far as the phone can tell: answers a join with a config, keeps every message,
/// and drops the first connection after a few chunks, the way a Wi-Fi blip would.
private final class FakeMac: @unchecked Sendable {
    let listener: NWListener
    private let q = DispatchQueue(label: "fake-mac")
    private let lock = NSLock()
    private var log: [[String: Any]] = []
    private var connections = 0
    let dropAfterChunks = 10

    var messages: [[String: Any]] { lock.withLock { log } }

    init() throws {
        let ws = NWProtocolWebSocket.Options()
        ws.autoReplyPing = true
        let params = NWParameters.tcp
        params.defaultProtocolStack.applicationProtocols.insert(ws, at: 0)
        listener = try NWListener(using: params, on: .any)
        listener.newConnectionHandler = { [weak self] c in self?.accept(c) }
    }

    func start() async throws -> UInt16 {
        listener.start(queue: q)
        for _ in 0..<100 {
            if listener.state == .ready, let port = listener.port { return port.rawValue }
            try await Task.sleep(nanoseconds: 20_000_000)
        }
        throw CocoaError(.featureUnsupported)
    }

    func stop() { listener.cancel() }

    private func accept(_ c: NWConnection) {
        connections += 1
        let n = connections
        var chunks = 0
        c.start(queue: q)
        func next() {
            c.receiveMessage { [self] data, _, _, error in
                guard error == nil, let data, let m = try? JSONSerialization.jsonObject(with: data) as? [String: Any] else { return }
                lock.withLock { log.append(m.merging(["connection": n]) { a, _ in a }) }
                switch m["type"] as? String {
                case "join": sendConfig(c)
                case "audio":
                    chunks += 1
                    if n == 1 && chunks == dropAfterChunks { c.cancel(); return }
                default: break
                }
                next()
            }
        }
        next()
    }

    private func sendConfig(_ c: NWConnection) {
        let config: [String: Any] = ["type": "config", "slot": 0, "chirp": [
            "f_lo": 12000.0, "f_hi": 16000.0, "length_ms": 40.0, "amplitude": 0.8, "direction": "none"]]
        let ctx = NWConnection.ContentContext(identifier: "config", metadata: [NWProtocolWebSocket.Metadata(opcode: .text)])
        c.send(content: try? JSONSerialization.data(withJSONObject: config), contentContext: ctx, isComplete: true,
               completion: .idempotent)
    }
}

@Suite struct PhoneClientTests {
    @Test func aDropoutKeepsTheRecordingAndResendsWhatWasHeld() async throws {
        let mac = try FakeMac()
        let port = try await mac.start()
        let mic = FakeMic()
        let client = PhoneClient(url: URL(string: "ws://127.0.0.1:\(port)")!, slot: 0, name: "test", audio: mic, retryDelay: 0.5)
        client.start()
        func audio(_ m: [[String: Any]], connection: Int? = nil) -> [[String: Any]] {
            m.filter { $0["type"] as? String == "audio" && (connection == nil || $0["connection"] as? Int == connection) }
        }
        for _ in 0..<200 where audio(mac.messages, connection: 2).count < 40 {
            try await Task.sleep(nanoseconds: 50_000_000)
        }
        client.stop()
        mac.stop()
        let m = mac.messages

        let joins = m.filter { $0["type"] as? String == "join" }
        #expect(joins.count == 2)
        #expect(Set(joins.compactMap { $0["timeline"] as? String }).count == 1)  // one unbroken recording
        #expect(mic.starts == 1)                                                  // the microphone never stopped
        let second = audio(m, connection: 2)
        #expect(second.count >= 40)
        #expect(second.first?["resent"] as? Bool == true)                         // what was held goes first
        #expect(second.filter { $0["resent"] as? Bool == true }.count >= 10)      // about 0.5 s of it
        let starts = audio(m).compactMap { $0["start"] as? Int }
        #expect(starts == starts.sorted() && Set(starts).count == starts.count)
        // Only chunks already on their way when the link died can be missing; the Mac fills those with silence.
        let missing = (starts.last! - starts.first!) / chunkSamples + 1 - starts.count
        #expect(missing <= 3, "missing \(missing) chunks")
    }
}
