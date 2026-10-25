import AVFoundation
import CoreMedia
import Foundation

/// Captures the microphone as 16 kHz mono Int16 in 100 ms chunks.
///
/// Path choice: `AVCaptureSession` pinned to the built-in mic by UID (`BuiltInMicrophoneDevice`), not a
/// second `AVAudioEngine` input tap. The engine tap follows the *system default* input, so if macOS flips the
/// default to the AirPods (it does on reconnect) capture would open the AirPods mic and force hands-free mode
/// before our routing rule can react. The capture session never opens any device but the one we pin, and it
/// never touches an output unit, so it cannot drag the output into an aggregate device either.
/// `audioSettings` asks for 16 kHz Int16 directly; the delivered format is still checked per buffer and
/// converted with AVAudioConverter if it differs (that delivery is UNVERIFIED at runtime).
public final class MicCapture: NSObject, AVCaptureAudioDataOutputSampleBufferDelegate {
    public enum MicError: Error, CustomStringConvertible {
        case noDevice, notAuthorized, cannotAddInput, cannotAddOutput
        public var description: String {
            switch self {
            case .noDevice: "No built-in microphone found"
            case .notAuthorized: "Microphone access denied (System Settings > Privacy & Security > Microphone)"
            case .cannotAddInput: "Could not open the microphone"
            case .cannotAddOutput: "Could not attach the audio output"
            }
        }
    }

    /// 100 ms chunks of 16 kHz mono Int16, on the capture queue.
    public var onChunk: (([Int16]) -> Void)?
    public private(set) var deviceName = "none"
    public private(set) var deviceUID = ""
    public private(set) var isRunning = false

    private let queue = DispatchQueue(label: "earmark.mic", qos: .userInitiated)
    private var session: AVCaptureSession?
    private var resampler: PCMResampler?
    private var chunker = SampleChunker<Int16>(size: PCM.micChunkFrames)

    public override init() { super.init() }

    public static var authorization: AVAuthorizationStatus { AVCaptureDevice.authorizationStatus(for: .audio) }

    /// Picks the built-in mic by UID, else any built-in input from the device list. Never anything else:
    /// no Bluetooth, Continuity (iPhone), USB or other mic, so a missing built-in mic is an error, not a guess.
    public static func pickDevice() -> AVCaptureDevice? {
        if let d = AVCaptureDevice(uniqueID: AudioDevices.builtInMicUID) { return d }
        guard let info = AudioDevices.all().first(where: { $0.isBuiltInMic }) else { return nil }
        return AVCaptureDevice(uniqueID: info.uid)
    }

    /// Requests permission if needed, then starts. Completion runs on the main queue.
    public func start(completion: @escaping (Error?) -> Void) {
        switch Self.authorization {
        case .authorized:
            completion(startAuthorized())
        case .notDetermined:
            AVCaptureDevice.requestAccess(for: .audio) { granted in
                DispatchQueue.main.async { completion(granted ? self.startAuthorized() : MicError.notAuthorized) }
            }
        default:
            completion(MicError.notAuthorized)
        }
    }

    private func startAuthorized() -> Error? {
        guard !isRunning else { return nil }
        guard let device = Self.pickDevice() else { return MicError.noDevice }
        let s = AVCaptureSession()
        s.beginConfiguration()
        guard let input = try? AVCaptureDeviceInput(device: device), s.canAddInput(input) else {
            s.commitConfiguration(); return MicError.cannotAddInput
        }
        s.addInput(input)
        let output = AVCaptureAudioDataOutput()
        output.audioSettings = [
            AVFormatIDKey: kAudioFormatLinearPCM,
            AVSampleRateKey: 16_000,
            AVNumberOfChannelsKey: 1,
            AVLinearPCMBitDepthKey: 16,
            AVLinearPCMIsFloatKey: false,
            AVLinearPCMIsBigEndianKey: false,
            AVLinearPCMIsNonInterleaved: false,
        ]
        output.setSampleBufferDelegate(self, queue: queue)
        guard s.canAddOutput(output) else { s.commitConfiguration(); return MicError.cannotAddOutput }
        s.addOutput(output)
        s.commitConfiguration()
        s.startRunning()
        session = s
        deviceName = device.localizedName
        deviceUID = device.uniqueID
        isRunning = true
        Log.mic("capturing from \(device.localizedName) (\(device.uniqueID)), 16 kHz Int16, 100 ms chunks")
        return nil
    }

    public func stop() {
        session?.stopRunning()
        session = nil
        isRunning = false
        queue.async { [weak self] in self?.chunker.reset(); self?.resampler = nil }
    }

    // MARK: AVCaptureAudioDataOutputSampleBufferDelegate (capture queue)

    public func captureOutput(_ output: AVCaptureOutput, didOutput sampleBuffer: CMSampleBuffer, from connection: AVCaptureConnection) {
        guard let pcm = Self.pcmBuffer(from: sampleBuffer) else { return }
        let samples: [Int16]
        if Self.isMicFormat(pcm.format) {
            samples = PCM.int16Samples(pcm)
        } else {
            if resampler?.input != pcm.format { resampler = PCMResampler(from: pcm.format, to: PCM.micFormat) }
            guard let out = resampler?.convert(pcm) else { return }
            samples = PCM.int16Samples(out)
        }
        for chunk in chunker.push(samples) { onChunk?(chunk) }
    }

    static func isMicFormat(_ f: AVAudioFormat) -> Bool {
        f.commonFormat == .pcmFormatInt16 && f.sampleRate == 16_000 && f.channelCount == 1 && f.isInterleaved
    }

    /// Copies a CMSampleBuffer into an AVAudioPCMBuffer in its own format.
    static func pcmBuffer(from sb: CMSampleBuffer) -> AVAudioPCMBuffer? {
        guard let desc = CMSampleBufferGetFormatDescription(sb) else { return nil }
        let format = AVAudioFormat(cmAudioFormatDescription: desc)
        let frames = AVAudioFrameCount(CMSampleBufferGetNumSamples(sb))
        guard frames > 0, let buf = AVAudioPCMBuffer(pcmFormat: format, frameCapacity: frames) else { return nil }
        buf.frameLength = frames
        let status = CMSampleBufferCopyPCMDataIntoAudioBufferList(sb, at: 0, frameCount: Int32(frames), into: buf.mutableAudioBufferList)
        return status == noErr ? buf : nil
    }
}
