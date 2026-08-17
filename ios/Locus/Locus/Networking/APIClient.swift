import Foundation

struct APIError: Error, LocalizedError, Sendable {
    let message: String
    let status: Int

    var errorDescription: String? { message }
}

/// One client for the whole REST surface. Bearer auth, backend-style error mapping
/// (`detail` can be a string, a validation-error list, or an object — same as the web
/// client's `request()`), and a 401 handoff back to the sign-in gate.
actor APIClient {
    static let shared = APIClient()

    /// Called on the main actor whenever a request comes back 401 (expired/rotated token).
    /// Login itself opts out — a 401 there means "wrong password", not a dead session.
    private var unauthorizedHandler: (@Sendable @MainActor () -> Void)?

    func setUnauthorizedHandler(_ handler: (@Sendable @MainActor () -> Void)?) {
        unauthorizedHandler = handler
    }

    private let session = URLSession.shared
    private static let tokenAccount = "locus.auth"

    /// Contains "iPhone"/"iPad" and "Mobile" so the backend's `_describe_client` reports the
    /// right OS and device; "Locus" is what the guests panel matches to label it as the app.
    static let userAgent: String = {
        let info = ProcessInfo.processInfo
        let version = info.operatingSystemVersion
        // Read the hardware identifier rather than UIDevice, which is main-actor isolated and
        // cannot be touched from this nonisolated initialiser.
        var system = utsname()
        uname(&system)
        let machine = withUnsafeBytes(of: &system.machine) { raw in
            String(cString: raw.baseAddress!.assumingMemoryBound(to: CChar.self))
        }
        let identifier = info.environment["SIMULATOR_MODEL_IDENTIFIER"] ?? machine
        let model = identifier.contains("iPad") ? "iPad" : "iPhone"
        return "Locus/1.0 (\(model); iOS \(version.majorVersion).\(version.minorVersion); Mobile)"
    }()

    // MARK: - Token

    nonisolated var token: String? { KeychainStore.read(account: Self.tokenAccount) }

    nonisolated func saveToken(_ value: String) {
        KeychainStore.save(value, account: Self.tokenAccount)
    }

    nonisolated func clearToken() {
        KeychainStore.delete(account: Self.tokenAccount)
    }

    // MARK: - Core request

    private func makeRequest(
        path: String,
        method: String,
        query: [String: String?] = [:],
        jsonBody: (any Encodable & Sendable)? = nil,
        multipartBody: Data? = nil,
        multipartContentType: String? = nil
    ) throws -> URLRequest {
        var components = URLComponents(string: ServerConfig.baseURL + "/api" + path)
        let items = query.compactMap { key, value -> URLQueryItem? in
            guard let value, !value.isEmpty else { return nil }
            return URLQueryItem(name: key, value: value)
        }
        if !items.isEmpty { components?.queryItems = items }
        guard let url = components?.url else { throw APIError(message: "Invalid server URL", status: 0) }

        var request = URLRequest(url: url, timeoutInterval: 120)
        request.httpMethod = method
        // The private-chat guests panel derives device/OS from the User-Agent, and URLSession's
        // default string says nothing useful — this makes the host's own row read correctly.
        request.setValue(Self.userAgent, forHTTPHeaderField: "User-Agent")
        if let token {
            request.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization")
        }
        if let jsonBody {
            request.setValue("application/json", forHTTPHeaderField: "Content-Type")
            request.httpBody = try JSONEncoder().encode(jsonBody)
        } else if let multipartBody {
            request.setValue(multipartContentType, forHTTPHeaderField: "Content-Type")
            request.httpBody = multipartBody
        }
        return request
    }

    /// Error body mapping identical to src/api.js: string detail, list of `{msg}`, or object.
    private static func errorMessage(from data: Data, status: Int) -> String {
        struct DetailProbe: Decodable { let detail: AnyCodable? }
        guard let probe = try? JSONDecoder().decode(DetailProbe.self, from: data),
              let detail = probe.detail else {
            return status == 404 ? "Not found" : "Something went wrong (\(status))"
        }
        if let message = detail.string { return message }
        if let list = detail.array {
            let parts = list.compactMap { $0["msg"]?.string ?? $0.string }
            if !parts.isEmpty { return parts.joined(separator: ", ") }
        }
        return "Something went wrong (\(status))"
    }

    /// Shared raw request: executes, maps errors, hands 401s to the gate.
    @discardableResult
    private func perform(_ request: URLRequest, allowUnauthorized: Bool = false) async throws -> (Data, HTTPURLResponse) {
        let (data, response): (Data, URLResponse)
        do {
            (data, response) = try await session.data(for: request)
        } catch {
            throw APIError(message: "Cannot reach the Locus server. Check the server URL in Settings.", status: 0)
        }
        guard let http = response as? HTTPURLResponse else {
            throw APIError(message: "Invalid server response", status: 0)
        }
        if http.statusCode == 401, !allowUnauthorized {
            let handler = unauthorizedHandler
            await MainActor.run { handler?() }
            throw APIError(message: "Sign in to continue", status: 401)
        }
        guard (200..<300).contains(http.statusCode) else {
            throw APIError(message: Self.errorMessage(from: data, status: http.statusCode), status: http.statusCode)
        }
        return (data, http)
    }

    private func decode<T: Decodable & Sendable>(_ type: T.Type, from data: Data) throws -> T {
        do {
            return try Self.decoder.decode(type, from: data)
        } catch {
            throw APIError(message: "Unexpected response format", status: 0)
        }
    }

    /// Backend timestamps are naive UTC ISO8601, with or without fractional seconds.
    static let decoder: JSONDecoder = {
        let decoder = JSONDecoder()
        decoder.dateDecodingStrategy = .custom { decoder in
            let container = try decoder.singleValueContainer()
            let raw = try container.decode(String.self)
            let withFraction = ISO8601DateFormatter()
            withFraction.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
            let plain = ISO8601DateFormatter()
            plain.formatOptions = [.withInternetDateTime]
            let cleaned = raw.hasSuffix("Z") || raw.contains("+") ? raw : raw + "Z"
            if let date = withFraction.date(from: cleaned) ?? plain.date(from: cleaned) {
                return date
            }
            throw DecodingError.dataCorruptedError(in: container, debugDescription: "Invalid date: \(raw)")
        }
        return decoder
    }()

    private func send<T: Decodable & Sendable>(
        _ type: T.Type,
        path: String,
        method: String = "GET",
        query: [String: String?] = [:],
        body: (any Encodable & Sendable)? = nil,
        allowUnauthorized: Bool = false
    ) async throws -> T {
        let request = try makeRequest(path: path, method: method, query: query, jsonBody: body)
        let (data, _) = try await perform(request, allowUnauthorized: allowUnauthorized)
        return try decode(type, from: data)
    }

    private func sendVoid(
        path: String,
        method: String,
        query: [String: String?] = [:],
        body: (any Encodable & Sendable)? = nil
    ) async throws {
        let request = try makeRequest(path: path, method: method, query: query, jsonBody: body)
        _ = try await perform(request)
    }

    // MARK: - Streaming primitives

    /// NDJSON stream (chat streaming endpoints): one JSON object per line.
    func ndjsonStream(
        path: String,
        body: any Encodable & Sendable
    ) -> AsyncThrowingStream<[String: AnyCodable], Error> {
        AsyncThrowingStream { continuation in
            let task = Task {
                do {
                    let request = try makeRequest(path: path, method: "POST", jsonBody: body)
                    let (bytes, response) = try await session.bytes(for: request)
                    guard let http = response as? HTTPURLResponse, (200..<300).contains(http.statusCode) else {
                        throw APIError(message: "Unable to start the stream", status: (response as? HTTPURLResponse)?.statusCode ?? 0)
                    }
                    for try await line in bytes.lines {
                        guard !line.trimmingCharacters(in: .whitespaces).isEmpty,
                              let data = line.data(using: .utf8),
                              let event = try? JSONDecoder().decode([String: AnyCodable].self, from: data) else { continue }
                        continuation.yield(event)
                    }
                    continuation.finish()
                } catch {
                    continuation.finish(throwing: error)
                }
            }
            continuation.onTermination = { _ in task.cancel() }
        }
    }

    /// SSE stream (secret chat): `event:` / `data:` frames, absolute path under /api.
    func sseStream(path: String, query: [String: String?] = [:]) -> AsyncThrowingStream<(event: String, data: String), Error> {
        AsyncThrowingStream { continuation in
            let task = Task {
                do {
                    let request = try makeRequest(path: path, method: "GET", query: query)
                    let (bytes, response) = try await session.bytes(for: request)
                    guard let http = response as? HTTPURLResponse, (200..<300).contains(http.statusCode) else {
                        throw APIError(message: "Stream unavailable", status: (response as? HTTPURLResponse)?.statusCode ?? 0)
                    }
                    var eventName = "message"
                    var dataLines: [String] = []
                    for try await line in bytes.lines {
                        if line.hasPrefix("event:") {
                            eventName = String(line.dropFirst(6)).trimmingCharacters(in: .whitespaces)
                        } else if line.hasPrefix("data:") {
                            dataLines.append(String(line.dropFirst(5)).trimmingCharacters(in: .whitespaces))
                        } else if line.isEmpty {
                            if !dataLines.isEmpty {
                                continuation.yield((eventName, dataLines.joined(separator: "\n")))
                            }
                            eventName = "message"
                            dataLines = []
                        }
                    }
                    continuation.finish()
                } catch {
                    continuation.finish(throwing: error)
                }
            }
            continuation.onTermination = { _ in task.cancel() }
        }
    }

    /// Raw bytes for an authenticated GET — used for secret images (binary content).
    func authenticatedData(path: String) async throws -> (Data, String?) {
        let request = try makeRequest(path: path, method: "GET")
        let (data, response) = try await perform(request)
        return (data, response.value(forHTTPHeaderField: "Content-Type"))
    }

    // MARK: - Auth

    struct LoginBody: Encodable, Sendable { let password: String }

    func authStatus() async throws -> AuthStatus {
        try await send(AuthStatus.self, path: "/auth/status")
    }

    func login(password: String) async throws -> AuthLoginResponse {
        try await send(AuthLoginResponse.self, path: "/auth/login", method: "POST",
                       body: LoginBody(password: password), allowUnauthorized: true)
    }

    func health() async throws -> Bool {
        struct Health: Decodable, Sendable { let status: String }
        let response = try await send(Health.self, path: "/health")
        return response.status == "ok"
    }

    // MARK: - Preferences

    struct PreferenceBody: Encodable, Sendable { let value: [String: AnyCodable] }

    func preference(_ key: String) async throws -> UserPreferenceRead {
        try await send(UserPreferenceRead.self, path: "/preferences/\(key)")
    }

    func updatePreference(_ key: String, value: [String: AnyCodable]) async throws -> UserPreferenceRead {
        try await send(UserPreferenceRead.self, path: "/preferences/\(key)", method: "PATCH",
                       body: PreferenceBody(value: value))
    }

    // MARK: - LLM

    func llmConfig() async throws -> LLMConfig {
        try await send(LLMConfig.self, path: "/llm/config")
    }

    struct ModelTestBody: Encodable, Sendable { let provider: String; let models: [String] }

    func testModels(provider: String, models: [String]) async throws -> ModelTestResponse {
        try await send(ModelTestResponse.self, path: "/llm/models/test", method: "POST",
                       body: ModelTestBody(provider: provider, models: models))
    }

    // MARK: - Collections & files

    func collections() async throws -> [CollectionRead] {
        try await send([CollectionRead].self, path: "/collections")
    }

    struct CollectionBody: Encodable, Sendable {
        let title: String
        let description: String
        let color: String
    }

    func createCollection(title: String, description: String = "", color: String = "violet") async throws -> CollectionRead {
        try await send(CollectionRead.self, path: "/collections", method: "POST",
                       body: CollectionBody(title: title, description: description, color: color))
    }

    func deleteCollection(_ id: Int) async throws {
        try await sendVoid(path: "/collections/\(id)", method: "DELETE")
    }

    func files() async throws -> [StoredFileRead] {
        try await send([StoredFileRead].self, path: "/files")
    }

    func deleteFile(_ id: Int) async throws {
        try await sendVoid(path: "/files/\(id)", method: "DELETE")
    }

    /// Multipart upload matching src/api.js: fields `store_id` + `file`, no manual
    /// Content-Type on the client side of the web version; here we set the boundary header.
    func uploadFile(storeId: Int, fileName: String, contentType: String, data: Data) async throws -> StoredFileRead {
        let boundary = "LocusBoundary-\(UUID().uuidString)"
        var body = Data()
        func append(_ string: String) {
            body.append(string.data(using: .utf8)!)
        }
        append("--\(boundary)\r\n")
        append("Content-Disposition: form-data; name=\"store_id\"\r\n\r\n")
        append("\(storeId)\r\n")
        append("--\(boundary)\r\n")
        append("Content-Disposition: form-data; name=\"file\"; filename=\"\(fileName)\"\r\n")
        append("Content-Type: \(contentType)\r\n\r\n")
        body.append(data)
        append("\r\n--\(boundary)--\r\n")
        let request = try makeRequest(path: "/files", method: "POST",
                                      multipartBody: body,
                                      multipartContentType: "multipart/form-data; boundary=\(boundary)")
        let (responseData, _) = try await perform(request)
        return try decode(StoredFileRead.self, from: responseData)
    }

    // MARK: - Chats & jobs

    func chats() async throws -> [ChatSessionRead] {
        try await send([ChatSessionRead].self, path: "/chats")
    }

    func chatMessages(_ id: Int) async throws -> [ChatMessageRead] {
        try await send([ChatMessageRead].self, path: "/chats/\(id)/messages")
    }

    func deleteChat(_ id: Int) async throws {
        try await sendVoid(path: "/chats/\(id)", method: "DELETE")
    }

    func deleteAllChats() async throws {
        try await sendVoid(path: "/chats", method: "DELETE")
    }

    func stopChat(_ id: Int) async throws {
        try await sendVoid(path: "/chats/\(id)/stop", method: "POST")
    }

    func truncateChat(chatId: Int, fromMessageId: Int) async throws {
        try await sendVoid(path: "/chats/\(chatId)/messages/\(fromMessageId)/from", method: "DELETE")
    }

    struct ChatJobBody: Encodable, Sendable {
        let question: String
        let conversationId: Int?
        let allowGeneralKnowledge: Bool
        let reasoningMode: String
        let fileIds: [Int]?
        let webSourceLimit: Int
        let webSearch: Bool

        enum CodingKeys: String, CodingKey {
            case question
            case conversationId = "conversation_id"
            case allowGeneralKnowledge = "allow_general_knowledge"
            case reasoningMode = "reasoning_mode"
            case fileIds = "file_ids"
            case webSourceLimit = "web_source_limit"
            case webSearch = "web_search"
        }
    }

    func createChatJob(question: String, conversationId: Int?, allowGeneralKnowledge: Bool,
                       reasoningMode: String, fileIds: [Int]?, webSourceLimit: Int = 200,
                       webSearch: Bool = false) async throws -> ChatJobRead {
        try await send(ChatJobRead.self, path: "/chat/jobs", method: "POST",
                       body: ChatJobBody(question: question, conversationId: conversationId,
                                         allowGeneralKnowledge: allowGeneralKnowledge,
                                         reasoningMode: reasoningMode, fileIds: fileIds,
                                         webSourceLimit: webSourceLimit, webSearch: webSearch))
    }

    func chatJobs() async throws -> [ChatJobRead] {
        try await send([ChatJobRead].self, path: "/chat/jobs")
    }

    func cancelChatJob(_ id: String) async throws {
        try await sendVoid(path: "/chat/jobs/\(id)/cancel", method: "POST")
    }

    struct DirectStreamBody: Encodable, Sendable {
        let question: String
        let conversationId: Int?
        let allowGeneralKnowledge: Bool
        let reasoningMode: String
        let fileIds: [Int]
        let webSearch: Bool

        enum CodingKeys: String, CodingKey {
            case question
            case conversationId = "conversation_id"
            case allowGeneralKnowledge = "allow_general_knowledge"
            case reasoningMode = "reasoning_mode"
            case fileIds = "file_ids"
            case webSearch = "web_search"
        }
    }

    /// Token-by-token NDJSON stream. The backend rejects anything it cannot answer directly
    /// (422 when effort > Normal, files are scoped, or it detects search intent), so callers
    /// fall back to the job pipeline on that status rather than duplicating the rules.
    func directChatStream(question: String, conversationId: Int?, allowGeneralKnowledge: Bool,
                          reasoningMode: String) -> AsyncThrowingStream<[String: AnyCodable], Error> {
        ndjsonStream(path: "/chat/direct-stream", body: DirectStreamBody(
            question: question,
            conversationId: conversationId,
            allowGeneralKnowledge: allowGeneralKnowledge,
            reasoningMode: reasoningMode,
            fileIds: [],
            webSearch: false
        ))
    }

    struct SuggestionsBody: Encodable, Sendable { let question: String; let answer: String }

    func chatSuggestions(question: String, answer: String) async throws -> SuggestionsResponse {
        try await send(SuggestionsResponse.self, path: "/chat/suggestions", method: "POST",
                       body: SuggestionsBody(question: question, answer: answer))
    }

    // MARK: - Secret chat

    struct SecretChatCreateBody: Encodable, Sendable {
        let title: String
        let hostKey: String
        let messageTTLSeconds: Int
        let linkExpiryMinutes: Int
        let roomExpiryMinutes: Int

        enum CodingKeys: String, CodingKey {
            case title
            case hostKey = "host_key"
            case messageTTLSeconds = "message_ttl_seconds"
            case linkExpiryMinutes = "link_expiry_minutes"
            case roomExpiryMinutes = "room_expiry_minutes"
        }
    }

    func secretChatCreate(title: String, hostKey: String, messageTTLSeconds: Int,
                          linkExpiryMinutes: Int, roomExpiryMinutes: Int) async throws -> SecretChatCreateResponse {
        try await send(SecretChatCreateResponse.self, path: "/secret-chat", method: "POST",
                       body: SecretChatCreateBody(title: title, hostKey: hostKey,
                                                  messageTTLSeconds: messageTTLSeconds,
                                                  linkExpiryMinutes: linkExpiryMinutes,
                                                  roomExpiryMinutes: roomExpiryMinutes))
    }

    func secretChatRooms(hostKey: String, clientId: String) async throws -> [SecretChatRoomSummary] {
        try await send([SecretChatRoomSummary].self, path: "/secret-chat",
                       query: ["host_key": hostKey, "client_id": clientId])
    }

    func secretChatGet(_ token: String, clientId: String, hostKey: String) async throws -> SecretChatSessionRead {
        try await send(SecretChatSessionRead.self, path: "/secret-chat/\(token)",
                       query: ["client_id": clientId, "host_key": hostKey])
    }

    struct SecretChatOptionsBody: Encodable, Sendable {
        let hostKey: String
        let title: String?
        let messageTTLSeconds: Int?
        let linkExpiryMinutes: Int?
        let roomExpiryMinutes: Int?
        let aiTone: String?
        let aiPersona: String?
        let aiAutopilot: Bool?
        let aiMimicMe: Bool?

        enum CodingKeys: String, CodingKey {
            case title
            case hostKey = "host_key"
            case messageTTLSeconds = "message_ttl_seconds"
            case linkExpiryMinutes = "link_expiry_minutes"
            case roomExpiryMinutes = "room_expiry_minutes"
            case aiTone = "ai_tone"
            case aiPersona = "ai_persona"
            case aiAutopilot = "ai_autopilot"
            case aiMimicMe = "ai_mimic_me"
        }
    }

    func secretChatUpdateOptions(_ token: String, body: SecretChatOptionsBody) async throws -> SecretChatSessionRead {
        try await send(SecretChatSessionRead.self, path: "/secret-chat/\(token)", method: "PATCH", body: body)
    }

    func secretChatDeleteRoom(_ token: String, hostKey: String) async throws {
        try await sendVoid(path: "/secret-chat/\(token)", method: "DELETE", query: ["host_key": hostKey])
    }

    func secretChatClearMessages(_ token: String, hostKey: String) async throws {
        try await sendVoid(path: "/secret-chat/\(token)/messages", method: "DELETE", query: ["host_key": hostKey])
    }

    func secretChatMessages(_ token: String, after: Int = 0) async throws -> [SecretChatMessageRead] {
        try await send([SecretChatMessageRead].self, path: "/secret-chat/\(token)/messages?after=\(after)")
    }

    struct SecretChatMessageBody: Encodable, Sendable {
        let sender: String
        let content: String
        let viaAI: Bool

        enum CodingKeys: String, CodingKey {
            case sender, content
            case viaAI = "via_ai"
        }
    }

    func secretChatSend(_ token: String, sender: String, content: String, viaAI: Bool = false) async throws -> SecretChatMessageRead {
        try await send(SecretChatMessageRead.self, path: "/secret-chat/\(token)/messages",
                       method: "POST", body: SecretChatMessageBody(sender: sender, content: content, viaAI: viaAI))
    }

    struct SecretChatPresenceBody: Encodable, Sendable {
        let clientId: String
        let name: String
        let role: String
        let hostKey: String
        let typing: Bool
        let lastReadId: Int
        let language: String
        let timezone: String
        let screen: String
        let viewport: String

        enum CodingKeys: String, CodingKey {
            case name, role, typing, language, timezone, screen, viewport
            case clientId = "client_id"
            case hostKey = "host_key"
            case lastReadId = "last_read_id"
        }
    }

    @discardableResult
    func secretChatPresence(_ token: String, body: SecretChatPresenceBody) async throws -> SecretChatPresenceResponse {
        try await send(SecretChatPresenceResponse.self, path: "/secret-chat/\(token)/presence",
                       method: "POST", body: body)
    }

    func secretChatParticipants(_ token: String, hostKey: String) async throws -> [SecretChatParticipantDetail] {
        try await send([SecretChatParticipantDetail].self, path: "/secret-chat/\(token)/participants",
                       query: ["host_key": hostKey])
    }

    struct SecretChatAssistBody: Encodable, Sendable {
        let hostKey: String
        let clientId: String
        let sender: String
        let mode: String
        let tone: String
        let persona: String
        let mimicMe: Bool
        let instruction: String

        enum CodingKeys: String, CodingKey {
            case sender, mode, tone, persona, instruction
            case hostKey = "host_key"
            case clientId = "client_id"
            case mimicMe = "mimic_me"
        }
    }

    func secretChatAssist(_ token: String, body: SecretChatAssistBody) async throws -> SecretChatAssistResponse {
        try await send(SecretChatAssistResponse.self, path: "/secret-chat/\(token)/assist",
                       method: "POST", body: body)
    }

    func secretChatAutopilotDraft(_ token: String, hostKey: String) async throws -> SecretChatAutopilotPending {
        try await send(SecretChatAutopilotPending.self, path: "/secret-chat/\(token)/autopilot",
                       query: ["host_key": hostKey])
    }

    struct SecretChatAutopilotDecisionBody: Encodable, Sendable {
        let hostKey: String
        let draftId: String
        let action: String

        enum CodingKeys: String, CodingKey {
            case action
            case hostKey = "host_key"
            case draftId = "draft_id"
        }
    }

    func secretChatAutopilotDecide(_ token: String, hostKey: String, draftId: String, action: String) async throws {
        try await sendVoid(path: "/secret-chat/\(token)/autopilot", method: "POST",
                           body: SecretChatAutopilotDecisionBody(hostKey: hostKey, draftId: draftId, action: action))
    }

    func secretChatBridgeStatus() async throws -> SecretChatBridgeStatus {
        try await send(SecretChatBridgeStatus.self, path: "/secret-chat/bridge/status")
    }

    // MARK: - Secret images

    func secretImagesStatus() async throws -> SecretImagesStatus {
        try await send(SecretImagesStatus.self, path: "/secret-images/status")
    }

    func secretImages() async throws -> [SecretImageRead] {
        try await send([SecretImageRead].self, path: "/secret-images")
    }

    func secretImageUpload(fileName: String, contentType: String, data: Data) async throws -> SecretImageRead {
        let boundary = "LocusBoundary-\(UUID().uuidString)"
        var body = Data()
        body.append("--\(boundary)\r\n".data(using: .utf8)!)
        body.append("Content-Disposition: form-data; name=\"file\"; filename=\"\(fileName)\"\r\n".data(using: .utf8)!)
        body.append("Content-Type: \(contentType)\r\n\r\n".data(using: .utf8)!)
        body.append(data)
        body.append("\r\n--\(boundary)--\r\n".data(using: .utf8)!)
        let request = try makeRequest(path: "/secret-images", method: "POST",
                                      multipartBody: body,
                                      multipartContentType: "multipart/form-data; boundary=\(boundary)")
        let (responseData, _) = try await perform(request)
        return try decode(SecretImageRead.self, from: responseData)
    }

    func secretImageDelete(_ id: Int) async throws {
        try await sendVoid(path: "/secret-images/\(id)", method: "DELETE")
    }
}
