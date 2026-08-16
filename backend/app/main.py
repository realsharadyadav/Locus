from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager, nullcontext
import asyncio
from datetime import datetime, timedelta, timezone
import hashlib
import httpx
import json
import os
from pathlib import Path
from queue import Queue
from types import SimpleNamespace
import random
import re
from inspect import signature
from threading import Event, Lock, Thread
import time
import traceback
from uuid import uuid4

from fastapi import Depends, FastAPI, File, Form, HTTPException, Response, UploadFile, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from sqlalchemy import delete, func, inspect, select, text, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from . import local_storage
from .database import Base, SessionLocal, engine, get_db
OLLAMA_URL = os.getenv("OLLAMA_URL", "http://127.0.0.1:11434")

from .config import (
    EMBEDDING_BATCH_SIZE, GROQ_MODEL_PRESETS,
    MAX_UPLOAD_FILE_MB, SEMANTIC_MIN_SCORE,
    configured_model, gateway_settings, llm_provider,
)
from .ai_defaults import preferred_ai
from .assistant_tools import classify_platform_action, execute_action, tool_label
from .auto_select import MODEL_HEALTH_PREFERENCE_KEY, choose_fallback, record_switch
from .diagnostics import delete_job_log, diagnostic_event, diagnostic_job, initialize_job_log
from .agentic_pipeline import run_agentic_pipeline
from .brand import (
    ABOUT_LOCUS_QUESTION_PATTERN,
    ABOUT_LOCUS_SYSTEM_PROMPT,
    CAPABILITY_ANSWER_INTRO,
    CAPABILITY_JOKE_CLOSERS,
    CAPABILITY_QUESTION_PATTERN,
    CREATOR_BIO_ANSWERS,
    CREATOR_JOKE_ANSWERS,
    CREATOR_NAME_PATTERN,
    CREATOR_QUESTION_PATTERN,
)
from .web_research import web_research, web_search_tracker
from .intent import _fallback_classify
from .deep_summary import deep_summarize_documents, is_full_summary_intent, is_summary_intent, missing_sections
from .files import IMAGE_EXTENSIONS, SUPPORTED_EXTENSIONS, TABULAR_EXTENSIONS, extract_text_from_path, relevant_excerpt
from .llm import ANSWER_SHAPE_INSTRUCTION, LLMProviderError, answer_planned_question, build_model_meta, clean_final_answer, enhance_question, extract_shared_evidence, generate_answer, generate_followup_questions, list_groq_models, list_openai_compatible_models, probe_model, llm_call_cache, llm_provider_context, refusal_diagnostic, repair_response, stream_answer, token_usage_tracker, verify_response
from .modes import MODE_CONFIG
from .models import ChatJob, ChatMessage, ChatSession, Collection, StoredFile, UserPreference
from .providers import PROVIDER_ORDER, PROVIDERS
from .schemas import ChatJobRead, ChatMessageRead, ChatRequest, ChatResponse, ChatSessionRead, ChatSource, CollectionCreate, CollectionRead, ModelTestRequest, ModelTestResponse, StoredFileRead, SuggestionsRequest, SuggestionsResponse, UserPreferenceRead, UserPreferenceUpdate
from .seed import seed_database
from . import telegram_bridge
from .vector_store import EMBEDDING_MODEL, VectorStoreUnavailable, active_embedding_model, delete_file_embeddings, ensure_vector_schema, index_file_with_status, search as semantic_search


class ChatJobCancelled(RuntimeError):
    pass


USER_STOPPED_DETAIL = "Answer stopped by user"
CHAT_DELETED_CANCEL_DETAIL = "Chat was deleted; answer pipeline cancelled"
_CHAT_JOB_CANCEL_EVENTS: dict[str, Event] = {}
_CHAT_JOB_CANCEL_REASONS: dict[str, str] = {}
_CHAT_JOB_CANCEL_LOCK = Lock()
_CHAT_STREAM_CANCEL_EVENTS: dict[int, list[Event]] = {}
_CHAT_STREAM_CANCEL_LOCK = Lock()


def _chat_job_cancel_event(job_id: str) -> Event:
    with _CHAT_JOB_CANCEL_LOCK:
        return _CHAT_JOB_CANCEL_EVENTS.setdefault(job_id, Event())


def _forget_chat_job_cancel_event(job_id: str) -> None:
    with _CHAT_JOB_CANCEL_LOCK:
        _CHAT_JOB_CANCEL_EVENTS.pop(job_id, None)
        _CHAT_JOB_CANCEL_REASONS.pop(job_id, None)


def _cancel_chat_jobs(job_ids: list[str], reason: str = CHAT_DELETED_CANCEL_DETAIL) -> None:
    with _CHAT_JOB_CANCEL_LOCK:
        for job_id in job_ids:
            _CHAT_JOB_CANCEL_REASONS[job_id] = reason
            _CHAT_JOB_CANCEL_EVENTS.setdefault(job_id, Event()).set()


def _chat_job_cancel_reason(job_id: str) -> str:
    with _CHAT_JOB_CANCEL_LOCK:
        return _CHAT_JOB_CANCEL_REASONS.get(job_id, CHAT_DELETED_CANCEL_DETAIL)


def _chat_stream_cancel_event(chat_id: int) -> Event:
    event = Event()
    with _CHAT_STREAM_CANCEL_LOCK:
        _CHAT_STREAM_CANCEL_EVENTS.setdefault(chat_id, []).append(event)
    return event


def _forget_chat_stream_cancel_event(chat_id: int, event: Event) -> None:
    with _CHAT_STREAM_CANCEL_LOCK:
        events = _CHAT_STREAM_CANCEL_EVENTS.get(chat_id)
        if not events:
            return
        try:
            events.remove(event)
        except ValueError:
            return
        if not events:
            _CHAT_STREAM_CANCEL_EVENTS.pop(chat_id, None)


def _cancel_chat_streams(chat_ids: list[int]) -> None:
    with _CHAT_STREAM_CANCEL_LOCK:
        events = [event for chat_id in chat_ids for event in _CHAT_STREAM_CANCEL_EVENTS.get(chat_id, [])]
    for event in events:
        event.set()


def _ensure_schema_columns():
    # These ALTERs only ever run against a database that predates a column, which in practice
    # means the deployed Postgres — a fresh database gets every column from create_all and
    # skips this entirely. So the DDL has to be portable, not SQLite-flavoured: Postgres has
    # no DATETIME type, and rejects 0/1 as a BOOLEAN default.
    postgres = engine.dialect.name == "postgresql"
    TIMESTAMP = "TIMESTAMP" if postgres else "DATETIME"
    FALSE, TRUE = ("FALSE", "TRUE") if postgres else ("0", "1")

    inspector = inspect(engine)
    chat_job_columns = {column["name"] for column in inspector.get_columns("chat_jobs")}
    chat_message_columns = {column["name"] for column in inspector.get_columns("chat_messages")}
    stored_file_columns = {column["name"] for column in inspector.get_columns("stored_files")}
    secret_chat_session_columns = {column["name"] for column in inspector.get_columns("secret_chat_sessions")}
    secret_chat_message_columns = {column["name"] for column in inspector.get_columns("secret_chat_messages")}
    secret_image_columns = {column["name"] for column in inspector.get_columns("secret_images")}
    BLOB = "BYTEA" if postgres else "BLOB"
    with engine.begin() as connection:
        if "file_ids" not in chat_job_columns:
            connection.execute(text("ALTER TABLE chat_jobs ADD COLUMN file_ids JSON"))
        if "embedding_status" not in stored_file_columns:
            connection.execute(text("ALTER TABLE stored_files ADD COLUMN embedding_status VARCHAR(24) NOT NULL DEFAULT 'pending'"))
        if "embedding_backend" not in stored_file_columns:
            connection.execute(text("ALTER TABLE stored_files ADD COLUMN embedding_backend VARCHAR(40) NOT NULL DEFAULT ''"))
        if "embedding_model" not in stored_file_columns:
            connection.execute(text("ALTER TABLE stored_files ADD COLUMN embedding_model VARCHAR(80) NOT NULL DEFAULT ''"))
        if "embedding_chunks" not in stored_file_columns:
            connection.execute(text("ALTER TABLE stored_files ADD COLUMN embedding_chunks INTEGER NOT NULL DEFAULT 0"))
        if "embedding_error" not in stored_file_columns:
            connection.execute(text("ALTER TABLE stored_files ADD COLUMN embedding_error TEXT NOT NULL DEFAULT ''"))
        if "provider" not in chat_job_columns:
            connection.execute(text("ALTER TABLE chat_jobs ADD COLUMN provider VARCHAR(20)"))
        if "web_search" not in chat_job_columns:
            connection.execute(text(f"ALTER TABLE chat_jobs ADD COLUMN web_search BOOLEAN NOT NULL DEFAULT {FALSE}"))
        if "provider" not in chat_message_columns:
            connection.execute(text("ALTER TABLE chat_messages ADD COLUMN provider VARCHAR(20)"))
        if "llm_hits" not in chat_job_columns:
            connection.execute(text("ALTER TABLE chat_jobs ADD COLUMN llm_hits INTEGER NOT NULL DEFAULT 0"))
        if "web_queries" not in chat_job_columns:
            connection.execute(text("ALTER TABLE chat_jobs ADD COLUMN web_queries INTEGER NOT NULL DEFAULT 0"))
        if "prompt_tokens" not in chat_job_columns:
            connection.execute(text("ALTER TABLE chat_jobs ADD COLUMN prompt_tokens INTEGER NOT NULL DEFAULT 0"))
        if "completion_tokens" not in chat_job_columns:
            connection.execute(text("ALTER TABLE chat_jobs ADD COLUMN completion_tokens INTEGER NOT NULL DEFAULT 0"))
        if "total_tokens" not in chat_job_columns:
            connection.execute(text("ALTER TABLE chat_jobs ADD COLUMN total_tokens INTEGER NOT NULL DEFAULT 0"))
        if "partial_answer" not in chat_job_columns:
            connection.execute(text("ALTER TABLE chat_jobs ADD COLUMN partial_answer TEXT"))
        for column, ddl in (
            ("host_key", "ALTER TABLE secret_chat_sessions ADD COLUMN host_key VARCHAR(64) NOT NULL DEFAULT ''"),
            ("message_ttl_seconds", "ALTER TABLE secret_chat_sessions ADD COLUMN message_ttl_seconds INTEGER NOT NULL DEFAULT 0"),
            ("link_expires_at", f"ALTER TABLE secret_chat_sessions ADD COLUMN link_expires_at {TIMESTAMP}"),
            ("expires_at", f"ALTER TABLE secret_chat_sessions ADD COLUMN expires_at {TIMESTAMP}"),
            ("closed_at", f"ALTER TABLE secret_chat_sessions ADD COLUMN closed_at {TIMESTAMP}"),
            ("ai_tone", "ALTER TABLE secret_chat_sessions ADD COLUMN ai_tone VARCHAR(40) NOT NULL DEFAULT 'friendly'"),
            ("ai_persona", "ALTER TABLE secret_chat_sessions ADD COLUMN ai_persona TEXT NOT NULL DEFAULT ''"),
            ("ai_autopilot", f"ALTER TABLE secret_chat_sessions ADD COLUMN ai_autopilot BOOLEAN NOT NULL DEFAULT {FALSE}"),
            ("ai_mimic_me", f"ALTER TABLE secret_chat_sessions ADD COLUMN ai_mimic_me BOOLEAN NOT NULL DEFAULT {TRUE}"),
        ):
            if column not in secret_chat_session_columns:
                connection.execute(text(ddl))
        if "via_ai" not in secret_chat_message_columns:
            connection.execute(text(f"ALTER TABLE secret_chat_messages ADD COLUMN via_ai BOOLEAN NOT NULL DEFAULT {FALSE}"))
        # `r2_key` was renamed to `file_path` when Secret Images moved off R2 onto disk, but
        # only in the model — create_all never alters an existing table, so every database
        # that predates the rename still has the old column and the ORM's `file_path` selects
        # fail against it. Rename it here before anything below touches the table.
        if "file_path" not in secret_image_columns and "r2_key" in secret_image_columns:
            connection.execute(text("ALTER TABLE secret_images RENAME COLUMN r2_key TO file_path"))
            secret_image_columns = (secret_image_columns - {"r2_key"}) | {"file_path"}
        if "data" not in secret_image_columns:
            connection.execute(text(f"ALTER TABLE secret_images ADD COLUMN data {BLOB}"))
            _backfill_secret_images_from_disk(connection, secret_image_columns)


def _backfill_secret_images_from_disk(connection, secret_image_columns: set[str]) -> None:
    """Move any still-present disk files into the rows that reference them.

    Only does anything on a host that kept its filesystem across the upgrade —
    a local checkout. Where the disk was ephemeral the files are already gone,
    and those rows stay empty; `_prune_dataless_secret_images` clears them so the
    gallery does not advertise photos it cannot serve.

    Takes the column set rather than probing, because this runs inside the same
    transaction as the ADD COLUMN above: a failed statement here would abort that
    transaction and roll the new column back, so every later boot would retry the
    identical failure and never start. Selecting a column that isn't there is not
    worth that, and a database with no path column has nothing to backfill from.
    """
    if "file_path" not in secret_image_columns:
        return
    rows = connection.execute(text("SELECT id, file_path FROM secret_images WHERE data IS NULL")).all()
    for image_id, file_path in rows:
        if not file_path:
            continue
        source = local_storage.get_file_path(file_path)
        try:
            if not source.exists():
                continue
            payload = source.read_bytes()
        except OSError:
            continue
        connection.execute(
            text("UPDATE secret_images SET data = :data WHERE id = :id"),
            {"data": payload, "id": image_id},
        )


