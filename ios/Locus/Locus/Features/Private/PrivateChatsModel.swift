import SwiftUI

@MainActor
@Observable
final class PrivateChatsModel {
    var rooms: [SecretChatRoomSummary] = []
    var bridge: SecretChatBridgeStatus?
    var loading = true
    var errorMessage: String?
    /// Surfaced as an alert and never cleared by polling, so a failed create is always seen.
    var createError: String?

    private var hasLoadedOnce = false
    private var refreshTask: Task<Void, Never>?

    var totalUnread: Int { rooms.reduce(0) { $0 + $1.unreadCount } }

    func loadIfNeeded() async {
        guard !hasLoadedOnce else { return }
        hasLoadedOnce = true
        await refresh()
        startPolling()
    }

    func refresh() async {
        do {
            rooms = try await APIClient.shared.secretChatRooms(
                hostKey: PrivateIdentity.hostKey,
                clientId: PrivateIdentity.clientId
            )
            errorMessage = nil
        } catch {
            errorMessage = error.localizedDescription
        }
        bridge = try? await APIClient.shared.secretChatBridgeStatus()
        loading = false
    }

    /// Unread counts are a server-side read cursor, so the list only moves when it is re-read.
    func startPolling() {
        refreshTask?.cancel()
        refreshTask = Task { [weak self] in
            while !Task.isCancelled {
                try? await Task.sleep(for: .seconds(8))
                guard !Task.isCancelled else { return }
                await self?.refresh()
            }
        }
    }

    func stopPolling() {
        refreshTask?.cancel()
        refreshTask = nil
    }

    func createRoom(title: String, ttlSeconds: Int, linkExpiryMinutes: Int, roomExpiryMinutes: Int) async -> String? {
        do {
            let created = try await APIClient.shared.secretChatCreate(
                title: title.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty ? "Private chat" : title,
                hostKey: PrivateIdentity.hostKey,
                messageTTLSeconds: ttlSeconds,
                linkExpiryMinutes: linkExpiryMinutes,
                roomExpiryMinutes: roomExpiryMinutes
            )
            await refresh()
            return created.token
        } catch {
            // Deliberately not `errorMessage`: that field is cleared by the next successful
            // refresh, which is how a failed create previously vanished without a trace.
            createError = error.localizedDescription
            return nil
        }
    }

    func delete(_ token: String) async {
        try? await APIClient.shared.secretChatDeleteRoom(token, hostKey: PrivateIdentity.hostKey)
        await refresh()
    }

    /// Absolute share URL for a room, resolved against the configured server.
    static func shareURL(for room: SecretChatRoomSummary) -> URL? {
        if room.url.hasPrefix("http") { return URL(string: room.url) }
        return URL(string: ServerConfig.baseURL + room.url)
    }
}
