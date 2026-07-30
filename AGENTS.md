# Agent Memory for Locus

This file is the first stop for any coding agent working in this repo. It exists so future sessions do not rediscover the app from scratch.

## User Preference

- The user likes direct action and short Hinglish updates.
- When asked to run the app, start it directly. Do not spend extra time checking ports unless a command fails.
- The user cares a lot about the visual feel. Dark mode should be calm, polished, developer-focused, and purple-accented.
- The app is a research workspace for developers, so pipeline/progress UI should expose useful method, request, response, event, and telemetry details.

## Quick Run

```bash
npm run dev:api          # backend on :8000
npm run dev -- --host 127.0.0.1 --port 5173   # frontend on :5173
```

- Frontend: `http://127.0.0.1:5173/`
- Backend: `http://127.0.0.1:8000`
- Health: `http://127.0.0.1:8000/api/health`

## Verification

```bash
npm run lint     # catches imports missed when moving code between modules
npm run build
.venv/bin/pytest backend/tests/test_api.py backend/tests/test_diagnostics.py backend/tests/test_auth.py
```

Broader tests when touching file parsing, vector search, tickets, or LLM behavior — name the
files your change touches:

```bash
.venv/bin/pytest backend/tests/test_vector_store.py backend/tests/test_tabular_files.py
```

`pytest backend/tests` (the whole directory at once) reports far more failures than any one
file does alone, and always has: each module sets `LOCUS_DATABASE_URL` to its own SQLite file
at import time and deletes that file in `teardown_module`, so whichever module runs first wins
the engine and later ones write to a deleted database. Run the files you touched, and compare
against the same command on `origin/main` before treating a failure as yours.

Re-run all of the above after merging or rebasing someone else's work in: a textual merge can
produce a file that still parses but behaves wrongly.

---

## Architecture

**Stack:** React 19 + Vite + lucide-react + react-markdown (SPA) | FastAPI + SQLAlchemy + Uvicorn (Python) | SQLite (default local) / Postgres (via `LOCUS_DATABASE_URL`) | pgvector/SQLite vector store | LLM: Ollama, Groq, OpenAI, Gemini

**Data flow:** User uploads files -> text extracted and indexed into pgvector (or SQLite fallback) -> user asks question -> background ChatJob pipeline: enhance question -> retrieve evidence (semantic + lexical) -> compose answer -> verify -> repair -> frontend polls and renders via PipelineActivity

**Reasoning modes:** `light` (fast excerpt), `thinking` (full-file), `deep_summary` (section-by-section), `ticket_analysis` (ITSM grouping), `web_research` (multi-round search + synthesis), `unrestricted` (no guardrails + jailbreak pipeline — 7 strategies + auto-rephrase on refusal)

**Model list rule:** Never hardcode Ollama model lists. Always query `OLLAMA_URL/api/tags` at runtime. Frontend fallback list should be empty for Ollama. User only wants to see actually-pulled models.

## Lessons Learned (Session History)

Keep these notes so future sessions don't repeat mistakes:

1. **Ollama model list** — `main.py:llm_config()` used to have a hardcoded list. Now queries `OLLAMA_URL/api/tags` at runtime. Frontend `fallbackModels.ollama` is empty `[]`. Only pulled models appear.

2. **`/unrestricted` mode** — Added to `MODE_CONFIG` in `modes.py`, added to `ChatRequest.reasoning_mode` Literal in `schemas.py`. Pipeline in `main.py` calls `generate_unrestricted_answer()` instead of going through standard pipeline.

3. **Jailbreak pipeline** — `_run_jailbreak_pipeline()` in `llm.py` tries 5 escalating strategies (direct → academic → roleplay → hypothetical → DAN). If all refuse, rephrases question via `_rephrase_question()` and retries with DAN prompt. Falls back to longest non-refusal attempt. Both paths (direct-stream + job) use the same pipeline via `generate_unrestricted_answer()`. `is_refusal()` (public) detects refusals via `_REFUSAL_PATTERNS` regex.

4. ~~**Auto-select dolphin-llama3** — Removed. `/unrestricted` no longer auto-selects model. User picks manually.~~

