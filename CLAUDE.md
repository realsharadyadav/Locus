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

- **Commit straight to `main` and push.** The user does not want a feature branch or a pull
  request per change, and does not want to be asked each session. Work on `main` directly
  unless they say otherwise for a specific piece of work. (A session prompt may still name a
  branch; if it does, use that branch and merge it to `main` when the work is done.)
- Start every change from `origin/main`, not from whatever the working tree happens to be on
  (`git checkout main && git pull --ff-only`, or `git checkout -B <branch> origin/main` when a
  branch is called for — keep any unmerged commits by rebasing them on).
- Already mid-change when new commits land upstream? Merge or rebase `origin/main` in *before*
  continuing, rather than at push time.
- If a push is rejected as non-fast-forward, do not force. Fetch, integrate, re-verify, push.
- Re-run the Verification commands in `AGENTS.md` after integrating anyone else's overlapping
  work, not just after your own edits.

## Notes

- Sign-in is off locally: the password gate only exists when `LOCUS_AUTH_PASSWORD` is set. See the Sign-in Gate section in `docs/RUNBOOK.md`.
- For broader project context, read `AGENTS.md` first, then the focused files in `docs/`.
