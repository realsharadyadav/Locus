# Locus Brand Guide

## Identity

- **Product name:** Locus
- **Assistant name:** Locus AI
- **Tagline:** Your knowledge, one question away.
- **Positioning:** Local developer research workspace — upload files, ask questions, inspect the pipeline.

## Navigation

| Route id | Label |
|---|---|
| `home` | Home |
| `hub` | Library |
| `explore` | Ask |
| `secret-chat` | Private |

## Voice

- Calm, precise, developer-focused
- Prefer operational clarity over marketing fluff
- Show method, evidence, and pipeline telemetry where useful

## Visual

- Dark mode: GitHub-like surfaces with restrained purple accents
- Logo mark: concentric focal rings (place / locus)
- Key file: `src/styles.css`

## Terminology

| Use | Avoid |
|---|---|
| Library | Knowledge hub |
| Ask | Explore (user-facing) |
| Private | Secret chat |
| Locus AI | MindMap AI |

Internal route ids (`explore`, `hub`) stay stable for URLs and API compatibility.

## Storage migration

Legacy `mindmap-*` localStorage and sessionStorage keys are read once and copied to `locus-*` keys on first access.

Legacy database path `backend/mindmap.db` is used automatically when `backend/locus.db` does not exist yet.

Legacy sqlite vector index `mindmap_vector_index.sqlite3` is used when `locus_vector_index.sqlite3` does not exist yet (fallback path only; the primary vector store is pgvector on Postgres).
