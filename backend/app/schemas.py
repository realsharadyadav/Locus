from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from .config import configured_model, llm_provider


Color = Literal["violet", "peach", "green"]


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
    provider: Literal["ollama", "groq", "openai", "gemini"] = Field(default_factory=llm_provider)
    allow_general_knowledge: bool = True
    reasoning_mode: Literal["light", "thinking", "deep_summary", "ticket_analysis", "web_research", "unrestricted"] = "light"
    web_search: bool = False
    web_source_limit: int = Field(default=200, ge=3, le=200)
    file_ids: list[int] | None = None


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
    llmProvider: Literal["ollama", "groq", "openai", "gemini"] | None = None
    pauseOkfTaxonomy: bool = False
    taxonomyRules: list[dict[str, Any]] | None = None


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


class ChatResponse(BaseModel):
    answer: str
    sources: list[ChatSource]
    model: str | None = None
    conversation_id: int
    llm_hits: int = 0
    web_queries: int = 0


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
    result: dict | None = None
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


class SecretChatMessageSend(BaseModel):
    sender: str = Field(default="Anonymous", min_length=1, max_length=60)
    content: str = Field(min_length=1, max_length=2000)


class SecretChatMessageRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    sender: str
    content: str
    created_at: datetime


class SecretChatSessionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    token: str
    title: str
    created_at: datetime
    last_activity: datetime
    messages: list[SecretChatMessageRead] = []
