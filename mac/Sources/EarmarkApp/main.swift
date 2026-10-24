import AppKit
import EarmarkAudio
import SwiftUI

struct EarmarkMacApp: App {
    @NSApplicationDelegateAdaptor(EarmarkAppDelegate.self) var delegate
    @StateObject private var model = AppModel()

    var body: some Scene {
        WindowGroup("Earmark") {
            AppView(m: model)
                .onAppear { model.start() }
        }
        .defaultSize(width: 1440, height: 920)
        .windowResizability(.contentMinSize)
    }
}

final class EarmarkAppDelegate: NSObject, NSApplicationDelegate {
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

EarmarkMacApp.main()
