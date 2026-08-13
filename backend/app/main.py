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
    EMBEDDING_BATCH_SIZE, GROQ_MODEL_PRESETS, TICKET_ANALYSIS_CLUSTER_SIMILARITY_THRESHOLD,
    MAX_UPLOAD_FILE_MB, SEMANTIC_MIN_SCORE, TICKET_ANALYSIS_ENABLED, TICKET_ANALYSIS_MAX_GROUPS,
    TICKET_ANALYSIS_MIN_GROUP_SIZE, TICKET_ANALYSIS_REPRESENTATIVE_TICKETS,
    configured_model, gateway_settings, llm_provider,
)
from .ai_defaults import preferred_ai
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
from .llm import ANSWER_SHAPE_INSTRUCTION, LLMProviderError, answer_planned_question, build_model_meta, clean_final_answer, enhance_question, extract_shared_evidence, generate_answer, generate_followup_questions, generate_unrestricted_answer, is_refusal, list_groq_models, list_openai_compatible_models, llm_call_cache, llm_provider_context, refusal_diagnostic, repair_response, stream_answer, token_usage_tracker, verify_response
from .modes import MODE_CONFIG
from .models import ChatJob, ChatMessage, ChatSession, Collection, StoredFile, TicketAnalysisResult, UserPreference
from .providers import PROVIDER_ORDER, PROVIDERS
from .schemas import ChatJobRead, ChatMessageRead, ChatRequest, ChatResponse, ChatSessionRead, ChatSource, CollectionCreate, CollectionRead, StoredFileRead, SuggestionsRequest, SuggestionsResponse, TicketAnalysisHistoryCreate, TicketAnalysisHistoryRead, TicketAnalysisRequest, UserPreferenceRead, UserPreferenceUpdate
from .seed import seed_database
from . import telegram_bridge
from .ticket_analysis import clean_tickets, read_ticket_rows, analyze_ticket_file, ticket_analysis_markdown
from .ticket_taxonomy_data import DEFAULT_TAXONOMY, DEFAULT_TAXONOMY_V2, TaxonomyRule
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
        if "data" not in secret_image_columns:
            connection.execute(text(f"ALTER TABLE secret_images ADD COLUMN data {BLOB}"))
            _backfill_secret_images_from_disk(connection)


def _backfill_secret_images_from_disk(connection) -> None:
    """Move any still-present disk files into the rows that reference them.

    Only does anything on a host that kept its filesystem across the upgrade —
    a local checkout. Where the disk was ephemeral the files are already gone,
    and those rows stay empty; `_prune_dataless_secret_images` clears them so the
    gallery does not advertise photos it cannot serve.
    """
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


def _first_matching_field(headers: list[str], aliases: tuple[str, ...]) -> str | None:
    normalized = {re.sub(r"[_\s-]+", " ", header.strip().lower()): header for header in headers}
    for alias in aliases:
        match = normalized.get(re.sub(r"[_\s-]+", " ", alias.strip().lower()))
        if match:
            return match
    return None


def _detect_ticket_fields(rows: list[dict]) -> dict:
    headers = list(dict.fromkeys(header for row in rows[:25] for header in row.keys()))
    detected = {
        "id": _first_matching_field(headers, ("ticket_id", "ticket id", "number", "incident_number", "incident number", "incident_no", "incident no", "sys_id", "sys id")),
        "title": _first_matching_field(headers, ("short_description", "short description", "title", "summary")),
        "description": _first_matching_field(headers, ("description", "details")),
        "category": _first_matching_field(headers, ("category", "record_type", "record type", "type")),
        "subcategory": _first_matching_field(headers, ("subcategory", "assignment_group", "assignment group", "business_service", "business service", "service")),
    }
    primary = {value for value in detected.values() if value}
    detected["metadata"] = [header for header in headers if header not in primary][:16]
    detected["all"] = headers
    return detected


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _group_source(group: dict) -> str:
    reason = str(group.get("matched_reason") or "").lower()
    if "llm fallback" in reason:
        return "LLM fallback"
    if "semantic" in reason:
        return "semantic cluster"
    if "category fallback" in reason or "structured" in reason:
        return "metadata"
    if "taxonomy" in reason or "okf" in reason or "rule" in reason or "post-processing taxonomy" in reason:
        return "taxonomy"
    return "semantic cluster"