def _prune_dataless_secret_images() -> None:
    """Drop rows whose bytes never made it into the database.

    These are leftovers from the disk-backed version whose files the host threw
    away. They can only ever render as broken tiles, so they are cleared once at
    startup rather than left for the reader to discover one by one.
    """
    with engine.begin() as connection:
        connection.execute(text("DELETE FROM secret_images WHERE data IS NULL"))


def _index_stored_file(db: Session, stored_file: StoredFile) -> None:
    stored_file.embedding_status = "indexing"
    stored_file.embedding_backend = ""
    stored_file.embedding_model = EMBEDDING_MODEL
    stored_file.embedding_chunks = 0
    stored_file.embedding_error = ""
    db.commit()
    try:
        result = index_file_with_status(stored_file.id, stored_file.store_id, stored_file.name, stored_file.extracted_text)
        stored_file.embedding_status = result.status
        stored_file.embedding_backend = result.backend
        stored_file.embedding_model = result.model
        stored_file.embedding_chunks = result.chunks
        stored_file.embedding_error = result.error
    except Exception as exception:
        stored_file.embedding_status = "failed"
        stored_file.embedding_backend = "unavailable"
        stored_file.embedding_model = EMBEDDING_MODEL
        stored_file.embedding_chunks = 0
        stored_file.embedding_error = str(exception)[:1000]
    db.commit()


def _startup_maintenance():
    """Catch-up work after a restart: refresh tabular profiles, index what is unindexed.

    Runs on its own thread so a cold start serves traffic immediately, and handles one file
    per transaction so a single large file cannot hold the whole set in memory — both of
    which is why this no longer lives in the lifespan handler.
    """
    try:
        with SessionLocal() as db:
            file_ids = list(db.scalars(select(StoredFile.id)).all())
    except Exception as exception:  # noqa: BLE001 - a restart must not die over catch-up work
        diagnostic_event("startup.maintenance_failed", error=str(exception)[:500])
        return

    current_embedding_model = active_embedding_model()
    refreshed = indexed = failed = 0
    for file_id in file_ids:
        try:
            with SessionLocal() as db:
                stored_file = db.get(StoredFile, file_id)
                if stored_file is None:
                    continue
                extension = Path(stored_file.name).suffix.lower()
                stored_path = UPLOAD_DIR / stored_file.stored_name
                # A fully-extracted tabular file can no longer be re-processed after a future
                # profiling-version bump: the raw file is deleted right after upload (and by the
                # dead-file sweep below), so this re-read only works while the bytes still exist.
                # Accepted tradeoff — the exists() guard below degrades gracefully by keeping
                # whatever text is already stored.
                if extension in TABULAR_EXTENSIONS and "Profile version: 3" not in stored_file.extracted_text and stored_path.exists():
                    stored_file.extracted_text = extract_text_from_path(stored_file.name, stored_path)
                    db.commit()
                    refreshed += 1
                stale_embedding = stored_file.embedding_status == "embedded" and stored_file.embedding_model != current_embedding_model
                needs_index = (
                    stored_file.embedding_status in {"", "pending", "failed", "indexing"}
                    or (stored_file.embedding_status == "embedded" and not stored_file.embedding_chunks)
                    or stale_embedding
                )
                if needs_index:
                    _index_stored_file(db, stored_file)
                    indexed += 1
        except Exception as exception:  # noqa: BLE001 - one bad file must not stop the sweep
            failed += 1
            diagnostic_event("startup.maintenance_file_failed", file_id=file_id, error=str(exception)[:500])

    # Dead-file sweep. Uploads are now unlinked right after extraction+indexing (the text is
    # committed to the DB before indexing runs), so anything still on disk is dead weight —
    # uploads made before that rule shipped, or orphans left by a past crash between a DB
    # delete and the disk unlink. It runs AFTER the loop above on purpose: that loop may still
    # re-read a tabular file's raw bytes off disk for this restart's re-profiling, and the
    # sweep must not delete them first. Idempotent by design — a second run finds nothing left
    # and just lists the directory.
    dead_files_removed = 0
    dead_bytes_freed = 0
    try:
        with SessionLocal() as db:
            stored_text = dict(db.execute(select(StoredFile.stored_name, StoredFile.extracted_text)).all())
    except Exception as exception:  # noqa: BLE001 - a restart must not die over cleanup
        diagnostic_event("startup.dead_file_sweep_failed", error=str(exception)[:500])
    else:
        try:
            disk_files = list(UPLOAD_DIR.iterdir())
        except Exception as exception:  # noqa: BLE001 - a restart must not die over cleanup
            diagnostic_event("startup.dead_file_sweep_failed", error=str(exception)[:500])
            disk_files = []
        for disk_file in disk_files:
            try:
                if not disk_file.is_file():
                    continue
                extracted_text = stored_text.get(disk_file.name)
                # Delete when there is no row at all (orphan) or the row's text is already
                # extracted. Keep when extraction never completed — a later pass may still need
                # the bytes to extract or index.
                if extracted_text is None or extracted_text:
                    dead_bytes_freed += disk_file.stat().st_size
                    disk_file.unlink(missing_ok=True)
                    dead_files_removed += 1
            except Exception as exception:  # noqa: BLE001 - one bad file must not stop the sweep
                diagnostic_event("startup.dead_file_sweep_failed", name=disk_file.name, error=str(exception)[:500])
    diagnostic_event(
        "startup.maintenance_complete",
        files=len(file_ids),
        profiles_refreshed=refreshed,
        files_indexed=indexed,
        files_failed=failed,
        dead_files_removed=dead_files_removed,
        dead_bytes_freed=dead_bytes_freed,
    )


@asynccontextmanager
async def lifespan(_: FastAPI):
    Base.metadata.create_all(bind=engine)
    ensure_vector_schema()
    _ensure_schema_columns()
    _prune_dataless_secret_images()
    with SessionLocal() as db:
        interrupted_jobs = db.scalars(select(ChatJob).where(ChatJob.status.in_(["queued", "running"]))).all()
        for job in interrupted_jobs:
            diagnostic_event(
                "job.interrupted",
                job_id=job.id,
                provider="unknown-after-restart",
                model=job.model,
                reasoning_mode=job.reasoning_mode,
                previous_status=job.status,
                previous_stage=job.stage,
                error="Backend restarted before the job completed",
                log_retained=True,
            )
        db.execute(
            update(ChatJob)
            .where(ChatJob.status.in_(["queued", "running"]))
            .values(status="failed", stage="failed", detail="Interrupted by a backend restart", error="This task was interrupted when the backend restarted. Please ask the question again.")
        )
        db.commit()
        seed_database(db)
    if STARTUP_MAINTENANCE:
        # Re-extraction and re-indexing used to run here, inline. On a small instance that
        # walked every uploaded file before the app would answer anything, which is how the
        # health check timed out and the service tripped its memory limit on boot. It is
        # catch-up work, not a precondition for serving, so it goes to a background thread.
        Thread(target=_startup_maintenance, name="locus-startup-maintenance", daemon=True).start()
    # Connecting the Telegram account is a network handshake, so it goes on its own thread
    # for the same reason as the maintenance pass: nothing here should delay /api/health.
    # It matters at boot rather than on first use because a bridged room has to keep
    # receiving the guest's replies even when nobody has Locus open.
    if telegram_bridge.configured():
        Thread(target=telegram_bridge.start, name="locus-telegram-start", daemon=True).start()
    yield


app = FastAPI(title="Locus API", version="0.1.0", lifespan=lifespan)
# LOCUS_UPLOAD_DIR lets tests (see conftest.py) point this at an isolated directory. Without
# it, the startup maintenance dead-file sweep and a real local dev tree would share one
# physical folder, so running the test suite against an isolated test database would see every
# real uploaded file as an "orphan" (no matching row in that empty test DB) and delete it.
UPLOAD_DIR = Path(os.getenv("LOCUS_UPLOAD_DIR") or (Path(__file__).resolve().parents[1] / "uploads"))
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
# Set LOCUS_STARTUP_MAINTENANCE=0 to skip the post-restart re-extract/re-index sweep entirely
# — useful on a memory-tight instance, at the cost of files staying unindexed until re-uploaded.
STARTUP_MAINTENANCE = os.getenv("LOCUS_STARTUP_MAINTENANCE", "1").strip().lower() not in {"0", "false", "off", "no"}
CHAT_JOB_MAX_RETRIES = int(os.getenv("CHAT_JOB_MAX_RETRIES", "3"))
# Extra gap-driven retrieval rounds the quality layer may run when the verifier reports omissions.
# Each round costs one retrieval pass plus a repair and a re-verify call, so this stays small.
CHAT_EVIDENCE_ROUNDS = int(os.getenv("LOCUS_CHAT_EVIDENCE_ROUNDS", "2"))
CHAT_JOB_RETRY_DELAY_SECONDS = float(os.getenv("CHAT_JOB_RETRY_DELAY_SECONDS", "2"))
# The lifespan handler fails any job still queued/running at boot, but that only catches a full
# process restart. A job whose background thread dies some other way (OOM kill that the process
# survives, a hung call with no timeout) leaves status="running" with nothing left ever going to
# touch it again — updated_at stops advancing once the heartbeat thread stops too, which is what
# this timeout actually detects. Generous on purpose: the heaviest jobs (deep research pulling
# 20+ sources) still finish in a couple of minutes, so anything untouched this long is dead, not
# slow.
CHAT_JOB_STALE_TIMEOUT_SECONDS = float(os.getenv("CHAT_JOB_STALE_TIMEOUT_SECONDS", "900"))
OPENAI_MODEL_FALLBACKS = ["gpt-5.4-mini", "gpt-5.5"]
GEMINI_MODEL_FALLBACKS = ["gemini-2.5-flash", "gemini-2.5-pro"]
from .auth import require_auth, router as auth_router
# Registered before CORS so CORS ends up the outer layer — otherwise a 401 would
# come back without CORS headers and the browser would report it as a network
# error instead of a sign-in prompt.
app.middleware("http")(require_auth)

