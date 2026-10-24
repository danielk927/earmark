import AppKit

/// App-wide plain-key shortcuts (R, Space, arrows) that never fire while the user types in a text field.
/// Plain-letter SwiftUI keyboard shortcuts would also trigger inside text fields, so this uses a local monitor.
public final class KeyMonitor {
    public enum Key: Hashable { case character(Character), space, left, right, up, down }
    public typealias Handler = (_ isDown: Bool, _ isRepeat: Bool, _ shift: Bool) -> Bool

    private var token: Any?
    private var handlers: [Key: Handler] = [:]

    public init() {}

    deinit { if let token { NSEvent.removeMonitor(token) } }

    /// The handler returns true to consume the event.
    public func on(_ key: Key, _ handler: @escaping Handler) { handlers[key] = handler }

    public func start() {
        guard token == nil else { return }
        token = NSEvent.addLocalMonitorForEvents(matching: [.keyDown, .keyUp]) { [weak self] event in
            guard let self else { return event }
            if event.modifierFlags.contains(.command) || event.modifierFlags.contains(.control) { return event }
            if let responder = event.window?.firstResponder, responder is NSText { return event }
            let key: Key?
            switch event.keyCode {
            case 49: key = .space
            case 123: key = .left
            case 124: key = .right
            case 125: key = .down
            case 126: key = .up
            default: key = event.charactersIgnoringModifiers?.lowercased().first.map(Key.character)
            }
            guard let key, let h = self.handlers[key] else { return event }
            let consumed = h(event.type == .keyDown, event.isARepeat, event.modifierFlags.contains(.shift))
            return consumed ? nil : event
        }
    }
}