def _build_group_explainability(groups: list[dict], total: int, use_llm_labels: bool) -> list[dict]:
    enriched = []
    for index, group in enumerate(groups, 1):
        source = _group_source(group)
        llm_named = bool(use_llm_labels and group.get("llm_named"))
        count = int(group.get("incidentCount") or 0)
        reason = group.get("matched_reason") or "Created by deterministic Patterns grouping."
        enriched.append({
            **group,
            "id": f"group_{index:02d}",
            "rank": index,
            "source": "LLM naming" if llm_named and source != "LLM fallback" else source,
            "taxonomy_parent": group.get("groupName") if source == "taxonomy" else group.get("subcategory"),
            "matched_rule": reason if source == "taxonomy" else None,
            "cluster_id": f"cluster_{index:02d}" if "cluster" in source.lower() else None,
            "why": f"{count} ticket(s) became this group because {reason}.",
            "recommended_action": "Review representative tickets, confirm ownership, and promote durable patterns into OKF taxonomy when repeated.",
            "confidence_breakdown": {
                "rule_or_cluster": group.get("confidence", 0),
                "coverage": round((count / total), 3) if total else 0,
                "human_review": 0.35 if group.get("manual_review_recommended") else 0,
            },
            "original_values": {
                "subcategory": group.get("subcategory"),
                "evidence": group.get("evidence") or [],
                "group_name": group.get("llm_original_name"),
            },
            "llm_naming_applied": llm_named,
        })
    return enriched


