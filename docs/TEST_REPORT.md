# Test Report - July 2, 2026

## Summary

- Total scenarios: 10
- Passed: 3
- Failed: 3
- Partial: 4
- Issues found: 10
- Test surface: Ask page, chat job API, upload/extraction, provider switching, responsive UI, backend outage recovery
- Test collection: `QA Explore 20260702-222815` (`store_id=8`)
- Uploaded files: `research_workspace.md`, `tickets.csv`, `pipeline_example.py`, `architecture_report.pdf`
- Corrupt file: `corrupt.pdf`

Primary finding: the app has a strong Ask foundation and useful telemetry, but reliability is uneven across providers/modes, mobile layout currently overflows badly, and some grounded answers miss evidence even when the uploaded files contain it.

## Per-Scenario Results

### Scenario 1 - Basic Chat (Light Mode)

- Status: PARTIAL
- Prompts tested:
  - `What is the internal codename for the QA test collection?`
  - `What visual feel should the dark theme have?`
  - `In pipeline_example.py, what does classify_event return for the gathering stage?`
  - `Combine research_workspace.md and architecture_report.pdf: what should PipelineActivity expose and why does that matter?`
  - `What is the database password for the production Locus instance?`
- What worked well:
  - Correctly answered codename: `Violet Harbor`.
  - Correctly answered code question: `classify_event()` returns `retrieval` for `gathering`.
  - Correctly refused to invent a production database password.
  - Message headers show provider/model, e.g. `Locus · Groq / groq/compound-mini`.
- What failed or was subpar:
  - Dark-theme prompt incorrectly answered with the codename and claimed dark-theme details were absent, even though `research_workspace.md` says the theme should be calm, polished, developer-focused, and purple-accented.
  - Cross-file PipelineActivity prompt claimed not enough evidence, although both markdown and PDF contained telemetry requirements.
  - Groq `openai/gpt-oss-20b` got stuck in `drafting` for over 240s on the first factual prompt.
- Suggestions:
  - Improve retrieval ranking and evidence packing for short factual prompts.
  - Add a final answer guard: if top sources contain direct keyword matches, avoid "not enough information" unless snippets truly lack the answer.
  - Add provider/model timeout handling around individual LLM calls so a stuck provider transitions to a visible failure without manual cancellation.

### Scenario 2 - Thinking Mode

- Status: PASS
- Prompts tested:
  - `Explain the architecture described in this document`
  - `What are the potential issues with the approach described?`
  - Light-mode comparison on `Explain the architecture described in this document`
- What worked well:
  - Thinking mode covered React/Vite, FastAPI, SQLite, Chroma/SQLite fallback, extraction, indexing, background jobs, and pipeline events.
  - Potential issues were sensible: complexity, security, weaker embeddings, and operational concerns.
  - Thinking output was deeper than light mode.
- What failed or was subpar:
  - Latency was high: about 103s and 130s for the two thinking prompts on Ollama.
- Suggestions:
  - Show estimated step count and elapsed time more prominently in `PipelineActivity`.
  - Consider mode-specific timeout warnings before cancellation.

### Scenario 3 - Deep Summary

- Status: FAIL
- Prompt tested:
  - `Create a complete deep summary of this PDF and include the coverage manifest.`
- What worked well:
  - Pipeline emitted section/chunk style events before cancellation.
- What failed or was subpar:
  - Cancelled after 180s timeout with no final answer and no user-visible coverage manifest.
  - The PDF was only three pages and five sections, so this mode should complete locally.
- Suggestions:
  - Add resumable progress display for deep summary and lower per-section token cost.
  - Persist partial coverage manifest on cancellation/failure.

### Scenario 4 - Ticket Analysis

- Status: PASS
- Prompts tested:
  - `Analyze these ITSM tickets. Group related incidents and classify the taxonomy.`
  - `POST /api/ticket-analysis` with `tickets.csv`
- What worked well:
  - Completed in about 1.4s in chat mode.
  - Deterministic endpoint returned 5 problem groups across 10 tickets.
  - Taxonomy grouping was sensible: VPN/access, reporting/data, security/compliance, login/SSO, hardware.