5. **Mode persistence** — `newChat()` no longer resets `reasoningMode`. Mode stays until user explicitly changes it.

6. **Frontend unrestricted** — Added `Zap` icon to lucide imports, `/unrestricted` to `SLASH_COMMANDS`, mode label mapping, pipeline stage handling (treated as direct chat), CSS class `.mode-unrestricted` (red tint).

7. **Provider stored in ChatMessage** — `ChatMessage` model now has a `provider` column (VARCHAR(20)). `ChatJob` also has `provider`. Displayed in frontend as `Provider / model` in every message head and pipeline console. Auto-migration via `_ensure_schema_columns()` on startup.

8. **PROVIDER_LABELS constant** — Shared at top of `main.jsx` (not inside `ModelControl`), used by message head and pipeline activity. Map: `{ ollama: 'Ollama', groq: 'Groq', openai: 'OpenAI', gemini: 'Gemini' }`.

9. **LLM-decided `source_limit`** — LLM planner dynamically decides how many web sources to collect per query. Simple lookups → 3-10, comparisons → 10-25, deep research → 25-50+, up to 200 max. Stored in `AgentPlan.source_limit`. User's `web_source_limit` is only a max cap. The `_execute_plan` clamps `min(plan.source_limit, user_source_limit)`. Fallback in `_build_plan` sets 5-20 based on route. Keys: `agentic_pipeline.py:AgentPlan.source_limit`, `_plan_from_json` (extract from LLM), `run_agentic_pipeline` (compute `effective_limit` early, pass to both `_execute_plan` and exception handler fallback).

10. **force_web route override fix** — `force_web=True` no longer blindly overrides all routes to `web_research`. Only overrides non-search-capable routes (`small_talk`, `direct_llm`, `complex_plan`). Routes like `product_recommendation`, `web_research`, `news`, `sports` are left intact so LLM's planned search_queries get used in `_planned_web_answer`. Critical: `_plan_from_json` line ~209.

11. **tenacity dependency** — Added to `backend/requirements.txt`. LiteLLM needs it for retries. Without it, evidence validation in `_validate_evidence_with_llm` silently falls back to `_fallback_evidence_filter` which caps at 15 sources.

12. **Sign-in gate (Phase 1)** — One shared password, not user accounts. `LOCUS_AUTH_PASSWORD` unset = gate absent, which is why no existing test needed changing. `auth.py` signs a stateless `{"exp"}` token with an HMAC derived from the password; the frontend sends it as a Bearer header (not a cookie — frontend and backend are separate origins on Render). The auth middleware is registered **before** `CORSMiddleware` in `main.py` on purpose: register it after and CORS is no longer the outer layer, so a 401 comes back without CORS headers and the browser reports a network error instead. Public paths: `/api/health`, `/api/auth/status`, `/api/auth/login`, plus the guest Private-chat routes in note 14. Dark theme paints every `<p>` muted with `!important`, so `.login-error` needs `!important` to show red.

13. **Private chats are multi-room** — `PrivateChatsPage` reuses Ask's `.chat-rail` classes so the two lists stay in visual sync. Rooms are created from the page, not by clicking the nav item (that used to leave an empty room behind on every click). Deleting a room is the revoke mechanism: the backend cascades the messages away and pushes a `REVOKED` sentinel into every live SSE queue, which the stream turns into an `event: revoked` frame before closing. Both the host view and the guest standalone listen for it, plus a 404 backstop in the 8s poll for a deletion that lands while the stream is down — without that the client reconnect-loops forever against a dead room.

14. **Secret Chat auth is split, not blanket-public** — `auth.GUEST_SECRET_CHAT_ROUTES` lists the exact four method+path pairs a link guest needs. Listing, creating, renaming and deleting rooms are the host's and stay guarded, so `is_public()` is method-aware: `GET /api/secret-chat/{token}` is public while `DELETE` on the same path is not.

