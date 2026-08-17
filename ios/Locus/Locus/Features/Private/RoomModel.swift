import SwiftUI

/// One live private room, host side. Ported from `src/secret-chat/useSecretChatRoom.js`:
/// SSE stream with reconnect, an 8s presence heartbeat that doubles as the read cursor, an 8s
/// safety-net poll in case the stream stalls, and a 1s tick that hides expiring messages locally
/// so the countdown looks live (the server still enforces it and broadcasts `purge`).
@MainActor
@Observable
final class RoomModel {
    let token: String

    var session: SecretChatSessionRead?
    var messages: [SecretChatMessageRead] = []
    var participants: [SecretChatParticipantRead] = []
    var guests: [SecretChatParticipantDetail] = []
    var draft = ""
    var status: Status = .loading
    var endedReason: String?
    var autopilotDraft: SecretChatAutopilotDraft?
    var copilotSuggestions: [String] = []
    var copilotBusy = false
    /// Frozen at open time so the "New messages" divider does not vanish as you read.
    var unreadFromId: Int?
    /// Drives the disappear countdown re-render.
    var tick = Date()

    enum Status { case loading, ready, ended }

    private var lastId = 0
    private var streamTask: Task<Void, Never>?
    private var presenceTask: Task<Void, Never>?
    private var pollTask: Task<Void, Never>?
    private var tickTask: Task<Void, Never>?
    private var autopilotTask: Task<Void, Never>?
    private var typingUntil = Date.distantPast

    init(token: String) {
        self.token = token
    }

    var title: String { session?.title ?? "Private chat" }
    var onlineGuests: Int { participants.filter { $0.online && $0.role != "host" }.count }
    var someoneTyping: Bool { participants.contains { $0.typing && $0.clientId != PrivateIdentity.clientId } }

    /// Messages still within their lifetime. Expiry is hidden locally on the tick; the server
    /// broadcasts `purge` so every client drops the same ones at the same moment anyway.
    var visibleMessages: [SecretChatMessageRead] {
        messages.filter { message in
            guard let expiry = message.expiresAt else { return true }
            return expiry > tick
        }
    }

    func remainingSeconds(for message: SecretChatMessageRead) -> Int? {
        guard let expiry = message.expiresAt else { return nil }
        return max(0, Int(expiry.timeIntervalSince(tick)))
    }

    // MARK: - Lifecycle

    func open() async {
        do {
            let room = try await APIClient.shared.secretChatGet(
                token, clientId: PrivateIdentity.clientId, hostKey: PrivateIdentity.hostKey
            )
            session = room
            messages = room.messages
            participants = room.participants
            lastId = room.messages.last?.id ?? 0
            let mine = room.participants.first { $0.clientId == PrivateIdentity.clientId }
            let readCursor = mine?.lastReadId ?? 0
            unreadFromId = room.messages.first { $0.id > readCursor }?.id
            status = .ready
            startStream()
            startPresence()
            startPoll()
            startTick()
            startAutopilotWatch()
            await loadGuests()
        } catch let error as APIError where error.status == 404 || error.status == 410 {
            status = .ended
            endedReason = "This private chat has ended."
        } catch {
            status = .ended
            endedReason = error.localizedDescription
        }
    }

    func close() {
        streamTask?.cancel()
        presenceTask?.cancel()
        pollTask?.cancel()
        tickTask?.cancel()
        autopilotTask?.cancel()
        streamTask = nil; presenceTask = nil; pollTask = nil; tickTask = nil; autopilotTask = nil
    }

    // MARK: - Stream

    private func startStream() {
        streamTask?.cancel()
        streamTask = Task { [weak self] in
            var retry: UInt64 = 1_000
            while !Task.isCancelled {
                guard let self else { return }
                do {
                    let stream = await APIClient.shared.sseStream(
                        path: "/secret-chat/\(self.token)/stream",
                        query: ["after": String(self.lastId)]
                    )
                    for try await frame in stream {
                        if Task.isCancelled { return }
                        // The server sends a named `revoked` event when the room is deleted and
                        // then closes; without handling it the client reconnects forever into a 404.
                        if frame.event == "revoked" {
                            self.finish("This private chat has ended.")
                            return
                        }
                        guard frame.data != ": keepalive",
                              let data = frame.data.data(using: .utf8),
                              let payload = try? JSONDecoder().decode([String: AnyCodable].self, from: data)
                        else { continue }
                        self.handle(payload)
                    }
                    retry = 1_000
                } catch {
                    if Task.isCancelled { return }
                }
                try? await Task.sleep(for: .milliseconds(retry))
                retry = min(retry * 2, 15_000)
            }
        }
    }

    private func handle(_ payload: [String: AnyCodable]) {
        switch payload["type"]?.string {
        case "purge":
            let ids = Set((payload["ids"]?.array ?? []).compactMap { $0.int })
            messages.removeAll { ids.contains($0.id) }
        case "presence":
            Task { await refreshPresence() }
        case "room":
            if payload["state"]?.string == "ended" {
                finish("This private chat has ended.")
            } else {
                Task { await refreshPresence() }
            }
        default:
            // Anything else is a message frame.
            guard let data = try? JSONEncoder().encode(payload),
                  let message = try? APIClient.decoder.decode(SecretChatMessageRead.self, from: data)
            else { return }
            apply([message])
        }
    }

    private func apply(_ incoming: [SecretChatMessageRead]) {
        guard !incoming.isEmpty else { return }
        var known = Set(messages.map(\.id))
        for message in incoming where !known.contains(message.id) {
            messages.append(message)
            known.insert(message.id)
        }
        messages.sort { $0.id < $1.id }
        lastId = max(lastId, messages.last?.id ?? 0)
    }

