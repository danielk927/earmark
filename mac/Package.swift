// swift-tools-version:6.0
import PackageDescription

// Earmark macOS package.
// - EarmarkAudio: every testable piece (head tracking, renderers, cues, guidance, devices, mic, speech, bus).
// - EarmarkUI: SwiftUI pieces shared by both apps (theme, status pills, head dial).
// - SpatialSpike: the Phase 0.5 gate app (no bus, no network).
// - EarmarkApp: the judge-facing app (brief 5.E).
// Built without Xcode; see build_app.sh. Swift 5 language mode avoids strict-concurrency friction
// around CoreMotion, CoreAudio, and AVAudioEngine callbacks (docs/sponsors/vendor-notes/apple-spatial-audio.md section 8).
let package = Package(
    name: "EarmarkMac",
    platforms: [.macOS(.v14)],
    products: [
        .library(name: "EarmarkAudio", targets: ["EarmarkAudio"]),
        .executable(name: "SpatialSpike", targets: ["SpatialSpike"]),
        .executable(name: "EarmarkApp", targets: ["EarmarkApp"]),
    ],
    dependencies: [
        .package(path: "../contracts/swift"),
    ],
    targets: [
        .target(
            name: "EarmarkAudio",
            dependencies: [.product(name: "EarmarkContracts", package: "swift")]
        ),
        .target(name: "EarmarkUI", dependencies: ["EarmarkAudio"]),
        .executableTarget(name: "SpatialSpike", dependencies: ["EarmarkAudio", "EarmarkUI"]),
        .executableTarget(
            name: "EarmarkApp",
            dependencies: ["EarmarkAudio", "EarmarkUI", .product(name: "EarmarkContracts", package: "swift")]
        ),
        .testTarget(
            name: "EarmarkAudioTests",
            dependencies: ["EarmarkAudio", .product(name: "EarmarkContracts", package: "swift")]
        ),
    ],
    swiftLanguageModes: [.v5]
)
