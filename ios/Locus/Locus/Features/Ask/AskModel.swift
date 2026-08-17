import SwiftUI

/// One rendered row in the transcript. Saved messages come from `/api/chats/{id}/messages`;
/// the optimistic user bubble is added locally the moment you hit send.
struct AskMessage: Identifiable, Equatable {
    enum Role: String { case user, assistant }

    let id: String
    let role: Role
    var text: String
    var sources: [ChatSource] = []
    var model: String?
    var provider: String?
    var totalTokens: Int = 0
    var isError = false
    /// Saved messages carry the backend id, which truncate-from needs.
    var serverId: Int?
    /// Live direct-stream state: tokens are appended into `text` as they arrive.
    var streaming = false
    var activity: [StreamStep] = []

    static func == (lhs: AskMessage, rhs: AskMessage) -> Bool {
        lhs.id == rhs.id && lhs.text == rhs.text && lhs.sources.count == rhs.sources.count
            && lhs.streaming == rhs.streaming && lhs.activity == rhs.activity
    }
}

/// One row of the direct-stream trace — the native equivalent of the web's `DirectStreamTrace`.
struct StreamStep: Identifiable, Equatable {
    enum State: Equatable { case pending, live, done, failed }
    let id: String
    let label: String
    var detail: String
    var state: State
}

@MainActor
@Observable
final class AskModel {
    // Transcript
    var messages: [AskMessage] = []
    var chats: [ChatSessionRead] = []
    var activeChatId: Int?

    // Composer
    var question = ""
    var effort: EffortMode = .light
    var allowGeneralKnowledge = true
    /// `nil` = search the whole library. A non-nil (possibly empty) set = an explicit scope.
    /// Defaults to `[]` like the web composer: an explicit empty scope is what lets the backend
    /// turn High/Max with no files into real web research instead of a from-memory answer.
    var selectedFileIds: [Int]? = []

    // Job state
    var activeJob: ChatJobRead?
    var jobStartedAt: Date?
    var suggestions: [String] = []

    var loading = true
    var sending = false

    private var pollTask: Task<Void, Never>?
    private var streamTask: Task<Bool, Never>?
    private var hasLoadedOnce = false

    /// A live direct stream. Kept separate from `sending` so the composer can show stop while
    /// tokens are still arriving.
    var streaming = false

    /// The default model label, shown on a streaming bubble before the `start` frame names it.
    var app_defaultModelLabel = ""

    var isBusy: Bool { activeJob != nil || sending || streaming }

    var effectiveEffort: EffortMode {
        Self.slashMode(in: question) ?? effort
    }

    // MARK: - Loading

    func loadIfNeeded() async {
        guard !hasLoadedOnce else { return }
        hasLoadedOnce = true
        await refreshChats()
        loading = false
        startPolling()
    }

    func refreshChats() async {
        chats = (try? await APIClient.shared.chats()) ?? []
    }

    func open(chatId: Int) async {
        activeChatId = chatId
        suggestions = []
        messages = ((try? await APIClient.shared.chatMessages(chatId)) ?? []).map(Self.message(from:))
    }

    func newChat() {
        activeChatId = nil
        messages = []
        suggestions = []
        selectedFileIds = nil
    }

    func delete(chatId: Int) async {
        try? await APIClient.shared.deleteChat(chatId)
        if activeChatId == chatId { newChat() }
        await refreshChats()
    }

    func deleteAllChats() async {
        try? await APIClient.shared.deleteAllChats()
        newChat()
        await refreshChats()
    }

    /// Long-press a message → "Delete from here": drops that message and everything after it.
    func truncate(from message: AskMessage) async {
        guard let chatId = activeChatId, let serverId = message.serverId else { return }
        try? await APIClient.shared.truncateChat(chatId: chatId, fromMessageId: serverId)
        await open(chatId: chatId)
    }

    // MARK: - Asking

