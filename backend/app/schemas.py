from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from .config import configured_model, llm_provider
from .providers import PROVIDER_ORDER, PROVIDERS


Color = Literal["violet", "peach", "green"]


def _require_known_provider(value: str | None) -> str | None:
    """Shared validator for every `provider`/`llmProvider` field below — keeps request
    validation in sync with the PROVIDERS registry instead of a hardcoded provider list that
    silently falls out of date whenever a provider is added there (see backend/app/providers.py).
    """
    if value is not None and value not in PROVIDERS:
        known = ", ".join(f"'{name}'" for name in PROVIDER_ORDER)
        raise ValueError(f"Input should be one of: {known}")
    return value


class CollectionCreate(BaseModel):
    title: str = Field(min_length=1, max_length=120)
    description: str = Field(default="", max_length=600)
    color: Color = "violet"


class CollectionRead(CollectionCreate):
    model_config = ConfigDict(from_attributes=True)

    id: int
    count: int = 0
    created_at: datetime


class StoredFileRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    content_type: str
    size: int
    store_id: int
    embedding_status: str = "pending"
    embedding_backend: str = ""
    embedding_model: str = ""
    embedding_chunks: int = 0
    embedding_error: str = ""
    created_at: datetime


class ChatRequest(BaseModel):
    question: str = Field(min_length=2, max_length=8000)
    conversation_id: int | None = None
    model: str = Field(default_factory=configured_model, min_length=1, max_length=200)
    provider: str = Field(default_factory=llm_provider)
    allow_general_knowledge: bool = True
    reasoning_mode: Literal["light", "thinking", "deep_summary", "ticket_analysis", "web_research", "unrestricted"] = "light"
    web_search: bool = False
    web_source_limit: int = Field(default=200, ge=3, le=200)
    file_ids: list[int] | None = None

    _check_provider = field_validator("provider")(_require_known_provider)


class TicketAnalysisRequest(BaseModel):
    fileId: int
    maxGroups: int | None = Field(default=None, ge=1, le=100)
    minGroupSize: int | None = Field(default=None, ge=1, le=1000)
    useLlmFallback: bool = False
    model: str | None = Field(default=None, min_length=1, max_length=200)
    embeddingMethod: Literal["tfidf", "neural_hash", "hybrid"] = "tfidf"
    clusteringMethod: Literal["taxonomy_semantic", "agglomerative", "kmeans", "hdbscan_lite", "google_kwikbucks"] = "taxonomy_semantic"
    problemGroupStrategy: Literal["taxonomy_then_cluster", "cluster_only", "taxonomy_only", "okf_first", "cluster_first", "okf_only"] = "taxonomy_then_cluster"
    similarityThreshold: float | None = Field(default=None, ge=0.05, le=0.95)
    targetClusters: int | None = Field(default=None, ge=2, le=200)
    hdbscanMinSamples: int | None = Field(default=None, ge=1, le=200)
    representativeCount: int | None = Field(default=None, ge=1, le=25)
    includeTelemetry: bool = True
    includeDebugSamples: bool = True
    useLlmLabels: bool = False
    suggestTaxonomyRules: bool = False
    llmProvider: str | None = None
    pauseOkfTaxonomy: bool = False
    taxonomyRules: list[dict[str, Any]] | None = None

    _check_provider = field_validator("llmProvider")(_require_known_provider)


class TicketAnalysisHistoryCreate(BaseModel):
    fileId: int
    fileName: str = Field(min_length=1, max_length=255)
    manifest: dict[str, Any]
    groups: list[dict[str, Any]]
    taxonomySuggestions: list[dict[str, Any]] = []
    config: dict[str, Any] = {}


class TicketAnalysisHistoryRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    file_id: int
    file_name: str
    manifest: dict[str, Any]
    groups: list[dict[str, Any]] = []
    taxonomy_suggestions: list[dict[str, Any]] = []
    config: dict[str, Any] = {}
    created_at: datetime


class ChatSource(BaseModel):
    id: int = 0
    name: str = ""
    store_id: int = 0
    excerpt: str = ""
    url: str = ""
    engine: str = ""
    meta: bool = False
    llm_hits: int = 0
    web_queries: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0


