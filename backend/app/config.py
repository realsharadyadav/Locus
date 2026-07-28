import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


PROJECT_ROOT = Path(__file__).resolve().parents[2]
ENV_PATH = PROJECT_ROOT / ".env"
load_dotenv(ENV_PATH)

TICKET_ANALYSIS_ENABLED = os.getenv("TICKET_ANALYSIS_ENABLED", "true").lower() in {"1", "true", "yes", "on"}
TICKET_ANALYSIS_MIN_GROUP_SIZE = max(1, int(os.getenv("TICKET_ANALYSIS_MIN_GROUP_SIZE", "3")))
TICKET_ANALYSIS_MAX_GROUPS = max(1, int(os.getenv("TICKET_ANALYSIS_MAX_GROUPS", "20")))
TICKET_ANALYSIS_REPRESENTATIVE_TICKETS = max(1, int(os.getenv("TICKET_ANALYSIS_REPRESENTATIVE_TICKETS", "3")))
TICKET_ANALYSIS_USE_EMBEDDINGS = os.getenv("TICKET_ANALYSIS_USE_EMBEDDINGS", "true").lower() in {"1", "true", "yes", "on"}
TICKET_ANALYSIS_DEDUP_THRESHOLD = float(os.getenv("TICKET_ANALYSIS_DEDUP_THRESHOLD", "0.92"))
TICKET_ANALYSIS_CLUSTER_SIMILARITY_THRESHOLD = float(os.getenv("TICKET_ANALYSIS_CLUSTER_SIMILARITY_THRESHOLD", "0.78"))
SEMANTIC_RETRIEVAL_ENABLED = os.getenv("SEMANTIC_RETRIEVAL_ENABLED", "true").lower() in {"1", "true", "yes", "on"}
# Used only as a last-resort fallback when LOCUS_DATABASE_URL isn't Postgres (pgvector is the
# primary vector store — see vector_store.py).
VECTOR_FALLBACK_PATH = (PROJECT_ROOT / os.getenv("VECTOR_FALLBACK_PATH", "backend/vector_fallback")).resolve()
EMBEDDING_DIMENSIONS = max(64, int(os.getenv("EMBEDDING_DIMENSIONS", "384")))
SEMANTIC_CHUNK_CHARS = max(300, int(os.getenv("SEMANTIC_CHUNK_CHARS", "1200")))
SEMANTIC_CHUNK_OVERLAP = max(0, int(os.getenv("SEMANTIC_CHUNK_OVERLAP", "180")))
SEMANTIC_TOP_K = max(1, int(os.getenv("SEMANTIC_TOP_K", "6")))
SEMANTIC_MIN_SCORE = float(os.getenv("SEMANTIC_MIN_SCORE", "0.18"))
# Uploads are parsed and embedded synchronously in-process (see main.py's upload_file), so the
# cap needs to fit the deployment's memory budget, not just reasonable document sizes. Default is
# sized for a 512MB host; raise via env on a larger plan.
MAX_UPLOAD_FILE_MB = max(1, int(os.getenv("MAX_UPLOAD_FILE_MB", "25")))
# Bounds how many chunks fastembed encodes per onnxruntime forward pass. Lower values trade
# indexing speed for a smaller peak memory footprint during embedding.
EMBEDDING_BATCH_SIZE = max(1, int(os.getenv("EMBEDDING_BATCH_SIZE", "16")))

WEB_RESEARCH_MAX_SOURCES = max(5, int(os.getenv("WEB_RESEARCH_MAX_SOURCES", "50")))
WEB_RESEARCH_RESULTS_PER_QUERY = max(3, min(50, int(os.getenv("WEB_RESEARCH_RESULTS_PER_QUERY", "10"))))
WEB_RESEARCH_INITIAL_QUERIES = max(2, min(10, int(os.getenv("WEB_RESEARCH_INITIAL_QUERIES", "5"))))
OPENSERP_BASE_URL = os.getenv("OPENSERP_BASE_URL", "").strip() or None

GROQ_MODEL_PRESETS = [
    "openai/gpt-oss-20b",
    "openai/gpt-oss-120b",
    "qwen/qwen3.6-27b",
    "llama-3.1-8b-instant",
    "llama-3.3-70b-versatile",
]


def require_environment_variable(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value or value.lower() in {"changeme", "placeholder", "your-key-here"}:
        raise RuntimeError(
            f"Missing required environment variable: {name}. "
            f"Set {name} in {ENV_PATH} and restart the backend."
        )
    return value


def llm_provider() -> str:
    provider = os.getenv("LLM_PROVIDER", "ollama").strip().lower()
    if provider not in {"ollama", "groq", "openai", "gemini"}:
        raise RuntimeError(
            f"Unsupported LLM_PROVIDER '{provider}'. Set LLM_PROVIDER to 'ollama', 'groq', 'openai', or 'gemini'."
        )
    return provider


@dataclass(frozen=True)
class GroqSettings:
    api_key: str
    base_url: str
    model: str
    temperature: float
    max_tokens: int
    timeout_seconds: float
    max_retries: int
    retry_backoff_seconds: float


def groq_settings(require_key: bool = True) -> GroqSettings:
    api_key = require_environment_variable("GROQ_API_KEY") if require_key else os.getenv("GROQ_API_KEY", "").strip()
    return GroqSettings(
        api_key=api_key,
        base_url=os.getenv("GROQ_BASE_URL", "https://api.groq.com/openai/v1").rstrip("/"),
        model=os.getenv("GROQ_MODEL", GROQ_MODEL_PRESETS[0]).strip() or GROQ_MODEL_PRESETS[0],
        temperature=float(os.getenv("GROQ_TEMPERATURE", "0.15")),
        max_tokens=int(os.getenv("GROQ_MAX_TOKENS", "4096")),
        timeout_seconds=float(os.getenv("GROQ_TIMEOUT_SECONDS", "120")),
        max_retries=max(0, int(os.getenv("GROQ_MAX_RETRIES", "2"))),
        retry_backoff_seconds=max(0, float(os.getenv("GROQ_RETRY_BACKOFF_SECONDS", "2"))),
    )


def configured_model() -> str:
    provider = llm_provider()
    if provider == "groq":
        return groq_settings(require_key=False).model
    if provider == "openai":
        return os.getenv("OPENAI_MODEL", "gpt-5.4-mini").strip() or "gpt-5.4-mini"
    if provider == "gemini":
        return os.getenv("GEMINI_MODEL", "gemini-2.5-flash").strip() or "gemini-2.5-flash"
    return os.getenv("OLLAMA_MODEL", "llama3.2:latest")


def validate_model_environment(model: str) -> None:
    if model.startswith("gpt-"):
        require_environment_variable("OPENAI_API_KEY")
    elif model.startswith("gemini-"):
        require_environment_variable("GEMINI_API_KEY")