    func send() async {
        let raw = question.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !raw.isEmpty, !isBusy else { return }
        let mode = Self.slashMode(in: raw) ?? effort
        let text = Self.stripSlashPrefix(raw)
        guard !text.isEmpty else { return }

        question = ""
        suggestions = []
        sending = true
        LocusHaptics.medium()
        messages.append(AskMessage(id: "local-\(UUID().uuidString)", role: .user, text: text))

        // Plain Normal-effort chat with no files streams token by token. Anything else — more
        // effort, scoped files, or a question the backend reads as search intent — comes back
        // 422 and falls through to the job pipeline below.
        if mode == .light, selectedFileIds?.isEmpty == true {
            let streamed = await streamAnswer(text)
            if streamed {
                sending = false
                return
            }
        }

        do {
            // `web_search` stays false: the backend's `_effective_web_search` ORs in its own
            // search-intent detection and the High/Max-with-no-files rule, so the client
            // doesn't need to duplicate that heuristic.
            let job = try await APIClient.shared.createChatJob(
                question: text,
                conversationId: activeChatId,
                allowGeneralKnowledge: allowGeneralKnowledge,
                reasoningMode: mode.backendId,
                fileIds: selectedFileIds,
                webSourceLimit: mode.webSourceLimit,
                webSearch: false
            )
            activeChatId = job.conversationId
            activeJob = job
            jobStartedAt = Date()
        } catch {
            messages.append(AskMessage(
                id: "error-\(UUID().uuidString)",
                role: .assistant,
                text: error.localizedDescription,
                isError: true
            ))
        }
        sending = false
    }

    /// Runs the direct NDJSON stream. Returns false when the backend declines it (422) so the
    /// caller can fall back to a job; true once the stream has finished, failed or been stopped.
    private func streamAnswer(_ text: String) async -> Bool {
        let streamId = "stream-\(UUID().uuidString)"
        var message = AskMessage(
            id: streamId,
            role: .assistant,
            text: "",
            model: app_defaultModelLabel,
            streaming: true,
            activity: [
                StreamStep(id: "request", label: "Sending request", detail: "Opening the stream", state: .live),
                StreamStep(id: "connect", label: "Connecting model", detail: "Waiting for first token", state: .pending),
                StreamStep(id: "stream", label: "Streaming answer", detail: "Preparing response", state: .pending),
                StreamStep(id: "save", label: "Saving chat", detail: "History updates when it finishes", state: .pending),
            ]
        )
        messages.append(message)
        streaming = true

        func update(_ transform: (inout AskMessage) -> Void) {
            guard let index = messages.firstIndex(where: { $0.id == streamId }) else { return }
            transform(&messages[index])
            message = messages[index]
        }

        func mark(_ id: String, _ state: StreamStep.State, _ detail: String? = nil) {
            update { current in
                guard let step = current.activity.firstIndex(where: { $0.id == id }) else { return }
                current.activity[step].state = state
                if let detail { current.activity[step].detail = detail }
            }
        }

        let task = Task { () -> Bool in
            var sawToken = false
            do {
                let stream = await APIClient.shared.directChatStream(
                    question: text,
                    conversationId: activeChatId,
                    allowGeneralKnowledge: allowGeneralKnowledge,
                    reasoningMode: EffortMode.light.backendId
                )
                for try await event in stream {
                    if Task.isCancelled { break }
                    switch event["type"]?.string {
                    case "start":
                        activeChatId = event["conversation_id"]?.int ?? activeChatId
                        mark("request", .done, "Stream open")
                        mark("connect", .live, event["model"]?.string ?? "Connected")
                        update { $0.model = event["model"]?.string ?? $0.model }
                    case "token":
                        if !sawToken {
                            sawToken = true
                            mark("connect", .done, "First token received")
                            mark("stream", .live, "Writing the answer")
                        }
                        update { $0.text += event["text"]?.string ?? "" }
                    case "result":
                        mark("stream", .done, "Answer complete")
                        mark("save", .live, "Persisting")
                    case "error":
                        throw APIError(message: event["detail"]?.string ?? "The stream failed", status: 0)
                    default:
                        break
                    }
                }
            } catch let error as APIError where error.status == 422 {
                // Not streamable — drop the placeholder and let the job pipeline handle it.
                messages.removeAll { $0.id == streamId }
                streaming = false
                return false
            } catch {
                update {
                    $0.streaming = false
                    if $0.text.isEmpty {
                        $0.text = error.localizedDescription
                        $0.isError = true
                    }
                }
                mark("stream", .failed, error.localizedDescription)
                streaming = false
                return true
            }

            update { $0.streaming = false }
            streaming = false
            // Reload the persisted transcript so the saved message (with its id and usage)
            // replaces the locally assembled one.
            if let chatId = activeChatId { await open(chatId: chatId) }
            await refreshChats()
            await loadSuggestions()
            LocusHaptics.success()
            return true
        }
        streamTask = task
        let handled = await task.value
        streamTask = nil
        return handled
    }