# "*" cannot be combined with credentials, and the Bearer-token gate does not
# need them. Set LOCUS_ALLOWED_ORIGINS once the frontend origin is known.
ALLOWED_ORIGINS = [origin.strip() for origin in os.getenv("LOCUS_ALLOWED_ORIGINS", "*").split(",") if origin.strip()] or ["*"]
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=ALLOWED_ORIGINS != ["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

from .secret_chat import router as secret_chat_router
from .secret_images import router as secret_images_router
app.include_router(secret_chat_router)
app.include_router(secret_images_router)
app.include_router(auth_router)


@app.get("/api/health")
def health():
    return {"status": "ok"}


@app.get("/api/llm/config")
def llm_config():
    provider = llm_provider()
    groq_models, using_fallback = list_groq_models()
    try:
        ollama_resp = httpx.get(f"{OLLAMA_URL}/api/tags", timeout=3)
        ollama_models = [m["name"] for m in ollama_resp.json().get("models", [])] if ollama_resp.status_code == 200 else []
    except Exception:
        ollama_models = []
    openai_models = []
    openai_key = os.getenv("OPENAI_API_KEY", "").strip()
    if openai_key:
        try:
            listing = list_openai_compatible_models(PROVIDERS["openai"].base_url, openai_key, timeout=5)
            openai_models = sorted(
                model_id for model_id in listing
                if model_id.startswith(("gpt-", "o1", "o3", "o4", "chatgpt-"))
                and not any(
                    excluded in model_id.lower()
                    for excluded in ("embedding", "whisper", "tts", "dall-e", "moderation", "davinci", "babbage", "computer-use")
                )
            )
        except Exception:
            openai_models = []
    gemini_models = []
    if os.getenv("GEMINI_API_KEY", "").strip():
        try:
            response = httpx.get(
                "https://generativelanguage.googleapis.com/v1beta/models",
                headers={"x-goog-api-key": os.environ["GEMINI_API_KEY"].strip()},
                timeout=5,
            )
            if response.status_code == 200:
                gemini_models = sorted(
                    item["name"].removeprefix("models/")
                    for item in response.json().get("models", [])
                    if isinstance(item, dict)
                    and "generateContent" in item.get("supportedGenerationMethods", [])
                    and item.get("name", "").startswith("models/gemini-")
                )
        except Exception:
            gemini_models = []

    cerebras_models = []
    if os.getenv("CEREBRAS_API_KEY", "").strip():
        try:
            base_url = os.getenv("CEREBRAS_BASE_URL", "https://api.cerebras.ai/v1").rstrip("/")
            listing = list_openai_compatible_models(base_url, os.environ["CEREBRAS_API_KEY"].strip(), timeout=5)
            cerebras_models = sorted(listing)
        except Exception:
            cerebras_models = []

    # Any OpenAI-compatible gateway provider (OpenRouter, TokenRouter, and future entries in
    # the registry) is listed the same generic way — a registry entry is all that's needed to
    # add another one, no new branch here.
    gateway_models: dict[str, list[str]] = {}
    gateway_metadata: dict[str, dict] = {}
    for provider_id, spec in PROVIDERS.items():
        if spec.kind != "gateway":
            continue
        api_key = os.getenv(spec.api_key_env, "").strip()
        if not api_key:
            gateway_models[provider_id] = []
            continue
        try:
            # Read the base URL through gateway_settings so a *_BASE_URL override in .env applies
            # to model discovery too, not just to the chat calls in llm.py.
            base_url = gateway_settings(provider_id, require_key=False).base_url
            listing = list_openai_compatible_models(base_url, api_key, timeout=5)
            gateway_models[provider_id] = sorted(listing)
            gateway_metadata[provider_id] = listing
        except Exception:
            gateway_models[provider_id] = []

    provider_models = {
        "ollama": ollama_models,
        "groq": groq_models,
        "openai": openai_models,
        "gemini": gemini_models,
        "cerebras": cerebras_models,
        **gateway_models,
    }
    return {
        "provider": provider,
        "model": configured_model(),
        "models": provider_models.get(provider, []),
        "providers": provider_models,
        "providers_catalog": {
            provider_id: {
                "label": spec.label,
                "icon": spec.icon,
                "blurb": spec.blurb,
                "requires_key": spec.api_key_env is not None,
                "env_hint": spec.env_hint,
                "docs_url": spec.docs_url,
            }
            for provider_id, spec in PROVIDERS.items()
        },
        "provider_order": PROVIDER_ORDER,
        "presets": GROQ_MODEL_PRESETS if provider == "groq" else provider_models.get(provider, []),
        "fallback_presets": {"openai": OPENAI_MODEL_FALLBACKS, "gemini": GEMINI_MODEL_FALLBACKS},
        "using_fallback_models": using_fallback,
        "model_meta": build_model_meta(provider_models, gateway_metadata),
    }


# Probes are network-bound, so a handful at a time finishes a page of models quickly without
# looking like a burst of abuse to a provider's rate limiter.
MODEL_TEST_CONCURRENCY = 4


@app.post("/api/llm/models/test", response_model=ModelTestResponse)
def test_models(payload: ModelTestRequest, db: Session = Depends(get_db)):
    """Ping each model and record whether it answered.

    Settings uses this to tag models as responding, so a default can be picked from models
    that are known to work rather than from everything a provider happens to list. Results are
    saved under the `model_health` preference: the tags survive a reload, and a model that has
    never been tested stays untagged rather than being guessed at.
    """
    checked_at = datetime.now(timezone.utc).isoformat()
    # Deduplicated, but kept in the order the client sent so the response reads like the table.
    models = list(dict.fromkeys(payload.models))

    def probe(model: str) -> tuple[str, dict]:
        return model, {**probe_model(payload.provider, model), "checked_at": checked_at}

    with ThreadPoolExecutor(max_workers=MODEL_TEST_CONCURRENCY) as pool:
        results = dict(pool.map(probe, models))

    preference = db.get(UserPreference, MODEL_HEALTH_PREFERENCE_KEY)
    stored = dict(preference.value) if preference and isinstance(preference.value, dict) else {}
    provider_health = dict(stored.get(payload.provider) or {})
    provider_health.update(results)
    stored[payload.provider] = provider_health
    if preference:
        preference.value = stored
    else:
        db.add(UserPreference(key=MODEL_HEALTH_PREFERENCE_KEY, value=stored))
    db.commit()
    return ModelTestResponse(provider=payload.provider, results=results)


@app.get("/api/preferences/{key}", response_model=UserPreferenceRead)
def get_preference(key: str, db: Session = Depends(get_db)):
    preference = db.get(UserPreference, key)
    if preference:
        return preference
    return UserPreferenceRead(key=key, value={}, updated_at=None)


@app.patch("/api/preferences/{key}", response_model=UserPreferenceRead)
def update_preference(key: str, payload: UserPreferenceUpdate, db: Session = Depends(get_db)):
    preference = db.get(UserPreference, key)
    if preference:
        preference.value = payload.value
    else:
        preference = UserPreference(key=key, value=payload.value)
        db.add(preference)
    db.commit()
    db.refresh(preference)
    return preference


@app.get("/api/collections", response_model=list[CollectionRead])
def list_collections(db: Session = Depends(get_db)):
    item_count = func.count(StoredFile.id).label("count")
    rows = db.execute(
        select(Collection, item_count)
        .outerjoin(StoredFile)
        .group_by(Collection.id)
        .order_by(Collection.created_at)
    ).all()
    return [CollectionRead.model_validate(collection).model_copy(update={"count": count}) for collection, count in rows]


@app.post("/api/collections", response_model=CollectionRead, status_code=status.HTTP_201_CREATED)
def create_collection(payload: CollectionCreate, db: Session = Depends(get_db)):
    collection = Collection(**payload.model_dump())
    db.add(collection)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="A collection with that title already exists")
    db.refresh(collection)
    return CollectionRead.model_validate(collection).model_copy(update={"count": 0})


