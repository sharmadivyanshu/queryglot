# queryglot frontend

Vite + React + TypeScript workspace for the queryglot playground UI and embeddable widget.

## Layout

- `src/playground/` — standalone playground app (dev server + default `build`)
- `src/widget/` — embeddable widget entry, built separately as an IIFE bundle
- `src/ui/tokens.css` — design tokens (CSS custom properties) scoped under `.qg-light` / `.qg-dark`. Components style themselves only via these variables.
- `src/test/` — Vitest setup and specs

## Commands

```bash
npm run dev          # playground dev server (proxies /api to http://127.0.0.1:8000)
npm run build         # type-check + build the playground app to dist/
npm run build:widget  # build the widget IIFE bundle to dist-widget/widget.js
npm run build:all     # build + build:widget + copy both into ../src/queryglot/_static (see below)
npm run test          # run Vitest
npm run lint          # type-check (no emit) + eslint
```

## Dev loop

1. Run the queryglot HTTP API on `:8000`: `poetry run queryglot-serve --prometheus http://localhost:9090` (from the repo root).
2. Run `npm run dev` in this directory — it proxies `/api` requests to `http://127.0.0.1:8000`.

## Embedding the widget

The widget is a self-contained IIFE bundle (React aliased to Preact for the
build to stay under the 60KB gzip ceiling — see `vite.config.ts`'s `widget`
mode). Drop one script tag on any page:

```html
<script
  src="https://your-queryglot-host/widget.js"
  data-api="https://your-queryglot-host"
  data-theme="auto"
  data-token="optional-bearer-token"
  data-backend="optional-backend-name"
></script>
```

- `data-api` (required) — base URL of the queryglot HTTP API.
- `data-theme` — `light`, `dark`, or `auto` (default; follows the host page's `prefers-color-scheme`).
- `data-token` — bearer token, only needed when the server sets `QUERYGLOT_SERVE_TOKEN`.
- `data-backend` — pins searches to one backend instead of auto-routing.

## Packaging into the wheel

`npm run build:all` builds the playground, builds the widget, and copies both
(`dist/*` and `dist-widget/widget.js`) into `../src/queryglot/_static/`, which
ships inside the `queryglot` Python wheel (see `pyproject.toml`'s `include`)
and is served by `queryglot-serve` at `/` and `/widget.js`. Run it before
cutting a release; the copy script prints the widget's gzipped size and fails
the build if it exceeds 60KB.
