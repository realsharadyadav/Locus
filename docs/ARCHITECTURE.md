# Locus Architecture Notes

Locus is a local research workspace with a Vite/React frontend and FastAPI backend.

## Frontend

- Entry point: `src/main.jsx`
- Styles: `src/styles.css`
- API client: `src/api.js`
- Small components: `src/components/`

Major frontend surfaces:

- `HomePage`: overview and quick actions
- `HubPage`: stores and file uploads
- `ExplorePage`: chat workspace, file scoping, reasoning modes (the model comes from Settings)
- `PipelineActivity`: live developer/research pipeline card
- `FileTreePanel`: right-side evidence scope selector
- `CommandPalette`: global search/navigation

## Backend

- FastAPI app and routes: `backend/app/main.py`
- Database/session setup: `backend/app/database.py`
- SQLAlchemy models: `backend/app/models.py`
- Pydantic schemas: `backend/app/schemas.py`
- File extraction: `backend/app/files.py`
- LLM providers and calls: `backend/app/llm.py`
- Reasoning mode config: `backend/app/modes.py`
- Deep summary: `backend/app/deep_summary.py`
- Local semantic retrieval: `backend/app/vector_store.py`
- Diagnostics logging: `backend/app/diagnostics.py`

## Data Flow

1. User creates a collection or store.
2. User uploads files.
3. Backend extracts text and stores metadata in the relational database (SQLite locally by default, Postgres when `LOCUS_DATABASE_URL` is set).
4. If semantic retrieval is enabled, backend indexes chunks via `vector_store.py` — pgvector when the database is Postgres, otherwise a plain-cosine SQLite fallback.
5. User asks a question in Ask.
6. Backend creates a `ChatJob` and runs it in a background thread.
7. Frontend polls `/api/chat/jobs`.
8. `PipelineActivity` renders job stage, live event metadata, telemetry, and console events.
9. Completed answers are persisted as `ChatMessage` rows with sources.

## Retrieval

Current retrieval is hybrid:

- Keyword and relevant excerpt retrieval in `files.py`
- Optional semantic retrieval in `vector_store.py`, backed by pgvector on Postgres (or a SQLite cosine fallback if no Postgres is configured)
- Semantic retrieval uses local embeddings (fastembed, or a hash-based fallback), not an external embedding API.
- The vector store is optional; if unavailable, the app continues without semantic search.

## Chat Jobs

`ChatJob.events` is intentionally rich. New events can include:

- `type`
- `direction`
- `method`
- `payload_preview`
- `response_preview`
- `tags`
- `stage`
- `detail`
- `at`

Keep these fields sanitized and avoid exposing secrets, full prompts, provider headers, or raw API keys.
