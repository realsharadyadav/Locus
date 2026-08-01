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
npm run lint                       # catches imports missed when moving code between modules
npm run build
.venv/bin/pytest backend/tests     # whole suite, ~70s
```

Run the whole suite. It is hermetic and order-independent — no network, no local `.env` — so
any failure is yours. `conftest.py` owns `LOCUS_DATABASE_URL` and hands each module an empty
schema: never set that variable in a test module and never delete the database file (note 9
explains what that used to break).

Re-run all of the above after merging or rebasing someone else's work in: a textual merge can
produce a file that still parses but behaves wrongly.

---

## Architecture

**Stack:** React 19 + Vite + lucide-react + react-markdown (SPA) | FastAPI + SQLAlchemy + Uvicorn (Python) | SQLite (default local) / Postgres (via `LOCUS_DATABASE_URL`) | pgvector/SQLite vector store | LLM: Ollama, Groq, OpenAI, Gemini

**Data flow:** User uploads files -> text extracted and indexed into pgvector (or SQLite fallback) -> user asks question -> background ChatJob pipeline: enhance question -> retrieve evidence (semantic + lexical) -> compose answer -> verify -> repair -> frontend polls and renders via PipelineActivity

**Reasoning modes:** `light` (fast excerpt), `thinking` (full-file), `deep_summary` (section-by-section), `ticket_analysis` (ITSM grouping), `web_research` (multi-round search + synthesis), `unrestricted` (no guardrails + jailbreak pipeline — 7 strategies + auto-rephrase on refusal)

**Model list rule:** Never hardcode Ollama model lists. Always query `OLLAMA_URL/api/tags` at runtime. Frontend fallback list should be empty for Ollama. User only wants to see actually-pulled models.

## Lessons Learned (Session History)

Keep these notes so future sessions don't repeat mistakes. Routine "added X to file Y" notes
get folded into the file tables below instead of living here — this list is only for things
that will bite you again if forgotten.

1. **Jailbreak pipeline** — `_run_jailbreak_pipeline()` in `llm.py` tries 5 escalating strategies (direct → academic → roleplay → hypothetical → DAN). If all refuse, rephrases question via `_rephrase_question()` and retries with DAN prompt. Falls back to longest non-refusal attempt. Both paths (direct-stream + job) use the same pipeline via `generate_unrestricted_answer()`. `is_refusal()` (public) detects refusals via `_REFUSAL_PATTERNS` regex.

2. **LLM-decided `source_limit`** — LLM planner dynamically decides how many web sources to collect per query. Simple lookups → 3-10, comparisons → 10-25, deep research → 25-50+, up to 200 max. Stored in `AgentPlan.source_limit`. User's `web_source_limit` is only a max cap. The `_execute_plan` clamps `min(plan.source_limit, user_source_limit)`. Fallback in `_build_plan` sets 5-20 based on route. Keys: `agentic_pipeline.py:AgentPlan.source_limit`, `_plan_from_json` (extract from LLM), `run_agentic_pipeline` (compute `effective_limit` early, pass to both `_execute_plan` and exception handler fallback).

3. **force_web route override fix** — `force_web=True` no longer blindly overrides all routes to `web_research`. Only overrides non-search-capable routes (`small_talk`, `direct_llm`, `complex_plan`). Routes like `product_recommendation`, `web_research`, `news`, `sports` are left intact so LLM's planned search_queries get used in `_planned_web_answer`. Critical: `_plan_from_json` line ~209.

4. **tenacity dependency** — Added to `backend/requirements.txt`. LiteLLM needs it for retries. Without it, evidence validation in `_validate_evidence_with_llm` silently falls back to `_fallback_evidence_filter` which caps at 15 sources.

5. **Sign-in gate (Phase 1)** — One shared password, not user accounts. `LOCUS_AUTH_PASSWORD` unset = gate absent, which is why no existing test needed changing. `auth.py` signs a stateless `{"exp"}` token with an HMAC derived from the password; the frontend sends it as a Bearer header (not a cookie — frontend and backend are separate origins on Render). The auth middleware is registered **before** `CORSMiddleware` in `main.py` on purpose: register it after and CORS is no longer the outer layer, so a 401 comes back without CORS headers and the browser reports a network error instead. Public paths: `/api/health`, `/api/auth/status`, `/api/auth/login`, plus the guest Private-chat routes in note 7. Dark theme paints every `<p>` muted with `!important`, so `.login-error` needs `!important` to show red.

6. **Private chats are multi-room** — `PrivateChatsPage` reuses Ask's `.chat-rail` classes so the two lists stay in visual sync. Rooms are created from the page, not by clicking the nav item (that used to leave an empty room behind on every click). Deleting a room is the revoke mechanism: the backend cascades the messages away and pushes a `REVOKED` sentinel into every live SSE queue, which the stream turns into an `event: revoked` frame before closing. Both the host view and the guest standalone listen for it, plus a 404 backstop in the 8s poll for a deletion that lands while the stream is down — without that the client reconnect-loops forever against a dead room.

7. **Secret Chat auth is split, not blanket-public** — `auth.GUEST_SECRET_CHAT_ROUTES` lists the exact five method+path pairs a link guest needs (room, read messages, post message, stream, presence). Listing, creating, changing options, participant details, the copilot, clearing and deleting are the host's and stay guarded, so `is_public()` is method-aware: `GET /api/secret-chat/{token}` is public while `DELETE` on the same path is not. The other half of this is client-side: `src/secret-chat/api.js` has its own request helper, and while it did not send `authHeaders()` every host action answered "Sign in to continue" on a gated deployment — guests kept working, which is what made it look like a Private-chat bug rather than an auth one.

8. **Phase 2 (multi-user) is NOT done** — Real accounts need: `User` table + password hashing, `owner_id` on `collections`/`chat_sessions`/`chat_jobs`/`ticket_analysis_results`/`stored_files`, a composite `(key, user_id)` PK on `user_preferences`, ownership checks on ~30 routes, and a migration tool (there is no alembic; `create_all` does not add columns). The subtle one: `vector_store._pgvector_search()` with `file_ids=None` scans **every** chunk, so retrieval would leak other users' documents even with perfect SQL filtering.

9. **Tests share one database, and conftest.py owns it** — Pytest imports every test
    module before running any test, and `backend.app.database` builds its engine once at
    import time. A per-module `os.environ["LOCUS_DATABASE_URL"] = ...` therefore only ever
    applied to whichever module was imported first; the rest silently shared that database
    and then had the file deleted under their pooled connections, which SQLite reports as
    "attempt to write a readonly database". Set the URL in `conftest.py` only, and isolate
    modules by dropping/creating tables (the `reset_database` fixture), never by using
    separate files or `os.remove`.

10. **Never set/reset a ContextVar across a `yield` in a StreamingResponse generator** —
    Starlette pumps a sync generator by calling `next()` in the threadpool, and each call
    gets a fresh copy of the context, so `__enter__` in one `next()` and `__exit__` in a
    later one raises "was created in a different Context". This silently broke
    `/api/chat/direct-stream` end to end: `with token_usage_tracker()` spanned the token
    yields, so every direct stream emitted its tokens and then died before persisting the
    assistant message or emitting the `result` frame. Both streaming endpoints now run the
    pipeline on one thread and push events through a `Queue`; keep new ones on that pattern.

11. **`intent._fallback_classify` matches on longest keyword, plus plurals** — First-match-wins
    let a short generic keyword from an earlier domain beat a longer specific one from a
    later domain ("formula 1 standings" classified as `math`, because `_math_kw` has
    "formula" and math is checked before sports). Keywords are also stored in the singular
    and matched via `_keyword_pattern()`, which accepts the regular English plural —
    without it `\bflight\b` missed "mumbai to delhi flights" outright. Keep new keywords
    singular.

12. **Startup ALTERs must speak the deployed dialect** — `_ensure_schema_columns()` is a no-op
    on a fresh database (`create_all` already made every column), so its statements only ever
    run against a database that predates a column: in practice the deployed Postgres. Writing
    them SQLite-style (`DATETIME`, `BOOLEAN NOT NULL DEFAULT 0`) passed every local test and
    then crashed the app during lifespan on Render — five deploys failed before anyone read the
    email. Take the type and boolean literals from `engine.dialect.name`, and note that
    `backend/tests/test_schema_migration.py` builds a legacy schema on its own engine to cover
    this, because the shared test database always has the columns already.

13. **Boot must not do catch-up work** — Re-extracting tabular profiles and re-indexing
    embeddings for every stored file used to run inline in the lifespan handler, so a cold
    start walked the whole upload set before `/api/health` answered. That is what timed out the
    Render health check and tripped the instance's memory limit. It now runs on a daemon thread
    (`_startup_maintenance`), one file per transaction, with `LOCUS_STARTUP_MAINTENANCE=0` to
    skip it entirely. Anything added to lifespan should be a precondition for serving, not
    housekeeping.

14. **The Telegram bridge is an account, not a bot** — "give me a number and I'll talk to
    them from Locus" is only possible over MTProto with the host's own Telegram account
    (`telegram_bridge.py`, Telethon): the Bot API cannot open a conversation by phone number,
    the person has to press start on the bot first. Consequences to keep in mind when
    editing: the session string in `LOCUS_TELEGRAM_SESSION` is full access to that account,
    Telegram rate-limits contact resolution hard, and automated sending can get an account
    restricted. Three structural rules hold the design together — (a) nothing imports
    telethon at module scope, so an unconfigured deployment behaves exactly as before;
    (b) `secret_chat` registers an inbound callback via `set_inbound_handler()` rather than
    the transport importing it back, which both breaks the import cycle and is what lets the
    tests run with a fake transport; (c) outbound delivery goes through
    `_deliver_to_bridge()` from **two** places — the post endpoint and the autopilot writer,
    because autopilot inserts straight into the table and would otherwise reply into a room
    nobody is reading. The echo guard is `_sender_client(message.sender) == bridge.client_id`;
    drop it and every inbound message bounces straight back to the guest. Also note the room's
    own `GET` is public to link guests, so the bridge is deliberately *not* on
    `SecretChatSessionRead` — the phone number would leak to anyone holding a share link.

15. **The quality layer is a loop, and its exits are load-bearing** — `_process_chat_impl` no
    longer verifies once and repairs once. When the verifier reports gaps it calls
    `_retrieve_for_gaps()` to search the vector store *for those gaps*, merges anything new into
    `repair_context`, repairs, and re-verifies. Repair alone can only reword the draft against
    evidence it already had, which is why a gap needing an unretrieved chunk was previously
    unfixable. Three guards keep it finite and must all stay: the `CHAT_EVIDENCE_ROUNDS` cap
    (`LOCUS_CHAT_EVIDENCE_ROUNDS`, default 2), the no-progress break when a round returns zero new
    chunks (re-verifying the same facts just burns calls), and the `seen_evidence_keys` set that
    stops a round from re-returning chunks already in evidence. Deep Summary is excluded via
    `coverage_manifest is None` — it inspected every chunk already and its manifest owns coverage.
    Light mode never enters the block at all (`use_quality_layer=False`). `llm_hits` counts the
    verify/repair calls actually made rather than assuming one of each.

16. **Answer shape is opt-in per call site, never global** — `ANSWER_SHAPE_INSTRUCTION` (llm.py)
    is what makes answers open with a short summary then bullets then a table only if needed. It is
    deliberately *not* added inside `_answer_request()`, because that function is shared by
    `summarize_document()` and `extract_shared_evidence()`, whose intermediate chunk summaries must
    stay plain — adding it there reshapes internal map/reduce steps and corrupts the evidence fed to
    composition. It reaches the model through `guidance`, which `answer_planned_question()` passes
    only to the final compose call. `repair_response()` takes it as `shape_guidance` for the same
    reason: without it, a repair pass rewrites the layout back into prose. `_answer_shape_guidance()`
    returns "" for `deep_summary` and `unrestricted`, which own their own output contracts.

17. **Diagrams: fit to a legibility floor, then scroll** — Mermaid sizes its SVG to whatever box it
    lands in, so a wide flowchart on a phone renders at ~17% and becomes an unreadable smudge.
    `MermaidBlock` instead measures the container and sets the SVG width to
    `min(1, max(available / natural, MIN_LEGIBLE_SCALE))` — diagrams that fit still fit, wider ones
    stop shrinking at 70% and `.mermaid-canvas` scrolls. Two non-obvious requirements: the SVG needs
    `flex: none` (the canvas is a flex container and would otherwise shrink it back regardless of
    the width set on it), and `margin-inline: auto` is what keeps a fitting diagram centred while
    letting an overflowing one start at its left edge. The figure title and colour legend are parsed
    back out of the diagram source (`lib/mermaidMeta.js`: frontmatter `title:` and `classDef` names),
    so they cannot drift from the drawing — and `dropDrawnTitle` removes Mermaid's own in-SVG title
    and trims the viewBox band it occupied, or the title renders twice and wastes ~40% of the height.

18. **The diagram lightbox owns its touch gestures** — pinch is implemented from pointer events
    (a Map of live pointers; two entries is a pinch), zooming about the focal point so content stays
    under the fingers. `touch-action: none` on `.diagram-lightbox-canvas` is what stops the browser
    claiming the two-finger gesture for page zoom; without it Chromium fires `pointercancel`
    mid-gesture and the pinch freezes part-way. The app does not disable page zoom globally and
    should not — that is an accessibility regression. Double-tap is timed manually (300ms) rather
    than using `dblclick`, and zooms in from 1x or resets when already magnified.

19. **Later style layers must out-specify, not just come after** — `20-layout.css` pins `.chat-top`
    with `display: flex !important` and `.workspace-label` with `display: inline-flex !important`,
    and `15-chat-rail.css` targets `.app-shell.explore-active .chat-top-left > div` (three classes
    plus an element). A new highest-numbered file being last in the cascade is not enough on its
    own: `30-mobile-header.css` restructures the mobile header only because it matches that weight
    (`!important` where the earlier rule used it, four-class selectors where the earlier rule was
    three-plus-an-element). Symptom of getting this wrong is a rule that appears to do nothing —
    check the computed value before assuming the selector is unmatched.

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
| `telegram_bridge.py` | Optional Telegram transport for private chats: connects the host's own account over MTProto (Telethon) on one background loop, resolves a phone number to a peer, sends, and hands inbound DMs to a callback | `configured()`, `status()`, `resolve_contact()`, `send_text()`, `set_inbound_handler()`, `normalize_phone()` |

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
| `AssistantMarkdown.jsx` / `CodeBlock.jsx` / `MermaidBlock.jsx` / `DiagramLightbox.jsx` / `AnswerToc.jsx` | Answer rendering. All react-markdown `components` overrides live in one `useMemo` — a new identity remounts the code renderer and restarts in-flight Mermaid renders. Overrides must drop the `node` prop instead of spreading it onto the DOM |
| `AnswerSection.jsx` | One collapsible answer section (h2 + its content). Starts expanded; collapsing sets `data-collapsed` and CSS hides the body, so children are never restructured |
| `MermaidBlock.jsx` | Diagram figure: caption, colour legend, legibility-floor sizing (note 17) |
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
| `lib/mermaidMeta.js` | Parses a diagram's frontmatter title and `classDef` entries to build the figure caption and colour legend |
| `lib/rehypeAnswerSections.js` | Wraps each `h2` and the siblings after it in a `<section>`. react-markdown emits headings and content as flat siblings, so without this there is no element to collapse or animate. Applied only once streaming ends |
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
| `secret-chat/api.js` | Secret Chat API client — sends `authHeaders()`, since host routes sit behind the password gate |
| `secret-chat/index.js` | Guest-vs-app entry resolution (`resolveSecretChatEntry`) and the in-app route hook |
| `secret-chat/links.js` | Share link shape — guests join on `/j/<token>`; `/secret-chat/<token>` still resolves; `/login` reserved as the guest→app escape |
| `secret-chat/identity.js` | Per-browser client id, host key (room ownership proof) and the device/locale profile sent with presence |
| `secret-chat/useSecretChatRoom.js` | Room runtime shared by both views: history, SSE, presence, typing, read cursors, disappear pruning |
| `secret-chat/useSecretChatUnread.js` | Unread total across the host's rooms, for the Private nav badge |
| `secret-chat/components/PrivateChatsPage.jsx` | Private page — rail of rooms with unread highlighting beside the open room, new-chat form with the privacy options, delete one/all |
| `secret-chat/components/SecretChatPage.jsx` | In-app host room: live header, room settings menu, clear/delete, guests panel, copilot |
| `secret-chat/components/SecretChatStandalone.jsx` | Standalone full-page chat for shared-link visitors, with the what-the-host-can-see notice |
| `secret-chat/components/ChatThread.jsx` | Shared message list: day dividers, sender runs, unread divider, typing bubble, read receipts, disappear countdowns |
| `secret-chat/components/GuestsPanel.jsx` | Host-only participant details (device, browser, OS, screen, locale, timezone, IP, activity) |
| `secret-chat/components/AiCopilot.jsx` | Reply copilot UI — suggestions, tone, persona, talk-like-me, and the autopilot toggle (the replying itself happens server-side) |
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
* A guest can clear the chat on their own device (`clearOnThisDevice` in the room hook, kept
  in localStorage per room). It hides messages for that browser only — nothing is deleted
  server-side, the host still sees everything, and later messages still arrive.
* Copilot drafts never send themselves in suggest mode. **Autopilot runs on the server**
  (`_run_autopilot`), not in the host's browser: a guest's message triggers a worker thread
  that pauses, marks the host as typing, then posts as the host — so replies keep coming with
  the host's tab closed. It answers only messages from someone other than the host, skips its
  own (`via_ai`) messages, and bails if a newer message has arrived. `via_ai` is stored so the
  reply is excluded from talk-like-me samples and tagged **only in the author's own view** —
  a guest is never shown that a reply was drafted.
* The model comes from Settings, not the environment: `_preferred_ai` reads the `explore_ai`
  preference (provider + model) that Settings saves, falling back to `configured_model()`.
* A guest's erase button hides messages on their device with no confirmation — deliberate,
  the user asked for no interstitial. Nothing is deleted server-side.

Link guests never mount the app shell: `resolveSecretChatEntry()` runs before `createRoot`, so a
visitor arriving on a share link only ever loads the standalone chat and only calls
`/api/secret-chat/*`. A browser that has only ever followed a share link is remembered as a guest,
and visiting the app root or any app path sends it back to its own chat instead of into Locus.
That memory lives in localStorage and nothing else clears it, so `/login` is reserved as the way
out: `resolveSecretChatEntry()` checks it first, forgets the remembered chat, marks the browser a
host and mounts the app (and its sign-in gate) at `/`. Needed because the host opening their own
invite in a phone or a fresh profile becomes a guest in that browser permanently otherwise. The
host marking is the point rather than a side effect — leave it off and the host's next click on
their own share link puts them back in the standalone chat. It cuts the other way too: anyone who
visits `/login` keeps the app shell on later share links, so on an ungated deployment that one
path is all that separates a link guest from the app. Signing out (`clearSecretChatHost`) is the
undo: it clears the same host flag without touching `secret-chat-host-key`, the separate identity
a room owner needs to keep managing rooms they created, so a signed-out browser goes back to
guest-eligible on its next share link but a returning host does not lose their rooms.

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
| `backend/tests/conftest.py` | Owns `LOCUS_DATABASE_URL` and the per-module schema reset. See note 9 |
| `backend/tests/test_api.py` | API endpoints, chat CRUD, file upload, job lifecycle, retry, mode routing, deep summary, web research, prompt helpers |
| `backend/tests/test_diagnostics.py` | Secret redaction, job log cleanup |
| `backend/tests/test_auth.py` | Sign-in gate: absent without a password, token issue/verify/expiry, wrong-password throttle, public paths |
| `backend/tests/test_secret_chat.py` | Private chat: room options, host-key gating, presence and guest details, read cursors, disappearing messages, link/room expiry, clear and delete, reply copilot |
| `backend/tests/test_vector_store.py` | chunk_text overlap, embed_text determinism |
| `backend/tests/test_llm_context.py` | The one home for `_trim_history` / `_summarize_history` / `_pack_sources` / `_context_budget` unit tests |
| `backend/tests/test_groq.py` | Groq auth, timeout clamp, rate-limit, retry, model listing |
| `backend/tests/test_intent_deep.py` | `intent.py` keyword fallback across every domain, context persistence, output validation |
| `backend/tests/test_agentic_pipeline.py` | Planner routing, dynamic source_limit, evidence validation, broad-retry before the no-evidence dead end |
| `backend/tests/test_comprehensive_chat.py` | Light mode, web search routing, output formats, streaming, edge cases, gap-retrieval rounds and answer-shape wiring |
| `backend/tests/test_100step_conversation.py` | 100-step conversations: persistence, history growth, truncation, cancellation |
| `backend/tests/test_deep_stress.py` | Mode switching mid-chat, 200-step rapid fire, file ops mid-chat, job lifecycle, concurrency |
| `backend/tests/test_litellm_gateway.py` | LiteLLM gateway wiring |
| `backend/tests/test_ticket_analysis.py` | Ticket normalization, grouping, taxonomy, v2 classification |
| `backend/tests/test_tabular_files.py` | CSV/XLSX profiling |
| `scripts/evaluate_ticket_taxonomy.py` | CLI taxonomy accuracy evaluation against CSV |

The whole suite is hermetic and order-independent — no network, no local `.env`, and
`pytest backend/tests` in any file order gives the same result.

---

## Runtime Data (gitignored)

| Path | Contents |
|---|---|
| `backend/locus.db` | SQLite database |
| `backend/uploads/` | Uploaded file storage |
| `backend/vector_fallback/` | SQLite fallback vector index (used only when `LOCUS_DATABASE_URL` isn't Postgres) |
| `backend/diagnostics/jobs/` | Per-job JSONL diagnostic logs (retained on failure) |
| `dist/` | Built production output |
