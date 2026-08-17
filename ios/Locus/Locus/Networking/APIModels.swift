import Foundation

/// Type-erased JSON value for the free-form dicts the API uses
/// (preference values, job events, job results).
enum AnyCodable: Codable, Sendable {
    case string(String)
    case int(Int)
    case double(Double)
    case bool(Bool)
    case dict([String: AnyCodable])
    case array([AnyCodable])
    case null

    init(from decoder: Decoder) throws {
        let container = try decoder.singleValueContainer()
        if container.decodeNil() {
            self = .null
        } else if let value = try? container.decode(Bool.self) {
            self = .bool(value)
        } else if let value = try? container.decode(Int.self) {
            self = .int(value)
        } else if let value = try? container.decode(Double.self) {
            self = .double(value)
        } else if let value = try? container.decode(String.self) {
            self = .string(value)
        } else if let value = try? container.decode([String: AnyCodable].self) {
            self = .dict(value)
        } else if let value = try? container.decode([AnyCodable].self) {
            self = .array(value)
        } else {
            throw DecodingError.dataCorruptedError(in: container, debugDescription: "Unsupported JSON value")
        }
    }

    func encode(to encoder: Encoder) throws {
        var container = encoder.singleValueContainer()
        switch self {
        case .string(let value): try container.encode(value)
        case .int(let value): try container.encode(value)
        case .double(let value): try container.encode(value)
        case .bool(let value): try container.encode(value)
        case .dict(let value): try container.encode(value)
        case .array(let value): try container.encode(value)
        case .null: try container.encodeNil()
        }
    }

    var string: String? {
        if case .string(let value) = self { return value }
        return nil
    }

    var bool: Bool? {
        if case .bool(let value) = self { return value }
        return nil
    }

    var int: Int? {
        switch self {
        case .int(let value): return value
        case .double(let value): return Int(value)
        default: return nil
        }
    }

    var dict: [String: AnyCodable]? {
        if case .dict(let value) = self { return value }
        return nil
    }

    var array: [AnyCodable]? {
        if case .array(let value) = self { return value }
        return nil
    }

    subscript(key: String) -> AnyCodable? { dict?[key] }
}

// MARK: - DTOs mirroring backend/app/schemas.py (snake_case as sent)

struct AuthStatus: Decodable, Sendable {
    let authRequired: Bool
    let authenticated: Bool
    let expiresAt: Date?

    enum CodingKeys: String, CodingKey {
        case authRequired = "auth_required"
        case authenticated
        case expiresAt = "expires_at"
    }
}

struct AuthLoginResponse: Decodable, Sendable {
    let token: String
    let expiresAt: Date?

    enum CodingKeys: String, CodingKey {
        case token
        case expiresAt = "expires_at"
    }
}

struct CollectionRead: Decodable, Identifiable, Sendable {
    let id: Int
    let title: String
    let description: String
    let color: String
    let count: Int
    let createdAt: Date

    enum CodingKeys: String, CodingKey {
        case id, title, description, color, count
        case createdAt = "created_at"
    }
}

struct StoredFileRead: Decodable, Identifiable, Sendable {
    let id: Int
    let name: String
    let contentType: String
    let size: Int
    let storeId: Int
    let embeddingStatus: String
    let embeddingBackend: String
    let embeddingModel: String
    let embeddingChunks: Int
    let embeddingError: String
    let createdAt: Date

    enum CodingKeys: String, CodingKey {
        case id, name, size
        case contentType = "content_type"
        case storeId = "store_id"
        case embeddingStatus = "embedding_status"
        case embeddingBackend = "embedding_backend"
        case embeddingModel = "embedding_model"
        case embeddingChunks = "embedding_chunks"
        case embeddingError = "embedding_error"
        case createdAt = "created_at"
    }
}

struct ChatSessionRead: Decodable, Identifiable, Sendable {
    let id: Int
    let title: String
    let createdAt: Date
    let updatedAt: Date
    let messageCount: Int
    let totalChars: Int

