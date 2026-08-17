# Locus iOS — Phase-wise Plan

> **Status: IN PROGRESS — Phase 0 started.** Every phase is a separate, shippable
> increment. Review after each phase, then the next one starts.

Native iOS app for Locus — same backend (`:8000`), same features, Claude-iOS-style floating
glass controls, Locus's purple-dark visual identity. Reference screenshots of the current
mobile web app live in `ios/reference/mobile-web/`.

**Language rule: every user-facing string in the app and every doc in `ios/` is English
only.**

---

## 1. Decisions (confirmed at kickoff)

| # | Question | Decision | Alternative (not taken) |
|---|---|---|---|
| D1 | **Tech stack** | **SwiftUI, native** (iOS 17+ baseline) | React Native/Expo, Capacitor wrap |
| D2 | **Navigation** | **Floating glass dock** — 5 tabs (Home · Ask · Library · Private · Secret) + floating gear button for Settings | 6-tab dock; hamburger drawer only |
| D3 | **Liquid Glass** | iOS 26: real `.glassEffect()` capsules; iOS 17–25: `.ultraThinMaterial` fallback — same layout | iOS 26-only |
| D4 | **Mermaid diagrams** | Phase 3: `WKWebView` + mermaid.js wrapper (same renderer as web, guaranteed parity) | Skip diagrams; third-party Swift renderer |
| D5 | **Server** | Configurable server URL in the app (default local, Render URL for deployed). **No backend changes** | Local-only build |

**Why SwiftUI (D1):** look & feel is the #1 priority. Only native gives real scroll physics,
haptics, context menus, sheets, SF Symbols, iOS 26 Liquid Glass and 120Hz animations. The
backend already exposes full REST + streaming — the app is a pure client.

---

## 2. North-star UX (Claude iOS patterns, Locus identity)

From the Claude mobile app:
- **Floating composer** at the bottom — text field + `+` button + send in one rounded glass card. (The Locus mobile web app already has this — rebuilt natively.)
- **`+` button** opens one menu/sheet: attachments, effort, toggles — one place, no clutter.
- **Floating capsule controls** — iOS 26 Liquid Glass guidance: controls float over content at the bottom edge instead of reserving a strip. Status capsule leading, action cluster trailing.
- **Calm & minimal** — one job per screen, generous spacing, no heavy chrome.
- **Top-center pill** — Claude shows a model selector; Locus shows a context pill (chat title / workspace label).

Locus's own identity (carried over from web):
- Deep dark canvas with **purple radial glows**, frosted glass cards, purple gradient primary buttons, pill chips, floating circular header buttons.
- SF Pro — the iOS system font, free parity.

---

## 3. Design system (coded as `LocusTheme` in Phase 0)

Exact tokens from the web CSS (`src/styles/34-glass.css`, `13-theme-dark.css`):

```
CANVAS (dark, 165° linear):  #05070C → #0A0D14 → #070910
GLOWS (radial, behind everything):
  top-left     rgba(139, 92, 246, .28)   (violet)
  top-right    rgba( 88,166, 255, .12)   (blue)
  bottom-right rgba(124, 58, 237, .16)   (deep purple)
  mid-left     rgba(167,139, 250, .08)   (soft violet)
GLASS FILL:   rgba(22,27,34,.48)  strong: .72  soft: rgba(13,17,23,.36)
GLASS EDGE:   rgba(255,255,255,.14)  soft: .08
GLASS BLUR:   28px saturate 180%  → iOS: .ultraThinMaterial / glassEffect
ACCENT:       #745CFF   primary gradient #7C6CFF → #6D28D9
ACCENT SOFT:  rgba(139,116,246,.18) (chip fills)
SUCCESS:      #3FB950 / #7EE787   DANGER: #F85149
TEXT:         #C9D1D9  heading #DCE4EE  muted #8B949E
CORNER RADII: cards 18–20, chips 999 (capsule), buttons 12–14
```

Reusable SwiftUI components (Phase 0): `GlassCard`, `GlassCircleButton`,
`FloatingDock`, `PillChip`, `GradientPrimaryButton`, `GlowBackground`,
`SegmentedPills` (as in Private room options), `FloatingComposer`.

Motion/haptics spec: tab switch = soft spring (0.35s), composer focus = gentle rise +
light impact haptic, send = medium impact, destructive = warning haptic, no haptics on
streaming tokens.

---

## 4. App architecture

```
LocusApp (SwiftUI)
├── LocusTheme/          ← design system (colors, materials, components)
├── Networking/
│   ├── APIClient        ← async/await, Bearer token, /api/* (pure REST)
│   ├── StreamClient     ← URLSession.bytes → NDJSON lines (/api/chat/stream,
│   │                      /api/chat/direct-stream) and SSE (secret-chat stream)
│   └── KeychainStore    ← auth token + server URL
├── Features/
│   ├── Home/  Ask/  Library/  Private/  Secret/  Settings/
└── AppShell             ← floating dock + floating gear + glow background
```

- **Auth:** same as web — `POST /api/auth/login` → Bearer token → Keychain. 401 returns to
  the login screen. `GET /api/auth/status` tells whether the gate is on at all.
