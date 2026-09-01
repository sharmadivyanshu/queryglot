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
npm run test          # run Vitest
npm run lint          # type-check (no emit) + eslint
```

## Backend

The dev server proxies `/api` requests to the queryglot HTTP API, expected at `http://127.0.0.1:8000`.
