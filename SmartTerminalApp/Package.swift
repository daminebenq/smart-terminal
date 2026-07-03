// swift-tools-version: 5.9
// The swift-tools-version declares the minimum version of Swift required to build this package.

import PackageDescription

let package = Package(
    name: "SmartTerminalApp",
    platforms: [
        .macOS(.v13)
    ],
    products: [
        .executable(
            name: "SmartTerminalApp",
            targets: ["SmartTerminalApp"]
        ),
    ],
    dependencies: [
        .package(url: "https://github.com/sindresorhus/KeyboardShortcuts.git", from: "1.0.0"),
        .package(url: "https://github.com/sindresorhus/LaunchAtLogin.git", from: "5.0.0")
    ],
    targets: [
        .executableTarget(
            name: "SmartTerminalApp",
            dependencies: [
                .product(name: "KeyboardShortcuts", package: "KeyboardShortcuts"),
                .product(name: "LaunchAtLogin", package: "LaunchAtLogin")
            ],
            path: "Sources"
        ),
    ]
)