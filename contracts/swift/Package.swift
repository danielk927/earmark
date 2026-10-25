// swift-tools-version:5.9
import PackageDescription

let package = Package(
    name: "EarmarkContracts",
    platforms: [.macOS(.v14), .iOS(.v17)],
    products: [.library(name: "EarmarkContracts", targets: ["EarmarkContracts"])],
    targets: [
        .target(name: "EarmarkContracts"),
        .testTarget(name: "EarmarkContractsTests", dependencies: ["EarmarkContracts"]),
    ]
)
