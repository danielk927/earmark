import Foundation

/// Phase 0.5 pointing test: trial sets, scoring, and the JSON-lines logger (`logs/spatial_gate.jsonl`).
public enum TrialSet: String, Codable, CaseIterable, Sendable, Identifiable {
    /// Random positions in the front half (-90...90 deg). The gate: >= 8 of 10 within 20 deg.
    case front
    /// Random positions behind (|azimuth| 100...180 deg); counts front/back confusions.
    case behind

    public var id: String { rawValue }
    public var displayName: String { self == .front ? "Front half (gate: 8 of 10 within 20\u{00B0})" : "Behind (4 trials, count front/back confusions)" }
    public var plannedTrials: Int { self == .front ? 10 : 4 }
}

public struct GateTrial: Codable, Equatable, Sendable {
    public var t: Double
    public var sessionId: String
    public var trial: Int
    public var set: TrialSet
    public var renderer: String
    public var timbre: String
    public var targetDeg: Double
    public var responseDeg: Double
    public var errorDeg: Double
    public var absErrorDeg: Double
    public var within20: Bool
    public var frontBackConfusion: Bool
    public var headTracking: String
    public var yawAtResponseDeg: Double
    public var outputDevice: String
    public var outputSampleRate: Double
    public var mockHead: Bool
    public var tester: String

    public init(t: Double = Date().timeIntervalSince1970, sessionId: String, trial: Int, set: TrialSet, renderer: String,
                timbre: String, targetDeg: Double, responseDeg: Double, headTracking: String, yawAtResponseDeg: Double,
                outputDevice: String, outputSampleRate: Double, mockHead: Bool, tester: String) {
        self.t = t; self.sessionId = sessionId; self.trial = trial; self.set = set; self.renderer = renderer
        self.timbre = timbre; self.targetDeg = targetDeg; self.responseDeg = responseDeg
        self.errorDeg = GateMath.signedError(targetDeg: targetDeg, responseDeg: responseDeg)
        self.absErrorDeg = abs(errorDeg)
        self.within20 = absErrorDeg <= 20
        self.frontBackConfusion = GateMath.isFrontBackConfusion(targetDeg: targetDeg, responseDeg: responseDeg)
        self.headTracking = headTracking; self.yawAtResponseDeg = yawAtResponseDeg
        self.outputDevice = outputDevice; self.outputSampleRate = outputSampleRate; self.mockHead = mockHead; self.tester = tester
    }
}

public enum GateMath {
    public static let passWithinDeg = 20.0
    public static let passHits = 8
    public static let passOutOf = 10

    /// Signed pointing error, response minus target, wrapped to (-180, 180].
    public static func signedError(targetDeg: Double, responseDeg: Double) -> Double {
        Angles.wrapDeg(responseDeg - targetDeg)
    }

    /// True when the response lands in the other hemisphere (front vs back), nearer the target's mirror image
    /// across the interaural axis than the target itself. Targets within 10 deg of +-90 (the ears) never count.
    public static func isFrontBackConfusion(targetDeg: Double, responseDeg: Double) -> Bool {
        let t = Angles.wrapDeg(targetDeg), r = Angles.wrapDeg(responseDeg)
        guard abs(abs(t) - 90) > 10 else { return false }
        let front: (Double) -> Bool = { abs($0) < 90 }
        guard front(t) != front(r) else { return false }
        let mirror = Angles.wrapDeg(180 - t)
        return abs(Angles.wrapDeg(r - mirror)) < abs(Angles.wrapDeg(r - t))
    }

    /// Candidate angles in 5 deg steps.
    public static func candidates(_ set: TrialSet) -> [Double] {
        switch set {
        case .front: stride(from: -90.0, through: 90, by: 5).map { $0 }
        case .behind: stride(from: 100.0, through: 180, by: 5).flatMap { $0 == 180 ? [180] : [$0, -$0] }
        }
    }

    /// A random angle from the set, never within 15 deg of the previous one (so trials are not guessable).
    public static func randomAngle<G: RandomNumberGenerator>(_ set: TrialSet, previous: Double?, using g: inout G) -> Double {
        let all = candidates(set)
        let pool = previous.map { p in all.filter { abs(Angles.wrapDeg($0 - p)) >= 15 } } ?? all
        return (pool.isEmpty ? all : pool).randomElement(using: &g)!
    }
}

