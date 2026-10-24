import Foundation
import PhoneCore

// A Mac stand-in for the phone app: uses this Mac's own speaker and microphone.
//   phone-cli --slot 0 --url ws://127.0.0.1:8766
//   phone-cli --sweep          (just plays the test sweep once, for checking what a speaker can make)
var slot = 0
var urlString = "ws://127.0.0.1:8766"
var sweepOnly = false
var args = CommandLine.arguments.dropFirst().makeIterator()
while let a = args.next() {
    switch a {
    case "--slot": slot = Int(args.next() ?? "") ?? 0
    case "--url": urlString = args.next() ?? urlString
    case "--sweep": sweepOnly = true
    case "--chirp-check":
        for d in ["up", "down"] {
            let s = ChirpSpec(direction: d).samples(sampleRate: phoneSampleRate)
            print(d, s.count, String(format: "sum %.5f  first-ish %.5f %.5f %.5f", s.reduce(0) { $0 + Double($1) }, s[100], s[300], s[500]))
        }
        exit(0)
    default: print("unknown argument \(a)"); exit(2)
    }
}
guard let url = URL(string: urlString) else { print("bad url"); exit(2) }
setvbuf(stdout, nil, _IOLBF, 0)

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