- **Server URL:** editable in Settings. Simulator = `http://127.0.0.1:8000`, device =
  the Mac's LAN IP, prod = Render URL. ATS exception for local http in dev builds.
- **No backend changes.** The whole surface already exists (endpoints listed per phase).
- **State:** SwiftUI + Observation (`@Observable` view models), actors for networking.

---

## 5. Feature inventory (nothing gets missed)

| Destination | Web route | Features coming to iOS |
|---|---|---|
| **Home** | `/` | Hero card, live capability cards (effort modes, providers/models count, health, auto-fallback, web research, private chats), stats (libraries/files/chats), quick actions |
| **Ask** | `/ask` | Chat list drawer, new chat, composer (effort Normal/High/Max, add files, upload, model chip, slash commands), chat jobs + cancel, NDJSON streaming, pipeline telemetry, markdown + sources, mermaid, suggestions, stop, truncate-from-message, delete chats |
| **Private** | `/secret-chat` | Rooms list + unread, create room (disappearing messages, link expiry, room auto-delete), live room chat (SSE), presence/typing/read receipts, share link sheet, guests panel, copilot, autopilot draft review, clear/delete, Telegram bridge status |
| **Secret** | `/secret-images` | Photo vault: grid, upload (compressed server-side), full-screen viewer, delete, auth-gated |
| **Library** | `/library` | Collections grid, create/delete library, file list, upload (document picker + photos), delete file, indexing status |
| **Settings** | `/settings` | Default model picker (grouped by provider, health tags), auto-select toggle + last-switch note, custom model ID, providers & models visibility, model health test, theme, server URL, sign out |

---

## 6. Phases (in the requested order: Home → Ask → Private → Secret → Library → Settings)

### Phase 0 — Foundation & Design System
**Goal:** the app runs, sign-in works, five empty screens behind a floating dock.

