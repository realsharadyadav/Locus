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

- `LOCUS_DATABASE_URL`: unset uses local SQLite (`backend/locus.db`); set to a Postgres URL to
  use Postgres + pgvector for both relational data and semantic search
- `LLM_PROVIDER`: `ollama`, `groq`, `openai`, or `gemini`
- `OLLAMA_URL`, `OLLAMA_MODEL`
- `GROQ_API_KEY`, `GROQ_MODEL`
- `OPENAI_API_KEY`
- `GEMINI_API_KEY`
- `SEMANTIC_RETRIEVAL_ENABLED`
- `VECTOR_FALLBACK_PATH`
- `TICKET_ANALYSIS_ENABLED`
- `LOCUS_AUTH_PASSWORD`: unset (the default) leaves the API open, which is what local dev wants;
  set it to put the whole app behind a password

## Sign-in Gate

Locus can sit behind one shared password. It is a deployment lock, not user accounts: everyone
who signs in shares the same libraries, files and chats.

```bash
LOCUS_AUTH_PASSWORD='something long' npm run dev:api
```

- Unset `LOCUS_AUTH_PASSWORD` and the gate disappears entirely — no login screen, no headers,
  which is why the test suite needs no special handling.
- `LOCUS_AUTH_SESSION_DAYS` (default 30) sets how long a browser stays signed in.
- `LOCUS_AUTH_SECRET` is optional. Left unset, the signing key derives from the password, so
  changing the password signs everyone out.
- `LOCUS_ALLOWED_ORIGINS` should list the frontend origin on a real deployment (comma
  separated). It defaults to `*`, fine for local dev.
- Public regardless of the gate: `/api/health`, `/api/auth/status`, `/api/auth/login`, and the
  five Private-chat routes a link guest needs (read the room, read/post messages, stream, and
  presence so the room can show them online, typing and up to date). Listing, creating,
  changing options, participant details, the copilot, clearing and deleting stay guarded — see
  `GUEST_SECRET_CHAT_ROUTES` in `backend/app/auth.py`.
- Every guarded call has to carry the token. `src/secret-chat/api.js` has its own request
  helper, and when it did not send `authHeaders()` every host action in Private answered
  "Sign in to continue" on a gated deployment while guests carried on working.
- Signing out is client-side only (Settings → Session). The backend keeps no session state, so
  a stolen token stays valid until it expires; rotate `LOCUS_AUTH_PASSWORD` to kill it early.
- Can't reach the login screen at all, and every URL bounces to a Private chat? That browser is
  remembered as a link guest. Open `/login` — it forgets the remembered chat and loads the app
  with the gate. Opening a share link afterwards still puts that browser back in guest mode.

To lock the Render deployment, set `LOCUS_AUTH_PASSWORD` on `locus-backend` and
`LOCUS_ALLOWED_ORIGINS` to the frontend URL. Both are declared in `render.yaml` with
`sync: false`, so the key names are in the repo but the values are not — Render keeps those in
the dashboard.

Render has no separate "secrets" screen for this: environment variables *are* the secret
store. Dashboard → the `locus-backend` service → **Environment** in the left nav → **Add
Environment Variable**. ("Secret Files" on the same page is for mounting whole files and is not
what this needs.) Note that `sync: false` values are only prompted for during the *initial*
Blueprint creation — on an existing service the dashboard is the only place to set them, and
Render will not overwrite them on a later Blueprint sync.

## Running Postgres Locally (optional, for pgvector parity with prod)

Local dev works with zero setup (defaults to SQLite). To run against Postgres + pgvector
locally, matching what Render runs:

```bash
docker run -d \
  --name locus-postgres \
  -e POSTGRES_USER=locus \
  -e POSTGRES_PASSWORD=locus \
  -e POSTGRES_DB=locus \
  -p 5432:5432 \
  pgvector/pgvector:pg16
```

Then in `.env`:

```
LOCUS_DATABASE_URL=postgresql://locus:locus@127.0.0.1:5432/locus
```

The backend creates the `vector` extension, tables, and indexes automatically on startup
(`ensure_vector_schema()` in `vector_store.py`) — the `pgvector/pgvector` image's default
`postgres` superuser role can do this, so no manual `psql` step is needed locally. On Render,
the managed Postgres role is also permitted to create supported extensions like `pgvector`.

## Common Local Data

- Database: `backend/locus.db` (SQLite, only if `LOCUS_DATABASE_URL` is unset)
- Uploaded files: `backend/uploads/`
- Vector fallback data (SQLite, only used without Postgres): `backend/vector_fallback`
- Job diagnostics: `backend/diagnostics/jobs/`

Do not delete these casually. They contain user data and local state.

## Deploy to Render (free tier)

Locus deploys as three free Render resources, defined in `render.yaml`
(a Render "Blueprint"):

- `locus-db`: a free Render Postgres instance (with the `pgvector` extension) for
  relational data and semantic-search embeddings
- `locus-backend`: a Docker web service built from the root `Dockerfile`,
  running the FastAPI app on port 8080, with `LOCUS_DATABASE_URL` wired to
  `locus-db` via the Blueprint's `fromDatabase` linking
- `locus-frontend`: a static site built with `npm run build`, publishing `dist/`

They're on different `*.onrender.com` subdomains, so the frontend calls the
backend via an absolute URL (`VITE_API_BASE_URL`, baked in at build time — see
`src/apiBase.js`); the backend's CORS defaults to open and narrows to whatever
`LOCUS_ALLOWED_ORIGINS` lists (`backend/app/main.py`).

**`locus-backend`'s own filesystem is still ephemeral** — every redeploy and
15-minute idle spin-down wipes `backend/uploads/` (uploaded file bytes; a
separate concern from the extracted text and embeddings, which live in
Postgres). **`locus-db` (the database) persists across those**, but only for
30 days on Render's free Postgres plan, plus a 14-day grace period to upgrade
before it's deleted — see Render's free Postgres policy. Free accounts are
limited to one free Postgres at a time.

### One-time setup

1. In the Render dashboard: **New → Blueprint**, connect this GitHub repo. Render
   reads `render.yaml` and creates all three resources.
2. On the `locus-backend` service, set the env vars marked `sync: false` in
   `render.yaml`: `LLM_PROVIDER`, and whichever provider key it needs
   (`OPENAI_API_KEY` / `GEMINI_API_KEY` / `GROQ_API_KEY`). `LOCUS_DATABASE_URL`
   is wired automatically — no manual connection string needed.
3. Once `locus-backend` has a URL, check it matches the `VITE_API_BASE_URL`
   placeholder in `render.yaml` (`https://locus-backend.onrender.com`). If Render
   picked a different subdomain (e.g. the name was taken), update that value and
   redeploy `locus-frontend`.
4. **When editing `render.yaml` on an already-deployed Blueprint** (e.g. this
   migration, which adds `locus-db`): pushing alone doesn't create new
   resources. Open the Blueprint in the Render dashboard and approve the sync —
   it shows a diff and asks for confirmation before creating `locus-db`.

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
