from __future__ import annotations

from dataclasses import dataclass
import hashlib
import importlib.util
import json
import math
import re
import sqlite3
from threading import Lock
from typing import Iterable

from sqlalchemy import text

from .brand import LEGACY_VECTOR_INDEX_FILENAME, VECTOR_INDEX_FILENAME
from .config import (
    EMBEDDING_DIMENSIONS,
    SEMANTIC_CHUNK_CHARS,
    SEMANTIC_CHUNK_OVERLAP,
    SEMANTIC_RETRIEVAL_ENABLED,
    SEMANTIC_TOP_K,
    VECTOR_FALLBACK_PATH,
)
from .database import engine


TOKEN_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{2,}")
HASH_EMBEDDING_MODEL = "local-hash-embedding-v1"
FASTEMBED_MODEL_NAME = "BAAI/bge-small-en-v1.5"
_FASTEMBED_INSTALLED = importlib.util.find_spec("fastembed") is not None
EMBEDDING_MODEL = f"fastembed:{FASTEMBED_MODEL_NAME}" if _FASTEMBED_INSTALLED else HASH_EMBEDDING_MODEL

_fastembed_model = None
_fastembed_load_failed = False

_pgvector_ready = False
_pgvector_lock = Lock()


@dataclass(frozen=True)
class SemanticHit:
    file_id: int
    store_id: int
    name: str
    excerpt: str
    score: float
    chunk_index: int


@dataclass(frozen=True)
class IndexResult:
    chunks: int
    backend: str
    model: str = EMBEDDING_MODEL
    status: str = "embedded"
    error: str = ""


class VectorStoreUnavailable(RuntimeError):
    pass


def _tokens(text: str) -> list[str]:
    return [token.lower() for token in TOKEN_PATTERN.findall(text)]


def _normalize(vector: list[float]) -> list[float]:
    magnitude = math.sqrt(sum(value * value for value in vector)) or 1.0
    return [float(value) / magnitude for value in vector]


def _hash_embed(text: str) -> list[float]:
    """Deterministic hashing-trick vector. No semantic meaning — only literal
    token overlap. Used only when fastembed is unavailable or fails to load."""
    vector = [0.0] * EMBEDDING_DIMENSIONS
    for token in _tokens(text):
        digest = hashlib.blake2b(token.encode("utf-8"), digest_size=8).digest()
        index = int.from_bytes(digest[:4], "big") % EMBEDDING_DIMENSIONS
        sign = 1.0 if digest[4] % 2 == 0 else -1.0
        vector[index] += sign
    return _normalize(vector)


def _get_fastembed_model():
    global _fastembed_model, _fastembed_load_failed
    if not _FASTEMBED_INSTALLED or _fastembed_load_failed:
        return None
    if _fastembed_model is None:
        try:
            from fastembed import TextEmbedding
            _fastembed_model = TextEmbedding(model_name=FASTEMBED_MODEL_NAME)
        except Exception:
            _fastembed_load_failed = True
            return None
    return _fastembed_model


def active_embedding_model() -> str:
    """The embedding scheme actually usable right now, verified by loading the
    model rather than just checking whether the package is installed."""
    return EMBEDDING_MODEL if _get_fastembed_model() is not None else HASH_EMBEDDING_MODEL


def embed_passages(texts: list[str]) -> list[list[float]]:
    """Embed document/chunk text for indexing. Batches through fastembed when
    available; falls back to the hashing trick otherwise."""
    if not texts:
        return []
    model = _get_fastembed_model()
    if model is not None:
        try:
            return [_normalize(list(vector)) for vector in model.passage_embed(texts)]
        except Exception:
            pass
    return [_hash_embed(text) for text in texts]


def embed_query(text: str) -> list[float]:
    """Embed a search query, using the asymmetric query prefix bge models expect."""
    model = _get_fastembed_model()
    if model is not None:
        try:
            return _normalize(list(next(iter(model.query_embed([text])))))
        except Exception:
            pass
    return _hash_embed(text)


def embed_text(text: str) -> list[float]:
    return embed_passages([text])[0] if text else _hash_embed(text)


def chunk_text(text: str, *, chunk_chars: int = SEMANTIC_CHUNK_CHARS, overlap: int = SEMANTIC_CHUNK_OVERLAP) -> list[str]:
    clean = re.sub(r"\s+", " ", text).strip()
    if not clean:
        return []
    chunks = []
    start = 0
    while start < len(clean):
        end = min(len(clean), start + chunk_chars)
        if end < len(clean):
            boundary = max(clean.rfind(". ", start, end), clean.rfind("\n", start, end))
            if boundary > start + chunk_chars * 0.55:
                end = boundary + 1
        chunks.append(clean[start:end].strip())
        if end >= len(clean):
            break
        start = max(end - overlap, start + 1)
    return [chunk for chunk in chunks if chunk]


