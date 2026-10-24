import CoreAudio
import Foundation

public enum AudioTransport: String, Sendable {
    case builtIn = "built_in"
    case bluetooth
    case bluetoothLE = "bluetooth_le"
    case usb
    case virtual
    case aggregate
    case airPlay = "airplay"
    case continuity
    case other

    init(code: UInt32) {
        switch code {
        case kAudioDeviceTransportTypeBuiltIn: self = .builtIn
        case kAudioDeviceTransportTypeBluetooth: self = .bluetooth
        case kAudioDeviceTransportTypeBluetoothLE: self = .bluetoothLE
        case kAudioDeviceTransportTypeUSB: self = .usb
        case kAudioDeviceTransportTypeVirtual: self = .virtual
        case kAudioDeviceTransportTypeAggregate, kAudioDeviceTransportTypeAutoAggregate: self = .aggregate
        case kAudioDeviceTransportTypeAirPlay: self = .airPlay
        case kAudioDeviceTransportTypeContinuityCaptureWired, kAudioDeviceTransportTypeContinuityCaptureWireless: self = .continuity
        default: self = .other
        }
    }

    public var isBluetooth: Bool { self == .bluetooth || self == .bluetoothLE }
}

public struct AudioDeviceInfo: Equatable, Sendable, Identifiable {
    public var id: AudioDeviceID
    public var uid: String
    public var name: String
    public var transport: AudioTransport
    public var inputChannels: Int
    public var outputChannels: Int
    public var nominalSampleRate: Double

    public init(id: AudioDeviceID, uid: String, name: String, transport: AudioTransport,
                inputChannels: Int, outputChannels: Int, nominalSampleRate: Double) {
        self.id = id; self.uid = uid; self.name = name; self.transport = transport
        self.inputChannels = inputChannels; self.outputChannels = outputChannels; self.nominalSampleRate = nominalSampleRate
    }

    public var isBuiltInMic: Bool { uid == AudioDevices.builtInMicUID || (transport == .builtIn && inputChannels > 0) }
}

/// CoreAudio device queries (docs/sponsors/vendor-notes/apple-spatial-audio.md section 5c).
public enum AudioDevices {
    /// VERIFIED LOCALLY: the built-in mic's CoreAudio UID, identical to its AVCaptureDevice.uniqueID.
    public static let builtInMicUID = "BuiltInMicrophoneDevice"

    static let system = AudioObjectID(kAudioObjectSystemObject)

    static func address(_ selector: AudioObjectPropertySelector,
                        _ scope: AudioObjectPropertyScope = kAudioObjectPropertyScopeGlobal) -> AudioObjectPropertyAddress {
        AudioObjectPropertyAddress(mSelector: selector, mScope: scope, mElement: kAudioObjectPropertyElementMain)
    }

    static func scalar<T>(_ object: AudioObjectID, _ selector: AudioObjectPropertySelector,
                          _ scope: AudioObjectPropertyScope = kAudioObjectPropertyScopeGlobal, default d: T) -> T {
        var addr = address(selector, scope)
        var value = d
        var size = UInt32(MemoryLayout<T>.size)
        let status = withUnsafeMutablePointer(to: &value) { AudioObjectGetPropertyData(object, &addr, 0, nil, &size, $0) }
        return status == noErr ? value : d
    }

    static func string(_ object: AudioObjectID, _ selector: AudioObjectPropertySelector) -> String {
        var addr = address(selector)
        var value: Unmanaged<CFString>?
        var size = UInt32(MemoryLayout<Unmanaged<CFString>?>.size)
        let status = AudioObjectGetPropertyData(object, &addr, 0, nil, &size, &value)
        guard status == noErr, let v = value else { return "" }
        return v.takeRetainedValue() as String
    }

    static func channels(_ device: AudioDeviceID, scope: AudioObjectPropertyScope) -> Int {
        var addr = address(kAudioDevicePropertyStreamConfiguration, scope)
        var size: UInt32 = 0
        guard AudioObjectGetPropertyDataSize(device, &addr, 0, nil, &size) == noErr, size > 0 else { return 0 }
        let raw = UnsafeMutableRawPointer.allocate(byteCount: Int(size), alignment: MemoryLayout<AudioBufferList>.alignment)
        defer { raw.deallocate() }
        guard AudioObjectGetPropertyData(device, &addr, 0, nil, &size, raw) == noErr else { return 0 }
        let list = UnsafeMutableAudioBufferListPointer(raw.assumingMemoryBound(to: AudioBufferList.self))
        return list.reduce(0) { $0 + Int($1.mNumberChannels) }
    }

