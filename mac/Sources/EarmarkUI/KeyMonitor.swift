import AppKit

/// App-wide plain-key shortcuts (R, Space, arrows) that never fire while the user types in a text field.
/// The one exception: Space still reaches push-to-talk while the focused text field is empty.
/// Plain-letter SwiftUI keyboard shortcuts would also trigger inside text fields, so this uses a local monitor.
public final class KeyMonitor {
    public enum Key: Hashable { case character(Character), space, left, right, up, down }
    public typealias Handler = (_ isDown: Bool, _ isRepeat: Bool, _ shift: Bool) -> Bool

    private var token: Any?
    private var clickToken: Any?
    private var handlers: [Key: Handler] = [:]

    public init() {}

    /// Whether a key goes to the shortcut handlers (true) or to the focused text field (false).
    public static func handlesKey(_ key: Key, textFieldFocused: Bool, fieldIsEmpty: Bool) -> Bool {
        guard textFieldFocused else { return true }
        return key == .space && fieldIsEmpty
    }

    deinit {
        if let token { NSEvent.removeMonitor(token) }
        if let clickToken { NSEvent.removeMonitor(clickToken) }
    }

    /// The handler returns true to consume the event.
    public func on(_ key: Key, _ handler: @escaping Handler) { handlers[key] = handler }

    public func start() {
        guard token == nil else { return }
        // A click anywhere outside the text field being edited ends the editing, so keys go back to shortcuts.
        clickToken = NSEvent.addLocalMonitorForEvents(matching: .leftMouseDown) { event in
            if let window = event.window, let editor = window.firstResponder as? NSText,
               let field = editor.delegate as? NSView {
                let hit = window.contentView?.hitTest(event.locationInWindow)
                if hit == nil || !(hit! === field || hit!.isDescendant(of: field)) { window.makeFirstResponder(nil) }
            }
            return event
        }
        token = NSEvent.addLocalMonitorForEvents(matching: [.keyDown, .keyUp]) { [weak self] event in
            guard let self else { return event }
            if event.modifierFlags.contains(.command) || event.modifierFlags.contains(.control) { return event }
            let key: Key?
            switch event.keyCode {
            case 49: key = .space
            case 123: key = .left
            case 124: key = .right
            case 125: key = .down
            case 126: key = .up
            default: key = event.charactersIgnoringModifiers?.lowercased().first.map(Key.character)
            }
            let text = event.window?.firstResponder as? NSText
            guard let key, Self.handlesKey(key, textFieldFocused: text != nil, fieldIsEmpty: text?.string.isEmpty ?? true),
                  let h = self.handlers[key] else { return event }
            let consumed = h(event.type == .keyDown, event.isARepeat, event.modifierFlags.contains(.shift))
            return consumed ? nil : event
        }
    }
}
