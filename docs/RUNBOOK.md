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

## Deploy to Render (free tier)

Locus deploys as two free Render services, defined in `render.yaml`
(a Render "Blueprint"):

- `locus-backend`: a Docker web service built from the root `Dockerfile`,
  running the FastAPI app on port 8080
- `locus-frontend`: a static site built with `npm run build`, publishing `dist/`

They're on different `*.onrender.com` subdomains, so the frontend calls the
backend via an absolute URL (`VITE_API_BASE_URL`, baked in at build time — see
`src/apiBase.js`); the backend's CORS is already open (`allow_origins=["*"]` in
`backend/app/main.py`).

**Storage is ephemeral on the free plan.** Render's free web services have no
persistent disk — every redeploy, and every wake from the 15-minute idle
spin-down, starts from a fresh filesystem. `locus.db`, `backend/chroma/`, and
`backend/uploads/` all reset when that happens; there's currently no
backup/restore in place. That's an acceptable tradeoff for trying the app out,
but means uploaded documents and chat history won't survive a spin-down. If you
want real persistence later, the options are a Render paid plan (persistent
disks), Render's free Postgres for the relational data, or wiring up backup to
some other object store — not something this setup does today.

### One-time setup

1. In the Render dashboard: **New → Blueprint**, connect this GitHub repo. Render
   reads `render.yaml` and creates both services.
2. On the `locus-backend` service, set the env vars marked `sync: false` in
   `render.yaml`: `LLM_PROVIDER`, and whichever provider key it needs
   (`OPENAI_API_KEY` / `GEMINI_API_KEY` / `GROQ_API_KEY`).
3. Once `locus-backend` has a URL, check it matches the `VITE_API_BASE_URL`
   placeholder in `render.yaml` (`https://locus-backend.onrender.com`). If Render
   picked a different subdomain (e.g. the name was taken), update that value and
   redeploy `locus-frontend`.

### Deploy

Render auto-deploys both services on push to the connected branch — no manual
deploy command. Push to `main` (or trigger a manual deploy from the dashboard).

### Verify

```bash
curl https://locus-backend.onrender.com/api/health
```

Expect `{"status":"ok"}` (allow ~1 min if the service was asleep). Then load
`https://locus-frontend.onrender.com` and send a chat message to confirm the
full round trip works.