    func stop() async {
        if streaming {
            streamTask?.cancel()
            streamTask = nil
            streaming = false
            if let index = messages.lastIndex(where: { $0.streaming }) {
                messages[index].streaming = false
                if messages[index].text.isEmpty { messages[index].text = "Stopped." }
                if let step = messages[index].activity.firstIndex(where: { $0.state == .live }) {
                    messages[index].activity[step].state = .failed
                    messages[index].activity[step].detail = "Stopped by you"
                }
            }
            if let chatId = activeChatId { try? await APIClient.shared.stopChat(chatId) }
            LocusHaptics.warning()
            return
        }
        if let job = activeJob {
            try? await APIClient.shared.cancelChatJob(job.id)
        } else if let chatId = activeChatId {
            try? await APIClient.shared.stopChat(chatId)
        }
        activeJob = nil
        jobStartedAt = nil
        if let chatId = activeChatId { await open(chatId: chatId) }
        LocusHaptics.warning()
    }

    // MARK: - Polling

    /// The web polls `/api/chat/jobs` every 1.5s; same cadence here so a running answer's
    /// stage/telemetry updates at the same rate.
    func startPolling() {
        pollTask?.cancel()
        pollTask = Task { [weak self] in
            while !Task.isCancelled {
                await self?.pollOnce()
                try? await Task.sleep(for: .milliseconds(1500))
            }
        }
    }

    func stopPolling() {
        pollTask?.cancel()
        pollTask = nil
    }

    private func pollOnce() async {
        guard let jobs = try? await APIClient.shared.chatJobs() else { return }
        // Jobs come back newest-first; the one for this conversation is the live one.
        let mine = jobs.first { job in
            guard let activeChatId else { return activeJob?.id == job.id }
            return job.conversationId == activeChatId
        }

        guard let mine else { return }

        if ["queued", "running"].contains(mine.status) {
            activeJob = mine
            if jobStartedAt == nil { jobStartedAt = mine.createdAt }
            return
        }

        // Finished — reload the saved transcript so the answer, sources and usage come from
        // the persisted message rather than the job blob.
        if activeJob != nil {
            activeJob = nil
            jobStartedAt = nil
            if mine.status == "failed" {
                messages.append(AskMessage(
                    id: "job-error-\(mine.id)",
                    role: .assistant,
                    text: mine.error ?? "The answer failed.",
                    isError: true
                ))
            }
            if let chatId = activeChatId { await open(chatId: chatId) }
            await refreshChats()
            LocusHaptics.success()
            await loadSuggestions()
        }
    }

    private func loadSuggestions() async {
        guard let last = messages.last, last.role == .assistant, !last.isError,
              let question = messages.last(where: { $0.role == .user })?.text else { return }
        let response = try? await APIClient.shared.chatSuggestions(question: question, answer: last.text)
        suggestions = response?.suggestions ?? []
    }

    // MARK: - Helpers

    private static func message(from saved: ChatMessageRead) -> AskMessage {
        AskMessage(
            id: "saved-\(saved.id)",
            role: saved.role == "user" ? .user : .assistant,
            text: saved.content,
            sources: saved.sources,
            model: saved.model,
            provider: saved.provider,
            totalTokens: saved.totalTokens,
            serverId: saved.id
        )
    }

    /// `/normal`, `/high`, `/max` prefixes, matching the web's `getReasoningMode`.
    static func slashMode(in text: String) -> EffortMode? {
        let trimmed = text.trimmingCharacters(in: .whitespaces)
        for mode in EffortMode.allCases {
            if trimmed == mode.slashCommand || trimmed.hasPrefix(mode.slashCommand + " ") { return mode }
        }
        return nil
    }

    static func stripSlashPrefix(_ text: String) -> String {
        let trimmed = text.trimmingCharacters(in: .whitespaces)
        for mode in EffortMode.allCases {
            if trimmed == mode.slashCommand { return "" }
            if trimmed.hasPrefix(mode.slashCommand + " ") {
                return String(trimmed.dropFirst(mode.slashCommand.count + 1))
                    .trimmingCharacters(in: .whitespaces)
            }
        }
        return trimmed
    }
}

extension EffortMode {
    /// The reasoning-mode id the backend has always used.
    var backendId: String {
        switch self {
        case .light: return "light"
        case .thinking: return "thinking"
        case .deepSummary: return "deep_summary"
        }
    }

    var slashCommand: String {
        switch self {
        case .light: return "/normal"
        case .thinking: return "/high"
        case .deepSummary: return "/max"
        }
    }

    /// Effort also caps how far web research may go — `EFFORT_WEB_SOURCE_LIMIT` in `ask.js`.
    var webSourceLimit: Int {
        switch self {
        case .light: return 20
        case .thinking: return 60
        case .deepSummary: return 200
        }
    }
}
