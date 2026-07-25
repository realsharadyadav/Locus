# Locus

Your knowledge, one question away.

Local-first research workspace: upload files, ask questions, inspect the retrieval pipeline. React + FastAPI, with local semantic search and pluggable LLM providers (Ollama, Groq, OpenAI, Gemini).

## Quick start

```bash
npm run dev:api
npm run dev -- --host 127.0.0.1 --port 5173
```

- Frontend: `http://127.0.0.1:5173/`
- Backend: `http://127.0.0.1:8000`
- Health check: `http://127.0.0.1:8000/api/health`

See [AGENTS.md](AGENTS.md) for architecture details and [docs/](docs/) for feature and design notes.