/// Running tally for one renderer + timbre in one session.
public struct GateTally: Equatable, Sendable {
    public var frontTrials = 0
    /// Hits within 20 deg among the most recent 10 front trials.
    public var frontHitsLast10 = 0
    public var frontLast10 = 0
    public var behindTrials = 0
    public var confusions = 0
    public var meanAbsErrorDeg: Double?

    public init(trials: [GateTrial]) {
        let front = trials.filter { $0.set == .front }
        let behind = trials.filter { $0.set == .behind }
        frontTrials = front.count
        let last = front.suffix(GateMath.passOutOf)
        frontLast10 = last.count
        frontHitsLast10 = last.filter(\.within20).count
        behindTrials = behind.count
        confusions = trials.filter(\.frontBackConfusion).count
        if !front.isEmpty { meanAbsErrorDeg = front.map(\.absErrorDeg).reduce(0, +) / Double(front.count) }
    }

    /// nil until 10 front trials exist.
    public var passed: Bool? {
        frontLast10 < GateMath.passOutOf ? nil : frontHitsLast10 >= GateMath.passHits
    }

    public var verdict: String {
        switch passed {
        case nil: "\(frontHitsLast10) of \(frontLast10) within 20\u{00B0} - need 8 of 10"
        case true?: "PASS - \(frontHitsLast10) of 10 within 20\u{00B0}"
        case false?: "FAIL - \(frontHitsLast10) of 10 within 20\u{00B0} (need 8)"
        }
    }
}

public final class GateLogger {
    public let url: URL
    private static let encoder: JSONEncoder = {
        let e = JSONEncoder()
        e.keyEncodingStrategy = .convertToSnakeCase
        e.outputFormatting = [.sortedKeys]
        return e
    }()
    private static let decoder: JSONDecoder = {
        let d = JSONDecoder()
        d.keyDecodingStrategy = .convertFromSnakeCase
        return d
    }()

    public init(url: URL) { self.url = url }

    public func append(_ trial: GateTrial) throws {
        try FileManager.default.createDirectory(at: url.deletingLastPathComponent(), withIntermediateDirectories: true)
        var line = try Self.encoder.encode(trial)
        line.append(0x0A)
        if let h = try? FileHandle(forWritingTo: url) {
            defer { try? h.close() }
            try h.seekToEnd()
            try h.write(contentsOf: line)
        } else {
            try line.write(to: url)
        }
    }

    public func load() -> [GateTrial] {
        guard let text = try? String(contentsOf: url, encoding: .utf8) else { return [] }
        return text.split(separator: "\n").compactMap { try? Self.decoder.decode(GateTrial.self, from: Data($0.utf8)) }
    }
}

/// Locates the repo root for repo-relative paths (logs/, config/).
/// Order: `EARMARK_REPO_ROOT`, the `EarmarkRepoRoot` Info.plist key written by build_app.sh,
/// then walking up from the bundle looking for BUILD_BRIEF.md.
public enum RepoLocator {
    public static func root() -> URL? {
        let fm = FileManager.default
        func valid(_ u: URL) -> Bool { fm.fileExists(atPath: u.appendingPathComponent("contracts").path) }
        if let env = ProcessInfo.processInfo.environment["EARMARK_REPO_ROOT"], !env.isEmpty {
            let u = URL(fileURLWithPath: env, isDirectory: true)
            if valid(u) { return u }
        }
        if let s = Bundle.main.object(forInfoDictionaryKey: "EarmarkRepoRoot") as? String {
            let u = URL(fileURLWithPath: s, isDirectory: true)
            if valid(u) { return u }
        }
        var dir = Bundle.main.bundleURL
        for _ in 0..<6 {
            dir.deleteLastPathComponent()
            if fm.fileExists(atPath: dir.appendingPathComponent("BUILD_BRIEF.md").path) { return dir }
        }
        return nil
    }

    public static func resolve(_ repoRelative: String) -> URL {
        if repoRelative.hasPrefix("/") { return URL(fileURLWithPath: repoRelative) }
        let base = root() ?? FileManager.default.homeDirectoryForCurrentUser.appendingPathComponent("Documents/Earmark")
        return base.appendingPathComponent(repoRelative)
    }
}
