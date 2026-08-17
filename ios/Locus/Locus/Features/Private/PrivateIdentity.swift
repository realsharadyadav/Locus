import SwiftUI

/// This device's private-chat identity.
///
/// The `host_key` is what authorises everything that manages a room — the room list, options,
/// clear/delete, guest details, copilot and autopilot (AGENTS.md "Private chat rules"). It is
/// the equivalent of the creating browser's key, so it lives in the Keychain and must survive
/// reinstalls of the view layer: lose it and this device can no longer manage its own rooms.
/// `client_id` is a per-device presence identity and is fine in UserDefaults.
enum PrivateIdentity {
    private static let hostKeyAccount = "locus.secretChat.hostKey"
    private static let clientIdKey = "locus.secretChat.clientId"
    private static let displayNameKey = "locus.secretChat.displayName"

    static var hostKey: String {
        // A key longer than the backend's 64-char limit can never own a room, so it is replaced
        // rather than kept — an over-long key from an earlier build had every create rejected.
        if let existing = KeychainStore.read(account: hostKeyAccount),
           !existing.isEmpty, existing.count <= 64 {
            return existing
        }
        // 32 hex characters, like the web's key. The backend caps `host_key` at 64 chars, so a
        // longer key (two joined UUIDs, say) makes every create fail with a 422.
        let generated = (0..<32).map { _ in String("0123456789abcdef".randomElement()!) }.joined()
        KeychainStore.save(generated, account: hostKeyAccount)
        return generated
    }

    static var clientId: String {
        if let existing = UserDefaults.standard.string(forKey: clientIdKey), !existing.isEmpty {
            return existing
        }
        let generated = UUID().uuidString
        UserDefaults.standard.set(generated, forKey: clientIdKey)
        return generated
    }

    static var displayName: String {
        get { UserDefaults.standard.string(forKey: displayNameKey) ?? "Host" }
        set { UserDefaults.standard.set(newValue, forKey: displayNameKey) }
    }

    /// Device facts the guests panel shows for each participant.
    @MainActor
    static func profile() -> (language: String, timezone: String, screen: String, viewport: String) {
        let bounds = UIScreen.main.bounds
        let scale = UIScreen.main.scale
        return (
            language: Locale.current.identifier,
            timezone: TimeZone.current.identifier,
            screen: "\(Int(bounds.width * scale))x\(Int(bounds.height * scale))",
            viewport: "\(Int(bounds.width))x\(Int(bounds.height))"
        )
    }
}

/// Room option choices, matching the web's create/options selects exactly.
enum RoomOption {
    static let messageTTL: [(label: String, seconds: Int)] = [
        ("Off", 0), ("1 min", 60), ("5 min", 300), ("1 hour", 3600), ("24 hours", 86_400),
    ]
    static let linkExpiry: [(label: String, minutes: Int)] = [
        ("Never", 0), ("5 min", 5), ("30 min", 30), ("2 hours", 120), ("24 hours", 1440),
    ]
    static let roomExpiry: [(label: String, minutes: Int)] = [
        ("Never", 0), ("1 hour", 60), ("8 hours", 480), ("24 hours", 1440), ("7 days", 10_080),
    ]

    static func label(forTTL seconds: Int) -> String {
        messageTTL.first { $0.seconds == seconds }?.label ?? "\(seconds)s"
    }
}