class ChatResponse(BaseModel):
    answer: str
    sources: list[ChatSource]
    model: str | None = None
    conversation_id: int
    llm_hits: int = 0
    web_queries: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0


class SuggestionsRequest(BaseModel):
    question: str = Field(min_length=1, max_length=8000)
    # generate_followup_questions() only ever uses the first 4000 chars of this (see
    # answer_excerpt in llm.py), so this ceiling exists purely to reject abusive payloads, not
    # to gate normal answers. 20000 was tight enough that a genuinely long unrestricted/web
    # research/deep_summary answer (tens of thousands of chars once sources and formatting are
    # included) got a 422 here before generate_followup_questions ever ran — invisible to the
    # try/except in the endpoint below, since Pydantic validation happens before that code runs
    # at all, and invisible to the user, since the frontend's catch turns any error into "no
    # suggestions" either way.
    answer: str = Field(min_length=1, max_length=200_000)
    model: str = Field(default_factory=configured_model, min_length=1, max_length=200)
    provider: str = Field(default_factory=llm_provider)

    _check_provider = field_validator("provider")(_require_known_provider)


class SuggestionsResponse(BaseModel):
    suggestions: list[str] = []


class ChatSessionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str
    created_at: datetime
    updated_at: datetime
    message_count: int = 0
    total_chars: int = 0


class ChatMessageRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    role: str
    content: str
    sources: list[ChatSource] = []
    model: str | None = None
    provider: str | None = None
    llm_hits: int = 0
    web_queries: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    created_at: datetime


class ChatJobRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    status: str
    stage: str
    detail: str
    question: str
    conversation_id: int
    model: str
    provider: str | None = None
    reasoning_mode: str
    web_search: bool = False
    file_ids: list[int] | None = None
    events: list[dict] = []
    llm_hits: int = 0
    web_queries: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    result: dict | None = None
    partial_answer: str | None = None
    error: str | None = None
    seen: bool
    created_at: datetime
    updated_at: datetime


class UserPreferenceRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    key: str
    value: dict[str, Any] = {}
    updated_at: datetime | None = None


class UserPreferenceUpdate(BaseModel):
    value: dict[str, Any] = {}


class SecretChatCreateResponse(BaseModel):
    token: str
    url: str


class SecretChatCreate(BaseModel):
    title: str = Field(default="Private", max_length=160)
    host_key: str = Field(default="", max_length=64)
    # Auto-disappear: messages vanish this many seconds after they are posted (0 = keep).
    message_ttl_seconds: int = Field(default=0, ge=0, le=86400)
    # The invite link stops admitting new people after this many minutes (0 = never).
    link_expiry_minutes: int = Field(default=0, ge=0, le=10080)
    # The whole room is destroyed after this many minutes of existence (0 = never).
    room_expiry_minutes: int = Field(default=0, ge=0, le=10080)


class SecretChatOptionsUpdate(BaseModel):
    # Optional: a room with no owner is managed by whoever passes the app's auth gate.
    host_key: str = Field(default="", max_length=64)
    title: str | None = Field(default=None, max_length=160)
    message_ttl_seconds: int | None = Field(default=None, ge=0, le=86400)
    link_expiry_minutes: int | None = Field(default=None, ge=0, le=10080)
    room_expiry_minutes: int | None = Field(default=None, ge=0, le=10080)
    ai_tone: str | None = Field(default=None, max_length=40)
    ai_persona: str | None = Field(default=None, max_length=2000)
    ai_autopilot: bool | None = None
    ai_mimic_me: bool | None = None


class SecretChatMessageSend(BaseModel):
    sender: str = Field(default="Anonymous", min_length=1, max_length=60)
    content: str = Field(min_length=1, max_length=2000)
    via_ai: bool = False


class SecretChatMessageRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    sender: str
    content: str
    created_at: datetime
    via_ai: bool = False
    expires_at: datetime | None = None


class SecretChatPresenceUpdate(BaseModel):
    client_id: str = Field(min_length=1, max_length=64)
    name: str = Field(default="Anonymous", min_length=1, max_length=60)
    role: str = Field(default="guest", pattern="^(host|guest)$")
    host_key: str = Field(default="", max_length=64)
    typing: bool = False
    last_read_id: int = Field(default=0, ge=0)
    language: str = Field(default="", max_length=40)
    timezone: str = Field(default="", max_length=60)
    screen: str = Field(default="", max_length=40)
    viewport: str = Field(default="", max_length=40)


