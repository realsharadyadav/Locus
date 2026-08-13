# Locus — What It Is and What It Does

A research workspace for developers: upload documents, ask questions across them with a
visible pipeline, group ticket data by problem pattern, and run private real-time chats that
can reach people on Telegram. Single-workspace app (no user accounts yet), deployed on
Render's free tier.

**Stack:** React 19 + Vite (SPA) · FastAPI + SQLAlchemy + Uvicorn · SQLite locally /
Postgres + pgvector on Render · LLMs via Ollama, Groq, OpenAI, Gemini.

---

## Deployment

Publicly deployed on Render (free tier), declared in `render.yaml`:

- **Backend:** `https://locus-backend-ewwe.onrender.com` (`locus-backend`, Docker, health
  check `/api/health`)
- **Frontend:** static site `locus-frontend` (`npm run build` → `dist`, SPA rewrite to
  `index.html`), pointed at the backend via `VITE_API_BASE_URL`
- **Database:** `locus-db`, managed Postgres, wired in as `LOCUS_DATABASE_URL`

Free tier means the instance sleeps — the first request after idle takes 30–60s. Secrets
(`LLM_PROVIDER`, API keys, `LOCUS_AUTH_PASSWORD`, `LOCUS_TELEGRAM_*`) are declared with
`sync: false`, so key names live in the repo and values only in the Render dashboard.

Locally everything runs on SQLite with zero setup. See `docs/RUNBOOK.md`.

---

## Library (Hub)

- Collections ("stores") for grouping uploads.
- Upload PDF, DOCX, XLSX/XLSM, CSV/TSV, TXT, MD, JSON, HTML, and code files (JS, JSX, CSS,
  Python).
- Text extraction plus deterministic profiling of tabular files (column stats, group/numeric/
  text/time analysis).
- Semantic indexing per file with visible status (pending / indexed / failed, backend, model,
  chunk count).
- Delete files, or a collection and everything in it.

## Ask (Explore)

- Ask across all uploaded knowledge, or scope evidence to specific files.
- Background job pipeline: enhance question → retrieve evidence (semantic + lexical) →
  compose → verify → repair.
- Streaming direct chat for conversational turns.
- Chat history: reopen, delete one, delete all. Copy any answer. Jump from a source back to
  its file.
- Answers render markdown, code blocks, Mermaid diagrams (with lightbox), and a table of
  contents for long answers.
- Follow-up question suggestions.

### Reasoning modes

| Mode | What it does |
|---|---|
| `light` | Fast answer from the most relevant excerpts |
| `thinking` | Full-file inspection, deeper reasoning |
| `deep_summary` | Section-by-section summary with a coverage manifest and deterministic gap detection |
| `ticket_analysis` | ITSM-style grouping of incidents and tickets |
| `web_research` | Multi-round web search (DDG) with LLM-planned queries and synthesis |
| `unrestricted` | No guardrails: 7 escalating strategies plus auto-rephrase on refusal |

In web research the LLM decides how many sources to gather per query (3–200); the user's
setting is only a cap.

## Patterns (Ticket Analysis)

- Upload a ticket export and group it by problem pattern.
- Rule-based ITSM taxonomy (25 v2 rules + 9 legacy) with confidence scoring and record-type
  detection, plus semantic clustering.
- Selectable embedding method (tfidf / neural hash / hybrid) and clustering strategy
  (taxonomy+semantic, agglomerative, kmeans, hdbscan-lite, kwikbucks).
- Markdown report export, taxonomy rule editing, saved analysis history.

## Private Chats (Secret Chat)

Real-time one-to-one and small-group rooms, separate from the document workspace.

- Multi-room: a rail of rooms with unread counts from a server-side read cursor.
- Live over SSE: messages, presence (who is online), typing indicators, read receipts.
- **Disappearing messages** — server-enforced TTL (1 min to 24 h), purged for everyone at the
  same moment.
- **Expiring invite links** — stops admitting new people without kicking out those already in.
- **Room expiry** — the whole room and its data delete themselves.
- Deleting a room is the revoke mechanism: messages go, and live guests are cut off
  immediately with a "chat ended" frame rather than a reconnect loop.
- Host vs guest split: the creating browser holds a host key; guests can chat but cannot
  manage the room or see anyone's device details.
- Guest view is a sandboxed standalone page — no app shell, no library access.
- Host-only guest panel: IP, browser, OS, device, language, timezone, local time, screen and
  viewport per participant.
