import Foundation

public enum ListenMode: String, CaseIterable, Sendable, Identifiable {
    /// Hold Space (or squeeze an AirPod stem) to talk. The default: the judging hall is noisy and Cartesia bills
    /// every streamed second.
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
    /// Hard cap on one push-to-talk utterance (chunks): a key-up that never arrives cannot stream forever.
    public var maxPushToTalkChunks = 300
    /// A squeeze with no speech after it ends after this many chunks (5 s). Taking an AirPod out sends the same
    /// command as a squeeze, so this is also how a false squeeze closes.
    public var handsFreeNoSpeechChunks = 50
    /// After speech, this many quiet chunks in a row (1.5 s) end a squeeze utterance.
    public var handsFreeEndSilenceChunks = 15
    /// Hard cap on one squeeze utterance (20 s), for a room too loud to ever sound quiet.
    public var maxHandsFreeChunks = 200
    /// The first chunks after a squeeze hold the listening earcon when the output is the Mac speakers (the keyboard
    /// play key also squeezes), so they never count as speech.
    public var handsFreeEarconChunks = 2
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
/// Push-to-talk also takes hands-free utterances (an AirPods stem squeeze): open at once, close on a second
/// squeeze, a pause after speech, no speech at all, or the cap.
/// Pure and deterministic; the mic pipeline calls `process` once per chunk.
public struct VoiceGate: Sendable {
    public var config: VoiceGateConfig
    public var mode: ListenMode { didSet { if mode != oldValue { forceClose = true; handsFree = false } } }
    public private(set) var isOpen = false
    public private(set) var lastLevelDb = -120.0
    private var levels: [Double] = []

    private var preRoll: [[Int16]] = []
    private var votes: [Bool] = []
    private var trailingLeft = 0
    private var utteranceChunks = 0
    private var pttHeld = false
    /// The push-to-talk cap ended the utterance; the key must be released before it can open again.
    private var pttCapped = false
    private var forceClose = false
    private var needsQuietBeforeReopen = false
    /// A squeeze utterance is running (push-to-talk mode only).
    public private(set) var handsFree = false
    private var handsFreeChunks = 0
    private var handsFreeHeardSpeech = false
    private var handsFreeQuiet = 0

    public init(mode: ListenMode, config: VoiceGateConfig = VoiceGateConfig()) {
        self.mode = mode
        self.config = config
    }

    /// Quietest recent chunk level, clamped to [-90, -30] dBFS.
    public var noiseFloorDb: Double { min(max(levels.min() ?? -60, -90), -30) }
    public var speechThresholdDb: Double { max(config.minSpeechDb, noiseFloorDb + config.startMarginDb) }

    public mutating func setPushToTalk(held: Bool) {
        pttHeld = held
        if !held { pttCapped = false }
    }

    /// Starts a squeeze utterance; the gate opens on the next chunk. Always-listening mode already opens on
    /// speech, so it returns false there.
    @discardableResult
    public mutating func startHandsFree() -> Bool {
        guard mode == .pushToTalk else { return false }
        handsFree = true
        handsFreeChunks = 0
        handsFreeHeardSpeech = false
        handsFreeQuiet = 0
        votes.removeAll()
        return true
    }

    /// A second squeeze: stop like a key release, with the usual trailing audio so the last word is kept.
    public mutating func stopHandsFree() { handsFree = false }

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
        case .pushToTalk: processPTT(chunk, db: db, &out)
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

    private mutating func processPTT(_ chunk: [Int16], db: Double, _ out: inout [GateOutput]) {
        let key = pttHeld && !pttCapped
        if !isOpen {
            remember(chunk)
            if key || handsFree {
                open(&out)
                trailingLeft = config.trailingChunks
            }
            return
        }
        out.append(.audio(chunk))
        utteranceChunks += 1
        if handsFree && handsFreeFinished(db: db) {
            handsFree = false
            // It ended on silence, or the cap: the quiet is already sent, so no trailing audio. A held key keeps it open.
            if !key { out.append(.ended); close(); return }
        }
        let held = key || handsFree
        if pttHeld && utteranceChunks >= config.maxPushToTalkChunks {
            out.append(.ended); close()
            pttCapped = true
            handsFree = false
        } else if held {
            trailingLeft = config.trailingChunks
        } else {
            trailingLeft -= 1
            if trailingLeft <= 0 { out.append(.ended); close() }
        }
    }

    /// Counts one open chunk of a squeeze utterance; true when it should end. Speech is heard the same way the
    /// always-listening gate opens (2 of the last 3 chunks above the threshold), so one click does not count.
    private mutating func handsFreeFinished(db: Double) -> Bool {
        handsFreeChunks += 1
        if handsFreeChunks >= config.maxHandsFreeChunks { return true }
        let threshold = speechThresholdDb
        if !handsFreeHeardSpeech {
            votes.append(handsFreeChunks > config.handsFreeEarconChunks && db > threshold)
            if votes.count > config.openWindow { votes.removeFirst(votes.count - config.openWindow) }
            handsFreeHeardSpeech = votes.filter { $0 }.count >= config.openVotes
            return !handsFreeHeardSpeech && handsFreeChunks >= config.handsFreeNoSpeechChunks
        }
        handsFreeQuiet = db > threshold - config.holdHysteresisDb ? 0 : handsFreeQuiet + 1
        return handsFreeQuiet >= config.handsFreeEndSilenceChunks
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
