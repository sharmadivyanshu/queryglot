# Ask surfaces (serve layer + widget + playground) — design

Date: 2026-09-01. Status: approved (mockups approved in-session; visual
authority: the "queryglot Ask Surfaces" canvas,
https://claude.ai/code/artifact/3aaf6f04-be5e-44af-9f54-b8990af77cb1, working
files in `design/`).

## Why

PROJECT_CORE's product phase: the widget IS the product. Two surfaces —
an embeddable ask-box a customer drops into their app with one script tag,
and a playground where someone points queryglot at their own backend and
watches it become answerable within five minutes. Both render the engine's
trust differentiators: the exact validated query is always shown, and
abstention is presented as calm information, never as an error.

queryglot currently speaks MCP (stdio) and CLI only — a browser has nothing
to call. So this feature is three phases, built in order:

- **Phase A — serve layer**: HTTP JSON API over the existing `Engine`.
- **Phase B — widget**: the embeddable React component + IIFE bundle.
- **Phase C — playground**: the SPA consuming the same component.

One spec because they share contracts and one design system; implementation
splits into two plans (A; then B+C in one frontend plan).

## Goals

- Zero changes to graph/engine/retrieval — the serve layer wraps `Engine`
  exactly as MCP and CLI do.
- One React codebase, two build targets: `widget.js` (IIFE, Shadow DOM) and
  the playground SPA, which imports the SAME widget component — the demo is
  the product, no drift.
- `queryglot-serve` alone is the five-minute demo: it serves the API, the
  playground, and the widget bundle.

## Non-goals (v1)

- Hosted/multi-tenant SaaS, accounts, OAuth — single-tenant self-hosted only.
- Streaming responses, result summarisation, chart rendering (results render
  as rows/JSON).
- Widget theme toggle — the widget follows its host (`data-theme`), only the
  playground has a user-facing toggle.
- framer-motion (CSS transitions only), component library imports beyond the
  named ingredient.
- Mobile-dedicated layouts (responsive down to 375px, no separate designs).

## Phase A — serve layer

**Dependency**: `fastapi` + `uvicorn` as optional dependencies behind the
`serve` extra (installed via `poetry install --extras serve` / `pip install
queryglot[serve]`). Core install keeps its three runtime deps. New module
`src/queryglot/server.py`, console script `queryglot-serve` (mirrors
`queryglot-mcp`): builds backends from the same `QUERYGLOT_*` env vars plus
identical CLI flags (`--prometheus`, `--elastic`, `--openapi`), lazy Engine,
`--port` (default 8000), `--host` (default 127.0.0.1).

Endpoints (JSON):

| Route | Contract |
|---|---|
| `POST /api/search` | body `{"question": str, "backend": str?}` → `Answer.as_dict()` + `"elapsed_ms": int` (measured in the route). 400 on missing/empty question. |
| `GET /api/schema` | `?query=&limit=` → `{"items": [rendered strings]}`, mirroring MCP `list_schema`. |
| `GET /api/status` | `{"backends": {name: item_count}, "version": str}` — feeds the playground connect bar. |
| `POST /api/refresh` | re-introspect; returns the counts dict. |
| `GET /` | the playground build (static files from the installed package when present, else 404 with a hint). |
| `GET /widget.js` | the widget bundle, `Cache-Control: no-cache`. |

**CORS**: off by default; `--cors-origin <origin>` (repeatable) /
`QUERYGLOT_CORS_ORIGINS` (comma-separated) feeds FastAPI's CORSMiddleware.
The widget README documents that embedding requires listing the host page's
origin.

**Auth**: optional shared secret — `QUERYGLOT_SERVE_TOKEN`; when set, all
`/api/*` routes require `Authorization: Bearer <token>`; the widget passes
it from `data-token`. No token = open (localhost/demo posture; README says
so plainly).

**Errors**: never a 500 for engine outcomes — abstained/failed are 200s with
their `outcome` (the outcome IS the payload). 500 only for genuine faults.

**Testing**: `fastapi.testclient` (dev dep httpx) unit tests with
`FakeBackend`/`ScriptedLLM` from conftest; one live test behind the existing
env guards exercising `/api/search` end-to-end against Prometheus.

## Phase B — widget

**Workspace**: `frontend/` — Vite + React + TypeScript + Tailwind, shadcn
project structure (`components/ui`), npm. Monorepo convention: own
package.json, own tooling, never mixed into Poetry.

**Embed contract** (the whole public API):

```html
<script src="https://your-host/widget.js"
        data-api="https://your-host"
        data-theme="auto"
        data-token=""
        data-backend=""></script>
```