class SecretChatParticipantRead(BaseModel):
    """Public shape — everyone in the room sees this much about everyone else."""

    client_id: str
    name: str
    role: str
    online: bool
    typing: bool
    joined_at: datetime
    last_seen: datetime
    message_count: int
    last_read_id: int


class SecretChatParticipantDetail(SecretChatParticipantRead):
    """Host-only shape: the connection and device details behind a participant."""

    ip: str = ""
    user_agent: str = ""
    browser: str = ""
    os: str = ""
    device: str = ""
    language: str = ""
    timezone: str = ""
    local_time: str = ""
    screen: str = ""
    viewport: str = ""
    minutes_in_room: int = 0


class SecretChatBridgeLink(BaseModel):
    """Connect a room to someone on an outside messenger, by phone number."""

    host_key: str = Field(default="", max_length=64)
    platform: str = Field(default="telegram", pattern="^(telegram)$")
    phone: str = Field(min_length=6, max_length=24)
    # Optional first message, so the guest sees why a chat just appeared.
    greeting: str = Field(default="", max_length=2000)


class SecretChatBridgeRead(BaseModel):
    platform: str
    phone: str
    peer_name: str = ""
    peer_username: str = ""
    client_id: str = ""
    created_at: datetime | None = None
    last_outbound_at: datetime | None = None
    last_inbound_at: datetime | None = None
    last_error: str = ""


class SecretChatBridgeStatus(BaseModel):
    """Whether this deployment can bridge at all — asked before showing the UI."""

    platform: str = "telegram"
    configured: bool = False
    connected: bool = False
    account: str = ""
    error: str = ""


class SecretChatSessionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    token: str
    title: str
    created_at: datetime
    last_activity: datetime
    message_ttl_seconds: int = 0
    link_expires_at: datetime | None = None
    expires_at: datetime | None = None
    link_expired: bool = False
    ai_tone: str = "friendly"
    ai_persona: str = ""
    ai_autopilot: bool = False
    ai_mimic_me: bool = True
    messages: list[SecretChatMessageRead] = []
    participants: list[SecretChatParticipantRead] = []


class SecretChatRoomSummary(BaseModel):
    """One row of the host's own room list."""

    token: str
    url: str
    title: str
    created_at: datetime
    last_activity: datetime
    message_count: int
    unread_count: int
    last_message_id: int
    last_message_preview: str = ""
    last_sender: str = ""
    participant_count: int
    online_count: int
    message_ttl_seconds: int = 0
    link_expires_at: datetime | None = None
    expires_at: datetime | None = None
    link_expired: bool = False
    # Host-only listing, so naming the bridged guest here is safe. The room's own
    # GET is public to link guests and deliberately says nothing about the bridge.
    bridge_platform: str = ""
    bridge_name: str = ""


class SecretChatAssistRequest(BaseModel):
    host_key: str = Field(default="", max_length=64)
    client_id: str = Field(default="", max_length=64)
    sender: str = Field(default="", max_length=60)
    mode: str = Field(default="suggest", pattern="^(suggest|autopilot)$")
    tone: str = Field(default="friendly", max_length=40)
    persona: str = Field(default="", max_length=2000)
    mimic_me: bool = True
    instruction: str = Field(default="", max_length=400)
    model: str | None = None
    provider: str | None = None


class SecretChatAssistResponse(BaseModel):
    suggestions: list[str] = []
    tone: str = "friendly"
    model: str = ""
    style_samples: int = 0


class AuthStatusRead(BaseModel):
    auth_required: bool
    authenticated: bool = False
    expires_at: datetime | None = None


class AuthLoginRequest(BaseModel):
    password: str = Field(min_length=1, max_length=200)


class AuthLoginResponse(BaseModel):
    token: str
    expires_at: datetime


class SecretImagesStatus(BaseModel):
    configured: bool


class SecretImageRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    content_type: str
    size_bytes: int
    original_filename: str
    created_at: datetime
    url: str = ""