    enum CodingKeys: String, CodingKey {
        case id, title
        case createdAt = "created_at"
        case updatedAt = "updated_at"
        case messageCount = "message_count"
        case totalChars = "total_chars"
    }
}

struct ChatSource: Decodable, Identifiable, Sendable {
    let id: Int
    let name: String
    let storeId: Int
    let excerpt: String
    let url: String
    let engine: String
    let meta: Bool
    let llmHits: Int
    let webQueries: Int
    let promptTokens: Int
    let completionTokens: Int
    let totalTokens: Int

    enum CodingKeys: String, CodingKey {
        case id, name, excerpt, url, engine, meta
        case storeId = "store_id"
        case llmHits = "llm_hits"
        case webQueries = "web_queries"
        case promptTokens = "prompt_tokens"
        case completionTokens = "completion_tokens"
        case totalTokens = "total_tokens"
    }
}

struct ChatMessageRead: Decodable, Identifiable, Sendable {
    let id: Int
    let role: String
    let content: String
    let sources: [ChatSource]
    let model: String?
    let provider: String?
    let llmHits: Int
    let webQueries: Int
    let promptTokens: Int
    let completionTokens: Int
    let totalTokens: Int
    let createdAt: Date

    enum CodingKeys: String, CodingKey {
        case id, role, content, sources, model, provider
        case llmHits = "llm_hits"
        case webQueries = "web_queries"
        case promptTokens = "prompt_tokens"
        case completionTokens = "completion_tokens"
        case totalTokens = "total_tokens"
        case createdAt = "created_at"
    }
}

struct ChatResponse: Decodable, Sendable {
    let answer: String
    let sources: [ChatSource]
    let model: String?
    let conversationId: Int
    let llmHits: Int
    let webQueries: Int
    let promptTokens: Int
    let completionTokens: Int
    let totalTokens: Int
    let actionsTaken: [[String: AnyCodable]]

    enum CodingKeys: String, CodingKey {
        case answer, sources, model
        case conversationId = "conversation_id"
        case llmHits = "llm_hits"
        case webQueries = "web_queries"
        case promptTokens = "prompt_tokens"
        case completionTokens = "completion_tokens"
        case totalTokens = "total_tokens"
        case actionsTaken = "actions_taken"
    }
}

struct ChatJobRead: Decodable, Identifiable, Sendable {
    let id: String
    let status: String
    let stage: String
    let detail: String
    let question: String
    let conversationId: Int
    let model: String
    let provider: String?
    let reasoningMode: String
    let webSearch: Bool
    let fileIds: [Int]?
    let events: [[String: AnyCodable]]
    let llmHits: Int
    let webQueries: Int
    let promptTokens: Int
    let completionTokens: Int
    let totalTokens: Int
    let result: [String: AnyCodable]?
    let partialAnswer: String?
    let error: String?
    let seen: Bool
    let createdAt: Date
    let updatedAt: Date

    enum CodingKeys: String, CodingKey {
        case id, status, stage, detail, question, model, provider, events, result, error, seen
        case conversationId = "conversation_id"
        case reasoningMode = "reasoning_mode"
        case webSearch = "web_search"
        case fileIds = "file_ids"
        case llmHits = "llm_hits"
        case webQueries = "web_queries"
        case promptTokens = "prompt_tokens"
        case completionTokens = "completion_tokens"
        case totalTokens = "total_tokens"
        case partialAnswer = "partial_answer"
        case createdAt = "created_at"
        case updatedAt = "updated_at"
    }
}

struct UserPreferenceRead: Decodable, Sendable {
    let key: String
    let value: [String: AnyCodable]
    let updatedAt: Date?

    enum CodingKeys: String, CodingKey {
        case key, value
        case updatedAt = "updated_at"
    }
}

struct SuggestionsResponse: Decodable, Sendable {
    let suggestions: [String]
}

struct ModelHealth: Codable, Sendable {
    let ok: Bool
    let latencyMs: Int
    let error: String
    let checkedAt: String

    enum CodingKeys: String, CodingKey {
        case ok, error
        case latencyMs = "latency_ms"
        case checkedAt = "checked_at"
    }
}