`data-api` required (serve-layer origin); `data-theme` light|dark|auto
(default auto); `data-token` optional bearer; `data-backend` optional pin.

The script mounts a Shadow-DOM root (all styles injected inside — Tailwind
compiled with a shadow-root selector strategy; zero leakage either way),
renders the floating "Ask" pill (bottom-right), opens the panel on click or
⌘K/ctrl+K. React is bundled into the IIFE; accepted budget ~50KB gzipped
(conscious tradeoff, decided in-session: DX + playground reuse over the
~12KB vanilla floor).

**States** (visual authority = the four approved artboards):

1. *Idle*: command-palette panel — search header with ⌘K kbd, SUGGESTED rows
   (⏎ hint on the highlighted row), schema-grounding note, footer kbd row
   (`enter` ask · `esc` close · queryglot mark).
2. *Thinking*: the four pipeline stages rendered from the request lifecycle
   (retrieve/compile/validate/execute), indigo progress bar. v1 has no
   streaming, so stages animate on a timer until the response lands, then
   snap to truth (attempts/abstention from the payload). No fabricated
   timings shown.
3. *Answered*: "RAN THIS EXACT QUERY" + "validated by your server" chip +
   syntax-tinted query block + result rows (instant vectors as label/value
   rows; other shapes as pretty-printed JSON, scrollable) + grounding line
   ("grounded in N schema items · M attempts").
4. *Abstained*: amber info card ("Nothing in your schema answers this",
   explanation, "refused to guess · 0 queries run" chip) + "closest your
   schema can answer" rows from `/api/schema` lexical suggestions. A failed
   outcome renders the same card shape with the reason; destructive red is
   reserved for genuine faults only.

**Theming**: design tokens as CSS variables on the shadow root (the two
approved palettes: paper `#FAFAF8`-family light, ink `#101014`-family dark,
fixed indigo `#6366F1` accent, amber abstention). `data-theme="auto"` follows
`prefers-color-scheme`. Fonts: system-stack fallbacks by default; the brand
faces (Bricolage Grotesque / Instrument Sans / IBM Plex Mono) load only via
opt-in `data-fonts="google"` — an embed must not force third-party font
loads on someone else's page.

**A11y**: full keyboard path (open ⌘K, navigate ↑↓, ask ⏎, close esc), focus
trap while open, `aria-live="polite"` on state changes, 44px minimum
targets, `prefers-reduced-motion` respected.

## Phase C — playground

One-page SPA (`frontend/` app target) per the approved artboard: top bar
(logo, connect input + status chip fed by `/api/status`, theme toggle),
schema rail (`/api/schema` with client-side filter, "+N more, introspected
live"), hero copy, ask bar, and the answer experience = the SAME widget
panel component rendered inline (not floating), plus the "HOW IT GOT THERE"
trace panel (stages, attempts, schema-items count, total `elapsed_ms`; no
per-stage timings in v1 — the API doesn't measure them).

**Theme toggle**: visual reference `@ayushmxxn/theme-toggle` (21st.dev id
1216) — implemented as the CSS-transition variant with the fixes decided
in-session: wired to a ~20-line ThemeProvider (class on root +
localStorage), keyboard activation (Enter/Space), `aria-pressed` + label,
≥44px hit area, token colors instead of zinc hardcodes. lucide-react for its
icons (and all playground icons).

**Serving**: `npm run build` outputs the SPA + `widget.js`; a build step
copies them into `src/queryglot/_static/` so the published wheel ships them
and `queryglot-serve` serves them. `frontend/README.md` documents the dev
loop (`vite dev` proxying `/api` to :8000).

## Testing & CI

- Phase A: pytest as above, inside the existing suite and gate.
- B/C: vitest + @testing-library/react for the widget state machine
  (idle→thinking→answered/abstained from mocked fetch), the theme provider,
  and the embed bootstrap (script dataset parsing, shadow-root mount).
- CI: a `frontend` job (npm ci, lint, vitest, build) added to the existing
  workflow; the build step asserts `widget.js` stays under a 60KB gzip
  ceiling (50 budget + slack).

## Files

Phase A — new: `src/queryglot/server.py`, `tests/test_server.py`; touched:
`pyproject.toml` (serve group + script + package data), `README.md`.
Phases B/C — new: `frontend/` workspace (vite config with two build modes,
`src/widget/` component + states, `src/playground/` app, shared
`src/ui/tokens.css`), `src/queryglot/_static/` (build output; gitignored
except `.gitkeep`, packaged into the wheel by the build step); touched:
`README.md`, `.github/workflows/ci.yml`, `.gitignore`.