15. **Phase 2 (multi-user) is NOT done** — Real accounts need: `User` table + password hashing, `owner_id` on `collections`/`chat_sessions`/`chat_jobs`/`ticket_analysis_results`/`stored_files`, a composite `(key, user_id)` PK on `user_preferences`, ownership checks on ~30 routes, and a migration tool (there is no alembic; `create_all` does not add columns). The subtle one: `vector_store._pgvector_search()` with `file_ids=None` scans **every** chunk, so retrieval would leak other users' documents even with perfect SQL filtering.

---

## Backend Files — `backend/app/`

### Core Pipeline

| File | Purpose | Key Functions |
|---|---|---|
| `main.py` (1469 lines) | FastAPI app, all REST endpoints, chat job orchestration, background threads, file upload, streaming, pipeline telemetry | `_process_chat_impl()` (line 361-610) — main chat pipeline; `_run_chat_job()` — background worker; `_pipeline_event_metadata()` — telemetry; `create_chat_job()` (line 916) — job creation endpoint |
| `agentic_pipeline.py` (865 lines) | LLM planner, agentic pipeline with dynamic source_limit, planned web answer, evidence validation, fallback paths | `run_agentic_pipeline()` — main entry; `_plan_with_llm()` — LLM planner with JSON schema; `_plan_from_json()` — extract source_limit/route/entities; `_execute_plan()` — dispatch with `effective_limit=min(plan.source_limit, user_source_limit)`; `_planned_web_answer()` — use LLM queries + dynamic source_limit; `_web_fallback()` — broad fallback; `_validate_evidence_with_llm()` — LLM evidence filter |
| `llm.py` (682 lines) | All LLM provider clients, chat/answer/verify/repair pipelines, question planning, evidence extraction, unrestricted/jailbreak pipeline | `enhance_question()` (line 373) — query planner; `generate_answer()` (line 482) — main answer gen; `verify_response()` (line 449) — quality check; `repair_response()` (line 466) — answer repair; `answer_planned_question()` (line ~590) — full pipeline; `generate_unrestricted_answer()` — jailbreak pipeline with 7 strategies + auto-rephrase; `clean_final_answer()` (line 398) — post-processing; `get_llm_client()` — provider factory |
| `modes.py` | Reasoning mode configs: light, thinking, deep_summary, ticket_analysis, web_research, unrestricted | `MODE_CONFIG` dict, `ModeConfig` dataclass |
| `auth.py` | Phase 1 sign-in gate: one shared password, stateless HMAC tokens, brute-force throttle. Off unless `LOCUS_AUTH_PASSWORD` is set | `require_auth()` — middleware, registered before CORS; `issue_token()`, `token_expiry()`, `is_public_path()`, `PUBLIC_PATHS` |

### File Processing

| File | Purpose | Key Functions |
|---|---|---|
| `files.py` | Text extraction from PDF, DOCX, XLSX, CSV, TXT, MD, JSON, HTML, code; deterministic tabular profiling | `extract_text_from_path()` — universal extractor; `relevant_excerpt()` — scoring + excerpt; `_spreadsheet_profile()` — group/numeric/text/time analysis; `_profile_table()` — column stats |

### Retrieval & Search

| File | Purpose | Key Functions |
|---|---|---|
| `vector_store.py` | Semantic retrieval: fastembed/hash-based embeddings, pgvector on Postgres (primary) or SQLite cosine fallback, chunking, indexing | `embed_text()` — embeddings; `chunk_text()` — overlap-aware chunking; `index_file()` / `index_files()` — index chunks; `search()` — semantic search; `SemanticHit` dataclass |
| `web_research.py` (230 lines) | Multi-round web search (DDG), LLM query planning, follow-up queries, source synthesis | `web_research()` (line 168) — main entry; `_search_web()` — DDG; `_generate_initial_queries()` — planner; `_generate_followup_queries()` — expansion; `_synthesize_answer()` — LLM synthesis with conversation history |

### Deep Summary

| File | Purpose | Key Functions |
|---|---|---|
| `deep_summary.py` | Section-by-section full-document summary with coverage manifests | `deep_summarize_documents()` — main pipeline; `chunk_document()` — splits into sections; `CoverageManifest` — tracks completeness; `missing_sections()` — deterministic gap detection |

