from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, JSON, LargeBinary, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base


class Collection(Base):
    __tablename__ = "collections"

    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    description: Mapped[str] = mapped_column(Text, default="")
    color: Mapped[str] = mapped_column(String(24), default="violet")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    files: Mapped[list["StoredFile"]] = relationship(back_populates="store", cascade="all, delete-orphan")


class StoredFile(Base):
    __tablename__ = "stored_files"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(255), index=True)
    stored_name: Mapped[str] = mapped_column(String(255), unique=True)
    content_type: Mapped[str] = mapped_column(String(120), default="application/octet-stream")
    size: Mapped[int] = mapped_column(Integer)
    extracted_text: Mapped[str] = mapped_column(Text, default="")
    embedding_status: Mapped[str] = mapped_column(String(24), default="pending")
    embedding_backend: Mapped[str] = mapped_column(String(40), default="")
    embedding_model: Mapped[str] = mapped_column(String(80), default="")
    embedding_chunks: Mapped[int] = mapped_column(Integer, default=0)
    embedding_error: Mapped[str] = mapped_column(Text, default="")
    store_id: Mapped[int] = mapped_column(ForeignKey("collections.id"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), index=True)
    store: Mapped[Collection] = relationship(back_populates="files")


class ChatSession(Base):
    __tablename__ = "chat_sessions"

    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(160), default="New chat")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now(), index=True)
    messages: Mapped[list["ChatMessage"]] = relationship(back_populates="session", cascade="all, delete-orphan")


class ChatMessage(Base):
    __tablename__ = "chat_messages"

    id: Mapped[int] = mapped_column(primary_key=True)
    session_id: Mapped[int] = mapped_column(ForeignKey("chat_sessions.id"), index=True)
    role: Mapped[str] = mapped_column(String(20))
    content: Mapped[str] = mapped_column(Text)
    sources: Mapped[list] = mapped_column(JSON, default=list)
    model: Mapped[str | None] = mapped_column(String(120), nullable=True)
    provider: Mapped[str | None] = mapped_column(String(20), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    session: Mapped[ChatSession] = relationship(back_populates="messages")


class ChatJob(Base):
    __tablename__ = "chat_jobs"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    status: Mapped[str] = mapped_column(String(20), default="queued", index=True)
    stage: Mapped[str] = mapped_column(String(40), default="starting")
    detail: Mapped[str] = mapped_column(Text, default="Request received and queued")
    question: Mapped[str] = mapped_column(Text)
    conversation_id: Mapped[int] = mapped_column(Integer, index=True)
    model: Mapped[str] = mapped_column(String(120))
    provider: Mapped[str | None] = mapped_column(String(20), nullable=True)
    reasoning_mode: Mapped[str] = mapped_column(String(20), default="light")
    web_search: Mapped[bool] = mapped_column(Boolean, default=False)
    file_ids: Mapped[list | None] = mapped_column(JSON, nullable=True)
    events: Mapped[list] = mapped_column(JSON, default=list)
    llm_hits: Mapped[int] = mapped_column(Integer, default=0)
    web_queries: Mapped[int] = mapped_column(Integer, default=0)
    prompt_tokens: Mapped[int] = mapped_column(Integer, default=0)
    completion_tokens: Mapped[int] = mapped_column(Integer, default=0)
    total_tokens: Mapped[int] = mapped_column(Integer, default=0)
    result: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    partial_answer: Mapped[str | None] = mapped_column(Text, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    seen: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())


class TicketAnalysisResult(Base):
    __tablename__ = "ticket_analysis_results"

    id: Mapped[int] = mapped_column(primary_key=True)
    file_id: Mapped[int] = mapped_column(ForeignKey("stored_files.id"), index=True)
    file_name: Mapped[str] = mapped_column(String(255))
    manifest: Mapped[dict] = mapped_column(JSON)
    groups: Mapped[list] = mapped_column(JSON)
    taxonomy_suggestions: Mapped[list] = mapped_column(JSON, default=list)
    config: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), index=True)


class UserPreference(Base):
    __tablename__ = "user_preferences"

    key: Mapped[str] = mapped_column(String(80), primary_key=True)
    value: Mapped[dict] = mapped_column(JSON, default=dict)
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())