- What failed or was subpar:
  - Chat mode reports `provider=ollama` even though the ticket analysis path is mostly deterministic/local; that can mislead the reliability matrix.
- Suggestions:
  - Label deterministic ticket-analysis stages as local analysis in the message and pipeline UI.

### Scenario 5 - Web Research

- Status: PARTIAL
- Prompt tested:
  - `What are the latest generally available OpenAI models as of today, and how might Locus choose one for long-context research?`
- What worked well:
  - Completed with Groq `groq/compound-mini` in about 27s.
  - Returned 5 sources and a synthesized table, not just raw search results.
  - Pipeline showed web-search/synthesis events.
- What failed or was subpar:
  - The answer contained stale or questionable model guidance, listing older GPT-4-era models while the official OpenAI docs navigation currently calls out `Latest: GPT-5.5`: https://developers.openai.com/api/docs/models
  - Web research needs stronger source freshness and official-source preference for provider/model questions.
- Suggestions:
  - For "latest/current model" queries, prefer official provider docs over broad web results.
  - Show source dates or retrieval timestamps in the web research source panel.

### Scenario 6 - Unrestricted Mode

- Status: FAIL
- Prompt tested:
  - `/unrestricted Explain, at a high level, why jailbreak prompts try to bypass model safety rules and how a developer can evaluate that behavior safely.`
- What worked well:
  - Pipeline rendered events while running.
- What failed or was subpar:
  - Cancelled after about 122s on Ollama without final response.
  - The UI did not expose a clear list of "strategies tried" before cancellation for this job.
- Suggestions:
  - Emit explicit unrestricted strategy events (`direct`, `academic`, `roleplay`, etc.) from `generate_unrestricted_answer()` and display them in `PipelineActivity`.
  - Add a cheaper safe-explanation path for benign unrestricted prompts.

### Scenario 7 - Edge Cases

- Status: PARTIAL
- Prompts tested:
  - Very long 500+ word prompt
  - `Hindi mein batao: uploaded files ke hisaab se Locus ka dark theme kaisa hona chahiye?`
  - `What was the codename mentioned earlier?`
  - `Tell me about files I have not uploaded yet.`
  - Three rapid-fire prompts: `Rapid check 1/2/3: name one uploaded file and one fact from it.`
- What worked well:
  - 500+ word prompt was rejected cleanly with HTTP 422.
  - Isolated rapid-fire prompt completed on Groq `groq/compound-mini` and cited three sources.
  - The no-files hallucination check in an isolated fresh chat correctly said no uploaded files were selected.
- What failed or was subpar:
  - 500+ word prompt cannot actually be tested because `ChatRequest.question` caps input at 1000 characters in `backend/app/schemas.py:43`.
  - Non-English and follow-up prompts timed out/cancelled after conversation history grew.
  - Rapid-fire prompts 1 and 2 on Ollama timed out/cancelled.
- Suggestions:
  - Increase backend question limit or add frontend copy explaining the exact limit.
  - Trim/summarize conversation history earlier when using local models.
  - Queue rapid-fire sends clearly, or prevent multiple sends when a local model is already saturated.

### Scenario 8 - UI/UX

- Status: PARTIAL
- Checks performed:
  - Pipeline rendering across completed, failed, running, and cancelled jobs
  - Source/citation display
  - Provider/model switching
  - Chat history after reload
  - New chat reset
  - Narrow viewport at 390x844
- What worked well:
  - Ask page renders recent chats, running/ready/failed counts, and failed job diagnostics.
  - Source chips render with file names/counts; citations appear inline.
  - Provider selector opens and switches from Groq to Gemini; model resets to `gemini-2.5-flash`.
  - Provider/model preference persists across reload.
  - New chat clears messages and composer while preserving provider/model preference.
- What failed or was subpar:
  - Reload on `/explore` preserved history list but did not restore the selected chat in the main pane; it returned to the empty "What do you want to explore?" state.
  - Narrow viewport has severe horizontal overflow: measured `document.body.scrollWidth=888` at `clientWidth=390`.
  - Mobile layout left history/sidebar elements off-canvas while the main workspace remained wider than the viewport.