def _build_pipeline_trace(
    *,
    run_id: str,
    path: Path,
    stored_file: StoredFile,
    rows: list[dict],
    valid_tickets: int,
    manifest: dict,
    groups: list[dict],
    taxonomy_suggestions: list[dict],
    options: dict,
    pipeline: list[dict],
    file_hash: str,
    field_detection: dict,
    started: float,
) -> dict:
    stored_file_name = getattr(stored_file, "name", getattr(stored_file, "stored_name", "Unknown file"))
    stored_file_size = getattr(stored_file, "size", path.stat().st_size if path.exists() else 0)
    total_rows = int(manifest.get("totalRows") or len(rows))
    valid = int(manifest.get("validTickets") or valid_tickets)
    okf_paused = bool(options.get("pauseOkfTaxonomy") or manifest.get("okfTaxonomyPaused"))
    taxonomy_matched = 0 if okf_paused else sum(int(group.get("incidentCount") or 0) for group in groups if _group_source(group) in {"taxonomy", "metadata"})
    llm_assisted = sum(int(group.get("incidentCount") or 0) for group in groups if _group_source(group) == "LLM fallback")
    clustered = max(0, valid - taxonomy_matched - llm_assisted)
    unresolved = sum(int(group.get("incidentCount") or 0) for group in groups if group.get("groupName") == "Other Service Issues")
    cache_key = hashlib.sha1("|".join([
        file_hash,
        str(options.get("embeddingMethod")),
        str(options.get("clusteringMethod")),
        str(options.get("similarityThreshold")),
        str(options.get("problemGroupStrategy")),
    ]).encode("utf-8")).hexdigest()

    stage_by_name = {event.get("stage"): event for event in pipeline}

    def stage(key: str, label: str, input_count: int, output_count: int, explanation: str, details: dict | None = None, status: str = "completed"):
        event = stage_by_name.get(key) or {}
        return {
            "key": key,
            "label": label,
            "status": status,
            "input_count": input_count,
            "output_count": output_count,
            "duration_ms": event.get("elapsedMs", 0),
            "explanation": explanation,
            "details": details or event.get("meta", {}),
        }

    stages = [
        stage("select_file", "Select File", 1 if stored_file else 0, 1 if stored_file else 0, "The run is bound to one uploaded ticket file.", {"file_name": stored_file_name, "size": stored_file_size}),
        stage("parse_clean", "Parse & Clean", total_rows, valid, "Rows were parsed, normalized, deduplicated, and empty records removed.", {
            "input_rows": total_rows,
            "valid_tickets": valid,
            "duplicates_removed": manifest.get("duplicatesRemoved", 0),
            "empty_removed": manifest.get("emptyTicketsRemoved", 0),
        }),
        stage("field_mapping", "Field Mapping", len(field_detection.get("all") or []), len([value for key, value in field_detection.items() if key != "all" and value]), "Detected standard ticket fields from source headers.", field_detection),
        stage("metadata_grouping", "Metadata Grouping", valid, taxonomy_matched, "Structured category and subcategory values were used when they formed durable groups.", {"metadata_fields": field_detection.get("metadata", []), "paused": okf_paused}, status="skipped" if okf_paused else "completed"),
        stage("okf_taxonomy", "OKF Taxonomy Match", valid, taxonomy_matched, "OKF taxonomy was paused; tickets moved directly into clustering." if okf_paused else "Tickets were matched against OKF/ITSM taxonomy rules before semantic fallback.", {"rules_available": manifest.get("taxonomyRules", 0), "matched_tickets": taxonomy_matched, "paused": okf_paused}, status="skipped" if okf_paused else "completed"),
        stage("unmatched", "Unmatched Tickets", valid, max(0, valid - taxonomy_matched), "Records not confidently assigned by metadata or taxonomy moved into discovery.", {"unmatched_tickets": max(0, valid - taxonomy_matched)}),
        stage("vectorization", "Vectorization / Embedding", max(0, valid - taxonomy_matched), max(0, valid - taxonomy_matched), "Fresh vectors were generated from this file and selected embedding configuration.", {
            "method": options.get("embeddingMethod"),
            "fresh": True,
            "cache_key": cache_key,
            "message": "Fresh vectors generated for this run.",
        }),
        stage("semantic_clustering", "Semantic Clustering", max(0, valid - taxonomy_matched), clustered, "Unmatched ticket text was grouped by selected similarity strategy.", {
            "method": options.get("clusteringMethod"),
            "threshold": options.get("similarityThreshold"),
            "target_clusters": options.get("targetClusters"),
            "min_samples": options.get("hdbscanMinSamples"),
            "noise_tickets": unresolved if options.get("clusteringMethod") == "hdbscan_lite" else 0,
        }),
        stage("llm", "LLM Fallback / LLM Naming", clustered, llm_assisted, "LLM assistance was applied only where enabled by run settings.", {
            "fallback_enabled": options.get("useLlmFallback"),
            "naming_enabled": options.get("useLlmLabels"),
            "naming_status": options.get("llmLabelStatus", "disabled"),
            "groups_renamed": sum(1 for group in groups if group.get("llm_named")),
            "taxonomy_suggestions_generated": len(taxonomy_suggestions),
        }, status="completed" if options.get("useLlmFallback") or options.get("useLlmLabels") else "skipped"),
        stage("consolidation", "Consolidation", len(groups), len(groups), "Duplicate labels were merged, ranked, capped, and prepared with evidence.", {"final_groups": len(groups), "overflow_groups_capped": any(group.get("groupName") == "Other Service Issues" for group in groups)}),
        stage("final_groups", "Final Problem Groups", valid, len(groups), "Ranked business problem groups are ready for review.", {"top_groups": [group.get("groupName") for group in groups[:3]]}),
        stage("taxonomy_suggestions", "Taxonomy Suggestions", len(groups), len(taxonomy_suggestions), "Suggested rules are generated only from recurring unmatched clusters.", {"suggestions": len(taxonomy_suggestions)}, status="completed" if taxonomy_suggestions else "skipped"),
    ]
    return {
        "run_id": run_id,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "input": {
            "file_name": stored_file_name,
            "file_hash": file_hash,
            "total_rows": total_rows,
            "valid_tickets": valid,
            "detected_fields": field_detection,
        },
        "config": options,
        "fingerprint": f"{stored_file_name}:{file_hash[:12]}:{options.get('embeddingMethod')}:{options.get('clusteringMethod')}:{options.get('similarityThreshold')}:{options.get('problemGroupStrategy')}",
        "vectorization": {
            "fresh": True,
            "cache_key": cache_key,
            "duration_ms": stage_by_name.get("embed", {}).get("elapsedMs", 0),
            "message": "Fresh vectors generated for this run.",
        },
        "stages": stages,
        "coverage": {
            "taxonomy_matched": taxonomy_matched,
            "clustered": clustered,
            "llm_assisted": llm_assisted,
            "unresolved": unresolved,
        },
        "problem_groups": _build_group_explainability(groups, valid, bool(options.get("useLlmLabels"))),
        "taxonomy_suggestions": taxonomy_suggestions,
        "duration_ms": int((time.perf_counter() - started) * 1000),
        "status": "completed",
    }


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
    diagnostic_event(
        "startup.maintenance_complete",
        files=len(file_ids),
        profiles_refreshed=refreshed,
        files_indexed=indexed,
        files_failed=failed,
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
UPLOAD_DIR = Path(__file__).resolve().parents[1] / "uploads"
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


def _ticket_analysis_for_file(
    stored_file: StoredFile,
    max_groups: int | None = None,
    min_group_size: int | None = None,
    llm_fallback: bool = False,
    llm_model: str | None = None,
    embedding_method: str = "tfidf",
    clustering_method: str = "taxonomy_semantic",
    problem_group_strategy: str = "taxonomy_then_cluster",
    similarity_threshold: float | None = None,
    target_clusters: int | None = None,
    hdbscan_min_samples: int | None = None,
    representative_count: int | None = None,
    include_telemetry: bool = True,
    include_debug_samples: bool = True,
    use_llm_labels: bool = False,
    suggest_taxonomy_rules: bool = False,
    llm_provider_name: str | None = None,
    pause_okf_taxonomy: bool = False,
    taxonomy_rules: tuple[TaxonomyRule, ...] | None = None,
    progress=None,
):
    if not TICKET_ANALYSIS_ENABLED:
        raise HTTPException(status_code=404, detail="Ticket Analysis is disabled")
    path = UPLOAD_DIR / stored_file.stored_name
    started = time.perf_counter()
    run_id = uuid4().hex
    try:
        file_hash = _file_sha256(path)
        rows = read_ticket_rows(path)
        tickets, _, _ = clean_tickets(rows)
        field_detection = _detect_ticket_fields(rows)
    except (ValueError, json.JSONDecodeError) as exception:
        raise HTTPException(status_code=422, detail=str(exception)) from exception
    pipeline: list[dict] = []
    # An explicitly empty rule set is a real choice ("group by clustering alone"),
    # so only a missing one falls back to the shipped taxonomy.
    active_taxonomy = DEFAULT_TAXONOMY if taxonomy_rules is None else taxonomy_rules
    taxonomy_source = "custom" if taxonomy_rules is not None else "default_v2"
    normalized_strategy = _normalize_ticket_strategy(problem_group_strategy)

    def event(stage: str, detail: str, meta: dict | None = None):
        payload = {
            "stage": stage,
            "detail": detail,
            "elapsedMs": int((time.perf_counter() - started) * 1000),
            "meta": meta or {},
        }
        pipeline.append(payload)
        if progress:
            progress(stage, detail)

    event("ingest", "Read uploaded ticket file and detected tabular records", {
        "fileId": getattr(stored_file, "id", 0),
        "fileName": getattr(stored_file, "name", stored_file.stored_name),
        "size": getattr(stored_file, "size", 0),
        "chunks": getattr(stored_file, "embedding_chunks", 0),
    })
    try:
        event("clean", "Normalize ticket ids, title/description fields, categories, and duplicate candidates")
        event("embed", f"Create fresh run-scoped {embedding_method} signatures for the selected file", {
            "embeddingMethod": embedding_method,
            "freshEmbeddings": True,
        })
        event("strategy", f"Use {normalized_strategy} problem-group strategy", {
            "problemGroupStrategy": normalized_strategy,
            "targetClusters": target_clusters,
            "okfTaxonomyPaused": pause_okf_taxonomy,
        })
        event(
            "taxonomy",
            "OKF/ITSM taxonomy paused; all tickets continue to clustering" if pause_okf_taxonomy else "Check tickets against approved OKF/ITSM taxonomy before fallback grouping",
            {"paused": pause_okf_taxonomy, "taxonomySource": taxonomy_source, "rules": len(active_taxonomy)},
        )
        event("cluster", f"Run {clustering_method} grouping for unresolved or selected records", {
            "clusteringMethod": clustering_method,
            "similarityThreshold": similarity_threshold or TICKET_ANALYSIS_CLUSTER_SIMILARITY_THRESHOLD,
            "hdbscanMinSamples": hdbscan_min_samples,
        })
        # The selected provider has to be active for the whole run: every LLM
        # step inside the pipeline resolves its provider from this context.
        provider_scope = llm_provider_context(llm_provider_name) if llm_provider_name else nullcontext()
        with provider_scope:
            result = analyze_ticket_file(
                path,
                max_groups=max_groups or TICKET_ANALYSIS_MAX_GROUPS,
                min_group_size=min_group_size or TICKET_ANALYSIS_MIN_GROUP_SIZE,
                similarity_threshold=similarity_threshold or TICKET_ANALYSIS_CLUSTER_SIMILARITY_THRESHOLD,
                representative_count=representative_count or TICKET_ANALYSIS_REPRESENTATIVE_TICKETS,
                taxonomy=active_taxonomy,
                pause_okf_taxonomy=pause_okf_taxonomy,
                strategy=normalized_strategy,
                embedding_method=embedding_method,
                clustering_method=clustering_method,
                target_clusters=target_clusters,
                hdbscan_min_samples=hdbscan_min_samples or TICKET_ANALYSIS_MIN_GROUP_SIZE,
                llm_fallback=llm_fallback,
                llm_labels=use_llm_labels,
                llm_model=llm_model,
                suggest_taxonomy_rules=suggest_taxonomy_rules,
                progress=lambda stage, detail: event(stage, detail),
            )
        if llm_fallback:
            event("llm_fallback", "LLM fallback evaluated unknown clusters", {
                "model": llm_model or configured_model(),
                "provider": llm_provider_name or llm_provider(),
                "status": result.get("manifest", {}).get("llmFallbackStatus"),
            })
        else:
            event("fallback", "Deterministic fallback handled unresolved records without LLM")
        if use_llm_labels:
            event("llm_labels_result", "LLM group-name editor rewrote final labels", {
                "provider": llm_provider_name or llm_provider(),
                "model": llm_model or configured_model(),
                "status": result.get("manifest", {}).get("llmLabelStatus"),
                "groupsRenamed": result.get("manifest", {}).get("llmGroupsRenamed", 0),
            })
        event("consolidate", "Merged duplicate labels, ranked by incident count, and prepared evidence samples", {
            "groups": result.get("manifest", {}).get("problemGroups", 0),
            "debugSamples": include_debug_samples,
        })
        event("complete", "Patterns analysis complete", {
            "durationMs": int((time.perf_counter() - started) * 1000),
            "validTickets": result.get("manifest", {}).get("validTickets", 0),
        })
        result["analysisOptions"] = {
            "runId": run_id,
            "embeddingMethod": embedding_method,
            "clusteringMethod": clustering_method,
            "problemGroupStrategy": normalized_strategy,
            "similarityThreshold": similarity_threshold or TICKET_ANALYSIS_CLUSTER_SIMILARITY_THRESHOLD,
            "targetClusters": target_clusters,
            "hdbscanMinSamples": hdbscan_min_samples,
            "representativeCount": representative_count or TICKET_ANALYSIS_REPRESENTATIVE_TICKETS,
            "includeTelemetry": include_telemetry,
            "includeDebugSamples": include_debug_samples,
            "useLlmFallback": llm_fallback,
            "useLlmLabels": use_llm_labels,
            "suggestTaxonomyRules": suggest_taxonomy_rules,
            "taxonomySuggestionStatus": result.get("manifest", {}).get("taxonomySuggestionStatus", "disabled"),
            "llmProvider": llm_provider_name,
            "pauseOkfTaxonomy": pause_okf_taxonomy,
            "taxonomySource": taxonomy_source,
            "taxonomyRulesConfigured": len(active_taxonomy),
            "llmLabelStatus": result.get("manifest", {}).get("llmLabelStatus", "disabled"),
            "llmGroupsRenamed": result.get("manifest", {}).get("llmGroupsRenamed", 0),
            "freshVectorMessage": "Fresh vectors generated for this run.",
            "detectedFields": field_detection,
            "fileHash": file_hash,
        }
        result["pipeline"] = pipeline if include_telemetry else []
        trace = _build_pipeline_trace(
            run_id=run_id,
            path=path,
            stored_file=stored_file,
            rows=rows,
            valid_tickets=len(tickets),
            manifest=result.get("manifest", {}),
            groups=result.get("groups", []),
            taxonomy_suggestions=result.get("taxonomySuggestions") or [],
            options=result["analysisOptions"],
            pipeline=pipeline,
            file_hash=file_hash,
            field_detection=field_detection,
            started=started,
        )
        result["pipeline_trace"] = trace
        result["groups"] = trace["problem_groups"]
        return result
    except (ValueError, json.JSONDecodeError) as exception:
        raise HTTPException(status_code=422, detail=str(exception)) from exception


def _ticket_analysis_ai(payload: TicketAnalysisRequest, db: Session) -> tuple[str, str]:
    """The provider/model this run's LLM steps use: the Settings default unless the request
    pinned its own, same rule the chat endpoints follow (see _validate_chat_request)."""
    default_provider, default_model = preferred_ai(db)
    provider = payload.llmProvider or default_provider
    model = payload.model or (default_model if provider == default_provider else configured_model())
    return provider, model


@app.post("/api/ticket-analysis")
def ticket_analysis(payload: TicketAnalysisRequest, db: Session = Depends(get_db)):
    stored_file = db.get(StoredFile, payload.fileId)
    if not stored_file:
        raise HTTPException(status_code=404, detail="File not found")
    taxonomy_rules = _parse_ticket_taxonomy_rules(payload.taxonomyRules)
    llm_provider_name, llm_model = _ticket_analysis_ai(payload, db)
    return _ticket_analysis_for_file(
        stored_file,
        payload.maxGroups,
        payload.minGroupSize,
        payload.useLlmFallback,
        llm_model,
        embedding_method=payload.embeddingMethod,
        clustering_method=payload.clusteringMethod,
        problem_group_strategy=payload.problemGroupStrategy,
        similarity_threshold=payload.similarityThreshold,
        target_clusters=payload.targetClusters,
        hdbscan_min_samples=payload.hdbscanMinSamples,
        representative_count=payload.representativeCount,
        include_telemetry=payload.includeTelemetry,
        include_debug_samples=payload.includeDebugSamples,
        use_llm_labels=payload.useLlmLabels,
        suggest_taxonomy_rules=payload.suggestTaxonomyRules,
        llm_provider_name=llm_provider_name,
        pause_okf_taxonomy=payload.pauseOkfTaxonomy,
        taxonomy_rules=taxonomy_rules,
    )


@app.post("/api/ticket-analysis/stream")
def ticket_analysis_stream(payload: TicketAnalysisRequest, db: Session = Depends(get_db)):
    """Same run as /api/ticket-analysis, streamed stage by stage.

    The pipeline already emits progress events; this endpoint forwards them as
    they happen so the UI can show which stage is actually running instead of
    guessing on a timer. The final message carries the identical result payload,
    so a client that only cares about the answer can ignore the stage events.
    """
    stored_file = db.get(StoredFile, payload.fileId)
    if not stored_file:
        raise HTTPException(status_code=404, detail="File not found")
    taxonomy_rules = _parse_ticket_taxonomy_rules(payload.taxonomyRules)
    # Resolved here rather than inside run(): that runs on its own thread, after this
    # request's session is gone.
    llm_provider_name, llm_model = _ticket_analysis_ai(payload, db)
    detached = SimpleNamespace(
        id=stored_file.id,
        name=stored_file.name,
        stored_name=stored_file.stored_name,
        size=stored_file.size,
        embedding_chunks=stored_file.embedding_chunks,
    )

    def event_stream():
        events: Queue = Queue()

        def run():
            try:
                result = _ticket_analysis_for_file(
                    detached,
                    payload.maxGroups,
                    payload.minGroupSize,
                    payload.useLlmFallback,
                    llm_model,
                    embedding_method=payload.embeddingMethod,
                    clustering_method=payload.clusteringMethod,
                    problem_group_strategy=payload.problemGroupStrategy,
                    similarity_threshold=payload.similarityThreshold,
                    target_clusters=payload.targetClusters,
                    hdbscan_min_samples=payload.hdbscanMinSamples,
                    representative_count=payload.representativeCount,
                    include_telemetry=payload.includeTelemetry,
                    include_debug_samples=payload.includeDebugSamples,
                    use_llm_labels=payload.useLlmLabels,
                    suggest_taxonomy_rules=payload.suggestTaxonomyRules,
                    llm_provider_name=llm_provider_name,
                    pause_okf_taxonomy=payload.pauseOkfTaxonomy,
                    taxonomy_rules=taxonomy_rules,
                    progress=lambda stage, detail: events.put({"type": "stage", "stage": stage, "detail": detail}),
                )
                events.put({"type": "result", "data": result})
            except HTTPException as exception:
                events.put({"type": "error", "detail": exception.detail})
            except Exception as exception:  # noqa: BLE001 - surfaced to the client
                events.put({"type": "error", "detail": str(exception)})
            finally:
                events.put(None)

        def run_guarded():
            # Same invariant as the chat streams: run() only queues its sentinel once it
            # is inside its try block, so anything failing before that would leave the
            # consumer below blocked on an empty queue forever.
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


def _string_list(value, *, limit: int = 80, max_items: int = 80) -> tuple[str, ...]:
    if value is None:
        return ()
    values = value if isinstance(value, list) else [value]
    cleaned = []
    for item in values:
        text = re.sub(r"\s+", " ", str(item or "")).strip()
        if text:
            cleaned.append(text[:limit])
    return tuple(dict.fromkeys(cleaned[:max_items]))


def _parse_ticket_taxonomy_rules(raw_rules: list[dict] | None) -> tuple[TaxonomyRule, ...] | None:
    if raw_rules is None:
        return None
    if not raw_rules:
        return ()
    if len(raw_rules) > 200:
        raise HTTPException(status_code=422, detail="Custom taxonomy supports up to 200 rules")
    rules: list[TaxonomyRule] = []
    for index, raw in enumerate(raw_rules, start=1):
        if not isinstance(raw, dict):
            raise HTTPException(status_code=422, detail=f"Taxonomy rule #{index} must be an object")
        name = re.sub(r"\s+", " ", str(raw.get("name") or raw.get("groupName") or "")).strip()
        description = re.sub(r"\s+", " ", str(raw.get("description") or "")).strip()
        patterns = _string_list(raw.get("patterns") or raw.get("includes") or raw.get("signals"), max_items=120)
        if not name or not patterns:
            raise HTTPException(status_code=422, detail=f"Taxonomy rule #{index} needs a name and at least one pattern/include")
        rules.append(TaxonomyRule(
            name=name[:140],
            description=description[:500] or f"Tickets matching {name}.",
            patterns=patterns,
            category_aliases=_string_list(raw.get("categoryAliases") or raw.get("contexts") or raw.get("assignmentHints"), max_items=40),
            excludes=_string_list(raw.get("excludes"), max_items=40),
        ))
    return tuple(rules)


def _normalize_ticket_strategy(strategy: str | None) -> str:
    mapping = {
        "okf_first": "taxonomy_then_cluster",
        "taxonomy_semantic": "taxonomy_then_cluster",
        "cluster_first": "cluster_only",
        "okf_only": "taxonomy_only",
    }
    value = mapping.get(strategy or "", strategy or "taxonomy_then_cluster")
    if value not in {"taxonomy_then_cluster", "cluster_only", "taxonomy_only"}:
        raise HTTPException(status_code=422, detail="Unsupported problem group strategy")
    return value


@app.get("/api/ticket-analysis/okf-taxonomy")
def ticket_analysis_okf_taxonomy():
    return {
        "version": "default_v2",
        "ruleCount": len(DEFAULT_TAXONOMY_V2),
        "rules": [
            {
                "name": rule.name,
                "description": rule.description,
                "includes": list(rule.includes),
                "contexts": list(rule.contexts),
                "excludes": list(rule.excludes),
                "recordTypes": list(rule.record_types),
                "subcategories": list(rule.subcategories),
                "assignmentHints": list(rule.assignment_hints),
            }
            for rule in DEFAULT_TAXONOMY_V2
        ],
    }


@app.get("/api/ticket-analysis/history", response_model=list[TicketAnalysisHistoryRead])
def ticket_analysis_history(db: Session = Depends(get_db)):
    return db.scalars(select(TicketAnalysisResult).order_by(TicketAnalysisResult.created_at.desc()).limit(50)).all()


@app.get("/api/ticket-analysis/history/{result_id}", response_model=TicketAnalysisHistoryRead)
def ticket_analysis_history_detail(result_id: int, db: Session = Depends(get_db)):
    result = db.get(TicketAnalysisResult, result_id)
    if not result:
        raise HTTPException(status_code=404, detail="Analysis history not found")
    return result


@app.post("/api/ticket-analysis/history", response_model=TicketAnalysisHistoryRead)
def save_ticket_analysis_history(payload: TicketAnalysisHistoryCreate, db: Session = Depends(get_db)):
    result = TicketAnalysisResult(
        file_id=payload.fileId,
        file_name=payload.fileName,
        manifest=payload.manifest,
        groups=payload.groups,
        taxonomy_suggestions=payload.taxonomySuggestions,
        config=payload.config,
    )
    db.add(result)
    db.commit()
    db.refresh(result)
    return result


@app.delete("/api/ticket-analysis/history/{result_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_ticket_analysis_history(result_id: int, db: Session = Depends(get_db)):
    result = db.get(TicketAnalysisResult, result_id)
    if not result:
        raise HTTPException(status_code=404, detail="Analysis history not found")
    db.delete(result)
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

    Deep Summary's whole contract is exhaustive section-by-section coverage tracked by a manifest, and
    Unrestricted deliberately runs without added guardrails, so neither gets the summary-first layout.
    """
    if reasoning_mode in {"deep_summary", "unrestricted"}:
        return ""
    return ANSWER_SHAPE_INSTRUCTION


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
    if payload.reasoning_mode == "ticket_analysis":
        if not payload.file_ids:
            raise HTTPException(status_code=422, detail="Select one uploaded ticket file for Ticket Analysis")
        stored_file = db.get(StoredFile, payload.file_ids[0])
        if not stored_file:
            raise HTTPException(status_code=404, detail="Selected file not found")
        notify("gathering", f"Normalizing and grouping tickets from {stored_file.name}")
        result = _ticket_analysis_for_file(stored_file, llm_fallback=True, llm_model=payload.model, progress=notify)
        answer = ticket_analysis_markdown(result)
        source = ChatSource(id=stored_file.id, name=stored_file.name, store_id=stored_file.store_id, excerpt=f"Processed all {result['manifest']['validTickets']} valid tickets with {result['manifest']['coverageStatus']} coverage.")
        ensure_not_cancelled()
        db.add_all([ChatMessage(session_id=session.id, role="user", content=payload.question), ChatMessage(session_id=session.id, role="assistant", content=answer, sources=_sources_with_meta([source], llm_hits=1, web_queries=0), model="Ticket Analysis", provider=payload.provider)])
        db.commit()
        notify("complete", "Ticket Analysis ready")
        return ChatResponse(answer=answer, sources=[source], model="Ticket Analysis", conversation_id=session.id, llm_hits=1, web_queries=0)
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
    effective_web_search = _effective_web_search(payload)
    if effective_web_search:
        web_mode = "unrestricted web research" if payload.reasoning_mode == "unrestricted" else "web research"
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
    if payload.reasoning_mode == "unrestricted":
        notify("drafting", f"Unrestricted mode — trying to get answer for: {payload.question[:60]}")
        stored_files = db.scalars(select(StoredFile).where(StoredFile.id.in_(payload.file_ids))).all() if payload.file_ids else []
        sources_list = [(stored_file.name, stored_file.extracted_text or "") for stored_file in stored_files]
        try:
            answer, model = generate_unrestricted_answer(
                payload.question,
                sources_list,
                history,
                payload.model,
                lambda detail: notify("drafting", detail),
            )
        except LLMProviderError as exception:
            raise HTTPException(status_code=exception.status_code, detail=str(exception))
        except RuntimeError as exception:
            raise HTTPException(status_code=503, detail=str(exception))
        ensure_not_cancelled()
        source_data = [ChatSource(id=stored_file.id, name=stored_file.name, store_id=stored_file.store_id, excerpt="Referenced file in unrestricted mode.") for stored_file in stored_files]
        llm_hits = 1
        web_queries = 0
        db.add_all([
            ChatMessage(session_id=session.id, role="user", content=payload.question),
            ChatMessage(session_id=session.id, role="assistant", content=answer, sources=_sources_with_meta(source_data, llm_hits, web_queries), model=model, provider=payload.provider),
        ])
        db.commit()
        notify("complete", "Unrestricted answer ready")
        return ChatResponse(answer=answer, sources=source_data, model=model, conversation_id=session.id, llm_hits=llm_hits, web_queries=web_queries)
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
    if reasoning_mode in {"ticket_analysis", "deep_summary"}:
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
    return payload.web_search or payload.reasoning_mode == "web_research" or should_auto_web_search(payload.question, payload.reasoning_mode)


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
    if _effective_web_search(payload) or payload.reasoning_mode not in {"light", "unrestricted"} or payload.file_ids != []:
        raise HTTPException(status_code=422, detail="Direct streaming is only available for Light or Unrestricted mode with no selected files and Web Search off")

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
                        if payload.reasoning_mode == "unrestricted" and is_refusal(answer):
                            events.put({"type": "token", "text": "\n\n_[Model initially refused. Running jailbreak pipeline…]_\n\n"})
                            answer, used_model = generate_unrestricted_answer(
                                payload.question,
                                [],
                                history,
                                payload.model,
                            )
                        else:
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
        "gathering": "extract_evidence()",
        "drafting": "answer_planned_question()",
        "verifying": "verify_response()",
        "repairing": "repair_response()",
        "complete": "persist_chat_messages()",
        "failed": "raise_pipeline_error()",
    }
    metadata["method"] = stage_methods.get(stage, metadata["method"])
    if "taxonomy fallback" in lowered:
        metadata["method"] = "ticket_taxonomy_llm_fallback()"
    if "directly; no files selected" in lowered:
        metadata.update(type="llm_call", direction="outbound", method="generate_answer()", payload_preview=detail)
    if "calling " in lowered:
        metadata.update(type="llm_call", direction="outbound", payload_preview=detail)
    elif "taxonomy fallback returned" in lowered or "taxonomy fallback skipped" in lowered:
        metadata.update(type="llm_result", direction="inbound", response_preview=detail)
        if "skipped" in lowered:
            metadata["tags"].append("skipped")
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
