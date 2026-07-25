from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import platform
import re
from threading import Lock
from typing import Any


DIAGNOSTICS_DIR = Path(__file__).resolve().parents[1] / "diagnostics" / "jobs"
_ACTIVE_JOB_ID: ContextVar[str | None] = ContextVar("locus_diagnostic_job_id", default=None)
_WRITE_LOCK = Lock()
_SECRET_PATTERNS = (
    re.compile(r"(?i)(authorization\s*[:=]\s*bearer\s+)[^\s,;]+"),
    re.compile(r"(?i)(bearer\s+)[A-Za-z0-9._~+/-]+"),
    re.compile(r"(?i)((?:api[_ -]?key|token|secret|password)\s*[:=]\s*)[^\s,;]+"),
)
_SENSITIVE_KEYS = {"authorization", "api_key", "apikey", "token", "secret", "password", "headers", "messages", "prompt", "content"}


def _timestamp() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sanitize_text(value: str) -> str:
    sanitized = value
    for pattern in _SECRET_PATTERNS:
        sanitized = pattern.sub(r"\1<redacted>", sanitized)
    for name in ("GROQ_API_KEY", "OPENAI_API_KEY", "GEMINI_API_KEY"):
        secret = os.getenv(name, "").strip()
        if secret:
            sanitized = sanitized.replace(secret, "<redacted>")
    return sanitized[:20_000]


def sanitize(value: Any, key: str = "") -> Any:
    if key.lower() in _SENSITIVE_KEYS:
        return "<redacted>"
    if isinstance(value, str):
        return _sanitize_text(value)
    if isinstance(value, dict):
        return {str(item_key): sanitize(item_value, str(item_key)) for item_key, item_value in value.items()}
    if isinstance(value, (list, tuple)):
        return [sanitize(item) for item in value]
    if value is None or isinstance(value, (bool, int, float)):
        return value
    return _sanitize_text(repr(value))


def log_path(job_id: str) -> Path:
    safe_id = re.sub(r"[^A-Za-z0-9_-]", "_", job_id)
    return DIAGNOSTICS_DIR / f"{safe_id}.jsonl"


def diagnostic_event(event: str, *, job_id: str | None = None, **fields: Any) -> None:
    selected_job_id = job_id or _ACTIVE_JOB_ID.get()
    if not selected_job_id:
        return
    record = sanitize({"at": _timestamp(), "event": event, "job_id": selected_job_id, **fields})
    path = log_path(selected_job_id)
    try:
        with _WRITE_LOCK:
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(record, ensure_ascii=True, separators=(",", ":")) + "\n")
    except OSError:
        # Diagnostics must never break the user request they are observing.
        return


def initialize_job_log(job_id: str, **metadata: Any) -> None:
    path = log_path(job_id)
    path.unlink(missing_ok=True)
    diagnostic_event(
        "job.created",
        job_id=job_id,
        schema_version=1,
        python=platform.python_version(),
        platform=platform.platform(),
        pid=os.getpid(),
        **metadata,
    )


def delete_job_log(job_id: str) -> None:
    try:
        log_path(job_id).unlink(missing_ok=True)
    except OSError:
        return


@contextmanager
def diagnostic_job(job_id: str):
    token = _ACTIVE_JOB_ID.set(job_id)
    try:
        yield
    finally:
        _ACTIVE_JOB_ID.reset(token)
