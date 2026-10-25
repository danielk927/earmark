import Foundation

/// Microphone chunks recorded while the link to the Mac is down, sent once it is back.
///
/// The microphone keeps running through a dropout, so the sample numbers stay true and the Mac's calibration still
/// holds; resending the held chunks fills the hole. Only the newest `capacity` chunks are kept (6 s of 50 ms chunks):
/// the Mac holds 8 s of a phone's audio, so a longer burst would overwrite itself there anyway.
public struct OutageBuffer {
    public let capacity: Int
    public private(set) var chunks: [(start: Int, pcm: Data)] = []
    /// Chunks thrown away because the dropout outlasted `capacity` (the Mac fills that hole with silence).
    public private(set) var dropped = 0

    public init(capacity: Int = 120) { self.capacity = capacity }

    public mutating func append(start: Int, pcm: Data) {
        chunks.append((start, pcm))
        if chunks.count > capacity {
            dropped += chunks.count - capacity
            chunks.removeFirst(chunks.count - capacity)
        }
    }

    /// Everything held, oldest first; the buffer is empty afterwards.
    public mutating func drain() -> [(start: Int, pcm: Data)] {
        defer { chunks.removeAll(); dropped = 0 }
        return chunks
    }
}