@app.delete("/api/collections/{store_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_collection(store_id: int, db: Session = Depends(get_db)):
    store = db.get(Collection, store_id)
    if not store:
        raise HTTPException(status_code=404, detail="Store not found")
    for stored_file in store.files:
        (UPLOAD_DIR / stored_file.stored_name).unlink(missing_ok=True)
        delete_file_embeddings(stored_file.id)
    db.delete(store)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


UPLOAD_LIMIT_PREFERENCE_KEY = "upload_limits"


def _effective_upload_limit_mb(db: Session) -> int:
    """The upload cap actually enforced: the user's saved preference, clamped to
    MAX_UPLOAD_FILE_MB (the deployment's memory-safe ceiling, set via env). Users can
    dial the limit down for faster feedback, but never raise it past what the host
    can safely embed in-process — that requires an operator to raise the env var."""
    preference = db.get(UserPreference, UPLOAD_LIMIT_PREFERENCE_KEY)
    if preference and isinstance(preference.value, dict):
        try:
            requested = int(preference.value.get("max_mb"))
        except (TypeError, ValueError):
            requested = None
        if requested and requested > 0:
            return min(requested, MAX_UPLOAD_FILE_MB)
    return MAX_UPLOAD_FILE_MB


@app.get("/api/system/limits")
def system_limits(db: Session = Depends(get_db)):
    return {
        "upload_max_mb": _effective_upload_limit_mb(db),
        "upload_ceiling_mb": MAX_UPLOAD_FILE_MB,
        "embedding_batch_size": EMBEDDING_BATCH_SIZE,
        "reason": (
            "Uploaded files are parsed and embedded in-process before the upload request "
            "finishes, so a large file can exhaust the backend's memory and crash it. The "
            "ceiling matches what this deployment can safely handle; you can set your own "
            "limit at or below it, but raising the ceiling itself requires more memory on "
            "the host (MAX_UPLOAD_FILE_MB env var)."
        ),
    }


@app.get("/api/files", response_model=list[StoredFileRead])
def list_files(store_id: int | None = None, db: Session = Depends(get_db)):
    statement = select(StoredFile)
    if store_id is not None:
        statement = statement.where(StoredFile.store_id == store_id)
    return db.scalars(statement.order_by(StoredFile.created_at.desc(), StoredFile.id.desc())).all()


@app.post("/api/files", response_model=StoredFileRead, status_code=status.HTTP_201_CREATED)
async def upload_file(store_id: int = Form(...), file: UploadFile = File(...), db: Session = Depends(get_db)):
    if not db.get(Collection, store_id):
        raise HTTPException(status_code=404, detail="Store not found")
    extension = Path(file.filename or "").suffix.lower()
    if extension in IMAGE_EXTENSIONS:
        raise HTTPException(status_code=415, detail=f"Cannot read '{file.filename}' (this model does not support image input).")
    if extension not in SUPPORTED_EXTENSIONS:
        raise HTTPException(status_code=415, detail="Supported files: XLSX, XLSM, CSV, TSV, TXT, MD, PDF, DOCX, JSON, HTML and source code")
    stored_name = f"{uuid4().hex}{extension}"
    stored_path = UPLOAD_DIR / stored_name
    upload_limit_mb = _effective_upload_limit_mb(db)
    max_upload_bytes = upload_limit_mb * 1024 * 1024
    size = 0
    with stored_path.open("wb") as destination:
        while chunk := await file.read(1024 * 1024):
            size += len(chunk)
            if size > max_upload_bytes:
                destination.close()
                stored_path.unlink(missing_ok=True)
                raise HTTPException(status_code=413, detail=f"Files must be {upload_limit_mb} MB or smaller")
            destination.write(chunk)
    try:
        text = await asyncio.to_thread(extract_text_from_path, file.filename or stored_name, stored_path)
    except Exception as exception:
        stored_path.unlink(missing_ok=True)
        raise HTTPException(status_code=422, detail=f"Could not read this file: {exception}")
    stored_file = StoredFile(name=file.filename or stored_name, stored_name=stored_name, content_type=file.content_type or "application/octet-stream", size=size, extracted_text=text, store_id=store_id)
    db.add(stored_file)
    db.commit()
    db.refresh(stored_file)
    await asyncio.to_thread(_index_stored_file, db, stored_file)
    # The extracted text was committed to the DB before indexing even ran (it is set in the
    # StoredFile constructor above), so the raw upload is dead weight now — whether indexing
    # succeeded or failed, nothing will ever read these bytes back off disk. Unconditional.
    stored_path.unlink(missing_ok=True)
    db.refresh(stored_file)
    return stored_file


@app.delete("/api/files/{file_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_file(file_id: int, db: Session = Depends(get_db)):
    stored_file = db.get(StoredFile, file_id)
    if not stored_file:
        raise HTTPException(status_code=404, detail="File not found")
    (UPLOAD_DIR / stored_file.stored_name).unlink(missing_ok=True)
    delete_file_embeddings(stored_file.id)
    db.delete(stored_file)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


def _sources_with_meta(sources, llm_hits=0, web_queries=0, prompt_tokens=0, completion_tokens=0, total_tokens=0):
    """Append a metadata entry to sources so the frontend can extract llm_hits, web_queries, and token usage."""
    source_dicts = [s.model_dump() if isinstance(s, ChatSource) else s for s in sources]
    source_dicts.append({
        "meta": True,
        "llm_hits": llm_hits,
        "web_queries": web_queries,
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "total_tokens": total_tokens,
    })
    return source_dicts


def _attach_usage_metrics(db: Session, conversation_id: int, usage: dict | None, web_queries: int | None = None) -> dict:
    """Overwrite the assistant message's LLM-call/token/search counts with the real tracked values for this request."""
    metrics = {
        "llm_hits": (usage or {}).get("calls", 0),
        "prompt_tokens": (usage or {}).get("prompt_tokens", 0),
        "completion_tokens": (usage or {}).get("completion_tokens", 0),
        "total_tokens": (usage or {}).get("total_tokens", 0),
        "web_queries": web_queries or 0,
    }
    message = db.scalars(
        select(ChatMessage)
        .where(ChatMessage.session_id == conversation_id, ChatMessage.role == "assistant")
        .order_by(ChatMessage.id.desc())
        .limit(1)
    ).first()
    if not message:
        return metrics
    sources = []
    for source in (message.sources or []):
        if isinstance(source, dict) and source.get("meta"):
            source = {**source, **metrics}
        sources.append(source)
    message.sources = sources
    db.add(message)
    db.commit()
    return metrics


def _message_read(message: ChatMessage) -> ChatMessageRead:
    raw_sources = list(message.sources or [])
    meta = next((source for source in raw_sources if isinstance(source, dict) and source.get("meta")), {})
    visible_sources = [source for source in raw_sources if not (isinstance(source, dict) and source.get("meta"))]
    return ChatMessageRead(
        id=message.id,
        role=message.role,
        content=message.content,
        sources=visible_sources,
        model=message.model,
        provider=message.provider,
        llm_hits=int(meta.get("llm_hits") or 0),
        web_queries=int(meta.get("web_queries") or 0),
        prompt_tokens=int(meta.get("prompt_tokens") or 0),
        completion_tokens=int(meta.get("completion_tokens") or 0),
        total_tokens=int(meta.get("total_tokens") or 0),
        created_at=message.created_at,
    )


CHAT_HISTORY_LOAD_LIMIT = 40
CHAT_HISTORY_CHAR_LIMIT = 80_000


def _load_chat_history(db: Session, session_id: int, limit: int = CHAT_HISTORY_LOAD_LIMIT, max_chars: int = CHAT_HISTORY_CHAR_LIMIT) -> list[tuple[str, str]]:
    previous = db.scalars(
        select(ChatMessage)
        .where(ChatMessage.session_id == session_id)
        .order_by(ChatMessage.id.desc())
        .limit(limit)
    ).all()
    history: list[tuple[str, str]] = []
    remaining = max_chars
    for message in reversed(previous):
        content = message.content or ""
        if remaining <= 0:
            break
        if len(content) > remaining:
            content = content[-remaining:]
        history.append((message.role, content))
        remaining -= len(content)
    return history


def _evidence_key(file_id: int, excerpt: str) -> tuple[int, str]:
    return (file_id, (excerpt or "")[:120])


def _retrieve_for_gaps(
    missing: list[str],
    search_file_ids: list[int] | None,
    seen_keys: set[tuple[int, str]],
    notify=lambda stage, detail: None,
) -> list[ChatSource]:
    """Search the vector store again using the verifier's gap list as the query.

    The repair step alone can only reword the draft against evidence it already has, so a gap that
    needs an unretrieved chunk can never be closed. This runs one targeted semantic search per gap
    and returns only chunks that are not already in the evidence set — an empty return is the
    caller's signal that another round would be wasted.
    """
    if not missing or search_file_ids == []:
        return []
    fresh: list[ChatSource] = []
    for gap in missing[:3]:
        gap_text = str(gap).strip()
        if not gap_text:
            continue
        notify("gathering", f"Searching files again for a gap the verifier found: {gap_text[:90]}")
        try:
            hits = semantic_search(gap_text, file_ids=search_file_ids)
        except VectorStoreUnavailable:
            notify("gathering", "Semantic retrieval unavailable for the gap round; keeping existing evidence")
            return fresh
        except Exception as exception:
            diagnostic_event("gap_retrieval.failed", error=str(exception), gap=gap_text[:200])
            continue
        for hit in hits:
            if hit.score < SEMANTIC_MIN_SCORE:
                continue
            key = _evidence_key(hit.file_id, hit.excerpt)
            if key in seen_keys:
                continue
            seen_keys.add(key)
            fresh.append(ChatSource(id=hit.file_id, name=hit.name, store_id=hit.store_id, excerpt=hit.excerpt))
    if fresh:
        notify("gathering", f"Gap round added {len(fresh)} new chunk{'s' if len(fresh) != 1 else ''} of evidence")
    else:
        notify("gathering", "Gap round found no new evidence; answering with what is already retrieved")
    return fresh


def _answer_shape_guidance(reasoning_mode: str) -> str:
    """The scannable answer shape, or an empty string for the modes that must keep their own shape.

    Deep Summary's whole contract is exhaustive section-by-section coverage tracked by a manifest,
    so it does not get the summary-first layout.
    """
    if reasoning_mode == "deep_summary":
        return ""
    return ANSWER_SHAPE_INSTRUCTION


def _handle_platform_action(payload: ChatRequest, db: Session, session: ChatSession, notify, action_call: dict) -> ChatResponse:
    """Run a whitelisted platform action and answer with the outcome.

    The action's summary text becomes the assistant message (so it survives a reload), and
    the structured record rides in `actions_taken` on the response — which the job result
    carries to the frontend, where the theme/model side effects get applied live.
    """
    name = action_call["tool"]
    arguments = action_call["arguments"]
    notify("action", f"Executing platform action: {tool_label(name)}")
    record = execute_action(db, name, arguments, payload.provider, payload.model)
    answer = record["summary"]
    db.add_all([
        ChatMessage(session_id=session.id, role="user", content=payload.question),
        ChatMessage(session_id=session.id, role="assistant", content=answer, sources=_sources_with_meta([], llm_hits=0, web_queries=0), model=payload.model, provider=payload.provider),
    ])
    db.commit()
    notify("complete", "Platform action completed")
    return ChatResponse(
        answer=answer,
        sources=[],
        model=payload.model,
        conversation_id=session.id,
        llm_hits=0,
        web_queries=0,
        actions_taken=[record],
    )


def _process_chat_impl(payload: ChatRequest, db: Session, notify=lambda stage, detail: None, cancelled=lambda: False, on_answer_token=lambda text: None):
    def ensure_not_cancelled():
        if cancelled():
            raise ChatJobCancelled("Chat was deleted; answer pipeline cancelled")

    ensure_not_cancelled()
    session = db.get(ChatSession, payload.conversation_id) if payload.conversation_id else None
    if payload.conversation_id and not session:
        raise HTTPException(status_code=404, detail="Chat not found")
    if not session:
        session = ChatSession(title=payload.question.strip()[:70])
        db.add(session)
        db.flush()
    # Answered deterministically instead of routed through the LLM/web-search pipeline: those
    # paths proved unreliable for this (e.g. web-search auto-trigger pulling in evidence about
    # an unrelated real company also named "Locus"). See brand.py for why.
    creator_name_match = CREATOR_NAME_PATTERN.search(payload.question)
    creator_match = creator_name_match or CREATOR_QUESTION_PATTERN.search(payload.question)
    capability_match = not creator_match and CAPABILITY_QUESTION_PATTERN.search(payload.question)
    if creator_match or capability_match:
        answer = (
            random.choice(CREATOR_BIO_ANSWERS) if creator_name_match
            else random.choice(CREATOR_JOKE_ANSWERS) if creator_match
            else CAPABILITY_ANSWER_INTRO + "\n\n" + random.choice(CAPABILITY_JOKE_CLOSERS)
        )
        ensure_not_cancelled()
        db.add_all([
            ChatMessage(session_id=session.id, role="user", content=payload.question),
            ChatMessage(session_id=session.id, role="assistant", content=answer, sources=_sources_with_meta([], llm_hits=0, web_queries=0), model="Locus", provider=payload.provider),
        ])
        db.commit()
        notify("complete", "Answered directly")
        return ChatResponse(answer=answer, sources=[], model="Locus", conversation_id=session.id, llm_hits=0, web_queries=0)
    if ABOUT_LOCUS_QUESTION_PATTERN.search(payload.question):
        # Broad "ask anything about Locus" coverage. Grounded strictly in ABOUT_LOCUS_SYSTEM_PROMPT
        # (see brand.py) via system_override, which skips web search and the model's own
        # "knowledge" entirely — an unrelated real company is also named Locus.
        notify("drafting", f"Answering from Locus's own knowledge with {payload.model}")
        history = _load_chat_history(db, session.id)
        try:
            answer, used_model = generate_answer(
                payload.question, [], history, payload.model,
                system_override=ABOUT_LOCUS_SYSTEM_PROMPT,
            )
        except LLMProviderError as exception:
            raise HTTPException(status_code=exception.status_code, detail=str(exception))
        except RuntimeError as exception:
            raise HTTPException(status_code=503, detail=str(exception))
        answer = clean_final_answer(answer)
        ensure_not_cancelled()
        db.add_all([
            ChatMessage(session_id=session.id, role="user", content=payload.question),
            ChatMessage(session_id=session.id, role="assistant", content=answer, sources=_sources_with_meta([], llm_hits=1, web_queries=0), model=used_model, provider=payload.provider),
        ])
        db.commit()
        notify("complete", "Answer ready")
        return ChatResponse(answer=answer, sources=[], model=used_model, conversation_id=session.id, llm_hits=1, web_queries=0)
    # Self-aware Ask: a settings/platform request ("switch to dark mode", "make gpt-4o the
    # default model", "run a model health test") is handled as a whitelisted platform action
    # instead of a retrieval question. Classification only ever sees the user's own question —
    # never retrieved evidence or web content — so a poisoned document cannot steer it.
    action_call = classify_platform_action(payload.question, payload.model)
    if action_call:
        return _handle_platform_action(payload, db, session, notify, action_call)
    effective_web_search = _effective_web_search(payload)
    if effective_web_search:
        web_mode = "web research"
        if not payload.web_search and payload.reasoning_mode != "web_research":
            notify("starting", f"Auto-enabled agentic {web_mode} for a search-intent question with {payload.model}")
        else:
            notify("starting", f"Starting agentic {web_mode} with {payload.model}")
        history = _load_chat_history(db, session.id)
        notify("understanding", f"Selected tools: agentic {web_mode}, web, final text")
        try:
            result = run_agentic_pipeline(
                payload.question,
                payload.model,
                notify,
                payload.web_source_limit,
                history=history,
                answer_mode=payload.reasoning_mode,
                force_web=effective_web_search,
                web_research_fn=lambda question, model, progress, source_limit, history, answer_mode: web_research(
                    question,
                    model,
                    progress,
                    source_limit,
                    history=history,
                    answer_mode=answer_mode,
                ),
            )
        except (LLMProviderError) as exception:
            raise HTTPException(status_code=exception.status_code, detail=str(exception))
        except RuntimeError as exception:
            raise HTTPException(status_code=503, detail=str(exception))
        answer = result["answer"]
        sources = []
        for s in result.get("sources", []):
            dummy_id = abs(hash(s["url"])) % (10 ** 9)
            sources.append(ChatSource(id=dummy_id, name=s["title"], store_id=0, excerpt=s["snippet"], url=s["url"], engine=s.get("engine", "")))
        ensure_not_cancelled()
        llm_hits = result.get("llm_hits", 0) or 3
        web_queries = result.get("web_queries", 0) or len(sources)
        db.add_all([
            ChatMessage(session_id=session.id, role="user", content=payload.question),
            ChatMessage(session_id=session.id, role="assistant", content=answer, sources=_sources_with_meta(sources, llm_hits, web_queries), model=result["model"], provider=payload.provider),
        ])
        db.commit()
        notify("complete", "Agentic answer ready")
        return ChatResponse(answer=answer, sources=sources, model=result["model"], conversation_id=session.id, llm_hits=llm_hits, web_queries=web_queries)
    history = _load_chat_history(db, session.id)
    if payload.reasoning_mode == "light" and payload.file_ids == []:
        notify("understanding", "Selected tools: general chat, final text")
        notify("understanding", f"Starting agentic light pipeline with {payload.model}")
        try:
            result = run_agentic_pipeline(
                payload.question,
                payload.model,
                notify,
                payload.web_source_limit,
                history=history,
                answer_mode="light",
                force_web=False,
                web_research_fn=lambda question, model, progress, source_limit, history, answer_mode: web_research(
                    question,
                    model,
                    progress,
                    source_limit,
                    history=history,
                    answer_mode=answer_mode,
                ),
                direct_answer_fn=lambda question, sources, history, model: generate_answer(
                    question,
                    sources,
                    history,
                    model,
                    allow_general_knowledge=True,
                    reasoning_mode="light",
                    guidance="No files are selected. Answer as a normal model chat without pretending to inspect uploaded files.\n\n" + _answer_shape_guidance("light"),
                ),
            )
        except LLMProviderError as exception:
            raise HTTPException(status_code=exception.status_code, detail=str(exception))
        except RuntimeError as exception:
            raise HTTPException(status_code=503, detail=str(exception))
        answer = clean_final_answer(result["answer"])
        sources = []
        for s in result.get("sources", []):
            dummy_id = abs(hash(s.get("url", "") or s.get("title", ""))) % (10 ** 9)
            sources.append(ChatSource(id=dummy_id, name=s.get("title", ""), store_id=0, excerpt=s.get("snippet", ""), url=s.get("url", ""), engine=s.get("engine", "")))
        ensure_not_cancelled()
        llm_hits = result.get("llm_hits", 0) or (2 if not sources else 3)
        web_queries = result.get("web_queries", 0) or len(sources)
        db.add_all([
            ChatMessage(session_id=session.id, role="user", content=payload.question),
            ChatMessage(session_id=session.id, role="assistant", content=answer, sources=_sources_with_meta(sources, llm_hits, web_queries), model=result["model"], provider=payload.provider),
        ])
        db.commit()
        notify("complete", "Agentic light answer ready")
        return ChatResponse(answer=answer, sources=sources, model=result["model"], conversation_id=session.id, llm_hits=llm_hits, web_queries=web_queries)
    mode = MODE_CONFIG[payload.reasoning_mode]
    full_summary_requested = is_full_summary_intent(payload.question) or (payload.reasoning_mode == "deep_summary" and is_summary_intent(payload.question))
    notify("understanding", f"Selected tools: local files, semantic search, final text")
    notify("understanding", f"Calling {payload.model} to understand intent and create an analysis plan")
    try:
        plan = enhance_question(payload.question, history, payload.model)
    except RuntimeError:
        plan = {"enhanced_question": payload.question, "subquestions": [], "answer_format": "Clear answer with supporting details", "supporting_details": [], "visualization": "none", "completeness_criteria": ["Directly answer the question", "Include useful supporting detail"], "requires_full_relevant_files": False, "aggregation_operation": "none", "entity_type": None}
    analysis_tasks = plan.get("subquestions") or [plan.get("enhanced_question") or payload.question]
    task_preview = "; ".join(str(task)[:70] for task in analysis_tasks[:5])
    notify("understanding", f"Analysis plan ready with {len(analysis_tasks)} task{'s' if len(analysis_tasks) != 1 else ''}: {task_preview}")
    retrieval_question = " ".join([payload.question, plan["enhanced_question"], *plan["subquestions"]])
    stop_words = {"what", "when", "where", "which", "that", "this", "with", "from", "about", "have", "does", "could", "would", "should", "tell"}
    terms = [word.strip(".,?!:;()[]{}\"") for word in retrieval_question.lower().split()]
    terms = [word for word in terms if len(word) > 3 and word not in stop_words]
    candidates = []
    file_statement = select(StoredFile)
    if payload.file_ids is not None:
        file_statement = file_statement.where(StoredFile.id.in_(payload.file_ids))
    stored_files = db.scalars(file_statement.order_by(StoredFile.created_at.desc(), StoredFile.id.desc())).all()
    if not stored_files and payload.file_ids == []:
        notify("gathering", "No files selected; continuing with general knowledge only")
    else:
        scope = "selected " if payload.file_ids is not None else ""
        notify("gathering", f"Searching {len(stored_files)} {scope}file{'s' if len(stored_files) != 1 else ''} for supporting evidence")
    semantic_sources = []
    if stored_files:
        try:
            notify("gathering", "Semantic retrieval: embedding question and querying vector store chunks")
            search_file_ids = payload.file_ids if payload.file_ids is not None else [stored_file.id for stored_file in stored_files]
            semantic_hits = [
                hit for hit in semantic_search(retrieval_question, file_ids=search_file_ids)
                if hit.score >= SEMANTIC_MIN_SCORE
            ]
            semantic_hits.sort(
                key=lambda hit: (
                    sum(hit.excerpt.lower().count(term) + hit.name.lower().count(term) for term in terms),
                    hit.score,
                ),
                reverse=True,
            )
            if semantic_hits:
                semantic_sources = [
                    ChatSource(id=hit.file_id, name=hit.name, store_id=hit.store_id, excerpt=hit.excerpt)
                    for hit in semantic_hits
                ]
                notify("gathering", f"Semantic retrieval returned {len(semantic_hits)} chunk{'s' if len(semantic_hits) != 1 else ''}")
            else:
                notify("gathering", "Semantic retrieval returned no chunks; falling back to lexical scan")
        except VectorStoreUnavailable:
            notify("gathering", "Semantic retrieval unavailable; falling back to lexical scan")
        except Exception as exception:
            diagnostic_event("semantic_retrieval.failed", error=str(exception), file_ids=payload.file_ids)
            notify("gathering", "Semantic retrieval failed; falling back to lexical scan")
    for stored_file in stored_files:
        score, excerpt = relevant_excerpt(stored_file.extracted_text, terms, length=2200)
        score += sum(2 for term in terms if term in stored_file.name.lower())
        candidates.append((score, stored_file, excerpt))
    candidates.sort(key=lambda result: result[0], reverse=True)
    minimum_score = 1 if len(terms) <= 1 else 2
    matching = [candidate for candidate in candidates if candidate[0] >= minimum_score]
    if matching and mode.select_strongest_excerpts_only:
        relevance_floor = max(1, matching[0][0] * 0.4)
        matches = [candidate for candidate in matching if candidate[0] >= relevance_floor][:4]
    elif mode.select_strongest_excerpts_only and plan.get("use_uploaded_files"):
        matches = candidates[:4]
    else:
        matches = []
    if not payload.allow_general_knowledge and not semantic_sources and not matches and not mode.inspect_all_chunks:
        answer = "I couldn't find enough information in your uploaded files to answer that. Enable general knowledge or add a relevant file."
        ensure_not_cancelled()
        db.add_all([ChatMessage(session_id=session.id, role="user", content=payload.question), ChatMessage(session_id=session.id, role="assistant", content=answer, sources=_sources_with_meta([], llm_hits=0, web_queries=0), provider=payload.provider)])
        db.commit()
        notify("complete", "Finished in strict file-only mode")
        return ChatResponse(answer=answer, sources=[], conversation_id=session.id, llm_hits=0, web_queries=0)
    lexical_sources = [ChatSource(id=file.id, name=file.name, store_id=file.store_id, excerpt=excerpt) for _, file, excerpt in matches]
    sources_by_id: dict[int, ChatSource] = {}
    for source in [*lexical_sources, *semantic_sources]:
        existing = sources_by_id.get(source.id)
        if not existing:
            sources_by_id[source.id] = source
            continue
        if source.excerpt and source.excerpt not in existing.excerpt:
            combined = f"{existing.excerpt}\n\nAdditional matching excerpt:\n{source.excerpt}"
            existing.excerpt = combined[:2600]
    sources = list(sources_by_id.values())
    repair_context = [(source.name, source.excerpt) for source in sources]
    guidance = (
        f"Preferred format: {plan['answer_format']}. Useful supporting details: "
        f"{', '.join(plan.get('supporting_details', [])) or 'only details that improve the answer'}. "
        f"Visualization: {plan.get('visualization', 'none')} (render charts as compact Markdown bars using █). Completeness requirements: "
        f"{'; '.join(plan['completeness_criteria'])}. "
        "If the user explicitly asks for a table/tabular format or the plan requests a table, use a concise Markdown table with the requested columns. "
        "Do not output internal planning text or labels such as Plan, enhanced_question, or completeness_criteria."
    )
    shape_guidance = _answer_shape_guidance(payload.reasoning_mode)
    if shape_guidance:
        guidance += "\n\n" + shape_guidance
    if full_summary_requested and payload.reasoning_mode == "light" and stored_files:
        guidance += " This is excerpt-based Light mode. Clearly state that the result is based on selected excerpts and is not a full-document summary."
    if payload.reasoning_mode in ("thinking", "deep_summary"):
        guidance += " Think step by step. Break down the reasoning. Consider multiple perspectives and edge cases. If the evidence is incomplete or no files are available, reason from first principles and clearly state any assumptions. Use structured analysis with pros/cons or tradeoffs where relevant."
    try:
        answer_format = str(plan.get("answer_format") or "clear response").replace("_", " ")
        if len(answer_format) > 70:
            answer_format = "best-fit structured response"
        notify("drafting", f"Preparing a {answer_format} with {payload.model}")
        evidence = [(source.name, source.excerpt) for source in sources]
        coverage_manifest = None
        if full_summary_requested and mode.inspect_all_chunks and stored_files:
            notify("gathering", f"Deep Summary: processing all content from {len(stored_files)} selected file{'s' if len(stored_files) != 1 else ''}")
            complete_documents = [(stored_file.name, stored_file.extracted_text) for stored_file in stored_files]
            answer, model, coverage_manifest, evidence = deep_summarize_documents(
                complete_documents,
                payload.model,
                lambda detail: notify("gathering", detail),
            )
            plan = {**plan, "coverage_manifest": coverage_manifest.to_dict()}
            sources = [ChatSource(id=stored_file.id, name=stored_file.name, store_id=stored_file.store_id, excerpt=f"Deep Summary processed the complete file ({coverage_manifest.processedChunks}/{coverage_manifest.totalChunks} chunks).") for stored_file in stored_files]
            repair_context = evidence
        elif mode.inspect_all_chunks and mode.extract_evidence_from_every_chunk and stored_files:
            notify("gathering", f"Inspecting all content from {len(stored_files)} selected file{'s' if len(stored_files) != 1 else ''}")
            complete_documents = [(stored_file.name, stored_file.extracted_text) for stored_file in stored_files]
            evidence = extract_shared_evidence(
                payload.question,
                [plan["enhanced_question"], *plan["subquestions"]],
                complete_documents,
                payload.model,
                lambda detail: notify("gathering", detail),
            )
            mode_name = payload.reasoning_mode.replace("_", " ").title()
            sources = [ChatSource(id=stored_file.id, name=stored_file.name, store_id=stored_file.store_id, excerpt=f"Full file inspected and consolidated in {mode_name} mode.") for stored_file in stored_files]
            repair_context = complete_documents
        if coverage_manifest is None:
            answer, model = answer_planned_question(payload.question, plan, evidence, history, payload.model, payload.allow_general_knowledge, guidance, lambda detail: notify("drafting", detail), on_answer_token)
            if full_summary_requested and payload.reasoning_mode == "light" and stored_files:
                answer = "This is a partial summary based on retrieved excerpts, not a full-document summary.\n\n" + answer
        verify_calls = 0
        repair_calls = 0
        needs_repair = False
        if mode.use_quality_layer:
            # Verify, and when the verifier reports gaps, go back to the vector store for evidence
            # that answers those specific gaps before repairing. Bounded by CHAT_EVIDENCE_ROUNDS and
            # by a no-progress guard, so the worst case is one extra retrieval per round plus the
            # repair that was going to happen anyway.
            gap_search_file_ids = payload.file_ids if payload.file_ids is not None else [stored_file.id for stored_file in stored_files]
            seen_evidence_keys = {_evidence_key(source.id, source.excerpt) for source in sources}
            gap_rounds_used = 0
            while True:
                ensure_not_cancelled()
                notify("verifying", f"Calling {payload.model} to verify grounding, completeness, conflicts, and consistency")
                deterministic_missing = missing_sections(answer, coverage_manifest) if coverage_manifest else []
                if coverage_manifest and not deterministic_missing:
                    verification = {"complete": True, "missing": [], "quality_score": 100}
                    notify("verifying", "Deep Summary coverage manifest is complete; skipping extra verifier call")
                else:
                    verify_calls += 1
                    try:
                        verification = verify_response(payload.question, answer, plan, payload.model, repair_context)
                    except RuntimeError as exception:
                        diagnostic_event(
                            "quality.verifier_failed",
                            provider=payload.provider,
                            model=payload.model,
                            reasoning_mode=payload.reasoning_mode,
                            error=str(exception),
                            fallback="deterministic_coverage" if coverage_manifest else "skip_quality_repair",
                        )
                        notify("verifying", f"Verifier returned malformed output; continuing with {'deterministic coverage' if coverage_manifest else 'the drafted answer'}")
                        verification = {"complete": True, "missing": [], "quality_score": 100}
                if deterministic_missing:
                    coverage_manifest.coverageStatus = "incomplete"
                    plan["coverage_manifest"] = coverage_manifest.to_dict()
                # Deep Summary already appends every consolidated section
                # deterministically. A verifier must not replace that complete answer
                # using a context-limited repair call unless deterministic coverage
                # itself detects a missing section.
                needs_repair = bool(deterministic_missing) if coverage_manifest else (not verification["complete"] or verification["quality_score"] < 80)
                if not needs_repair:
                    break
                missing = verification["missing"] or []
                missing.extend(f'Missing detected section: {section}' for section in deterministic_missing)
                missing = missing or ["Improve grounding, completeness, and consistency"]
                # Deep Summary is excluded: it already inspected every chunk, so a gap round could
                # only return evidence it has seen, and its manifest owns coverage decisions.
                gap_sources = []
                if gap_rounds_used < CHAT_EVIDENCE_ROUNDS and coverage_manifest is None and stored_files:
                    gap_sources = _retrieve_for_gaps(missing, gap_search_file_ids, seen_evidence_keys, notify)
                    if gap_sources:
                        sources.extend(gap_sources)
                        repair_context = [*repair_context, *[(source.name, source.excerpt) for source in gap_sources]]
                        diagnostic_event(
                            "quality.gap_round",
                            round=gap_rounds_used + 1,
                            new_chunks=len(gap_sources),
                            gaps=missing[:3],
                            reasoning_mode=payload.reasoning_mode,
                        )
                round_label = f" (round {gap_rounds_used + 1})" if gap_sources else ""
                notify("repairing", f"Calling {payload.model} to repair the answer{round_label}: {', '.join(missing[:3])}")
                prioritized_context = repair_context
                if deterministic_missing:
                    wanted = [section.lower() for section in deterministic_missing]
                    prioritized_context = sorted(repair_context, key=lambda source: not any(section in source[0].lower() or section in source[1].lower() for section in wanted))
                repair_calls += 1
                answer = repair_response(payload.question, answer, plan, missing, prioritized_context, payload.model, payload.allow_general_knowledge and not repair_context, shape_guidance)
                if coverage_manifest and not missing_sections(answer, coverage_manifest):
                    coverage_manifest.coverageStatus = "complete"
                on_answer_token(answer)
                # Without fresh evidence a re-verify would grade the same facts again, so stop here.
                if not gap_sources:
                    break
                gap_rounds_used += 1
        answer = clean_final_answer(answer)
    except LLMProviderError as exception:
        raise HTTPException(status_code=exception.status_code, detail=str(exception))
    except RuntimeError as exception:
        raise HTTPException(status_code=503, detail=str(exception))
    # Planner + composer, plus however many verify/repair calls the gap loop actually made.
    llm_hits = 2 + verify_calls + repair_calls
    web_queries = 0
    ensure_not_cancelled()
    db.add_all([ChatMessage(session_id=session.id, role="user", content=payload.question), ChatMessage(session_id=session.id, role="assistant", content=answer, sources=_sources_with_meta(sources, llm_hits, web_queries), model=model, provider=payload.provider)])
    db.commit()
    notify("complete", "Answer ready")
    return ChatResponse(answer=answer, sources=sources, model=model, conversation_id=session.id, llm_hits=llm_hits, web_queries=web_queries)


def _process_chat(payload: ChatRequest, db: Session, notify=lambda stage, detail: None, cancelled=lambda: False, on_answer_token=lambda text: None):
    with llm_provider_context(payload.provider):
        return _process_chat_impl(payload, db, notify, cancelled, on_answer_token)


def _call_process_chat(payload: ChatRequest, db: Session, notify, cancelled, on_answer_token=lambda text: None):
    param_count = len(signature(_process_chat).parameters)
    if param_count < 4:
        return _process_chat(payload, db, notify)
    if param_count < 5:
        return _process_chat(payload, db, notify, cancelled)
    return _process_chat(payload, db, notify, cancelled, on_answer_token)


def _validate_chat_request(payload: ChatRequest):
    """Fill in the provider/model the request left out from the default saved in Settings.

    Every chat entry point calls this first, so the app can stop sending a provider and model
    with each question: there is one default, Settings owns it, and a request that names
    neither picks up whatever Settings holds at the moment it runs rather than whatever the
    page happened to load when it mounted. Mutated in place because the payload is threaded
    through the pipeline, the job row and the stored message from here on.
    """
    if payload.provider and payload.model:
        return None
    provider, model = preferred_ai()
    # A caller that pinned a provider but no model gets that provider's own default rather
    # than the saved model id, which only means anything to the provider it was chosen for.
    if payload.provider and payload.provider != provider:
        model = configured_model()
    payload.provider = payload.provider or provider
    payload.model = payload.model or model
    return None


AUTO_WEB_SEARCH_PATTERNS = [
    r"\b(search|browse|look\s*up|google|find\s+(?:me\s+)?(?:latest|current|recent|news|online|web|internet))\b",
    r"\b(latest|current|recent|today|yesterday|this\s+week|this\s+month|news|breaking|updates?)\b",
    r"\b(youtube|video|videos)\b",
    r"\b(source|sources|citation|citations|link|links|url|website|webpage)\b",
    r"\b(under|below|less\s+than|within|budget|upto|up\s+to)\s*(?:rs\.?|inr|₹)?\s*\d+(?:\.\d+)?\s*(?:k|thousand)?\b",
    r"\b(?:rs\.?|inr|₹)\s*\d+(?:\.\d+)?\s*(?:k|thousand)?\b",
    r"\b(comp(?:are|aire?)|vs\.?|versus|difference\s+between|contras?t)\b",
    r"\b(better|worse|best|worst|which\s+(?:one|is|should|do)|recommend(?:ed|ation)?|suggestion|pros?\s+and\s+cons?)\b",
]

MIXED_LANGUAGE_WEB_SEARCH_KEYWORDS = [
    # Weather
    r"\b(barish|barsaat|mausam|tapman|garmi|thand|sardi|toofan|aandhi|kohra|dhund)\b",
    # Sports
    r"\b(cricket|football|match|score|team|player|khel|maukka)\b",
    # Stock/Finance
    r"\b(stock|share|nse|bse|sensex|nifty|bazaar|bhav|kimat|dam|nivesh|munafa)\b",
    # Currency
    r"\b(dollar|euro|pound|rupaye|exchange|currency|kitna|barabar)\b",
    # Flight
    r"\b(flight|hawai|jadah|pnr|boarding)\b",
    # Food
    r"\b(recipe|pakwan|khaana|khana|restaurant|food)\b",
    # Health
    r"\b(bimari|dawa|ilaj|doctor|hospital|bukhar|khasi|dard)\b",
    # Entertainment
    r"\b(movie|film|cinema|gaana|concert|serial)\b",
    # Current info
    r"\b(aaj|kal|abhi|taza|samachar|khabar|score|natija|bhav|kimat|dam)\b",
    # Generic
    r"\b(hoga|hogi|hoga\s+kya|batao|dikhao|btao|konsa|kaunsa|kaisa|kaise)\b",
    r"\b(sasta|mehnga|kharid|accha|badhiya|sabse|best|top|price)\b",
]


def should_auto_web_search(question: str, reasoning_mode: str = "light") -> bool:
    if reasoning_mode == "deep_summary":
        return False
    normalized = " ".join(question.lower().split())
    if not normalized:
        return False
    # Check regex patterns
    if any(re.search(pattern, normalized) for pattern in AUTO_WEB_SEARCH_PATTERNS):
        return True
    # Check keyword-based intent classifier for domain-specific intents
    try:
        intent = _fallback_classify(normalized)
        if intent.intent in ("weather", "sports", "stock", "currency", "flight", "food", "health", "entertainment", "product", "current", "news"):
            return True
    except Exception:
        pass
    return any(re.search(pattern, normalized) for pattern in MIXED_LANGUAGE_WEB_SEARCH_KEYWORDS)


def _effective_web_search(payload: ChatRequest) -> bool:
    if payload.web_search or payload.reasoning_mode == "web_research":
        return True
    # High/Max effort (thinking/deep_summary) with no files selected means there is nothing to
    # inspect locally, so "spend more effort" has to mean going and finding real sources instead
    # of answering from the model's own memory — otherwise raising effort with no file context
    # does nothing a user can see. By the time a question reaches here, the greeting/creator/
    # about-Locus short-circuits earlier in _process_chat_impl have already caught anything
    # trivial, so any question still in flight is worth grounding in evidence. This does not
    # apply once files ARE selected: there, thinking/deep_summary's job is to inspect those
    # files, not detour to the web, so the keyword-gated check below still applies.
    if payload.reasoning_mode in ("thinking", "deep_summary") and payload.file_ids == []:
        return True
    return should_auto_web_search(payload.question, payload.reasoning_mode)


@app.post("/api/chat/stream")
def chat_stream(payload: ChatRequest):
    _validate_chat_request(payload)

    def event_stream():
        events: Queue = Queue()

        def run():
            stream_cancel_event = None
            stream_chat_id = None
            with SessionLocal() as db:
                try:
                    session = db.get(ChatSession, payload.conversation_id) if payload.conversation_id else None
                    if payload.conversation_id and not session:
                        raise HTTPException(status_code=404, detail="Chat not found")
                    if not session:
                        session = ChatSession(title=payload.question.strip()[:70])
                        db.add(session)
                        db.flush()
                        db.commit()
                    stream_chat_id = session.id
                    stream_cancel_event = _chat_stream_cancel_event(stream_chat_id)
                    stream_payload = payload.model_copy(update={"conversation_id": stream_chat_id})
                    result = _call_process_chat(stream_payload, db, lambda stage, detail: events.put({"type": "stage", "stage": stage, "detail": detail}), stream_cancel_event.is_set)
                    events.put({"type": "result", "data": result.model_dump(mode="json")})
                except HTTPException as exception:
                    events.put({"type": "error", "detail": exception.detail})
                except Exception as exception:
                    events.put({"type": "error", "detail": str(exception)})
                finally:
                    if stream_chat_id is not None and stream_cancel_event is not None:
                        _forget_chat_stream_cancel_event(stream_chat_id, stream_cancel_event)
                    events.put(None)

        def run_guarded():
            # run() queues its own sentinel in a finally, but only once it is inside its
            # try block: anything that fails before that (opening the session, say) would
            # otherwise leave the consumer below blocked on an empty queue forever.
            try:
                run()
            except BaseException as exception:  # noqa: BLE001 - surfaced to the client
                events.put({"type": "error", "detail": str(exception)})
            finally:
                events.put(None)

        Thread(target=run_guarded, daemon=True).start()
        while True:
            event = events.get()
            if event is None:
                break
            yield json.dumps(event) + "\n"

    return StreamingResponse(event_stream(), media_type="application/x-ndjson")


@app.post("/api/chat/direct-stream")
def chat_direct_stream(payload: ChatRequest):
    _validate_chat_request(payload)
    if _effective_web_search(payload) or payload.reasoning_mode != "light" or payload.file_ids != []:
        raise HTTPException(status_code=422, detail="Direct streaming is only available for Light mode with no selected files and Web Search off")

    def event_stream():
        # The work runs on its own thread and reports through a queue, exactly like
        # /api/chat/stream. Starlette pumps a sync generator by calling next() in the
        # threadpool, and each of those calls gets a fresh copy of the context — so a
        # ContextVar-backed helper such as token_usage_tracker() cannot be entered in
        # one next() and exited in a later one ("was created in a different Context").
        # Keeping the whole pipeline inside one thread keeps the context intact.
        events: Queue = Queue()

        def run():
            stream_cancel_event = None
            stream_chat_id = None
            with SessionLocal() as db:
                try:
                    session = db.get(ChatSession, payload.conversation_id) if payload.conversation_id else None
                    if payload.conversation_id and not session:
                        raise HTTPException(status_code=404, detail="Chat not found")
                    if not session:
                        session = ChatSession(title=payload.question.strip()[:70])
                        db.add(session)
                        db.flush()
                    stream_chat_id = session.id
                    stream_cancel_event = _chat_stream_cancel_event(stream_chat_id)
                    previous = db.scalars(select(ChatMessage).where(ChatMessage.session_id == session.id).order_by(ChatMessage.id.desc()).limit(10)).all()
                    history = [(message.role, message.content) for message in reversed(previous)]
                    db.add(ChatMessage(session_id=session.id, role="user", content=payload.question))
                    db.commit()
                    events.put({"type": "start", "conversation_id": session.id, "model": payload.model, "provider": payload.provider})
                    answer_parts = []
                    with token_usage_tracker() as usage:
                        token_stream, used_model = stream_answer(
                            payload.question,
                            [],
                            history,
                            payload.model,
                            payload.allow_general_knowledge,
                            payload.reasoning_mode,
                            guidance=("No files are selected. Answer as a normal model chat without pretending to inspect uploaded files.\n\n" + _answer_shape_guidance(payload.reasoning_mode)).strip(),
                            provider=payload.provider,
                        )
                        for token in token_stream:
                            if stream_cancel_event and stream_cancel_event.is_set():
                                raise ChatJobCancelled("Chat was deleted; direct stream cancelled")
                            answer_parts.append(token)
                            events.put({"type": "token", "text": token})
                        answer = clean_final_answer("".join(answer_parts))
                        if not answer:
                            raise RuntimeError("The model returned an empty answer.")
                        diagnostic = refusal_diagnostic(answer, payload.provider, used_model)
                        if diagnostic:
                            events.put({"type": "diagnostic", "level": "warning", "detail": diagnostic})
                    llm_hits = usage["calls"]
                    web_queries = 0
                    db.add(ChatMessage(session_id=session.id, role="assistant", content=answer, sources=_sources_with_meta([], llm_hits, web_queries, usage["prompt_tokens"], usage["completion_tokens"], usage["total_tokens"]), model=used_model, provider=payload.provider))
                    session.updated_at = datetime.now(timezone.utc)
                    db.commit()
                    result = ChatResponse(answer=answer, sources=[], model=used_model, conversation_id=session.id, llm_hits=llm_hits, web_queries=web_queries, prompt_tokens=usage["prompt_tokens"], completion_tokens=usage["completion_tokens"], total_tokens=usage["total_tokens"])
                    events.put({"type": "result", "data": result.model_dump(mode="json")})
                except ChatJobCancelled:
                    pass
                except HTTPException as exception:
                    events.put({"type": "error", "detail": exception.detail})
                except LLMProviderError as exception:
                    events.put({"type": "error", "detail": str(exception)})
                except Exception as exception:
                    events.put({"type": "error", "detail": str(exception)})
                finally:
                    if stream_chat_id is not None and stream_cancel_event is not None:
                        _forget_chat_stream_cancel_event(stream_chat_id, stream_cancel_event)
                    events.put(None)

        def run_guarded():
            # run() queues its own sentinel in a finally, but only once it is inside its
            # try block: anything that fails before that (opening the session, say) would
            # otherwise leave the consumer below blocked on an empty queue forever.
            try:
                run()
            except BaseException as exception:  # noqa: BLE001 - surfaced to the client
                events.put({"type": "error", "detail": str(exception)})
            finally:
                events.put(None)

        Thread(target=run_guarded, daemon=True).start()
        while True:
            event = events.get()
            if event is None:
                break
            yield json.dumps(event) + "\n"

    return StreamingResponse(event_stream(), media_type="application/x-ndjson")


@app.post("/api/chat/suggestions", response_model=SuggestionsResponse)
def chat_suggestions(payload: SuggestionsRequest):
    default_provider, default_model = preferred_ai()
    provider = payload.provider or default_provider
    model = payload.model or (default_model if provider == default_provider else configured_model())
    with llm_provider_context(provider):
        try:
            suggestions = generate_followup_questions(payload.question, payload.answer, model)
        except Exception as exception:  # noqa: BLE001 - follow-up chips are a nicety, never an error
            # Anything raised here used to surface as a 500, and the frontend's catch turned that
            # into "no suggestions" with no way to tell a broken call from a model with nothing
            # to suggest. Degrade quietly, but leave a diagnostic behind.
            diagnostic_event("chat.suggestions_failed", provider=provider, model=model, error=str(exception)[:500])
            suggestions = []
    return SuggestionsResponse(suggestions=suggestions)


def _pipeline_event_metadata(stage: str, detail: str) -> dict:
    lowered = detail.lower()
    metadata = {
        "type": "status",
        "direction": "internal",
        "method": "pipeline.tick()",
        "payload_preview": detail,
        "response_preview": "",
        "tags": [],
    }
    stage_methods = {
        "starting": "run_chat_job()",
        "understanding": "enhance_question()",
        "action": "execute_assistant_tool()",
        "gathering": "extract_evidence()",
        "drafting": "answer_planned_question()",
        "verifying": "verify_response()",
        "repairing": "repair_response()",
        "complete": "persist_chat_messages()",
        "failed": "raise_pipeline_error()",
    }
    metadata["method"] = stage_methods.get(stage, metadata["method"])
    if stage == "action":
        metadata.update(type="tool", direction="outbound", method="execute_assistant_tool()", payload_preview=detail)
    if "directly; no files selected" in lowered:
        metadata.update(type="llm_call", direction="outbound", method="generate_answer()", payload_preview=detail)
    if "calling " in lowered:
        metadata.update(type="llm_call", direction="outbound", payload_preview=detail)
    elif "analysis plan ready" in lowered:
        metadata.update(type="llm_result", direction="inbound", response_preview=detail)
        match = re.search(r"with (\d+) tasks?", detail)
        if match:
            metadata["tags"].append(f"{match.group(1)} tasks")
    elif lowered.startswith("searching"):
        metadata.update(type="retrieval", direction="read", method="relevant_excerpt()", payload_preview=detail)
        match = re.search(r"searching (\d+)", lowered)
        if match:
            metadata["tags"].append(f"{match.group(1)} files")
    elif "summarizing" in lowered:
        metadata.update(type="chunk", direction="outbound", method="deep_summarize_documents()", payload_preview=detail)
        match = re.search(r"\((\d+) of (\d+)\)", detail)
        if match:
            metadata["tags"].extend([f"chunk {match.group(1)}/{match.group(2)}", "map"])
    elif "consolidating section" in lowered:
        metadata.update(type="reduce", direction="inbound", method="_reduce_sources()", response_preview=detail)
        metadata["tags"].append("reduce")
    elif "synthesizing" in lowered:
        metadata.update(type="synthesis", direction="outbound", method="_reduce_sources()", payload_preview=detail)
        metadata["tags"].append("final synthesis")
    elif lowered.startswith("  → "):
        metadata.update(type="web", direction="inbound", method="web_search()", response_preview=detail)
        url_match = re.search(r"https?://[^\s]+", detail)
        if url_match:
            metadata["tags"].append(url_match.group(0))
            title_part = detail[4:detail.index("http")].strip()
            if title_part:
                metadata["tags"].append(title_part)
    elif "searching web" in lowered or "web search" in lowered or "running" in lowered and "follow-up" in lowered:
        metadata.update(type="web_search", direction="outbound", method="web_search()", payload_preview=detail)
        metadata["tags"].append("web")
    elif lowered.startswith("preparing"):
        metadata.update(type="llm_call", direction="outbound", method="answer_planned_question()", payload_preview=detail)
    elif "still" in lowered or "active:" in lowered:
        if "directly; no files selected" in lowered:
            metadata["method"] = "generate_answer()"
        metadata.update(type="heartbeat", direction="internal", payload_preview=detail)
    elif "verify" in lowered or "quality" in lowered:
        metadata.update(type="quality", direction="outbound", method="verify_response()", payload_preview=detail)
    elif "repair" in lowered:
        metadata.update(type="quality", direction="outbound", method="repair_response()", payload_preview=detail)
    elif "answer ready" in lowered or stage == "complete":
        metadata.update(type="complete", direction="inbound", method="clean_final_answer()", response_preview=detail)
    elif stage == "failed":
        metadata.update(type="error", direction="inbound", response_preview=detail)
    if not metadata["response_preview"] and metadata["direction"] == "inbound":
        metadata["response_preview"] = detail
    return metadata


def _update_chat_job(job_id: str, **changes):
    event_meta = changes.pop("event_meta", None) or {}
    diagnostic_event("job.state", job_id=job_id, **{key: changes[key] for key in ("status", "stage", "detail", "error") if key in changes})
    with SessionLocal() as db:
        job = db.get(ChatJob, job_id)
        if not job:
            return
        if "stage" in changes:
            events = list(job.events or [])
            detail = changes.get("detail", job.detail)
            event = {
                "stage": changes["stage"],
                "detail": detail,
                "at": datetime.now(timezone.utc).isoformat(),
                **_pipeline_event_metadata(changes["stage"], detail),
                **event_meta,
            }
            events.append(event)
            changes["events"] = events[-120:]
        for key, value in changes.items():
            setattr(job, key, value)
        db.commit()


def _ensure_stopped_question_message(db: Session, job: ChatJob) -> None:
    existing = db.scalars(
        select(ChatMessage)
        .where(ChatMessage.session_id == job.conversation_id, ChatMessage.role == "user", ChatMessage.content == job.question)
        .order_by(ChatMessage.id.desc())
        .limit(1)
    ).first()
    if existing:
        return
    db.add(ChatMessage(session_id=job.conversation_id, role="user", content=job.question))
    session = db.get(ChatSession, job.conversation_id)
    if session:
        session.updated_at = datetime.now(timezone.utc)


def _run_chat_job_impl(job_id: str, payload: ChatRequest):
    cancellation = _chat_job_cancel_event(job_id)

    def ensure_not_cancelled():
        if cancellation.is_set():
            raise ChatJobCancelled(_chat_job_cancel_reason(job_id))

    _update_chat_job(job_id, status="running", stage="starting", detail="Answer pipeline started", partial_answer=None)
    stopped = Event()
    progress = {"stage": "starting", "detail": "Answer pipeline started", "ticks": 0}
    token_usage: dict = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0, "calls": 0}
    search_usage: dict = {"queries": 0}
    last_partial_write = {"at": 0.0}

    def notify(stage: str, detail: str):
        ensure_not_cancelled()
        progress.update(stage=stage, detail=detail, ticks=0)
        _update_chat_job(
            job_id,
            stage=stage,
            detail=detail,
            llm_hits=token_usage["calls"],
            web_queries=search_usage["queries"],
            prompt_tokens=token_usage["prompt_tokens"],
            completion_tokens=token_usage["completion_tokens"],
            total_tokens=token_usage["total_tokens"],
        )

    def on_answer_token(text: str):
        # Best-effort live preview: throttled so a fast stream doesn't turn into a DB write
        # per token, and wrapped so a write failure never takes down the actual answer.
        now = time.monotonic()
        if now - last_partial_write["at"] < 0.35:
            return
        last_partial_write["at"] = now
        try:
            _update_chat_job(job_id, partial_answer=text)
        except Exception as exception:
            diagnostic_event("job.partial_answer_write_failed", job_id=job_id, error=str(exception))

    def heartbeat():
        while not stopped.wait(10):
            if cancellation.is_set():
                stopped.set()
                return
            progress["ticks"] += 1
            stage = progress["stage"]
            if stage == "drafting":
                detail = f"{payload.model} is still generating this step: {progress['detail']}"
            elif stage == "gathering":
                detail = f"Evidence processing is active: {progress['detail']}"
            elif stage == "understanding":
                detail = f"{payload.model} is still analyzing the request and answer structure"
            elif stage in {"verifying", "repairing"}:
                detail = f"Quality pass is still active: {progress['detail']}"
            else:
                detail = f"Pipeline is active: {progress['detail']}"
            _update_chat_job(
                job_id,
                stage=stage,
                detail=detail,
                llm_hits=token_usage["calls"],
                web_queries=search_usage["queries"],
                prompt_tokens=token_usage["prompt_tokens"],
                completion_tokens=token_usage["completion_tokens"],
                total_tokens=token_usage["total_tokens"],
            )

    Thread(target=heartbeat, daemon=True).start()
    completed_calls: dict = {}
    consecutive_failures = 0
    total_attempts = 0
    # Built lazily on the first retryable failure, then frozen for the whole job: the
    # fallback is decided once per ChatJob so later stages (and later retry rounds) all run
    # against the same replacement instead of renegotiating a different model each time.
    fallback_plan: dict | None = None
    while True:
        total_attempts += 1
        completed_before_attempt = len(completed_calls)
        diagnostic_event("pipeline.attempt_started", attempt=total_attempts, cached_llm_calls=completed_before_attempt)
        try:
            ensure_not_cancelled()
            with llm_call_cache(completed_calls), token_usage_tracker(token_usage), web_search_tracker(search_usage):
                with SessionLocal() as db:
                    result = _call_process_chat(payload, db, notify, cancellation.is_set, on_answer_token)
                    metrics = _attach_usage_metrics(db, result.conversation_id, token_usage, search_usage["queries"])
                    result.llm_hits = metrics["llm_hits"]
                    result.web_queries = metrics["web_queries"]
                    result.prompt_tokens = metrics["prompt_tokens"]
                    result.completion_tokens = metrics["completion_tokens"]
                    result.total_tokens = metrics["total_tokens"]
            ensure_not_cancelled()
            stopped.set()
            _update_chat_job(
                job_id,
                status="completed",
                stage="complete",
                detail="Answer ready",
                result=result.model_dump(mode="json"),
                llm_hits=result.llm_hits,
                web_queries=result.web_queries,
                prompt_tokens=result.prompt_tokens,
                completion_tokens=result.completion_tokens,
                total_tokens=result.total_tokens,
                error=None,
            )
            diagnostic_event("job.succeeded", attempts=total_attempts, completed_llm_calls=len(completed_calls))
            # The job recovered through an auto-selected fallback model: make the switch
            # permanent so the next request does not fail the same way. Only when the failed
            # model was the saved default — a model pinned for this one request still falls
            # back for the request, but the user's default is not rewritten behind their back.
            if fallback_plan and fallback_plan["switched"] and fallback_plan["was_default"]:
                with SessionLocal() as db:
                    record_switch(
                        db,
                        fallback_plan["original_provider"],
                        fallback_plan["original_model"],
                        payload.provider,
                        payload.model,
                        fallback_plan["original_error"],
                        job_id=job_id,
                    )
                diagnostic_event("job.auto_selected_model", job_id=job_id, previous_model=fallback_plan["original_model"], fallback_provider=payload.provider, fallback_model=payload.model)
            delete_job_log(job_id)
            return
        except ChatJobCancelled as exception:
            stopped.set()
            _update_chat_job(job_id, status="cancelled", stage="cancelled", detail=str(exception), error=str(exception))
            diagnostic_event("job.cancelled", attempts=total_attempts, cached_llm_calls=len(completed_calls))
            delete_job_log(job_id)
            return
        except HTTPException as exception:
            detail = str(exception.detail)
            failure_trace = traceback.format_exc()
            exception_type = type(exception).__name__
            status_code = exception.status_code
            # Provider clients own rate-limit retries so the full pipeline is not replayed after a 429.
            retryable = exception.status_code in {500, 502, 503, 504}
        except Exception as exception:
            detail = str(exception)
            failure_trace = traceback.format_exc()
            exception_type = type(exception).__name__
            status_code = None
            retryable = True

        made_progress = len(completed_calls) > completed_before_attempt
        consecutive_failures = 1 if made_progress else consecutive_failures + 1
        diagnostic_event("pipeline.attempt_failed", attempt=total_attempts, exception_type=exception_type, status_code=status_code, error=detail, traceback=failure_trace, retryable=retryable, made_progress=made_progress, cached_llm_calls=len(completed_calls), consecutive_failures=consecutive_failures)
        # Auto-select: a retryable failure of the current model earns the job one run with
        # the healthiest alternative before the old back-off-retry logic takes over. The
        # candidate list is negotiated once (see the fallback_plan comment above) and capped
        # at FALLBACK_CANDIDATE_LIMIT, so worst case is a handful of retries, not an endless
        # tour of the catalogue. Once every alternative has also failed, the original error
        # surfaces instead of retrying a dead model.
        if retryable and fallback_plan is None:
            with SessionLocal() as db:
                try:
                    default_provider, default_model = preferred_ai(db)
                    candidates = choose_fallback(db, payload.provider, payload.model)
                except Exception:  # noqa: BLE001 - a broken fallback plan must not hide the real error
                    default_provider, default_model = payload.provider, payload.model
                    candidates = []
            fallback_plan = {
                "candidates": candidates,
                "index": 0,
                "switched": False,
                "original_error": detail,
                "original_provider": payload.provider,
                "original_model": payload.model,
                "was_default": payload.provider == default_provider and payload.model == default_model,
            }
        if fallback_plan and fallback_plan["index"] < len(fallback_plan["candidates"]):
            candidate_provider, candidate_model = fallback_plan["candidates"][fallback_plan["index"]]
            fallback_plan["index"] += 1
            fallback_plan["switched"] = True
            payload.provider, payload.model = candidate_provider, candidate_model
            consecutive_failures = 0
            progress.update(stage="starting", detail=f"Auto-switching model to {candidate_model} after: {fallback_plan['original_error']}", ticks=0)
            _update_chat_job(
                job_id,
                status="running",
                stage="starting",
                detail=f"{fallback_plan['original_model']} failed. Auto-switching to {candidate_model} and retrying.",
                error=None,
                partial_answer=None,
            )
            diagnostic_event("pipeline.fallback_attempt", job_id=job_id, attempt=total_attempts, previous_provider=fallback_plan["original_provider"], previous_model=fallback_plan["original_model"], fallback_provider=candidate_provider, fallback_model=candidate_model, reason=fallback_plan["original_error"])
            continue
        if fallback_plan and fallback_plan["switched"] and fallback_plan["index"] >= len(fallback_plan["candidates"]):
            # Every alternative failed too; surface the failure that started all this rather
            # than the last candidate's, and stop — there is nothing left to try.
            stopped.set()
            suffix = f" after {total_attempts} attempts" if total_attempts > 1 else ""
            _update_chat_job(job_id, status="failed", stage="failed", detail=f"{fallback_plan['original_error']}{suffix}", error=f"{fallback_plan['original_error']}{suffix}")
            diagnostic_event("job.failed", attempts=total_attempts, exception_type=exception_type, status_code=status_code, error=f"{fallback_plan['original_error']}{suffix}", cached_llm_calls=len(completed_calls), log_retained=True, fallback_candidates_exhausted=True)
            return
        if retryable and consecutive_failures <= CHAT_JOB_MAX_RETRIES:
            delay = CHAT_JOB_RETRY_DELAY_SECONDS * (2 ** (consecutive_failures - 1))
            preserved = len(completed_calls)
            resume_detail = f"; preserving {preserved} completed model step{'s' if preserved != 1 else ''}" if preserved else ""
            reset_detail = "; retry count reset after successful progress" if made_progress and total_attempts > 1 else ""
            progress.update(stage="starting", detail=f"Attempt {total_attempts} failed; resuming from checkpoint", ticks=0)
            _update_chat_job(
                job_id,
                status="running",
                stage="starting",
                detail=f"Attempt {total_attempts} failed: {detail}. Retrying ({consecutive_failures}/{CHAT_JOB_MAX_RETRIES}) in {delay:g}s{resume_detail}{reset_detail}",
                error=None,
                partial_answer=None,
            )
            diagnostic_event("pipeline.retry_scheduled", attempt=total_attempts, next_attempt=total_attempts + 1, delay_seconds=delay, cached_llm_calls=preserved, retry_count=consecutive_failures, max_retries=CHAT_JOB_MAX_RETRIES)
            if cancellation.wait(delay):
                stopped.set()
                reason = _chat_job_cancel_reason(job_id)
                _update_chat_job(job_id, status="cancelled", stage="cancelled", detail=reason, error=reason)
                diagnostic_event("job.cancelled", attempts=total_attempts, cached_llm_calls=len(completed_calls))
                delete_job_log(job_id)
                return
            continue

        stopped.set()
        suffix = f" after {total_attempts} attempts" if total_attempts > 1 else ""
        _update_chat_job(job_id, status="failed", stage="failed", detail=f"{detail}{suffix}", error=f"{detail}{suffix}")
        diagnostic_event("job.failed", attempts=total_attempts, exception_type=exception_type, status_code=status_code, error=f"{detail}{suffix}", cached_llm_calls=len(completed_calls), log_retained=True)
        return


def _run_chat_job(job_id: str, payload: ChatRequest):
    effective_web_search = _effective_web_search(payload)
    initialize_job_log(
        job_id,
        provider=payload.provider,
        model=payload.model,
        reasoning_mode=payload.reasoning_mode,
        web_search=effective_web_search,
        allow_general_knowledge=payload.allow_general_knowledge,
        conversation_id=payload.conversation_id,
        file_ids=payload.file_ids,
        selected_file_count=None if payload.file_ids is None else len(payload.file_ids),
        question_chars=len(payload.question),
    )
    with diagnostic_job(job_id):
        try:
            return _run_chat_job_impl(job_id, payload)
        except ChatJobCancelled as exception:
            diagnostic_event("job.cancelled", error=str(exception), log_retained=False)
            return
        except BaseException as exception:
            diagnostic_event("job.crashed", exception_type=type(exception).__name__, error=str(exception), traceback=traceback.format_exc(), log_retained=True)
            raise
        finally:
            _forget_chat_job_cancel_event(job_id)


@app.post("/api/chat/jobs", response_model=ChatJobRead, status_code=status.HTTP_202_ACCEPTED)
def create_chat_job(payload: ChatRequest, db: Session = Depends(get_db)):
    _validate_chat_request(payload)
    effective_web_search = _effective_web_search(payload)
    session = db.get(ChatSession, payload.conversation_id) if payload.conversation_id else None
    if payload.conversation_id and not session:
        raise HTTPException(status_code=404, detail="Chat not found")
    if not session:
        session = ChatSession(title=payload.question.strip()[:70])
        db.add(session)
        db.flush()
    job = ChatJob(
        id=uuid4().hex,
        question=payload.question,
        conversation_id=session.id,
        model=payload.model,
        provider=payload.provider,
        reasoning_mode=payload.reasoning_mode,
        web_search=effective_web_search,
        file_ids=payload.file_ids,
        events=[{
            "stage": "starting",
            "detail": "Request received and queued",
            "at": datetime.now(timezone.utc).isoformat(),
            "type": "request",
            "direction": "inbound",
            "method": "POST /api/chat/jobs",
            "payload_preview": payload.question,
            "response_preview": "202 Accepted; background worker scheduled",
            "tags": [
                payload.provider,
                payload.reasoning_mode,
                "web" if effective_web_search else "no-web",
                f"{0 if payload.file_ids == [] else 'all' if payload.file_ids is None else len(payload.file_ids)} files",
            ],
        }],
    )
    db.add(job)
    db.commit()
    db.refresh(job)
    worker_payload = payload.model_copy(update={"conversation_id": session.id, "web_search": effective_web_search})
    _chat_job_cancel_event(job.id)
    Thread(target=_run_chat_job, args=(job.id, worker_payload), daemon=True).start()
    return job


def _fail_stale_chat_jobs(db: Session) -> None:
    """Lazily heal jobs whose background thread died without the process restarting.

    Runs on every jobs poll (every 1.5s from the frontend) rather than on a schedule, so a
    stuck job self-heals within one poll cycle without needing a background scheduler. Frontend
    conversation-level "is this chat busy" checks match on conversation_id and status together
    (see the chat rail and ExplorePage's activeJob), so a job stuck at "running" forever pins
    that conversation's whole UI as busy indefinitely even after a later question in the same
    conversation completes normally - this is the cheap fix on the other side of that.
    """
    # ChatJob.updated_at is a plain DateTime column (no timezone), and func.now() fills it with
    # a naive UTC value on both SQLite and Postgres here — matching that convention rather than
    # comparing against an aware datetime is what keeps this query dialect-portable.
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    cutoff = now - timedelta(seconds=CHAT_JOB_STALE_TIMEOUT_SECONDS)
    stale_jobs = db.scalars(
        select(ChatJob).where(ChatJob.status.in_(["queued", "running"]), ChatJob.updated_at < cutoff)
    ).all()
    if not stale_jobs:
        return
    for job in stale_jobs:
        diagnostic_event(
            "job.stale_timeout",
            job_id=job.id,
            conversation_id=job.conversation_id,
            previous_status=job.status,
            previous_stage=job.stage,
            idle_seconds=(now - job.updated_at).total_seconds(),
            log_retained=True,
        )
    db.execute(
        update(ChatJob)
        .where(ChatJob.id.in_([job.id for job in stale_jobs]))
        .values(status="failed", stage="failed", detail="This task stalled and was stopped automatically. Please ask the question again.", error="Stale job timeout")
    )
    db.commit()


@app.get("/api/chat/jobs", response_model=list[ChatJobRead])
def list_chat_jobs(db: Session = Depends(get_db)):
    _fail_stale_chat_jobs(db)
    return db.scalars(select(ChatJob).order_by(ChatJob.created_at.desc(), ChatJob.id.desc()).limit(100)).all()


@app.patch("/api/chat/jobs/{job_id}/seen", response_model=ChatJobRead)
def mark_chat_job_seen(job_id: str, db: Session = Depends(get_db)):
    job = db.get(ChatJob, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Chat job not found")
    job.seen = True
    db.commit()
    db.refresh(job)
    return job


@app.post("/api/chat/jobs/{job_id}/cancel", response_model=ChatJobRead)
def cancel_chat_job(job_id: str, db: Session = Depends(get_db)):
    job = db.get(ChatJob, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Chat job not found")
    if job.status in {"queued", "running"}:
        _cancel_chat_jobs([job_id], USER_STOPPED_DETAIL)
        _ensure_stopped_question_message(db, job)
        job.status = "cancelled"
        job.stage = "cancelled"
        job.detail = USER_STOPPED_DETAIL
        job.error = USER_STOPPED_DETAIL
        events = list(job.events or [])
        events.append({
            "stage": "cancelled",
            "detail": USER_STOPPED_DETAIL,
            "at": datetime.now(timezone.utc).isoformat(),
            **_pipeline_event_metadata("cancelled", USER_STOPPED_DETAIL),
        })
        job.events = events[-120:]
    db.commit()
    db.refresh(job)
    return job


@app.get("/api/chats", response_model=list[ChatSessionRead])
def list_chats(db: Session = Depends(get_db)):
    from sqlalchemy import func
    from sqlalchemy.orm import joinedload

    # Subquery to get message counts and total chars per session
    msg_stats = db.query(
        ChatMessage.session_id,
        func.count(ChatMessage.id).label("message_count"),
        func.sum(func.length(ChatMessage.content)).label("total_chars")
    ).group_by(ChatMessage.session_id).subquery()

    # Main query with joined stats
    sessions = db.query(ChatSession).outerjoin(
        msg_stats, ChatSession.id == msg_stats.c.session_id
    ).order_by(ChatSession.updated_at.desc(), ChatSession.id.desc()).all()

    # Attach stats to each session
    for session in sessions:
        stat = db.query(msg_stats).filter(msg_stats.c.session_id == session.id).first()
        session.message_count = stat.message_count if stat else 0
        session.total_chars = stat.total_chars if stat else 0

    return sessions


@app.get("/api/chats/{chat_id}/messages", response_model=list[ChatMessageRead])
def list_chat_messages(chat_id: int, db: Session = Depends(get_db)):
    if not db.get(ChatSession, chat_id):
        raise HTTPException(status_code=404, detail="Chat not found")
    messages = db.scalars(select(ChatMessage).where(ChatMessage.session_id == chat_id).order_by(ChatMessage.id)).all()
    return [_message_read(message) for message in messages]


@app.post("/api/chats/{chat_id}/stop")
def stop_chat(chat_id: int, db: Session = Depends(get_db)):
    if not db.get(ChatSession, chat_id):
        raise HTTPException(status_code=404, detail="Chat not found")
    active_job_ids = db.scalars(select(ChatJob.id).where(ChatJob.conversation_id == chat_id, ChatJob.status.in_(["queued", "running"]))).all()
    _cancel_chat_jobs(list(active_job_ids), USER_STOPPED_DETAIL)
    _cancel_chat_streams([chat_id])
    if active_job_ids:
        now = datetime.now(timezone.utc)
        jobs = db.scalars(select(ChatJob).where(ChatJob.id.in_(active_job_ids))).all()
        for job in jobs:
            _ensure_stopped_question_message(db, job)
            job.status = "cancelled"
            job.stage = "cancelled"
            job.detail = USER_STOPPED_DETAIL
            job.error = USER_STOPPED_DETAIL
            events = list(job.events or [])
            events.append({
                "stage": "cancelled",
                "detail": USER_STOPPED_DETAIL,
                "at": now.isoformat(),
                **_pipeline_event_metadata("cancelled", USER_STOPPED_DETAIL),
            })
            job.events = events[-120:]
        db.commit()
    return {"status": "stopped", "cancelled_jobs": list(active_job_ids)}


@app.delete("/api/chats/{chat_id}/messages/{message_id}/from", response_model=list[ChatMessageRead])
def truncate_chat_from_message(chat_id: int, message_id: int, db: Session = Depends(get_db)):
    session = db.get(ChatSession, chat_id)
    if not session:
        raise HTTPException(status_code=404, detail="Chat not found")
    message = db.get(ChatMessage, message_id)
    if not message or message.session_id != chat_id:
        raise HTTPException(status_code=404, detail="Message not found")
    active_job_ids = db.scalars(select(ChatJob.id).where(ChatJob.conversation_id == chat_id, ChatJob.status.in_(["queued", "running"]))).all()
    _cancel_chat_jobs(list(active_job_ids), USER_STOPPED_DETAIL)
    _cancel_chat_streams([chat_id])
    db.execute(delete(ChatJob).where(ChatJob.conversation_id == chat_id))
    db.execute(delete(ChatMessage).where(ChatMessage.session_id == chat_id, ChatMessage.id >= message_id))
    latest_message = db.scalars(select(ChatMessage).where(ChatMessage.session_id == chat_id).order_by(ChatMessage.id.desc()).limit(1)).first()
    session.updated_at = latest_message.created_at if latest_message else datetime.now(timezone.utc)
    db.commit()
    return db.scalars(select(ChatMessage).where(ChatMessage.session_id == chat_id).order_by(ChatMessage.id)).all()


@app.delete("/api/chats", status_code=status.HTTP_204_NO_CONTENT)
def delete_all_chats(db: Session = Depends(get_db)):
    active_job_ids = db.scalars(select(ChatJob.id).where(ChatJob.status.in_(["queued", "running"]))).all()
    chat_ids = db.scalars(select(ChatSession.id)).all()
    _cancel_chat_jobs(list(active_job_ids))
    _cancel_chat_streams(list(chat_ids))
    db.execute(delete(ChatJob))
    db.execute(delete(ChatMessage))
    db.execute(delete(ChatSession))
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@app.delete("/api/chats/{chat_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_chat(chat_id: int, db: Session = Depends(get_db)):
    session = db.get(ChatSession, chat_id)
    if not session:
        raise HTTPException(status_code=404, detail="Chat not found")
    active_job_ids = db.scalars(select(ChatJob.id).where(ChatJob.conversation_id == chat_id, ChatJob.status.in_(["queued", "running"]))).all()
    _cancel_chat_jobs(list(active_job_ids))
    _cancel_chat_streams([chat_id])
    db.execute(delete(ChatJob).where(ChatJob.conversation_id == chat_id))
    db.delete(session)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