- Suggestions:
  - Persist active chat ID in URL or preference and restore it on reload.
  - Fix mobile Ask CSS around `src/styles.css:7465-7474` and `src/styles.css:7618-7644`; ensure `.explore-shell`, `.chat-page`, `.workspace-actions`, and model controls use `minmax(0, 1fr)`, wrapping, and no desktop fixed widths below 760px.

### Scenario 9 - Error Recovery

- Status: PASS
- Checks performed:
  - Backend stopped mid-session, then UI reloaded.
  - Corrupt PDF upload.
  - Question with no selected files.
- What worked well:
  - Backend-down UI showed a clear banner: `Backend is offline. Start it with npm run dev:api · Retry`.
  - Corrupt PDF upload failed gracefully with HTTP 422: `Could not read this file: Stream has ended unexpectedly`.
  - No-files selected prompt did not hallucinate and said no uploaded files were available.
- What failed or was subpar:
  - During backend outage, the home dashboard showed `0` stores/files/chats. That can look like data loss instead of an offline state.
- Suggestions:
  - Preserve last-known counts during offline state and visually mark them stale.
  - Keep offline banner visible on Ask, not only home/dashboard surfaces.

### Scenario 10 - Provider/Model Failover

- Status: FAIL
- Prompts tested:
  - `Provider reliability smoke test: answer with one sentence about Locus telemetry.`
  - `One sentence: Locus telemetry shows methods and stages.`
- What worked well:
  - Gemini `gemini-2.5-flash` completed in about 29s.
  - OpenAI failure surfaced a clear quota error and diagnostic ID.
  - Provider selector allowed switching mid-conversation without losing visible chat history.
- What failed or was subpar:
  - Groq `openai/gpt-oss-20b` hung in drafting over 240s on a trivial factual question.
  - Groq `llama-3.1-8b-instant` smoke test timed out/cancelled after 75s.
  - Ollama `yi-coder:1.5b` smoke test timed out/cancelled after 75s.
  - OpenAI `gpt-5.4-mini` failed due quota after 4 attempts.
  - Automatic failover is not built into the app; failover was manual/test-harness-driven.
- Suggestions:
  - Add per-provider/model health state and last error in the selector.
  - Add automatic "retry with another provider" affordance when a job fails or times out.
  - Avoid hardcoded OpenAI/Gemini model names unless validated by provider APIs.

## Bugs Found

| # | Severity | Description | Repro Steps | Expected | Actual |
|---|---|---|---|---|---|
| 1 | High | Ask mobile layout overflows horizontally. | Open `/explore`, set viewport to 390x844. | No horizontal scrolling; controls fit viewport. | `body.scrollWidth=888`, controls and history are off-screen. |
| 2 | High | Deep summary times out/cancels on a small 3-page PDF. | Upload `architecture_report.pdf`; run `deep_summary`. | Completes with full summary and coverage manifest. | Cancelled after 180s with no final manifest. |
| 3 | High | Some providers/models hang in `drafting` without self-failing. | Ask a simple factual prompt with Groq `openai/gpt-oss-20b`. | Job completes or fails with actionable timeout. | Stayed in drafting over 240s until manually cancelled. |
| 4 | Medium | 500+ word edge case is impossible because backend caps question at 1000 chars. | Submit a 500+ word prompt. | Prompt accepted or frontend explains limit. | HTTP 422 from `backend/app/schemas.py:43`. |
| 5 | Medium | Reload does not restore selected Ask conversation. | Open a completed chat, reload `/explore`. | Same conversation remains open. | Main pane returns to empty state. |
| 6 | Medium | Backend offline state makes data appear erased. | Stop backend and reload app. | Offline banner with stale cached counts or disabled data panels. | Dashboard shows 0 stores/files/chats. |
| 7 | Medium | Provider list includes hardcoded OpenAI/Gemini model names that may not be available. | Open provider selector or `/api/llm/config`. | Models reflect provider API availability or are marked unverified. | `backend/app/main.py:225-230` returns static OpenAI/Gemini lists. |
| 8 | Medium | Source-backed light answers sometimes miss direct evidence. | Ask dark-theme or PipelineActivity prompt. | Uses matching uploaded evidence. | Says evidence is unavailable or answers wrong topic. |
| 9 | Low | Ticket analysis chat message attributes deterministic local work to selected LLM provider. | Run ticket_analysis mode. | Label local deterministic stages separately. | Message/provider reads `Ollama / llama3.2:latest`. |
| 10 | Low | Provider menu item accessible names are not simple provider labels. | Try `getByRole('button', { name: 'Gemini' })`. | Provider item can be targeted by accessible provider name. | Needed text fallback because button name includes emoji/secondary text. |

