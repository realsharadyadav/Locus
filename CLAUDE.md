# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

Read `AGENTS.md` next — it's the detailed file-by-file map (backend + frontend tables,
session history / lessons learned) and is kept current. This file covers commands,
big-picture architecture, and the conventions that don't fit a table.

## Commands

Run both services directly when asked to run the app — don't spend time checking ports first:

```bash
npm run dev:api                                # backend on :8000 (uvicorn --reload)
npm run dev -- --host 127.0.0.1 --port 5173    # frontend on :5173 (vite)
```

- Frontend: `http://127.0.0.1:5173/`
- Backend: `http://127.0.0.1:8000`
- Health check: `http://127.0.0.1:8000/api/health`

Verification, in this order, after any change:

```bash
npm run lint                         # eslint src — catches imports missed when moving code
npm run build                        # vite build
.venv/bin/pytest backend/tests       # whole suite, ~70s, hermetic
```

Single test file / single test:

```bash
.venv/bin/pytest backend/tests/test_api.py
.venv/bin/pytest backend/tests/test_api.py::test_name -v
```

The suite is hermetic and order-independent — no network, no local `.env`. `conftest.py` owns
`LOCUS_DATABASE_URL` and resets the schema per module; never set that env var inside a test
module and never delete the database file (see AGENTS.md note 16). Any failure is yours to fix.
Re-run lint + build + pytest after merging/rebasing someone else's work — a textual merge can
produce a file that still parses but behaves wrongly.

Setup (first time):

```bash
npm install
python3 -m venv .venv && .venv/bin/pip install -r backend/requirements.txt
cp .env.example .env
```

## Architecture

**Stack:** React 19 + Vite SPA (`src/`) · FastAPI + SQLAlchemy backend (`backend/app/`) ·
SQLite by default locally, Postgres + pgvector when `LOCUS_DATABASE_URL` is set · local
embeddings (fastembed, hash fallback) · pluggable LLM providers: Ollama, Groq, OpenAI, Gemini.

**Data flow:** upload files -> text extracted (`files.py`) and indexed into pgvector or the
SQLite fallback (`vector_store.py`) -> user asks a question in Ask -> backend creates a
`ChatJob` and runs it on a background thread -> pipeline: enhance question -> retrieve evidence
(semantic + lexical) -> compose answer -> verify -> repair -> frontend polls `/api/chat/jobs`
and `PipelineActivity` renders stage/telemetry live -> answer persisted as a `ChatMessage`.

**Reasoning modes** (`backend/app/modes.py`, `MODE_CONFIG`): `light` (fast excerpt),
`thinking` (full-file), `deep_summary` (section-by-section with coverage manifests),
`ticket_analysis` (ITSM grouping via `ticket_taxonomy.py`), `web_research` (multi-round
DDG search + synthesis), `unrestricted` (no guardrails — 7-strategy jailbreak pipeline with
auto-rephrase-on-refusal in `llm.py`).

**Core backend pipeline files** — `main.py` (REST endpoints, job orchestration),
`agentic_pipeline.py` (LLM planner, dynamic per-query `source_limit`, evidence validation),
`llm.py` (provider clients, enhance/generate/verify/repair, unrestricted pipeline). See
AGENTS.md's "Backend Files" table for the full file-by-file breakdown before editing any of
these — the pipeline has several load-bearing behaviors (context budgeting, streaming,
schema migration dialect-awareness) documented there as numbered lessons.

**Frontend:** `App.jsx` is the shell/router; pages live in `src/pages/` (Home, Hub/Library,
Explore/Ask, Settings, TicketAnalysis); `src/api.js` wraps the REST client; `src/lib/` and
`src/hooks/` hold cross-page helpers. `src/secret-chat/` is a self-contained module for
Private Chats (host/guest rooms, SSE, presence, optional Telegram bridge) — see AGENTS.md's
"Private chat rules" before touching it, the auth/ownership model is not obvious from the code
alone.

**Styles:** `src/styles/` is 25+ numbered files imported in order by `src/styles.css`. The
numbering is load-bearing — later files are chronological override layers on earlier ones, not
independent per-component sheets. Never reorder existing files; add new overrides as a new
highest-numbered file.

**Model selection rule:** Settings owns the one provider/model default (saved as the
`explore_ai` preference, resolved server-side by `backend/app/ai_defaults.py`). No other page
picks a model — Ask, Ticket Analysis and Private Chats just show it.

**Model list rule:** never hardcode an Ollama model list. Always query `OLLAMA_URL/api/tags` at
runtime; the frontend's Ollama fallback list must stay empty so only actually-pulled models show.

## Docs map

- `AGENTS.md` — the primary architecture/file reference; read it before non-trivial backend or
  Private Chat changes.
- `docs/ARCHITECTURE.md` — shorter system-design overview.
- `docs/FEATURES.md` — user-facing feature list.
- `docs/RUNBOOK.md` — env vars, Sign-in Gate, Telegram bridge setup, local Postgres, Render deploy.
- `docs/UI_DECISIONS.md` — dark mode / pipeline UX rationale.

## Notes

- Sign-in is off locally: the password gate only exists when `LOCUS_AUTH_PASSWORD` is set. See
  the Sign-in Gate section in `docs/RUNBOOK.md`.
- Runtime data is gitignored and holds real local state — don't delete casually:
  `backend/locus.db`, `backend/uploads/`, `backend/vector_fallback/`, `backend/diagnostics/jobs/`.

## Git

Other sessions push here, so start every change from the latest `origin/main`
(`git fetch origin main`, then `git checkout main && git pull --ff-only`).