### Ticket Analysis

| File | Purpose | Key Functions |
|---|---|---|
| `ticket_analysis.py` | Ticket normalization, cleaning, hierarchical grouping, semantic clustering, taxonomy classification, markdown report | `analyze_ticket_file()` — main entry; `normalize_ticket()` — field extraction; `clean_tickets()` — dedup + normalization; `ticket_analysis_markdown()` — report gen |
| `ticket_taxonomy.py` | ITSM taxonomy engine: v2 rule-based scoring with overrides, record type detection, confidence | `classify_ticket_v2()` — main classifier; `find_taxonomy_match()` — rule matching; `normalize_signal()` — text normalization |
| `ticket_taxonomy_data.py` | All taxonomy rules: 9 legacy + 25 v2 rules covering ITSM domain | `DEFAULT_TAXONOMY_V2` — rule list; `TaxonomyRuleV2` dataclass |

### Data Layer

| File | Purpose | Key Functions |
|---|---|---|
| `models.py` | SQLAlchemy ORM models for all tables | `Collection`, `StoredFile`, `ChatSession`, `ChatMessage`, `ChatJob`, `UserPreference`, `SecretChatSession`, `SecretChatMessage` |
| `schemas.py` | Pydantic request/response schemas for REST API | `ChatRequest`, `ChatResponse`, `ChatSource`, `ChatJobRead`, `ChatMessageRead`, `StoredFileRead`, `TicketAnalysisRequest` |
| `database.py` | SQLAlchemy engine, session factory, DB dependency | `engine`, `SessionLocal`, `get_db()` |

### Config & Utilities

| File | Purpose | Key Functions |
|---|---|---|
| `config.py` | Loads `.env`, exposes all env-based config | `llm_provider()`, `configured_model()`, `GroqSettings`, `groq_settings()`, `TICKET_ANALYSIS_*`, `SEMANTIC_*`, `WEB_RESEARCH_*` |
| `diagnostics.py` | Per-job diagnostic event logging to JSONL with secret sanitization | `diagnostic_event()` — log event; `initialize_job_log()` — create log file; `sanitize()` — redact secrets |
| `seed.py` | Seeds database with three default collections on first launch | `seed_database()` |
| `secret_chat.py` | Real-time SSE private chat rooms: host-owned rooms, presence, disappearing messages, expiring links, reply copilot | APIRouter with `create_secret_chat()`, `list_secret_chats()`, `update_secret_chat()`, `delete_secret_chat()`, `clear_secret_chat_messages()`, `update_secret_chat_presence()`, `assist_secret_chat()`, `stream_secret_chat()` |

---

## Frontend Files — `src/`

### Core

| File | Purpose | Key Components |
|---|---|---|
| `main.jsx` | Entry point only — mounts `<App />` and imports the stylesheet | — |
| `App.jsx` | Root component: app shell, page routing, global state, boot load, toasts, confirm dialogs, sign-in gating | `App` |
| `auth.js` | Client half of the password gate: token storage, `Authorization` header, 401 handoff | `authHeaders()`, `handleUnauthorized()`, `onUnauthorized()`, `setAuthToken()` |
| `api.js` | Frontend API client wrapping all REST endpoints | `api.createChatJob()`, `api.chatJobs()`, `api.chatStream()`, `api.chats()`, `api.chatMessages()`, `api.uploadFile()`, `api.collections()`, `api.preference()` |
| `utils.js` | Shared UI utilities | `displayTime()`, `STORE_COLORS`, `buildSuggestions()`, `resizeTextarea()` |
| `styles.css` | Ordered `@import` list only — the real CSS lives in `src/styles/` | — |

### Pages — `src/pages/`

| File | Purpose |
|---|---|
| `HomePage.jsx` | Landing dashboard |
| `HubPage.jsx` | Library / collections |
| `ExplorePage.jsx` | Ask — chat, composer, slash commands, reasoning modes |
| `SettingsPage.jsx` | Settings |
| `TicketAnalysisPage.jsx` | Patterns — ticket grouping cockpit |

### Components — `src/components/`