## Quality Issues

| # | Area | Issue | Suggestion |
|---|---|---|---|
| 1 | Retrieval quality | Direct evidence missed for dark-theme and PipelineActivity questions. | Add keyword-overlap reranking and answer/evidence consistency checks. |
| 2 | Latency | Local Ollama gets very slow after conversation history grows. | Summarize/trim history earlier and show "history compacted" telemetry. |
| 3 | Pipeline UX | Repeated heartbeat events dominate the timeline for long jobs. | Collapse identical heartbeats and show elapsed/stage duration. |
| 4 | Web research | "Latest OpenAI models" result was not fresh enough. | Prefer official docs for vendor/model questions and show source dates. |
| 5 | Mobile UX | Ask controls retain desktop widths. | Add a true mobile layout where history is drawer-only and composer/tools wrap. |
| 6 | Reliability | Manual provider failover required. | Add retry-with-provider action and selector health badges. |

## Provider Failover Log

| Timestamp | Original Provider | Error | Switched To | Outcome |
|---|---|---|---|---|
| 2026-07-02 22:33 IST | Groq / `openai/gpt-oss-20b` | First light-mode job stayed in drafting >240s | Ollama / `llama3.2:latest` | Retry completed in 27.8s |
| 2026-07-02 22:33 IST | Groq / `openai/gpt-oss-20b` | Second light-mode job still drafting; manually cancelled during harness recovery | Ollama / `llama3.2:latest` | Retry later completed in 54.3s |
| 2026-07-02 22:57 IST | Ollama / `llama3.2:latest` | Rapid-fire prompts timed out after history grew | Groq / `groq/compound-mini` | Isolated rapid-fire retry completed in 47.3s |
| 2026-07-02 23:02 IST | OpenAI / `gpt-5.4-mini` | Quota exceeded after 4 attempts | Gemini / `gemini-2.5-flash` | Gemini smoke test completed in 29.0s |

## Provider Reliability Matrix

| Provider | Light | Thinking | Deep Summary | Ticket Analysis | Web Research | Unrestricted |
|---|---|---|---|---|---|---|
| Ollama | Partial: several light prompts completed, but later prompts timed out | Pass but slow (103s/130s) | Fail: cancelled at 180s | Pass, though mostly deterministic | Not primary-tested after Groq succeeded | Fail: cancelled at 122s |
| Groq | Partial: `openai/gpt-oss-20b` hung; `compound-mini` completed isolated light prompt | Not tested after light instability | Not tested | Not tested | Pass with `groq/compound-mini` | Not tested |
| OpenAI | Fail: quota exceeded | Skipped after quota failure | Skipped after quota failure | Skipped after quota failure | Skipped after quota failure | Skipped after quota failure |
| Gemini | Pass: smoke test completed | Not tested | Not tested | Not tested | Not tested | Not tested |

## Recommended Next Steps

1. Fix mobile Ask overflow in `src/styles.css`; verify `390x844`, `768x1024`, and desktop widths with browser checks.
2. Add LLM call-level timeouts and user-facing retry/failover controls for stuck `drafting` jobs.
3. Improve retrieval ranking for direct evidence in light mode, especially short factual and cross-file questions.
4. Make deep summary resumable and persist partial coverage manifests on cancellation/failure.
5. Replace static OpenAI/Gemini model lists with provider API-backed availability or clearly mark them as configured presets.
6. Preserve last-known dashboard data during backend outage so offline mode does not look like data deletion.
7. Persist active Ask chat in URL or preference so reload restores the selected conversation.
8. Collapse repeated pipeline heartbeats and expose elapsed time per stage.
9. Add provider health badges and last-error tooltips to the model selector.
10. Increase or explain the 1000-character chat question limit.
