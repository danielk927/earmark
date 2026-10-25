import Foundation
import EarmarkCore

// WAV, output JSONL, optional full settings JSON, optional epoch of first sample.
do {
    let arguments = CommandLine.arguments
    guard (3...5).contains(arguments.count) else { throw LocatorError.invalid("Usage: earmark-file input.wav fixes.jsonl [settings.json] [epoch]") }
    let wave = try WaveFile(data: Data(contentsOf: URL(fileURLWithPath: arguments[1])))
    var config = arguments.count >= 4 ? try LocatorConfig.importing(Data(contentsOf: URL(fileURLWithPath: arguments[3]))) : LocatorConfig()
    config.fs = wave.sampleRate
    let epoch = arguments.count == 5 ? Double(arguments[4]) : 0
    guard let epoch, epoch.isFinite else { throw LocatorError.invalid("Epoch must be finite Unix seconds") }
    let pipeline = try LocatorPipeline(config: config)
    let writer = try JSONLinesWriter(url: URL(fileURLWithPath: arguments[2]))
    for start in stride(from: 0, to: wave.samples.count, by: 2400) {
        let end = min(wave.samples.count, start + 2400)
        let anchor = SampleAnchor(sample: Int64(start), unix: epoch + Double(start) / wave.sampleRate, fs: wave.sampleRate)
        for fix in pipeline.append(Array(wave.samples[start..<end]), anchor: anchor) { try writer.append(fix) }
    }
    try writer.close()
} catch {
    FileHandle.standardError.write(Data("\(error.localizedDescription)\n".utf8))
    exit(1)
}
