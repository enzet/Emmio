// swift-tools-version:5.9
//
// EmmioKit: the platform-independent core of the Emmio iOS client.
//
// It holds the HTTP client and Codable models for the Emmio API (see
// `emmio/api/app.py`) and nothing UI-specific, so it builds and unit-tests with
// the plain Swift toolchain (`swift test`) on any host, while the SwiftUI app in
// `../EmmioApp` depends on it for all networking.

import PackageDescription

let package = Package(
    name: "EmmioKit",
    platforms: [.iOS(.v17), .macOS(.v13)],
    products: [
        .library(name: "EmmioKit", targets: ["EmmioKit"]),
    ],
    targets: [
        .target(name: "EmmioKit"),
        .testTarget(name: "EmmioKitTests", dependencies: ["EmmioKit"]),
    ]
)