    public static func deviceIDs() -> [AudioDeviceID] {
        var addr = address(kAudioHardwarePropertyDevices)
        var size: UInt32 = 0
        guard AudioObjectGetPropertyDataSize(system, &addr, 0, nil, &size) == noErr else { return [] }
        var ids = [AudioDeviceID](repeating: 0, count: Int(size) / MemoryLayout<AudioDeviceID>.size)
        guard AudioObjectGetPropertyData(system, &addr, 0, nil, &size, &ids) == noErr else { return [] }
        return ids
    }

    public static func info(_ id: AudioDeviceID) -> AudioDeviceInfo? {
        guard id != kAudioObjectUnknown else { return nil }
        return AudioDeviceInfo(
            id: id,
            uid: string(id, kAudioDevicePropertyDeviceUID),
            name: string(id, kAudioObjectPropertyName),
            transport: AudioTransport(code: scalar(id, kAudioDevicePropertyTransportType, default: UInt32(0))),
            inputChannels: channels(id, scope: kAudioObjectPropertyScopeInput),
            outputChannels: channels(id, scope: kAudioObjectPropertyScopeOutput),
            nominalSampleRate: scalar(id, kAudioDevicePropertyNominalSampleRate, default: Float64(0))
        )
    }

    public static func all() -> [AudioDeviceInfo] { deviceIDs().compactMap(info) }

    public static func defaultInputID() -> AudioDeviceID {
        scalar(system, kAudioHardwarePropertyDefaultInputDevice, default: AudioDeviceID(kAudioObjectUnknown))
    }

    public static func defaultOutputID() -> AudioDeviceID {
        scalar(system, kAudioHardwarePropertyDefaultOutputDevice, default: AudioDeviceID(kAudioObjectUnknown))
    }

    /// Output latency in seconds: device latency + safety offset + first output stream latency + one IO buffer
    /// (what AVAudioOutputNode.presentationLatency reports for AVAudioEngine; used for PHASE, which reports none).
    public static func outputLatency(_ id: AudioDeviceID) -> TimeInterval {
        let out = kAudioObjectPropertyScopeOutput
        let rate = scalar(id, kAudioDevicePropertyNominalSampleRate, default: Float64(0))
        guard rate > 0 else { return 0 }
        var frames = Double(scalar(id, kAudioDevicePropertyLatency, out, default: UInt32(0)))
        frames += Double(scalar(id, kAudioDevicePropertySafetyOffset, out, default: UInt32(0)))
        frames += Double(scalar(id, kAudioDevicePropertyBufferFrameSize, out, default: UInt32(0)))
        var addr = address(kAudioDevicePropertyStreams, out)
        var size: UInt32 = 0
        if AudioObjectGetPropertyDataSize(id, &addr, 0, nil, &size) == noErr, size >= UInt32(MemoryLayout<AudioStreamID>.size) {
            var streams = [AudioStreamID](repeating: 0, count: Int(size) / MemoryLayout<AudioStreamID>.size)
            if AudioObjectGetPropertyData(id, &addr, 0, nil, &size, &streams) == noErr, let first = streams.first {
                frames += Double(scalar(first, kAudioStreamPropertyLatency, default: UInt32(0)))
            }
        }
        return frames / rate
    }

    public static func defaultInput() -> AudioDeviceInfo? { info(defaultInputID()) }
    public static func defaultOutput() -> AudioDeviceInfo? { info(defaultOutputID()) }

    /// Makes `id` the system default input. Changes a user-visible system setting; non-sandboxed apps only.
    @discardableResult
    public static func setDefaultInput(_ id: AudioDeviceID) -> OSStatus {
        var addr = address(kAudioHardwarePropertyDefaultInputDevice)
        var d = id
        return AudioObjectSetPropertyData(system, &addr, 0, nil, UInt32(MemoryLayout<AudioDeviceID>.size), &d)
    }
}

/// Pure routing decisions, unit-tested.
public enum RoutingPolicy {
    /// AirPods (or any Bluetooth headset) output below 44.1 kHz means hands-free (HFP) mode: mono, low quality,
    /// and spatial cues are destroyed. A2DP output runs at 48 kHz.
    public static func hfpSuspected(_ output: AudioDeviceInfo?) -> Bool {
        guard let o = output, o.transport.isBluetooth, o.nominalSampleRate > 0 else { return false }
        return o.nominalSampleRate < 44_100
    }

