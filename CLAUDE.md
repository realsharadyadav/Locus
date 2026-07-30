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

## Git — always start from the latest main

Other sessions push to this repo, so treat the local view of `main` as stale until proven
otherwise. Before writing any code:

```bash
git fetch origin main
git log --oneline origin/main -5      # what landed since last time
```

- Start every change from `origin/main`, not from whatever the working tree happens to be on:
  `git checkout -B <branch> origin/main` (keep any unmerged commits by rebasing them on).
- Already mid-change when new commits land upstream? Merge or rebase `origin/main` in *before*
  continuing, rather than at push time.
- If a push is rejected as non-fast-forward, do not force. Fetch, integrate, re-verify, push.
- Re-run the checks below after integrating anyone else's overlapping work: a textual merge
  can leave code that builds a broken result silently.

## Checks

```bash
npm run build                                  # frontend
npm run lint                                   # eslint src
.venv/bin/python -m pytest backend/tests/<file>.py -q
```

`backend/tests` has pre-existing failures when files run together (each module points the
app at its own SQLite file and deletes it in teardown). Run the files your change touches,
and compare against the same run on `origin/main` before calling a failure yours.

## Notes

- Sign-in is off locally: the password gate only exists when `LOCUS_AUTH_PASSWORD` is set. See the Sign-in Gate section in `docs/RUNBOOK.md`.
- For broader project context, read `AGENTS.md` first, then the focused files in `docs/`.
