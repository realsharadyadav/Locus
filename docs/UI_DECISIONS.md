# Locus UI Decisions

## Dark Mode

The user disliked bright white controls in dark mode. Keep dark mode calm and developer-focused.

Current direction:

- Base: GitHub-like dark surfaces.
- Accent: purple.
- Avoid bright white active controls.
- Active segmented controls, selected file checkboxes, send buttons, and pipeline active states should use purple accents.
- Text should be readable but not harsh white.

Key file:

- `src/styles.css`

## Pipeline

The pipeline should feel engaging because this is a developer research app.

Keep:

- Live developer trace.
- Current call panel.
- Sending/receiving previews.
- Runtime console.
- Telemetry chips.
- Animated scan/progress/live rows.

Avoid:

- Generic spinner-only loading states.
- Hiding all useful internals.
- Showing secrets, raw provider headers, raw prompts, or API keys.

Key frontend component:

- `PipelineActivity` in `src/main.jsx`

Key backend event enrichment:

- `_pipeline_event_metadata` in `backend/app/main.py`

## Focus Mode

Ask has side panels:

- Left: chat history.
- Right: file/evidence scope.

The user wanted show and hide controls to focus. Keep the panel toggles visible in the header and make sure there is always a way back from focus mode.

Current controls:

- Hide/show chats.
- Hide/show files.
- Focus: hides both side panels.

## Layout Notes

- This is not a marketing site; it is a dense research/workspace UI.
- Prefer compact controls and operational clarity over large decorative sections.
- Cards are acceptable for repeated items and tool panels, but avoid unnecessary card nesting.
