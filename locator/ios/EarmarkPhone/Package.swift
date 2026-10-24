// swift-tools-version:6.0
import PackageDescription

// PhoneCore: everything the phone does (chirp, audio, connection). Builds on macOS too, so it can be
// tried on a Mac with its own speaker and microphone. App/ holds the SwiftUI shell for the iPhone.
let package = Package(
    name: "EarmarkPhone",
    platforms: [.macOS(.v14), .iOS(.v17)],
    products: [
        .library(name: "PhoneCore", targets: ["PhoneCore"]),
        .executable(name: "phone-cli", targets: ["phone-cli"]),
        .executable(name: "PhoneApp", targets: ["PhoneApp"]),
    ],
    targets: [
        .target(name: "PhoneCore"),
        .executableTarget(name: "phone-cli", dependencies: ["PhoneCore"]),
        // The same SwiftUI screens the iPhone project uses; building it here only checks that they compile.
        .executableTarget(name: "PhoneApp", dependencies: ["PhoneCore"], path: "App"),
    ],
    swiftLanguageModes: [.v5]
)
