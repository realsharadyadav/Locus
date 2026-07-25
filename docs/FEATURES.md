# Locus Current Features

## Library

- Create stores and collections.
- Upload documents and data files.
- Supported uploads include PDF, DOCX, XLSX, XLSM, CSV, TSV, TXT, MD, JSON, HTML, CSS, JS, JSX, and Python.
- Delete files.
- Delete stores and their files.

## Ask

- Ask questions across uploaded knowledge.
- Select all files, no files, or specific files as evidence scope.
- Reopen previous chats.
- Delete one chat or all chats.
- Copy assistant answers.
- Jump from answer sources back to stores.

## Reasoning Modes

- `Light`: fast answer from relevant excerpts.
- `Thinking`: inspect selected content more deeply.
- `Deep Summary`: section-by-section, full-document style summary.
- `Ticket Analysis`: group incidents and tickets by problem pattern.

## Model Controls

Providers:

- Ollama
- Groq
- OpenAI
- Gemini

The UI supports provider selection, model presets, and custom model IDs.

## Pipeline / Developer Trace

The answer pipeline shows:

- Current method and call.
- Sending and receiving previews.
- Runtime console feed.
- Event telemetry counters.
- Model/provider/mode/file scope metadata.
- Animated stage progress.

This app is used like a developer research tool, so pipeline transparency is valuable.

## UI Productivity

- Dark mode with a calm, purple-accented developer theme.
- Left chat panel hide and show controls.
- Right file panel hide and show controls.
- Focus mode hides both side panels.
- Command palette and global search.
- Responsive mobile layout.
- Backend offline banner with retry.

## Diagnostics

- Background job diagnostics are written under `backend/diagnostics/jobs/`.
- Diagnostics are sanitized by `backend/app/diagnostics.py`.
- Do not expose secrets or raw prompt/provider headers in user-visible UI.