struct ProviderCatalogEntry: Decodable, Sendable {
    let label: String
    let icon: String
    let blurb: String
    let requiresKey: Bool
    let envHint: String
    let docsUrl: String

    enum CodingKeys: String, CodingKey {
        case label, icon, blurb
        case requiresKey = "requires_key"
        case envHint = "env_hint"
        case docsUrl = "docs_url"
    }
}

struct LLMConfig: Decodable, Sendable {
    let provider: String
    let model: String
    let models: [String]
    let providers: [String: [String]]
    let providersCatalog: [String: ProviderCatalogEntry]
    let providerOrder: [String]
    let presets: [String]
    let usingFallbackModels: Bool
    let modelMeta: [String: [String: AnyCodable]]

    enum CodingKeys: String, CodingKey {
        case provider, model, models, providers, presets
        case providersCatalog = "providers_catalog"
        case providerOrder = "provider_order"
        case usingFallbackModels = "using_fallback_models"
        case modelMeta = "model_meta"
    }
}

struct ModelTestResponse: Decodable, Sendable {
    let provider: String
    let results: [String: ModelHealth]
}

// MARK: - Secret chat DTOs

struct SecretChatCreateResponse: Decodable, Sendable {
    let token: String
    let url: String
}

struct SecretChatMessageRead: Decodable, Identifiable, Sendable {
    let id: Int
    let sender: String
    let content: String
    let createdAt: Date
    let viaAI: Bool
    let expiresAt: Date?

    enum CodingKeys: String, CodingKey {
        case id, sender, content
        case createdAt = "created_at"
        case viaAI = "via_ai"
        case expiresAt = "expires_at"
    }
}

struct SecretChatParticipantRead: Decodable, Identifiable, Sendable {
    let clientId: String
    let name: String
    let role: String
    let online: Bool
    let typing: Bool
    let joinedAt: Date
    let lastSeen: Date
    let messageCount: Int
    let lastReadId: Int

    var id: String { clientId }

    enum CodingKeys: String, CodingKey {
        case name, role, online, typing
        case clientId = "client_id"
        case joinedAt = "joined_at"
        case lastSeen = "last_seen"
        case messageCount = "message_count"
        case lastReadId = "last_read_id"
    }
}

struct SecretChatParticipantDetail: Decodable, Identifiable, Sendable {
    let clientId: String
    let name: String
    let role: String
    let online: Bool
    let typing: Bool
    let joinedAt: Date
    let lastSeen: Date
    let messageCount: Int
    let lastReadId: Int
    let ip: String
    let userAgent: String
    let browser: String
    let os: String
    let device: String
    let language: String
    let timezone: String
    let localTime: String
    let screen: String
    let viewport: String
    let minutesInRoom: Int

    var id: String { clientId }

    enum CodingKeys: String, CodingKey {
        case name, role, online, typing, ip, browser, os, device, language, timezone, screen, viewport
        case clientId = "client_id"
        case joinedAt = "joined_at"
        case lastSeen = "last_seen"
        case messageCount = "message_count"
        case lastReadId = "last_read_id"
        case userAgent = "user_agent"
        case localTime = "local_time"
        case minutesInRoom = "minutes_in_room"
    }
}

struct SecretChatRoomSummary: Decodable, Identifiable, Sendable {
    let token: String
    let url: String
    let title: String
    let createdAt: Date
    let lastActivity: Date
    let messageCount: Int
    let unreadCount: Int
    let lastMessageId: Int
    let lastMessagePreview: String
    let lastSender: String
    let participantCount: Int
    let onlineCount: Int
    let messageTTLSeconds: Int
    let linkExpiresAt: Date?
    let expiresAt: Date?
    let linkExpired: Bool
    let bridgePlatform: String
    let bridgeName: String

    var id: String { token }