def _is_postgres() -> bool:
    return engine.url.get_backend_name() == "postgresql"


def ensure_vector_schema() -> None:
    """Create the pgvector extension, chunks table, and index once per process.
    No-op on non-Postgres engines — those fall back to the plain-cosine sqlite path."""
    global _pgvector_ready
    if _pgvector_ready or not _is_postgres():
        return
    with _pgvector_lock:
        if _pgvector_ready:
            return
        with engine.begin() as connection:
            connection.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
            connection.execute(text(
                f"""
                CREATE TABLE IF NOT EXISTS chunks (
                    id TEXT PRIMARY KEY,
                    file_id INTEGER NOT NULL,
                    store_id INTEGER NOT NULL,
                    name TEXT NOT NULL,
                    chunk_index INTEGER NOT NULL,
                    document TEXT NOT NULL,
                    embedding vector({EMBEDDING_DIMENSIONS}) NOT NULL
                )
                """
            ))
            connection.execute(text("CREATE INDEX IF NOT EXISTS idx_chunks_file_id ON chunks (file_id)"))
            connection.execute(text(
                "CREATE INDEX IF NOT EXISTS idx_chunks_embedding ON chunks "
                "USING hnsw (embedding vector_cosine_ops)"
            ))
        _pgvector_ready = True


def _require_pgvector() -> None:
    if not SEMANTIC_RETRIEVAL_ENABLED:
        raise VectorStoreUnavailable("Semantic retrieval is disabled")
    if not _is_postgres():
        raise VectorStoreUnavailable("pgvector requires a Postgres LOCUS_DATABASE_URL")
    ensure_vector_schema()


def _vector_literal(embedding: list[float]) -> str:
    return "[" + ",".join(repr(float(value)) for value in embedding) + "]"


def _pgvector_delete(file_id: int) -> None:
    with engine.begin() as connection:
        connection.execute(text("DELETE FROM chunks WHERE file_id = :file_id"), {"file_id": file_id})


def _pgvector_insert(file_id: int, store_id: int, name: str, chunks: list[str], embeddings: list[list[float]]) -> None:
    with engine.begin() as connection:
        connection.execute(text("DELETE FROM chunks WHERE file_id = :file_id"), {"file_id": file_id})
        connection.execute(
            text(
                """
                INSERT INTO chunks (id, file_id, store_id, name, chunk_index, document, embedding)
                VALUES (:id, :file_id, :store_id, :name, :chunk_index, :document, CAST(:embedding AS vector))
                """
            ),
            [
                {
                    "id": f"file-{file_id}-chunk-{index}",
                    "file_id": file_id,
                    "store_id": store_id,
                    "name": name,
                    "chunk_index": index,
                    "document": chunk,
                    "embedding": _vector_literal(embedding),
                }
                for index, (chunk, embedding) in enumerate(zip(chunks, embeddings))
            ],
        )


def _pgvector_search(query_embedding: list[float], *, file_ids: list[int] | None, top_k: int) -> list[SemanticHit]:
    params: dict = {"embedding": _vector_literal(query_embedding), "top_k": top_k}
    where_clause = ""
    if file_ids is not None:
        where_clause = "WHERE file_id = ANY(:file_ids)"
        params["file_ids"] = list(file_ids)
    with engine.connect() as connection:
        rows = connection.execute(
            text(
                f"""
                SELECT file_id, store_id, name, chunk_index, document,
                       embedding <=> CAST(:embedding AS vector) AS distance
                FROM chunks
                {where_clause}
                ORDER BY embedding <=> CAST(:embedding AS vector)
                LIMIT :top_k
                """
            ),
            params,
        ).fetchall()
    return [
        SemanticHit(
            file_id=int(row.file_id),
            store_id=int(row.store_id),
            name=str(row.name),
            excerpt=str(row.document),
            score=max(0.0, 1.0 - float(row.distance)),
            chunk_index=int(row.chunk_index),
        )
        for row in rows
    ]


def _sqlite_path():
    VECTOR_FALLBACK_PATH.mkdir(parents=True, exist_ok=True)
    primary = VECTOR_FALLBACK_PATH / VECTOR_INDEX_FILENAME
    legacy = VECTOR_FALLBACK_PATH / LEGACY_VECTOR_INDEX_FILENAME
    if primary.exists() or not legacy.exists():
        return primary
    return legacy


