# Locus Brand Guide

## Identity

- **Product name:** Locus
- **Assistant name:** Locus AI
- **Tagline:** Your knowledge, one question away.
- **Positioning:** Local developer research workspace — upload files, ask questions, inspect the pipeline.

## Navigation

| Route id | Label |
|---|---|
| `home` | Home |
| `hub` | Library |
| `explore` | Ask |
| `ticket-analysis` | Patterns |
| `secret-chat` | Private |

## Voice

- Calm, precise, developer-focused
- Prefer operational clarity over marketing fluff
- Show method, evidence, and pipeline telemetry where useful

## Visual

- Dark mode: GitHub-like surfaces with restrained purple accents
- Logo mark: concentric focal rings (place / locus)
- Key file: `src/styles.css`

## Terminology

| Use | Avoid |
|---|---|
| Library | Knowledge hub |
| Ask | Explore (user-facing) |
| Patterns | TicketInsight |
| Private | Secret chat |
| Locus AI | MindMap AI |

Internal route ids (`explore`, `hub`, `ticket-analysis`) stay stable for URLs and API compatibility.

## Storage migration

Legacy `mindmap-*` localStorage and sessionStorage keys are read once and copied to `locus-*` keys on first access.

Legacy database path `backend/mindmap.db` is used automatically when `backend/locus.db` does not exist yet.

Legacy Chroma collection `mindmap_chunks` is used when `locus_chunks` is empty but legacy data exists.