    private func finish(_ reason: String) {
        status = .ended
        endedReason = reason
        close()
    }

    // MARK: - Heartbeats

    private func startPresence() {
        presenceTask?.cancel()
        presenceTask = Task { [weak self] in
            while !Task.isCancelled {
                await self?.refreshPresence()
                try? await Task.sleep(for: .seconds(8))
            }
        }
    }

    /// Presence doubles as the read cursor, which is what clears the unread badge server-side.
    func refreshPresence() async {
        let profile = PrivateIdentity.profile()
        do {
            let response = try await APIClient.shared.secretChatPresence(token, body: .init(
                clientId: PrivateIdentity.clientId,
                name: PrivateIdentity.displayName,
                role: "host",
                hostKey: PrivateIdentity.hostKey,
                typing: Date() < typingUntil,
                lastReadId: lastId,
                language: profile.language,
                timezone: profile.timezone,
                screen: profile.screen,
                viewport: profile.viewport
            ))
            let joined = Set(response.participants.map(\.clientId)) != Set(participants.map(\.clientId))
            participants = response.participants
            // Someone arrived or left — the detailed panel is a separate host-only endpoint,
            // so it has to be refetched or it would still show only whoever was here at open.
            if joined { await loadGuests() }
        } catch let error as APIError where error.status == 410 {
            finish("This private chat has ended.")
        } catch {
            // Transient — the next heartbeat retries.
        }
    }

    private func startPoll() {
        pollTask?.cancel()
        pollTask = Task { [weak self] in
            while !Task.isCancelled {
                try? await Task.sleep(for: .seconds(8))
                guard let self, !Task.isCancelled else { return }
                do {
                    let missed = try await APIClient.shared.secretChatMessages(self.token, after: self.lastId)
                    self.apply(missed)
                } catch let error as APIError where error.status == 410 {
                    self.finish("This private chat has ended.")
                } catch {}
            }
        }
    }

    private func startTick() {
        tickTask?.cancel()
        tickTask = Task { [weak self] in
            while !Task.isCancelled {
                try? await Task.sleep(for: .seconds(1))
                self?.tick = Date()
            }
        }
    }

    // MARK: - Sending

    func send() async {
        let text = draft.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !text.isEmpty else { return }
        draft = ""
        LocusHaptics.medium()
        do {
            let message = try await APIClient.shared.secretChatSend(
                token, sender: PrivateIdentity.displayName, content: text
            )
            apply([message])
            // Answering by hand drops any autopilot reply still being held for review.
            autopilotDraft = nil
        } catch {
            draft = text
        }
    }

    func markTyping() {
        typingUntil = Date().addingTimeInterval(4)
    }

    // MARK: - Host tools

    func loadGuests() async {
        guests = (try? await APIClient.shared.secretChatParticipants(
            token, hostKey: PrivateIdentity.hostKey
        )) ?? []
    }

    func updateOptions(title: String, ttlSeconds: Int, linkExpiryMinutes: Int, roomExpiryMinutes: Int,
                       tone: String, persona: String, autopilot: Bool, mimicMe: Bool) async {
        let updated = try? await APIClient.shared.secretChatUpdateOptions(token, body: .init(
            hostKey: PrivateIdentity.hostKey,
            title: title,
            messageTTLSeconds: ttlSeconds,
            linkExpiryMinutes: linkExpiryMinutes,
            roomExpiryMinutes: roomExpiryMinutes,
            aiTone: tone,
            aiPersona: persona,
            aiAutopilot: autopilot,
            aiMimicMe: mimicMe
        ))
        if let updated { session = updated }
    }

    func clearMessages() async {
        try? await APIClient.shared.secretChatClearMessages(token, hostKey: PrivateIdentity.hostKey)
        messages = []
        lastId = 0
        autopilotDraft = nil
    }

    func deleteRoom() async {
        try? await APIClient.shared.secretChatDeleteRoom(token, hostKey: PrivateIdentity.hostKey)
        finish("Chat deleted.")
    }

    // MARK: - Copilot / autopilot

    func suggestReplies() async {
        copilotBusy = true
        let response = try? await APIClient.shared.secretChatAssist(token, body: .init(
            hostKey: PrivateIdentity.hostKey,
            clientId: PrivateIdentity.clientId,
            sender: PrivateIdentity.displayName,
            // Suggest mode never sends anything by itself — the host picks a draft.
            mode: "suggest",
            tone: session?.aiTone ?? "friendly",
            persona: session?.aiPersona ?? "",
            mimicMe: session?.aiMimicMe ?? false,
            instruction: ""
        ))
        copilotSuggestions = response?.suggestions ?? []
        copilotBusy = false
    }

    /// Autopilot runs on the *server*: a guest's message starts a worker that drafts a reply and
    /// holds it for review. The draft is host-key authorised and never touches the room stream,
    /// so it has to be polled — the guest only ever sees a typing indicator.
    private func startAutopilotWatch() {
        autopilotTask?.cancel()
        autopilotTask = Task { [weak self] in
            while !Task.isCancelled {
                guard let self else { return }
                if self.session?.aiAutopilot == true {
                    let pending = try? await APIClient.shared.secretChatAutopilotDraft(
                        self.token, hostKey: PrivateIdentity.hostKey
                    )
                    self.autopilotDraft = pending?.pending
                } else if self.autopilotDraft != nil {
                    self.autopilotDraft = nil
                }
                try? await Task.sleep(for: .seconds(2))
            }
        }
    }

    func decideAutopilot(_ action: String) async {
        guard let draft = autopilotDraft else { return }
        try? await APIClient.shared.secretChatAutopilotDecide(
            token, hostKey: PrivateIdentity.hostKey, draftId: draft.id, action: action
        )
        autopilotDraft = nil
        LocusHaptics.light()
    }
}