def _sqlite_connection():
    connection = sqlite3.connect(_sqlite_path())
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS chunks (
            id TEXT PRIMARY KEY,
            file_id INTEGER NOT NULL,
            store_id INTEGER NOT NULL,
            name TEXT NOT NULL,
            chunk_index INTEGER NOT NULL,
            document TEXT NOT NULL,
            embedding TEXT NOT NULL
        )
        """
    )
    connection.execute("CREATE INDEX IF NOT EXISTS idx_chunks_file_id ON chunks(file_id)")
    return connection


def _cosine(left: list[float], right: list[float]) -> float:
    return sum(a * b for a, b in zip(left, right))


def delete_file_embeddings(file_id: int) -> None:
    try:
        _require_pgvector()
        _pgvector_delete(file_id)
        return
    except Exception:
        pass
    with _sqlite_connection() as connection:
        connection.execute("DELETE FROM chunks WHERE file_id = ?", (file_id,))


def index_file(file_id: int, store_id: int, name: str, text: str) -> int:
    return index_file_with_status(file_id, store_id, name, text).chunks


def index_file_with_status(file_id: int, store_id: int, name: str, text: str) -> IndexResult:
    chunks = chunk_text(text)
    model_used = active_embedding_model()
    try:
        _require_pgvector()
        if not chunks:
            _pgvector_delete(file_id)
            return IndexResult(chunks=0, backend="pgvector", model=model_used, status="empty")
        _pgvector_insert(file_id, store_id, name, chunks, embed_passages(chunks))
        return IndexResult(chunks=len(chunks), backend="pgvector", model=model_used)
    except VectorStoreUnavailable:
        pass
    except Exception:
        pass
    with _sqlite_connection() as connection:
        connection.execute("DELETE FROM chunks WHERE file_id = ?", (file_id,))
        if not chunks:
            return IndexResult(chunks=0, backend="sqlite", model=model_used, status="empty")
        chunk_embeddings = embed_passages(chunks)
        connection.executemany(
            """
            INSERT INTO chunks (id, file_id, store_id, name, chunk_index, document, embedding)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    f"file-{file_id}-chunk-{index}",
                    file_id,
                    store_id,
                    name,
                    index,
                    chunk,
                    json.dumps(embedding, separators=(",", ":")),
                )
                for index, (chunk, embedding) in enumerate(zip(chunks, chunk_embeddings))
            ],
        )
        return IndexResult(chunks=len(chunks), backend="sqlite", model=model_used)


def index_files(files: Iterable) -> int:
    indexed = 0
    for stored_file in files:
        try:
            indexed += index_file(stored_file.id, stored_file.store_id, stored_file.name, stored_file.extracted_text)
        except Exception:
            continue
    return indexed


def search(query: str, *, file_ids: list[int] | None = None, top_k: int = SEMANTIC_TOP_K) -> list[SemanticHit]:
    if file_ids == []:
        return []
    query_embedding = embed_query(query)
    try:
        _require_pgvector()
        return _pgvector_search(query_embedding, file_ids=file_ids, top_k=top_k)
    except VectorStoreUnavailable:
        return _sqlite_search(query_embedding, file_ids=file_ids, top_k=top_k)
    except Exception:
        return _sqlite_search(query_embedding, file_ids=file_ids, top_k=top_k)


def _sqlite_search(query_embedding: list[float], *, file_ids: list[int] | None, top_k: int) -> list[SemanticHit]:
    with _sqlite_connection() as connection:
        if file_ids is None:
            rows = connection.execute("SELECT file_id, store_id, name, chunk_index, document, embedding FROM chunks").fetchall()
        else:
            placeholders = ",".join("?" for _ in file_ids)
            rows = connection.execute(
                f"SELECT file_id, store_id, name, chunk_index, document, embedding FROM chunks WHERE file_id IN ({placeholders})",
                tuple(file_ids),
            ).fetchall()
    scored = []
    for file_id, store_id, name, chunk_index, document, embedding_json in rows:
        score = _cosine(query_embedding, json.loads(embedding_json))
        scored.append(SemanticHit(
            file_id=int(file_id),
            store_id=int(store_id),
            name=str(name),
            excerpt=str(document),
            score=score,
            chunk_index=int(chunk_index),
        ))
    return sorted(scored, key=lambda hit: hit.score, reverse=True)[:top_k]