- **AI copilot** — drafts three reply options in a chosen tone, optionally mimicking the
  host's own writing style from their past messages.
- **Autopilot** — the server answers on the host's behalf with human-like pacing (a pause
  before noticing, a typing indicator, time proportional to reply length), so it works with
  the browser closed.
- **Held for review** — during that typing pause the host (and only the host) sees exactly
  what autopilot is about to send, typing itself out with a countdown, and can **Stop** it
  before it lands or **Send now** to skip the wait. Leave it alone and it sends itself.

### Telegram bridge

- Connect a room to a **phone number** instead of a share link. The guest gets a normal
  Telegram DM from the host's own account and replies land back in the room; they install
  nothing and sign in nowhere.
- Runs on the host's own account over MTProto (Telethon), not a bot — the Bot API cannot
  open a conversation by phone number.
- Per room and opt-in: one room ↔ one number. Unbridged rooms keep the ordinary share-link
  flow, unchanged.
- The bridged guest appears as a normal participant, so presence, unread counts and autopilot
  work over Telegram with no special case.
- Hidden entirely unless `LOCUS_TELEGRAM_API_ID`, `_API_HASH` and `_SESSION` are set.

## Model Controls

- Providers: Ollama, Groq, OpenAI, Gemini — switchable per conversation.
- Ollama models are always queried live from `OLLAMA_URL/api/tags`; nothing is hardcoded, so
  only actually-pulled models appear.
- Provider and model are stored per message and shown in every message head.
- Settings: default provider, default model (or a custom model ID), default reasoning mode,
  upload size limit.
- Settings model table: search, free-only filter, sortable parameters/context/price columns, and
  a per-model Show checkbox that controls which models appear elsewhere in the app.
- Model connectivity test: **Test N models** pings every model currently listed for the provider
  with a one-word prompt and marks each row as responded (with latency) or failed (with the
  provider's error). A listed model is not always a usable one — keys can be gated, out of
  quota, or pointed at a retired model, and only a real round-trip shows that.
- **Responded only** filters the table down to the models that answered; **Select all
  respondents** enables exactly those, and **Clear all selection** empties the provider's
  selection first so the two compose into "keep only what works".

## Pipeline / Developer Trace

Built for a developer audience, so the machinery is visible rather than hidden:

- Current method and call, with request/response previews.
- Live console feed and event telemetry counters (LLM hits, web queries, token usage).
- Model / provider / mode / file-scope metadata per run.
- Animated stage progress.

## Access and UI

- **Sign-in gate** — one shared workspace password (`LOCUS_AUTH_PASSWORD`), stateless HMAC
  tokens. Unset means no gate at all, which is what local dev uses.
- Dark mode built to be calm, polished and purple-accented.
- Collapsible chat and file panels, focus mode, command palette with global search.
- Responsive mobile layout with a collapsible menu.
- Splash screen showing real load progress; backend-offline banner with retry.

## Diagnostics

- Background job diagnostics are written under `backend/diagnostics/jobs/`.
- Diagnostics are sanitized by `backend/app/diagnostics.py`.
- Do not expose secrets or raw prompt/provider headers in user-visible UI.

---

## Known gaps and constraints

Worth knowing before planning new work:

1. **No real multi-user (Phase 2 not done).** One shared password, one shared workspace. Real
   accounts need a `User` table, `owner_id` on collections/chats/jobs/files, ownership checks
   on ~30 routes, and a migration tool (there is no Alembic). The subtle one:
   `vector_store._pgvector_search()` with `file_ids=None` scans every chunk, so retrieval
   would leak other users' documents even with perfect SQL filtering.
2. **The Telegram bridge is an account, not a bot.** The session string is full access to that
   account; Telegram rate-limits contact resolution and can restrict accounts for automated
   sending. Do not run one session string from two places at once (local *and* Render) — it
   can be invalidated, and both instances would answer the same inbound message.
3. **Disappearing messages only clear Locus.** Anything delivered to Telegram lives on the
   guest's phone; the room TTL cannot reach it.
4. **Only text is bridged.** Photos, voice notes and files from Telegram are ignored, and
   group chats are deliberately not routed.
5. **Free-tier Render sleeps.** Cold start is 30–60s, and boot deliberately does no catch-up
   work so the health check cannot time out.
6. **WhatsApp is not supported.** It is possible via the Meta Cloud API, but the first contact
   has to be a pre-approved template message, with a 24 h free-form window only after they
   reply — plus business verification and a dedicated number.