| File | Purpose |
|---|---|
| `Sidebar.jsx` / `Header.jsx` / `Logo.jsx` | App shell chrome |
| `SplashScreen.jsx` | Boot screen with real load progress |
| `ModelControl.jsx` | Provider + model picker |
| `PipelineActivity.jsx` / `DirectStreamTrace.jsx` | Live pipeline and stream telemetry |
| `AssistantMarkdown.jsx` / `CodeBlock.jsx` / `MermaidBlock.jsx` / `DiagramLightbox.jsx` / `AnswerToc.jsx` | Answer rendering |
| `CollapsibleSources.jsx` | Source/evidence display |
| `CreateStoreModal.jsx` / `ConfirmModal.jsx` | Modals |
| `CommandPalette.jsx` | Global Cmd+K search: pages, stores, files, chats |
| `Toast.jsx` | Auto-dismissing toast notification stack |

### Helpers — `src/lib/` and `src/hooks/`

| File | Purpose |
|---|---|
| `lib/format.js` | File size, elapsed time, context length, embedding meta, job failure text |
| `lib/appState.js` | Storage keys, page ids, provider defaults, cached app data |
| `lib/pipelineNotes.js` | Turns pipeline events into human-readable working notes |
| `lib/mermaid.js` / `lib/highlight.js` | Lazy-loaded diagram and syntax-highlighting integration |
| `lib/ask.js` | Slash commands and auto web-search heuristics |
| `hooks/useChatViewport.js` | Mobile keyboard / viewport locking for chat surfaces |
| `hooks/useClickOutside.js` | Shared popover dismissal (outside click + Escape) |

### Styles — `src/styles/`

25+ numbered files imported in order by `src/styles.css`. **The numbering is
load-bearing:** these are chronological override layers (later layers
deliberately re-style earlier ones), not independent component sheets. Do not
reorder them, and add new overrides as a new highest-numbered file.

### Secret Chat

| File | Purpose |
|---|---|
| `secret-chat/api.js` | Secret Chat API client |
| `secret-chat/index.js` | Guest-vs-app entry resolution (`resolveSecretChatEntry`) and the in-app route hook |
| `secret-chat/links.js` | Share link shape — guests join on `/j/<token>`; `/secret-chat/<token>` still resolves |
| `secret-chat/identity.js` | Per-browser client id, host key (room ownership proof) and the device/locale profile sent with presence |
| `secret-chat/useSecretChatRoom.js` | Room runtime shared by both views: history, SSE, presence, typing, read cursors, disappear pruning |
| `secret-chat/useSecretChatUnread.js` | Unread total across the host's rooms, for the Private nav badge |
| `secret-chat/components/PrivateChatsPage.jsx` | Private page — rail of rooms with unread highlighting beside the open room, new-chat form with the privacy options, delete one/all |
| `secret-chat/components/SecretChatPage.jsx` | In-app host room: live header, room settings menu, clear/delete, guests panel, copilot |
| `secret-chat/components/SecretChatStandalone.jsx` | Standalone full-page chat for shared-link visitors, with the what-the-host-can-see notice |
| `secret-chat/components/ChatThread.jsx` | Shared message list: day dividers, sender runs, unread divider, typing bubble, read receipts, disappear countdowns |
| `secret-chat/components/GuestsPanel.jsx` | Host-only participant details (device, browser, OS, screen, locale, timezone, IP, activity) |
| `secret-chat/components/AiCopilot.jsx` | Reply copilot — suggestions, autopilot, tone, persona, talk-like-me |
| `secret-chat/components/ShareMenu.jsx` | Share popover — copy link, WhatsApp, Telegram, SMS, email, X, native share sheet |
| `secret-chat/messageGroups.js` | Day dividers and sender-run grouping for both chat views |
| `secret-chat/styles.css` | All Secret Chat styles |

Private chat rules worth knowing before changing this feature:

* The creating browser holds a `host_key`; the room list, settings, clear/delete, participant
  details and the AI copilot are all authorised against it, so a link guest can chat but can
  never manage the room or see anyone's device details. A room with no owner — created before
  host keys existed, or by a client that sends none — falls back to the app's own auth gate
  (`auth.GUEST_SECRET_CHAT_ROUTES`), and the first host key to manage it claims it. Guests
  additionally reach only five routes through that gate: read room, read/post messages,
  stream, and presence.
* `link_expires_at` only stops *new* clients joining — anyone already known keeps chatting.
  `expires_at` ends the room for everybody, and the data is deleted on first touch after that.
* Disappearing messages are enforced server-side and broadcast as a `purge` event, so every
  open client drops the same messages at the same moment; the client also hides them locally
  on a one-second tick so the countdown looks live.
* Unread state is a server-side read cursor per participant, pushed on presence heartbeats.
  The in-room "New messages" divider is frozen at open time so it does not vanish as you read.
* Copilot drafts never send themselves in suggest mode. Autopilot only answers messages that
  arrive after it is switched on, and every AI-sent message is stored with `via_ai` so it is
  labelled in the thread and excluded from talk-like-me style samples.

Link guests never mount the app shell: `resolveSecretChatEntry()` runs before `createRoot`, so a
visitor arriving on a share link only ever loads the standalone chat and only calls
`/api/secret-chat/*`. A browser that has only ever followed a share link is remembered as a guest,
and visiting the app root or any app path sends it back to its own chat instead of into Locus.

---

## Config Files — Root

| File | Purpose |
|---|---|
| `package.json` | NPM deps: vite, react, lucide-react, react-markdown, remark-gfm |
| `vite.config.js` | Vite config: proxy `/api` to backend, historyApiFallback |
| `index.html` | SPA HTML shell |
| `pytest.ini` | Pytest: pythonpath, testpaths |
| `.env.example` | Template env: LLM_PROVIDER, Ollama, Groq, OpenAI, Gemini, semantic, ticket settings |
| `backend/requirements.txt` | Python deps: fastapi, uvicorn, sqlalchemy, pydantic, httpx, pypdf, python-docx, openpyxl, psycopg2-binary, pgvector, ddgs, litellm, tenacity |

---

## Docs

| File | Contents |
|---|---|
| `docs/ARCHITECTURE.md` | App structure, data flow, retrieval strategy, chat job internals |
| `docs/FEATURES.md` | User-facing features: library, ask, reasoning modes, pipeline, diagnostics |
| `docs/RUNBOOK.md` | Startup, troubleshooting, test commands, env config, local data paths |
| `docs/UI_DECISIONS.md` | Dark mode philosophy, pipeline UX, focus mode, layout notes |

---

## Tests

| File | Covers |
|---|---|
| `backend/tests/test_api.py` (881 lines) | API endpoints, chat CRUD, file upload, job lifecycle, retry, mode routing, deep summary, web research, prompt helpers |
| `backend/tests/test_diagnostics.py` | Secret redaction, job log cleanup |
| `backend/tests/test_auth.py` | Sign-in gate: absent without a password, token issue/verify/expiry, wrong-password throttle, public paths |
| `backend/tests/test_secret_chat.py` | Private chat: room options, host-key gating, presence and guest details, read cursors, disappearing messages, link/room expiry, clear and delete, reply copilot |
| `backend/tests/test_vector_store.py` | chunk_text overlap, embed_text determinism |
| `backend/tests/test_groq.py` | Groq auth, rate-limit, retry, model listing |
| `backend/tests/test_ticket_analysis.py` | Ticket normalization, grouping, taxonomy, v2 classification |
| `backend/tests/test_tabular_files.py` | CSV/XLSX profiling |
| `scripts/evaluate_ticket_taxonomy.py` | CLI taxonomy accuracy evaluation against CSV |

---

## Runtime Data (gitignored)

| Path | Contents |
|---|---|
| `backend/locus.db` | SQLite database |
| `backend/uploads/` | Uploaded file storage |
| `backend/vector_fallback/` | SQLite fallback vector index (used only when `LOCUS_DATABASE_URL` isn't Postgres) |
| `backend/diagnostics/jobs/` | Per-job JSONL diagnostic logs (retained on failure) |
| `dist/` | Built production output |
