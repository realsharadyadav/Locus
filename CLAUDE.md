# Locus Project Memory

## Quick Run

Start both services directly when the user asks to run the app:

```bash
npm run dev:api
npm run dev -- --host 127.0.0.1 --port 5173
```

URLs:

- Frontend: `http://127.0.0.1:5173/`
- Backend: `http://127.0.0.1:8000`
- Health check: `http://127.0.0.1:8000/api/health`

## Git

Other sessions push here, so start every change from the latest `origin/main`
(`git fetch origin main`, then `git checkout main && git pull --ff-only`).

- **Commit straight to `main` and push.** No feature branch, no pull request, don't ask.
  If a session prompt names a branch, use that branch instead.
- Never force-push. If a push is rejected, fetch, integrate, re-verify, push.

## Notes

- Sign-in is off locally: the password gate only exists when `LOCUS_AUTH_PASSWORD` is set. See the Sign-in Gate section in `docs/RUNBOOK.md`.
- For broader project context, read `AGENTS.md` first, then the focused files in `docs/`.
