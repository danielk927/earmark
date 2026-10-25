import SwiftUI

@main
@MainActor
struct EarmarkUWBApp: App {
    @StateObject private var model = AppModel()

    var body: some Scene {
        WindowGroup {
            RootView(model: model)
        }
    }
}

@MainActor
struct RootView: View {
    @ObservedObject var model: AppModel
    @Environment(\.scenePhase) private var scenePhase

    var body: some View {
        Group {
            switch model.active {
            case .anchor(let controller)?:
                AnchorView(controller: controller, hub: controller.hub, beacon: controller.beacon) { model.disconnect() }
            case .wearer(let controller)?:
                WearerView(controller: controller, hub: controller.hub, sound: controller.sound) { model.disconnect() }
            case nil:
                RolePickerView(model: model)
            }
        }
        .onChange(of: scenePhase) { _, phase in
            model.scenePhaseChanged(phase)
        }
    }
}
