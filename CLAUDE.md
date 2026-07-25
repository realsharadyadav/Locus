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

## Notes

- Frontend uses Vite.
- Backend uses FastAPI via Uvicorn.
- Vite proxies `/api` to `http://127.0.0.1:8000`.
- If the user says the backend is offline, start `npm run dev:api`.
- Avoid spending extra time checking ports unless something fails or the user asks for debugging.
- For broader project context, read `AGENTS.md` first, then the focused files in `docs/`.
