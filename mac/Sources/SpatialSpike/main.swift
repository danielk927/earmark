import AppKit
import EarmarkAudio
import SwiftUI

struct SpatialSpikeApp: App {
    @NSApplicationDelegateAdaptor(SpikeAppDelegate.self) var delegate
    @StateObject private var model = SpikeModel()

    var body: some Scene {
        WindowGroup("Earmark Spatial Spike") {
            SpikeView(m: model)
                .onAppear { model.start() }
        }
        .defaultSize(width: 1280, height: 860)
        .windowResizability(.contentMinSize)
    }
}

final class SpikeAppDelegate: NSObject, NSApplicationDelegate {
    func applicationDidFinishLaunching(_ notification: Notification) {
        NSApp.setActivationPolicy(.regular)
        // --appearance=light|dark overrides the system appearance (screenshots, demos); default follows the system.
        switch LaunchArgs().value("appearance") {
        case "light": NSApp.appearance = NSAppearance(named: .aqua)
        case "dark": NSApp.appearance = NSAppearance(named: .darkAqua)
        default: break
        }
        NSApp.activate(ignoringOtherApps: true)
    }
    func applicationShouldTerminateAfterLastWindowClosed(_ sender: NSApplication) -> Bool { true }
}

SpatialSpikeApp.main()
