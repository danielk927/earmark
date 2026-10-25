import Foundation
import Testing
@testable import PhoneCore

@Suite struct PhoneAddressTests {
    @Test(arguments: [
        ("192.168.1.20:8766", "ws://192.168.1.20:8766"),
        ("192.168.1.20", "ws://192.168.1.20:8766"),               // the port can be left off
        (" titanium-cute-upcoming-proportion.trycloudflare.com ", "wss://titanium-cute-upcoming-proportion.trycloudflare.com"),
        ("https://some-words.trycloudflare.com", "wss://some-words.trycloudflare.com"),   // pasted from the terminal
        ("ws://127.0.0.1:8766", "ws://127.0.0.1:8766"),
        ("wss://some-words.trycloudflare.com", "wss://some-words.trycloudflare.com"),
        ("localhost", "ws://localhost:8766"),
        ("my-mac.local", "ws://my-mac.local:8766"),
    ])
    func typedAddressBecomesAURL(typed: String, expected: String) {
        #expect(PhoneAddress.url(typed)?.absoluteString == expected)
    }

    @Test func nonsenseIsRefused() {
        #expect(PhoneAddress.url("") == nil)
        #expect(PhoneAddress.url("   ") == nil)
        #expect(PhoneAddress.url("ftp://example.com") == nil)
    }
}

@Suite struct OutageBufferTests {
    @Test func holdsInOrderAndEmptiesOnDrain() {
        var b = OutageBuffer(capacity: 3)
        for k in 0..<2 { b.append(start: k * 2400, pcm: Data([UInt8(k)])) }
        #expect(b.drain().map(\.start) == [0, 2400])
        #expect(b.chunks.isEmpty)
    }

    @Test func aLongDropoutKeepsTheNewest() {
        var b = OutageBuffer(capacity: 3)
        for k in 0..<5 { b.append(start: k * 2400, pcm: Data()) }
        #expect(b.dropped == 2)
        #expect(b.drain().map(\.start) == [4800, 7200, 9600])   // the Mac fills the older hole with silence
        #expect(b.dropped == 0)
    }

    @Test func defaultFitsInsideTheMacsEightSeconds() {
        #expect(Double(OutageBuffer().capacity * chunkSamples) / phoneSampleRate < 8)
    }
}
