import Foundation

public enum ListenMode: String, CaseIterable, Sendable, Identifiable {
    /// Hold Space to talk. The default: the judging hall is noisy and Cartesia bills every streamed second.
    case pushToTalk = "push_to_talk"
    /// A simple energy voice detector opens the gate.
    case alwaysListening = "always_listening"

    public var id: String { rawValue }
    public var displayName: String {
        switch self {
        case .pushToTalk: "Push to talk (hold Space)"
        case .alwaysListening: "Always listening"
        }
    }
}

public struct VoiceGateConfig: Sendable, Equatable {
    /// Chunks kept before the gate opens and sent first (3 x 100 ms = 300 ms pre-roll).
    public var preRollChunks = 3
    /// Chunks still sent after speech ends or the key is released (10 x 100 ms = 1 s), so turn detection can finish.
    public var trailingChunks = 10
    /// Speech must be this many dB above the tracked noise floor...
    public var startMarginDb = 12.0
    /// ...and never below this absolute level.
    public var minSpeechDb = -50.0
    /// The gate opens when at least `openVotes` of the last `openWindow` chunks are speech (rejects single clicks).
    public var openVotes = 2
    public var openWindow = 3
    /// While open, a chunk counts as speech if it is within this many dB of the start threshold.
    public var holdHysteresisDb = 4.0
    /// Hard cap on one always-listening utterance (chunks), so background noise cannot stream forever.
    public var maxUtteranceChunks = 300
    /// The noise floor is the quietest chunk level of the last `floorWindowChunks` (3 s): speech always has
    /// short dips, steady noise does not, so the floor follows room noise without a separate "is it speech" guess.
    public var floorWindowChunks = 30
    /// No opening until this many chunks of level history exist (0.5 s warm-up after start).
    public var warmupChunks = 5

    public init() {}
}

public enum GateOutput: Equatable, Sendable {
    /// A new utterance starts; pre-roll chunks follow immediately.
    case began
    case audio([Int16])
    case ended
}

/// Gates 100 ms mic chunks: push-to-talk or energy VAD, with pre-roll and trailing audio.
/// Pure and deterministic; the mic pipeline calls `process` once per chunk.
public struct VoiceGate: Sendable {
    public var config: VoiceGateConfig
    public var mode: ListenMode { didSet { if mode != oldValue { forceClose = true } } }
    public private(set) var isOpen = false
    public private(set) var lastLevelDb = -120.0
    private var levels: [Double] = []

    private var preRoll: [[Int16]] = []
    private var votes: [Bool] = []
    private var trailingLeft = 0
    private var utteranceChunks = 0
    private var pttHeld = false
    private var forceClose = false
    private var needsQuietBeforeReopen = false

    public init(mode: ListenMode, config: VoiceGateConfig = VoiceGateConfig()) {
        self.mode = mode
        self.config = config
    }

    /// Quietest recent chunk level, clamped to [-90, -30] dBFS.
    public var noiseFloorDb: Double { min(max(levels.min() ?? -60, -90), -30) }
    public var speechThresholdDb: Double { max(config.minSpeechDb, noiseFloorDb + config.startMarginDb) }

    public mutating func setPushToTalk(held: Bool) { pttHeld = held }

    public mutating func process(_ chunk: [Int16]) -> [GateOutput] {
        let db = PCM.rmsDBFS(chunk)
        lastLevelDb = db
        levels.append(db)
        if levels.count > config.floorWindowChunks { levels.removeFirst(levels.count - config.floorWindowChunks) }
        var out: [GateOutput] = []

        if forceClose {
            forceClose = false
            if isOpen { out.append(.ended); close() }
        }

        switch mode {
        case .pushToTalk: processPTT(chunk, &out)
        case .alwaysListening: processVAD(chunk, db: db, &out)
        }
        return out
    }

    private mutating func remember(_ chunk: [Int16]) {
        preRoll.append(chunk)
        if preRoll.count > config.preRollChunks { preRoll.removeFirst(preRoll.count - config.preRollChunks) }
    }

    private mutating func open(_ out: inout [GateOutput]) {
        isOpen = true
        utteranceChunks = 0
        out.append(.began)
        for c in preRoll { out.append(.audio(c)); utteranceChunks += 1 }
        preRoll.removeAll()
    }

    private mutating func close() {
        isOpen = false
        trailingLeft = 0
        utteranceChunks = 0
        votes.removeAll()
    }

    private mutating func processPTT(_ chunk: [Int16], _ out: inout [GateOutput]) {
        if !isOpen {
            if pttHeld {
                remember(chunk)
                open(&out)
                trailingLeft = config.trailingChunks
            } else {
                remember(chunk)
            }
            return
        }
        out.append(.audio(chunk))
        if pttHeld {
            trailingLeft = config.trailingChunks
        } else {
            trailingLeft -= 1
            if trailingLeft <= 0 { out.append(.ended); close() }
        }
    }

    private mutating func processVAD(_ chunk: [Int16], db: Double, _ out: inout [GateOutput]) {
        let threshold = speechThresholdDb
        if !isOpen {
            let speech = db > threshold
            remember(chunk)
            if needsQuietBeforeReopen {
                if !speech { needsQuietBeforeReopen = false }
                return
            }
            votes.append(speech)
            if votes.count > config.openWindow { votes.removeFirst(votes.count - config.openWindow) }
            if levels.count >= config.warmupChunks && votes.filter({ $0 }).count >= config.openVotes {
                open(&out)
                trailingLeft = config.trailingChunks
            }
            return
        }
        out.append(.audio(chunk))
        utteranceChunks += 1
        if db > threshold - config.holdHysteresisDb {
            trailingLeft = config.trailingChunks
        } else {
            trailingLeft -= 1
        }
        if trailingLeft <= 0 {
            out.append(.ended); close()
        } else if utteranceChunks >= config.maxUtteranceChunks {
            out.append(.ended); close()
            needsQuietBeforeReopen = true
        }
    }
}
