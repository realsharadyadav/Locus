# Locus Runbook

## Start the App

Use two terminals or long-running sessions.

Backend:

```bash
npm run dev:api
```

Frontend:

```bash
npm run dev -- --host 127.0.0.1 --port 5173
```

URLs:

- Frontend: `http://127.0.0.1:5173/`
- Backend: `http://127.0.0.1:8000`
- Health: `http://127.0.0.1:8000/api/health`

## If the Backend Looks Offline

Start:

```bash
npm run dev:api
```

Expected health response:

```json
{"status":"ok"}
```

## If the Frontend Looks Offline

Start:

```bash
npm run dev -- --host 127.0.0.1 --port 5173
```

Vite proxies `/api` to `http://127.0.0.1:8000` via `vite.config.js`.

## Tests and Build

Frontend build:

```bash
npm run build
```

Focused backend checks:

```bash
.venv/bin/pytest backend/tests/test_api.py backend/tests/test_diagnostics.py
```

Full backend tests:

```bash
.venv/bin/pytest backend/tests
```

## Environment

Use `.env.example` as the source of truth for expected config.

Important settings:

- `LLM_PROVIDER`: `ollama`, `groq`, `openai`, or `gemini`
- `OLLAMA_URL`, `OLLAMA_MODEL`
- `GROQ_API_KEY`, `GROQ_MODEL`
- `OPENAI_API_KEY`
- `GEMINI_API_KEY`
- `SEMANTIC_RETRIEVAL_ENABLED`
- `CHROMA_PATH`
- `TICKET_ANALYSIS_ENABLED`

## Common Local Data

- SQLite database: `backend/locus.db`
- Uploaded files: `backend/uploads/`
- Optional Chroma vector data: `backend/chroma`
- Job diagnostics: `backend/diagnostics/jobs/`

Do not delete these casually. They contain user data and local state.
