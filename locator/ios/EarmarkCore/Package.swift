// swift-tools-version:5.10
import PackageDescription

let package = Package(
    name: "EarmarkCore",
    platforms: [.macOS(.v14), .iOS(.v17)],
    products: [
        .library(name: "EarmarkCore", targets: ["EarmarkCore"]),
        .executable(name: "earmark-file", targets: ["EarmarkFile"])
    ],
    targets: [
        .target(name: "EarmarkCore"),
        .executableTarget(name: "EarmarkFile", dependencies: ["EarmarkCore"]),
        .testTarget(name: "EarmarkCoreTests", dependencies: ["EarmarkCore"])
    ]
)
