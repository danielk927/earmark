import Foundation
import MediaPlayer

/// The AirPods stem squeeze as Earmark's talk button.
///
/// macOS hands headphone and media-key presses to the Now Playing app through `MPRemoteCommandCenter`, so Earmark
/// claims Now Playing while it runs. macOS cannot infer that from audio output: `playbackState` must be set by hand.
/// Depending on what macOS thinks is playing, a squeeze can arrive as play, pause or toggle, so all three count.
/// Taking an AirPod out also sends pause and nothing tells the two apart; a squeeze utterance with no speech closes
/// on its own (`VoiceGateConfig.handsFreeNoSpeechChunks`). The keyboard play/pause key works the same way.
/// UNVERIFIED on real AirPods: which command a squeeze sends, and whether an app really playing audio (Music, a
/// browser video) takes the press away from Earmark.
public final class StemButton {
    /// Main queue.
    public var onSqueeze: (() -> Void)?
    private var targets: [(MPRemoteCommand, Any)] = []
    private var debounce = SqueezeDebounce()

    public init() {}

    public func start() {
        guard targets.isEmpty else { return }
        let center = MPRemoteCommandCenter.shared()
        for command in [center.togglePlayPauseCommand, center.playCommand, center.pauseCommand] {
            command.isEnabled = true
            let token = command.addTarget { [weak self] _ in
                DispatchQueue.main.async { self?.pressed() }
                return .success
            }
            targets.append((command, token))
        }
        let info = MPNowPlayingInfoCenter.default()
        info.nowPlayingInfo = [MPMediaItemPropertyTitle: "Earmark", MPMediaItemPropertyArtist: "Squeeze an AirPod to talk"]
        info.playbackState = .playing
        Log.mic("AirPods squeeze: listening for play/pause as the Now Playing app")
    }

    public func stop() {
        for (command, token) in targets { command.removeTarget(token) }
        targets.removeAll()
        let info = MPNowPlayingInfoCenter.default()
        info.nowPlayingInfo = nil
        info.playbackState = .stopped
    }

    private func pressed() {
        guard debounce.accept(now: ProcessInfo.processInfo.systemUptime) else { return }
        onSqueeze?()
    }
}

/// Presses closer together than `window` count once, in case one squeeze arrives as two commands.
public struct SqueezeDebounce: Sendable {
    public var window: Double
    private var last = -Double.infinity

    public init(window: Double = 0.4) { self.window = window }

    public mutating func accept(now: Double) -> Bool {
        guard now - last >= window else { return false }
        last = now
        return true
    }
}

/// What a squeeze does. In push-to-talk mode the first squeeze stops Earmark talking, plays the listening sound and
/// opens the mic; the next squeeze closes it. `poll()` (the app tick) notices when the gate closed the utterance by
/// itself and plays the done sound. Always-listening mode needs no button, so squeezes are ignored there.
public final class SqueezeToTalk {
    /// A squeeze this soon after the utterance ended by itself is the user's late "stop", not a new start.
    public static let lateStopWindow = 1.0

    private let pipeline: MicPipeline
    private let speech: SpeechOutput
    private let clock: () -> Double
    public private(set) var listening = false
    private var userStopped = false
    private var selfEndedAt = -Double.infinity

    public init(pipeline: MicPipeline, speech: SpeechOutput,
                clock: @escaping () -> Double = { ProcessInfo.processInfo.systemUptime }) {
        self.pipeline = pipeline
        self.speech = speech
        self.clock = clock
    }

    public func squeeze() {
        if pipeline.handsFreeActive {
            pipeline.stopHandsFree()
            userStopped = true
            Log.mic("squeeze: stop listening")
        } else if poll() || clock() - selfEndedAt < Self.lateStopWindow {
            Log.mic("squeeze: listening had just stopped by itself; taken as the stop")
        } else if pipeline.startHandsFree() {
            speech.stopAll()
            speech.playEarcon(.listening)
            listening = true
            Log.mic("squeeze: listening")
        } else {
            Log.mic("squeeze ignored: the mic is always listening")
        }
    }

    /// Returns true when `listening` changed.
    @discardableResult
    public func poll() -> Bool {
        guard listening, !pipeline.handsFreeActive else { return false }
        listening = false
        if !userStopped { selfEndedAt = clock() }
        userStopped = false
        speech.playEarcon(.done)
        return true
    }
}
