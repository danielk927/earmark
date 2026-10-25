import Foundation

/// Where chirps go in a beacon's output stream, counted in output samples.
///
/// A self-timed beacon chirps every `period` output samples, starting at `firstStart`. Everything here is plain
/// integer arithmetic with no allocation, so the audio render block can call it on every buffer. Because the
/// positions are counted in the device's own output samples, the spacing between chirps is exact: no timer,
/// thread or Wi-Fi delay can move one.
public struct ChirpScheduler: Equatable, Sendable {
    /// Output samples between chirp starts, e.g. round(0.5 * 48000) = 24000.
    public let period: Int
    /// Output sample index (0 = first sample the render block ever produced) of the first chirp.
    public let firstStart: Int
    /// Samples in one chirp (1920 for 40 ms at 48 kHz).
    public let chirpLength: Int

    public init(period: Int, firstStart: Int, chirpLength: Int) {
        precondition(period > chirpLength, "chirps must not overlap")
        self.period = period
        self.firstStart = firstStart
        self.chirpLength = chirpLength
    }

    public init(cycleSeconds: Double, sampleRate: Double, firstStart: Int, chirpLength: Int) {
        self.init(period: ChirpScheduler.period(cycleSeconds: cycleSeconds, sampleRate: sampleRate),
                  firstStart: firstStart, chirpLength: chirpLength)
    }

    public static func period(cycleSeconds: Double, sampleRate: Double) -> Int {
        Int((cycleSeconds * sampleRate).rounded())
    }

    /// The first chirp start at or after `sample`.
    public func nextStart(atOrAfter sample: Int) -> Int {
        if sample <= firstStart { return firstStart }
        let k = (sample - firstStart + period - 1) / period
        return firstStart + k * period
    }

    /// Chirp starts that fall inside the buffer [position, position + count).
    public func starts(inBufferAt position: Int, count: Int) -> [Int] {
        var out: [Int] = []
        var s = nextStart(atOrAfter: position)
        while s < position + count { out.append(s); s += period }
        return out
    }

    /// Calls `body` with the start index of every chirp that has at least one sample inside
    /// [position, position + count), including chirps that began in an earlier buffer. Does not allocate.
    @inline(__always)
    public func forEachChirp(overlapping position: Int, count: Int, _ body: (Int) -> Void) {
        var s = nextStart(atOrAfter: position - chirpLength + 1)
        let end = position + count
        while s < end { body(s); s += period }
    }

    /// Fills `out` (count samples, starting at output sample `position`) with silence and the parts of any chirps
    /// that land in it. Pure and allocation-free: the render block calls this, and so do the tests.
    public func fill(_ out: UnsafeMutablePointer<Float>, count: Int, position: Int, chirp: UnsafePointer<Float>) {
        out.update(repeating: 0, count: count)
        forEachChirp(overlapping: position, count: count) { start in
            let chirpFrom = max(0, position - start)        // first chirp sample that is in this buffer
            let outFrom = max(0, start - position)          // where in the buffer it goes
            let n = min(chirpLength - chirpFrom, count - outFrom)
            if n > 0 { (out + outFrom).update(from: chirp + chirpFrom, count: n) }
        }
    }

    /// Number of chirps whose start is before `position` (i.e. fully scheduled by the time the stream reaches it).
    public func chirpsStarted(before position: Int) -> Int {
        if position <= firstStart { return 0 }
        return (position - firstStart - 1) / period + 1
    }

    // MARK: Wall-clock alignment (done once, when the stream starts)

    /// The wall-clock phase (seconds into each cycle) at which beacon `beaconNumber` (1-based) starts its chirp.
    public static func phase(beaconNumber: Int, slotSeconds: Double) -> Double {
        Double(beaconNumber - 1) * slotSeconds
    }

    /// The earliest wall-clock time (seconds since 1970) that is at least `lead` after `now` and sits exactly at
    /// this beacon's phase within the cycle: the moment the first chirp should start.
    public static func firstChirpTime(after now: Double, beaconNumber: Int, cycleSeconds: Double, slotSeconds: Double, lead: Double) -> Double {
        let phase = ChirpScheduler.phase(beaconNumber: beaconNumber, slotSeconds: slotSeconds)
        let earliest = now + lead
        var t = ((earliest - phase) / cycleSeconds).rounded(.down) * cycleSeconds + phase
        if t < earliest { t += cycleSeconds }
        return t
    }
}