- Xcode project `ios/Locus/` (SwiftUI, iOS 17+), app icon placeholder, launch screen with glow.
- `LocusTheme` module: all tokens + reusable components (§3).
- `APIClient` + `KeychainStore` + server-URL config; auth gate flow (login screen like the web's calm purple login).
- `AppShell`: `GlowBackground` + floating glass dock (5 tabs) + floating settings gear (top-right glass circle).
- iOS 26 `glassEffect` with iOS 17–25 material fallback behind one API.
- **Acceptance:** sign in → 5 tabs switch smoothly; glow + glass dock on every screen; token survives relaunch.
- **APIs:** `/api/auth/status`, `/api/auth/login`, `/api/auth/me`, `/api/health`.

### Phase 1 — Home
**Goal:** full parity with web Home, native feel.

- Hero card ("Your second brain") with logo + gradient.
- Live capability grid: effort modes (Normal/High/Max), providers·models count, health ("23/684 responding"), auto-fallback, web research, private chats — all live data, tapping jumps to the related destination.
- Stats row (Libraries / Files / Chats) + quick actions (New library, Upload, Ask).
- Pull-to-refresh; skeleton glass cards while loading.
- **Acceptance:** every web Home data point live on iOS; cards navigate correctly.
- **APIs:** `/api/collections`, `/api/files`, `/api/chats`, `/api/llm/config`,
  `/api/preferences/{key}` (`explore_ai`, `model_health`, `auto_select_model`).

### Phase 2 — Ask (core chat)
**Goal:** the full question→answer loop, job-based, with pipeline telemetry.

- Chat list: leading-edge drawer (like web `.chat-rail`) — opens on swipe, New chat, delete, delete-all.
- Chat screen: messages, markdown answers (headers, tables, code blocks + copy), collapsible sources, answer sections.
- **Floating composer** (centerpiece): chips row (effort dial Normal/High/Max, model chip) + `+` menu (Add files / Upload — Claude style) + growing text field + send.
- Slash commands (`/normal`, `/high`, `/max`, `/web`…) — from the web's `SLASH_COMMANDS`.
- Job flow: `POST /chat/jobs` → poll `GET /chat/jobs` → result; cancel; **PipelineActivity card** — live steps + method/request/response telemetry (the developer-focused progress requirement).
- File picker sheet: libraries → files, multi-select chips.
- **Acceptance:** Normal/High/Max all work end-to-end; pipeline card updates live; sources render; cancel works.
- **APIs:** `/api/chat/jobs*`, `/api/chats*`, `/api/files`, `/api/chat/suggestions`.

### Phase 3 — Ask (streaming + polish)
**Goal:** Claude-like live feel — token streaming + advanced rendering.

- NDJSON streaming via `URLSession.bytes`: `/api/chat/direct-stream` + `/api/chat/stream`; a `DirectStreamTrace` equivalent.
- Mermaid: `WKWebView` wrapper (lazy mermaid.js like web), legibility-floor sizing + lightbox (pinch/pan — native port of web notes 17/18).
- Follow-up suggestion chips; stop mid-stream; truncate-from-message (long-press → "delete from here").
- **Acceptance:** smooth streaming (60fps scroll), crisp mermaid + lightbox gestures, instant cancel.
- **APIs:** `/api/chat/stream`, `/api/chat/direct-stream`, `/api/chats/{id}/stop`,
  `DELETE /api/chats/{chat}/messages/{msg}/from`.

### Phase 4 — Private (private chat rooms)
**Goal:** full parity with web Private Chats — host side.

- Rooms list + unread highlighting; "New room" sheet: topic + **Disappearing messages** (Off/1m/5m/1h/24h), **Invite link expires** (Never/5m/30m/2h/24h), **Delete whole chat** (Never/1h/8h/24h/7d) — native segmented pills.
- Room screen: live chat via SSE (`/api/secret-chat/{token}/stream`), message groups + day dividers, typing bubble, read receipts, disappear countdowns, purge events.
- Floating composer (same component as Ask, reused).
- Share: `ShareLink` sheet (copy, WhatsApp, Telegram, SMS, mail) — web `ShareMenu` parity.
- Host tools: guests panel (device/browser/OS/IP/activity), room options edit, clear chat, delete room, copilot (suggestions + tone/persona), **autopilot draft review card** (countdown, Stop / Send now).
- Telegram bridge status row (when configured).
- **Acceptance:** real-time chat across two devices (web guest + iOS host); disappearing messages vanish in sync; autopilot draft card works.
- **APIs:** `/api/secret-chat/*` — create, rooms, messages, presence, participants, assist,
  autopilot GET/POST, options PATCH, clear/delete, bridge status, SSE stream.

### Phase 5 — Secret (Secret Images vault)
**Goal:** a calm, private photo vault.

- Grid of thumbnails (lazy, glass tiles), upload from Photos/Files, full-screen viewer (pinch-zoom, swipe-down dismiss), delete with confirmation.
- Auth-gated; backend-unreachable error state (like the web's "storage" hint).
- **Acceptance:** upload → grid → viewer → delete loop; same images visible on web (same DB).
- **APIs:** `/api/secret-images` status/list/upload, `/api/secret-images/view/{id}`,
  `DELETE /api/secret-images/{id}`.

### Phase 6 — Library
**Goal:** full collection + file management.

- Collections grid (glass cards like the web's store cards, color chips), create library (name + color), delete with confirmation.
- Library detail: file list with type icons + size + indexing status, upload via document picker / photo library (multipart `POST /api/files`), delete file.
- Ask integration: the file picker reads this data (read-only since Phase 2).
- **Acceptance:** create → upload → index status visible → selectable in Ask → delete; all in sync with web (same DB).
- **APIs:** `/api/collections` (GET/POST/DELETE), `/api/files` (GET/POST multipart/DELETE).

### Phase 7 — Settings
**Goal:** parity with web Settings, reorganized mobile-friendly.

- **Default model:** searchable sheet — provider groups, health tags (responding / no answer), "responding only" filter; custom model ID field; saves to the `explore_ai` preference.
- **Auto-select toggle** + dismissible last-switch note (`auto_select_last_switch`).
- **Providers & models:** provider chips with counts, model list with visibility toggles, "Test all" / per-provider test with latency tags (`POST /llm/models/test` — batches, capped at 40).
- **App settings:** theme (Bright/Dark), server URL, sign out.
- **Acceptance:** changing the default model reflects on the Ask composer chip; health tags update; prefs stay in sync with web (same keys).
- **APIs:** `/api/preferences/*` (`explore_ai`, `enabled_providers`, `enabled_models`,
  `model_health`, `auto_select_model`, `auto_select_last_switch`), `/api/llm/config`,
  `/api/llm/models/test`.

### Phase 8 — Polish & release
- Haptics + micro-animations full pass; empty states; error toasts (web `Toast` parity).
- Global search (the Cmd+K palette's iOS version: swipe-down search sheet — pages, libraries, files, chats).
- Splash screen with real boot progress; final app icon.
- Accessibility: Dynamic Type, VoiceOver labels, Reduce Motion respect.
- TestFlight build + deployment notes (Render URL, ATS).

---

## 7. Risks / watch-items

1. **SSE + NDJSON on iOS:** `URLSession.bytes` handles both, but iOS kills streams in the
   background — reconnect + `after=` cursor resume (the web does the same) is a must in Phase 4.
2. **Mermaid parity:** only `WKWebView` + the same mermaid.js version guarantees it — no
   custom Swift renderer.
3. **Local http:** device testing needs an ATS exception + the Mac's LAN IP; no issue on
   production https.
4. **Auth token expiry:** the stateless HMAC token has an `exp` — silent re-login flow on 401
   in every stream client.
5. **683-model catalogue:** the Settings list must be virtualized; test batches capped (the
   backend already caps at 40).

---

## 8. Rough estimates

| Phase | Size |
|---|---|
| 0 Foundation + design system | M |
| 1 Home | S |
| 2 Ask core | L |
| 3 Ask streaming + mermaid | M |
| 4 Private | L |
| 5 Secret Images | S |
| 6 Library | M |
| 7 Settings | M |
| 8 Polish | M |

**Flow:** one phase completes → review → next phase starts.
