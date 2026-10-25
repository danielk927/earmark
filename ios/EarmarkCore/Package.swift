// swift-tools-version:5.9
import PackageDescription

let package = Package(
    name: "EarmarkCore",
    platforms: [.iOS(.v16), .macOS(.v13)],
    products: [.library(name: "EarmarkCore", targets: ["EarmarkCore"])],
    targets: [
        .target(name: "EarmarkCore"),
        .testTarget(name: "EarmarkCoreTests", dependencies: ["EarmarkCore"])
    ],
    swiftLanguageVersions: [.v5]
)