class SecretChatSession(Base):
    __tablename__ = "secret_chat_sessions"

    token: Mapped[str] = mapped_column(String(64), primary_key=True)
    title: Mapped[str] = mapped_column(String(160), default="Private")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    last_activity: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())
    # Only the creating browser knows this key; every host-only action is checked against it.
    host_key: Mapped[str] = mapped_column(String(64), default="", index=True)
    # 0 disables auto-disappear; otherwise messages are purged this many seconds after posting.
    message_ttl_seconds: Mapped[int] = mapped_column(Integer, default=0)
    # The invite stops admitting *new* people at link_expires_at; the room itself dies at expires_at.
    link_expires_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    ai_tone: Mapped[str] = mapped_column(String(40), default="friendly")
    ai_persona: Mapped[str] = mapped_column(Text, default="")
    ai_autopilot: Mapped[bool] = mapped_column(Boolean, default=False)
    ai_mimic_me: Mapped[bool] = mapped_column(Boolean, default=True)
    messages: Mapped[list["SecretChatMessage"]] = relationship(back_populates="session", cascade="all, delete-orphan")
    participants: Mapped[list["SecretChatParticipant"]] = relationship(back_populates="session", cascade="all, delete-orphan")
    bridge: Mapped["SecretChatBridge | None"] = relationship(
        back_populates="session", cascade="all, delete-orphan", uselist=False
    )


class SecretChatMessage(Base):
    __tablename__ = "secret_chat_messages"

    id: Mapped[int] = mapped_column(primary_key=True)
    session_token: Mapped[str] = mapped_column(ForeignKey("secret_chat_sessions.token"), index=True)
    sender: Mapped[str] = mapped_column(String(60), default="Anonymous")
    content: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    # Set when the author was the AI copilot on someone's behalf, so the UI can label it.
    via_ai: Mapped[bool] = mapped_column(Boolean, default=False)
    session: Mapped[SecretChatSession] = relationship(back_populates="messages")


class SecretChatBridge(Base):
    """Links one private chat room to one person on an outside messenger.

    One row per room (the token is the primary key): a room talks to exactly one bridged
    guest, which is what lets the host address them by phone number instead of a link.
    `peer_id` is the platform's own id for that person, resolved once at link time —
    the phone number is only ever an input, never how messages are routed.
    """

    __tablename__ = "secret_chat_bridges"

    session_token: Mapped[str] = mapped_column(
        ForeignKey("secret_chat_sessions.token"), primary_key=True
    )
    platform: Mapped[str] = mapped_column(String(20), default="telegram")
    phone: Mapped[str] = mapped_column(String(24), default="")
    peer_id: Mapped[str] = mapped_column(String(40), default="", index=True)
    peer_name: Mapped[str] = mapped_column(String(80), default="")
    peer_username: Mapped[str] = mapped_column(String(64), default="")
    # The synthetic participant this bridge writes as, so the guest shows up in the
    # host's room like any other participant.
    client_id: Mapped[str] = mapped_column(String(64), default="", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    last_outbound_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_inbound_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_error: Mapped[str] = mapped_column(String(300), default="")
    session: Mapped[SecretChatSession] = relationship(back_populates="bridge")


class SecretChatParticipant(Base):
    """One row per browser that has opened a private chat — the host's live view of who is in."""

    __tablename__ = "secret_chat_participants"

    id: Mapped[int] = mapped_column(primary_key=True)
    session_token: Mapped[str] = mapped_column(ForeignKey("secret_chat_sessions.token"), index=True)
    client_id: Mapped[str] = mapped_column(String(64), index=True)
    name: Mapped[str] = mapped_column(String(60), default="Anonymous")
    role: Mapped[str] = mapped_column(String(10), default="guest")
    first_seen: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    last_seen: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    typing_until: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_read_id: Mapped[int] = mapped_column(Integer, default=0)
    message_count: Mapped[int] = mapped_column(Integer, default=0)
    ip: Mapped[str] = mapped_column(String(64), default="")
    user_agent: Mapped[str] = mapped_column(String(400), default="")
    browser: Mapped[str] = mapped_column(String(60), default="")
    os: Mapped[str] = mapped_column(String(60), default="")
    device: Mapped[str] = mapped_column(String(24), default="")
    language: Mapped[str] = mapped_column(String(40), default="")
    timezone: Mapped[str] = mapped_column(String(60), default="")
    screen: Mapped[str] = mapped_column(String(40), default="")
    viewport: Mapped[str] = mapped_column(String(40), default="")
    session: Mapped[SecretChatSession] = relationship(back_populates="participants")


class SecretImage(Base):
    __tablename__ = "secret_images"

    id: Mapped[int] = mapped_column(primary_key=True)
    # Bytes live in the row, not on disk. The container filesystem is ephemeral on
    # the hosts this deploys to, so local files vanished on every restart while
    # these rows survived — a gallery of images that no longer existed. At the
    # 50KB compression budget a few thousand photos is tens of megabytes, well
    # within the database, and they get backed up with everything else.
    data: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    # Retained for rows written by the previous disk-backed version; new rows
    # leave it blank. Nothing reads it any more.
    file_path: Mapped[str] = mapped_column(String(160), unique=True, index=True)
    content_type: Mapped[str] = mapped_column(String(120), default="application/octet-stream")
    size_bytes: Mapped[int] = mapped_column(Integer, default=0)
    original_filename: Mapped[str] = mapped_column(String(255), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), index=True)
