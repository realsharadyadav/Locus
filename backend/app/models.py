from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, JSON, String, Text, func
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
    result: Mapped[dict | None] = mapped_column(JSON, nullable=True)
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
    messages: Mapped[list["SecretChatMessage"]] = relationship(back_populates="session", cascade="all, delete-orphan")


class SecretChatMessage(Base):
    __tablename__ = "secret_chat_messages"

    id: Mapped[int] = mapped_column(primary_key=True)
    session_token: Mapped[str] = mapped_column(ForeignKey("secret_chat_sessions.token"), index=True)
    sender: Mapped[str] = mapped_column(String(60), default="Anonymous")
    content: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    session: Mapped[SecretChatSession] = relationship(back_populates="messages")