    enum CodingKeys: String, CodingKey {
        case token, url, title
        case createdAt = "created_at"
        case lastActivity = "last_activity"
        case messageCount = "message_count"
        case unreadCount = "unread_count"
        case lastMessageId = "last_message_id"
        case lastMessagePreview = "last_message_preview"
        case lastSender = "last_sender"
        case participantCount = "participant_count"
        case onlineCount = "online_count"
        case messageTTLSeconds = "message_ttl_seconds"
        case linkExpiresAt = "link_expires_at"
        case expiresAt = "expires_at"
        case linkExpired = "link_expired"
        case bridgePlatform = "bridge_platform"
        case bridgeName = "bridge_name"
    }
}

struct SecretChatSessionRead: Decodable, Sendable {
    let token: String
    let title: String
    let createdAt: Date
    let lastActivity: Date
    let messageTTLSeconds: Int
    let linkExpiresAt: Date?
    let expiresAt: Date?
    let linkExpired: Bool
    let aiTone: String
    let aiPersona: String
    let aiAutopilot: Bool
    let aiMimicMe: Bool
    let messages: [SecretChatMessageRead]
    let participants: [SecretChatParticipantRead]

    enum CodingKeys: String, CodingKey {
        case token, title, messages, participants
        case createdAt = "created_at"
        case lastActivity = "last_activity"
        case messageTTLSeconds = "message_ttl_seconds"
        case linkExpiresAt = "link_expires_at"
        case expiresAt = "expires_at"
        case linkExpired = "link_expired"
        case aiTone = "ai_tone"
        case aiPersona = "ai_persona"
        case aiAutopilot = "ai_autopilot"
        case aiMimicMe = "ai_mimic_me"
    }
}

struct SecretChatAssistResponse: Decodable, Sendable {
    let suggestions: [String]
    let tone: String
    let model: String
    let styleSamples: Int

    enum CodingKeys: String, CodingKey {
        case suggestions, tone, model
        case styleSamples = "style_samples"
    }
}

struct SecretChatAutopilotDraft: Decodable, Identifiable, Sendable {
    let id: String
    let content: String
    let triggerMessageId: Int?
    let holdSeconds: Double
    let remainingSeconds: Double

    enum CodingKeys: String, CodingKey {
        case id, content
        case triggerMessageId = "trigger_message_id"
        case holdSeconds = "hold_seconds"
        case remainingSeconds = "remaining_seconds"
    }
}

struct SecretChatAutopilotPending: Decodable, Sendable {
    let pending: SecretChatAutopilotDraft?
}

/// Presence heartbeat response. The participant list comes back detailed for the host and
/// public for a guest, and `room` carries option changes made from another device.
struct SecretChatPresenceResponse: Decodable, Sendable {
    struct Room: Decodable, Sendable {
        let title: String
        let messageTTLSeconds: Int
        let linkExpiresAt: Date?
        let expiresAt: Date?
        let linkExpired: Bool

        enum CodingKeys: String, CodingKey {
            case title
            case messageTTLSeconds = "message_ttl_seconds"
            case linkExpiresAt = "link_expires_at"
            case expiresAt = "expires_at"
            case linkExpired = "link_expired"
        }
    }

    /// Decoded as the *public* shape on purpose: the backend only returns the detailed one
    /// when this client is the room's host, so decoding detail here would break presence for
    /// a room hosted from another device. The guests panel uses `/participants` for detail.
    let participants: [SecretChatParticipantRead]
    let room: Room?
}

struct SecretChatBridgeStatus: Decodable, Sendable {
    let platform: String
    let configured: Bool
    let connected: Bool
    let account: String
    let error: String
}

// MARK: - Secret images DTOs

struct SecretImagesStatus: Decodable, Sendable {
    let configured: Bool
}

struct SecretImageRead: Decodable, Identifiable, Sendable {
    let id: Int
    let contentType: String
    let sizeBytes: Int
    let originalFilename: String
    let createdAt: Date
    let url: String

    enum CodingKeys: String, CodingKey {
        case id, url
        case contentType = "content_type"
        case sizeBytes = "size_bytes"
        case originalFilename = "original_filename"
        case createdAt = "created_at"
    }
}
