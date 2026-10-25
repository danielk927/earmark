import Foundation
import PhoneCore

// A Mac stand-in for the phone app: uses this Mac's own speaker and microphone.
//   phone-cli --slot 0 --url ws://127.0.0.1:8766     (or --url some-words.trycloudflare.com, through the tunnel)
//   phone-cli --sweep          (just plays the test sweep once, for checking what a speaker can make)
//   phone-cli --beacon 1 [--band 12000 16000] [--volume 0.8]
//                              (a self-timed beacon on the Mac's speaker: no Mac service, no microphone)
var slot = 0
var urlString = "ws://127.0.0.1:8766"
var sweepOnly = false
var beaconNumber: Int?
var band = (12000.0, 16000.0)
var volume = 0.8
var args = CommandLine.arguments.dropFirst().makeIterator()
while let a = args.next() {
    switch a {
    case "--slot": slot = Int(args.next() ?? "") ?? 0
    case "--url": urlString = args.next() ?? urlString
    case "--sweep": sweepOnly = true
    case "--beacon": beaconNumber = Int(args.next() ?? "")
    case "--band":
        guard let lo = Double(args.next() ?? ""), let hi = Double(args.next() ?? ""), lo < hi else { print("--band needs LO HI in Hz"); exit(2) }
        band = (lo, hi)
    case "--volume":
        guard let v = Double(args.next() ?? ""), (0.1...1.0).contains(v) else { print("--volume needs a number from 0.1 to 1.0"); exit(2) }
        volume = v
    case "--chirp-check":
        for d in ["up", "down"] {
            let s = ChirpSpec(direction: d).samples(sampleRate: phoneSampleRate)
            print(d, s.count, String(format: "sum %.5f  first-ish %.5f %.5f %.5f", s.reduce(0) { $0 + Double($1) }, s[100], s[300], s[500]))
        }
        exit(0)
    default: print("unknown argument \(a)"); exit(2)
    }
}
setvbuf(stdout, nil, _IOLBF, 0)

if let n = beaconNumber {
    guard (1...4).contains(n) else { print("--beacon needs a number from 1 to 4"); exit(2) }
    let beacon = SelfTimedBeacon(beaconNumber: n, band: band, amplitude: volume)
    let clock = DateFormatter()
    clock.dateFormat = "HH:mm:ss.SSS"
    print("self-timed beacon \(n): chirp \(Int(band.0))-\(Int(band.1)) Hz \(beacon.spec.direction), volume \(volume), every 0.5 s at phase \(beacon.phaseSeconds) s")
    print("turn this Mac's volume all the way up; nothing else is needed")
    beacon.onEvent = { event in
        switch event {
        case .started(let t):
            let inCycle = t.timeIntervalSince1970 - (t.timeIntervalSince1970 / 0.5).rounded(.down) * 0.5
            print("first chirp at \(clock.string(from: t)) (\(String(format: "%.3f", t.timeIntervalSince1970)), phase in cycle \(String(format: "%.3f", inCycle)) s)")
        case .played(let c): if c % 10 == 0 { print("chirps played: \(c)") }
        case .error(let e): print("problem: \(e)")
        }
    }
    do { try beacon.start() } catch { print("could not start: \(error.localizedDescription)"); exit(1) }
    signal(SIGINT) { _ in print("\nstopped"); exit(0) }
    RunLoop.main.run()
}

guard let url = PhoneAddress.url(urlString) else { print("bad url"); exit(2) }

let client = PhoneClient(url: url, slot: slot, name: "Mac slot \(slot)")
var lastLevelPrint = Date.distantPast
client.onEvent = { event in
    switch event {
    case .connecting: print("connecting to \(urlString)")
    case .connected(let s, let c): print("joined as slot \(s); chirp \(Int(c.fLo))-\(Int(c.fHi)) Hz \(c.direction)")
    case .played(let n): if n % 10 == 1 { print("played chirp #\(n)") }
    case .level(let l):
        if Date().timeIntervalSince(lastLevelPrint) > 2 { lastLevelPrint = Date(); print(String(format: "microphone level %.4f", l)) }
    case .fix(let f): print(String(format: "you are at x %.2f y %.2f z %.2f (%@, %d phones)", f.x, f.y, f.z, f.quality, f.used))
    case .error(let e): print("problem: \(e)")
    case .disconnected: print("disconnected")
    }
}
client.start()
if sweepOnly {
    DispatchQueue.main.asyncAfter(deadline: .now() + 2) { client.playTestSweep() }
}
RunLoop.main.run()