    /// The device to switch the system default input to, or nil to leave it alone.
    /// Rule (brief 5.E, notes section 5b): if the default input is Bluetooth, use the built-in mic.
    /// A USB or other wired mic chosen by the user is kept.
    public static func inputSwitchTarget(defaultInput: AudioDeviceInfo?, devices: [AudioDeviceInfo]) -> AudioDeviceInfo? {
        guard let d = defaultInput, d.transport.isBluetooth else { return nil }
        return devices.first { $0.uid == AudioDevices.builtInMicUID && $0.inputChannels > 0 }
            ?? devices.first { $0.transport == .builtIn && $0.inputChannels > 0 }
    }
}

/// Listens for default input/output device changes, device-list changes, and nominal sample-rate changes
/// of the current default output (HFP switches the rate without changing the default device).
/// Callbacks arrive on the main queue.
public final class AudioDeviceWatcher {
    public enum Change: String, Sendable { case defaultInput, defaultOutput, deviceList, outputSampleRate }

    private let onChange: (Change) -> Void
    private var systemBlocks: [(AudioObjectPropertyAddress, AudioObjectPropertyListenerBlock)] = []
    private var rateBlock: (AudioDeviceID, AudioObjectPropertyListenerBlock)?

    public init(onChange: @escaping (Change) -> Void) {
        self.onChange = onChange
        let pairs: [(AudioObjectPropertySelector, Change)] = [
            (kAudioHardwarePropertyDefaultInputDevice, .defaultInput),
            (kAudioHardwarePropertyDefaultOutputDevice, .defaultOutput),
            (kAudioHardwarePropertyDevices, .deviceList),
        ]
        for (sel, change) in pairs {
            var addr = AudioDevices.address(sel)
            let block: AudioObjectPropertyListenerBlock = { [weak self] _, _ in
                if change == .defaultOutput { self?.watchOutputRate() }
                self?.onChange(change)
            }
            if AudioObjectAddPropertyListenerBlock(AudioDevices.system, &addr, .main, block) == noErr {
                systemBlocks.append((addr, block))
            }
        }
        watchOutputRate()
    }

    deinit {
        for (addr, block) in systemBlocks {
            var a = addr
            AudioObjectRemovePropertyListenerBlock(AudioDevices.system, &a, .main, block)
        }
        removeRateListener()
    }

    private func removeRateListener() {
        if let (dev, block) = rateBlock {
            var a = AudioDevices.address(kAudioDevicePropertyNominalSampleRate)
            AudioObjectRemovePropertyListenerBlock(dev, &a, .main, block)
        }
        rateBlock = nil
    }

    private func watchOutputRate() {
        removeRateListener()
        let dev = AudioDevices.defaultOutputID()
        guard dev != kAudioObjectUnknown else { return }
        var a = AudioDevices.address(kAudioDevicePropertyNominalSampleRate)
        let block: AudioObjectPropertyListenerBlock = { [weak self] _, _ in self?.onChange(.outputSampleRate) }
        if AudioObjectAddPropertyListenerBlock(dev, &a, .main, block) == noErr { rateBlock = (dev, block) }
    }
}

/// Coalesces bursts of route notifications into one action ("no restart storms").
/// Each trigger restarts a `delay` countdown; fires are spaced at least `minSpacing` apart.
public final class DebouncedTrigger {
    public let delay: TimeInterval
    public let minSpacing: TimeInterval
    private let queue: DispatchQueue
    private let action: () -> Void
    private var pending: DispatchWorkItem?
    private var lastFire: DispatchTime?
    public private(set) var fireCount = 0

    public init(delay: TimeInterval, minSpacing: TimeInterval, queue: DispatchQueue = .main, action: @escaping () -> Void) {
        self.delay = delay; self.minSpacing = minSpacing; self.queue = queue; self.action = action
    }

    /// Call on `queue`.
    public func trigger() {
        pending?.cancel()
        var when = DispatchTime.now() + delay
        if let last = lastFire, when < last + minSpacing { when = last + minSpacing }
        let item = DispatchWorkItem { [weak self] in
            guard let self else { return }
            self.pending = nil
            self.lastFire = .now()
            self.fireCount += 1
            self.action()
        }
        pending = item
        queue.asyncAfter(deadline: when, execute: item)
    }

    public func cancel() { pending?.cancel(); pending = nil }
}
