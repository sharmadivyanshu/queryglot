# Discover-Style Playground Design

**Date:** 2026-09-02
**Status:** Approved (mockups: `design/queryglot-discover-restyle.html`, keyframes reviewed 2026-09-02)
**Scope:** Two phases in one spec. Phase A — schema sidebar restyle, result bar chart, re-run
control. Phase B — global time-range picker, `query_range` execution, range histogram.

## Why

The playground's schema rail renders every metric as ~6 lines of prose (name + type + labels +
full help), which makes 230 metrics unscannable, and results render only as rows. The approved
direction borrows Elastic Discover's field-list anatomy (typed badges, grouping, counts,
progressive disclosure) and its time-range/histogram controls — translated into queryglot's
identity, not copied. What we deliberately do NOT copy: the document table, the KQL filter bar,
and pagination. queryglot's pitch is *ask in plain language, see the validated query, trust the
refusal* — a raw-data explorer would dilute it.

Two queryglot-native twists anchor the design:

- Elastic's "Popular fields" becomes **IN LAST ANSWER** — the `schema_used` items from the most
  recent answer, pinned at the top of the rail. The sidebar becomes a live explanation of why
  the answer looked the way it did.
- The time window comes from the picker, never the model. The model writes the expression; the
  engine applies the range. The trace card says so explicitly.

## Binding constraints (all phases)

1. **Prompt parity is frozen.** `prompts.SYSTEM` and `compile_prompt()` are shared verbatim with
   `dataset.py` and the current adapters were trained on them. Nothing in this spec may change
   either. The time window is applied at execution only.
2. **Widget budget.** The embeddable widget stays rows-only. `widget.js` gzipped must stay under
   the 60 KB ceiling and should stay within ~1 KB of today's 13.7 KB. Charts are
   playground-only code that the widget build never imports.
3. **Abstention identity.** Abstained/failed states are untouched. Charts never replace rows;
   rows stay one toggle away and remain the accessibility fallback.
4. **API compatibility.** Existing response fields keep their exact shapes. All API changes in
   this spec are additive (new fields, new optional request keys).
5. **No new runtime deps.** Charts are hand-rolled divs/SVG. Backend stays stdlib-HTTP.
6. **No emoji icons.** All new glyphs are inline SVG matching the existing 1.5px-stroke set.
   The existing ayushmxxn theme toggle is untouched (the mockup's 🌙/☀️ was a placeholder).

---

## Phase A — sidebar restyle + result chart + re-run

### A1. Structured schema API (serve layer, additive)

`GET /api/schema` today returns `{"items": ["name (type) — labels: … — help", …]}`. The rail
needs structure, and parsing the render format client-side is fragile. Add a parallel field:

```json
{
  "items": ["…rendered strings, unchanged…"],
  "fields": [
    {"name": "prometheus_http_request_duration_seconds",
     "type": "histogram",
     "kind": "metric",
     "labels": ["handler", "instance", "job", "le"],
     "help": "Histogram of latencies for HTTP requests.",
     "backend": "prometheus"}
  ]
}
```

- `fields` is built from the same `SchemaItem` list, same filter, same `limit` — `items[i]`
  and `fields[i]` describe the same item.
- `items` stays for the widget's abstain-suggestion lookup (no widget change).
- The playground rail switches to `fields` and stops string-parsing entirely.

### A2. Schema rail anatomy (`frontend/src/playground/SchemaRail.tsx`)

Top to bottom:

1. **Header** — `YOUR SCHEMA` label + count pill `230 fields` (count = total fields returned by
   an unfiltered fetch; the rail fetches with a high limit, e.g. `limit=500`).
2. **Filter input** — unchanged behavior (client-side substring filter over name + help).
3. **Type filter chips** — `all 230 · C 96 · G 108 · H 18 · S 8`, monospace, one active at a
   time (`all` default). Counts computed client-side from `fields`. Chips for types with zero
   members are hidden. Elastic backends surface `keyword`/`date`/etc. the same way (chip label
   = first letter uppercased); the chip row is data-driven, not hardcoded to Prometheus types.
4. **IN LAST ANSWER group** — appears only after an answered ask; contains the `schema_used`
   names from the latest `SearchResponse`, matched against `fields` by name (unmatched names
   render with a neutral badge). Expanded by default. Rows in this group use full-strength text
   (`--qg-text`); all other rows use `--qg-text-mut`.
5. **Prefix groups** — group key = first `_`-delimited token of the metric name (`go`,
   `prometheus`, `process`, `net`, …), rendered as `go_* 118`. Groups sorted by descending
   member count. All collapsed by default except IN LAST ANSWER. Expand/collapse is component
   state (chevron ▸/▾), not persisted. When the filter input or a type chip is active, grouping
   flattens to a single result list (groups reappear when the filter clears).
6. **Row** — 18×18 rounded type badge + monospace name, single line, ellipsis. Badge palette
   (tokens, both themes; dark values shown):
   - counter `C` — sky (`#38BDF8` on 13% bg)
   - gauge `G` — emerald (`#34D399` on 13% bg)
   - histogram `H` — violet (`#A78BFA` on 14% bg)
   - summary `S` — amber (`#FBBF24` on 13% bg)
   - anything else — neutral (`--qg-text-faint` on `--qg-surface2`)
   Light-mode variants darken one step to hold ≥4.5:1 (values in the mockup's `.qg-light`
   block). Badges carry `aria-hidden`; the row's accessible name includes the type word.
7. **Expanded row** — clicking a row toggles an inline card: full name (wrapping), label chips,
   help text, and an **↳ ask about this metric** link that focuses the ask input pre-filled
   with the metric name. Only one row expanded at a time.
8. **Footer** — `+ N more, introspected live` when the fetch limit truncated the list.

New CSS custom properties for badge colors go in `frontend/src/ui/tokens.css` under both
`.qg-light` and `.qg-dark` (`--t-counter`, `--t-gauge`, `--t-hist`, `--t-summ`, each with a
`-bg` pair), matching the mockup values.

### A3. Result chart (playground-only, via a Panel slot)

`Panel` gains an optional render slot so the widget build never imports chart code:

```ts
export interface PanelProps {
  // …existing…
  /** Playground-only: alternative renderer for an answered result. Receives the
   *  raw answer and decides what (if anything) to draw — vector → BarChart in
   *  Phase A, matrix → Histogram in Phase B. Returning null falls back to
   *  ResultRows, so the slot never has to handle shapes it doesn't recognise. */
  resultView?: (answer: SearchResponse) => ReactNode | null
}
```

- The widget entry never passes `resultView` → rows-only, bundle unchanged.
- The playground passes a `BarChart` renderer (new file
  `frontend/src/playground/BarChart.tsx`): hand-rolled div bars, grid
  `label | track | value`, sorted descending, max row solid `--bar`, others `--bar-soft`,
  monospace tabular values. Reuses `ResultRows`' existing unwrap/parse logic — that logic moves
  to a shared helper (`frontend/src/lib/resultData.ts`) exporting `parseVector(result)` used by
  both `ResultRows` and `BarChart`.
- **Chart/rows toggle** sits on the RESULT label row (`chart | rows`), chart default. The
  toggle only renders when a chart is applicable; preference is component state per answer
  (resets to chart on each new answer).
- Chart applicability: instant vector with ≥2 rows and numeric values. Scalars, single-row
  vectors, and non-vector results render rows/empty-state exactly as today.
- Accessibility: the chart container has `role="img"` and an `aria-label` summarising top
  entry and count ("bar chart, 5 rows, max /api/v1/series at 26.8"); the rows view remains the
  screen-reader-friendly representation one toggle away. Bars animate width via the existing
  `qg-anim` conventions; `prefers-reduced-motion` disables it via the existing global off-switch.

### A4. Re-run control + cache age

- **Serve:** `POST /api/search` accepts optional `"fresh": true`. When set, the cache read is
  skipped (the fresh result still overwrites the cache entry). Cached responses additionally
  carry `"cache_age_s": <int>` (seconds since stored) alongside the existing `"cached": true`.
- **Panel:** in the answered state a 26×26 refresh icon-button appears in the header (next to
  ⌘K), tooltip "re-run". Clicking re-asks the same question with `fresh: true` through the
  normal thinking flow. This is shared Panel code (works in the widget too — it is a few hundred
  bytes, not a chart).
- **Meta line:** when the answer came from cache, append `· cached {age}s ago` in accent color.
- `useAsk.ask` gains an options argument: `ask(question, {fresh?: boolean})`; the client's
  `search()` passes `fresh` through when set.

### A5. Files touched (Phase A)

| File | Change |
|---|---|
| `src/queryglot/server.py` | `fields` in `/api/schema`; `fresh` + `cache_age_s` in `/api/search` |
| `tests/test_server.py` | structured-fields test, fresh-bypass test, cache-age test |
| `frontend/src/lib/api.ts` | `SchemaField` type, `fields` in `SchemaResponse`, `fresh` param, `cache_age_s` |
| `frontend/src/lib/resultData.ts` | new — shared `parseVector` |
| `frontend/src/lib/useAsk.ts` | `ask(question, {fresh})` |
| `frontend/src/playground/SchemaRail.tsx` | full restyle per A2 |
| `frontend/src/playground/BarChart.tsx` | new |
| `frontend/src/playground/App.tsx` | pass `resultView`, wire schema_used → rail |
| `frontend/src/widget/Panel.tsx` | `resultView` slot, refresh button, cache-age meta |
| `frontend/src/widget/ResultRows.tsx` | use shared `parseVector` |
| `frontend/src/ui/tokens.css` | badge + bar color tokens, both themes |

---

## Phase B — time window + range execution + histogram

### B1. Engine + backend: range execution

The `Backend` Protocol gains one method; `Execution` is reused:

```python
class Backend(Protocol):
    # …existing introspect / validate / execute…
    def execute_range(self, query: str, start: float, end: float, step: float) -> Execution:
        """Evaluate `query` over [start, end] at `step` seconds. Backends that have
        no range concept raise NotImplementedError; the engine falls back to execute()."""
```

- **Prometheus:** `GET /api/v1/query_range?query=…&start=…&end=…&step=…` (matrix result).
  Validation is unchanged — the same expression text is parsed by `format_query` exactly as
  today.
- **Elasticsearch / OpenAPI:** raise `NotImplementedError` in v1. The engine catches it and
  runs plain `execute()` — a window on a non-range backend degrades gracefully rather than
  erroring.
- **Graph:** `build_graph` state gains an optional `window` (`{start, end, step}` floats,
  epoch seconds). The execute node calls `execute_range` when `window` is present, else
  `execute()`. Retrieve/compile/validate nodes never see the window — constraint 1.
- **Engine:** `Engine.search(question, backend=None, window_minutes=None)`. When set, the
  engine computes `end = now`, `start = end - 60*window_minutes`, and
  `step = max(15.0, (end - start) / 120)` (≤ ~120 points), passing the window into the graph.
  `Answer.as_dict()` gains `"window": {"minutes": m, "step_s": s}` when a window ran (absent
  otherwise).

### B2. Serve layer

- `POST /api/search` accepts optional `"window_minutes": <int>` (validated: one of the preset
  values 5, 15, 30, 60, 180, 360, 1440; anything else → 400). Passed to `Engine.search`.
- The answer cache key becomes `(normalized question, backend, window_minutes or 0)`.
- `POST /api/summary` for matrix results: the serve layer downsamples before prompting —
  per series: latest value, peak value, peak timestamp. The existing 1500-char truncation
  remains the backstop.

### B3. Top-bar time control (playground)

Segmented control in the top bar, right-aligned before the backend pills (mockup keyframe 2):

`[clock icon] [Last 30 minutes ▾] [refresh icon Refresh]`

- Presets: Last 5 m, 15 m, 30 m, 1 h, 3 h, 6 h, 24 h, and **Instant** (default). Instant means
  no `window_minutes` is sent and behavior is exactly pre-Phase-B.
- Selection is playground state, applies to every subsequent ask, and re-runs the current
  question immediately if one is answered (with `fresh: true`).
- The Refresh segment re-runs the current question with `fresh: true` (same action as the
  panel's icon button; both exist — the top bar one is discoverable, the panel one is local).
- The dropdown is a simple popover listing presets; full keyboard support (arrow keys + enter,
  esc closes), focus-visible rings from existing conventions.
- The widget does NOT get the time control in this phase (embeds stay instant-only).

### B4. Range result rendering

- `parseVector` grows a sibling `parseMatrix(result)` in `resultData.ts` →
  `{series: [{labels, points: [t, v][]}]}`.
- **Single-series matrix** → `Histogram` renderer (new
  `frontend/src/playground/Histogram.tsx`, passed via the same `resultView` slot): flex-column
  bars (one per step, capped at 120), peak bar solid `--bar` with a hover/focus tooltip
  (`value + timestamp`, monospace), others `--bar-soft`; x-axis start/mid/end time labels;
  footnote `interval: {step}s · {n} points · peak highlighted`. Container `role="img"` with a
  summary `aria-label` ("histogram, 60 points, peak 84.2 at 01:06"); bars are not individually
  focusable in v1 — the rows toggle is the accessible path.
- **Multi-series matrix** → rows fallback: one row per series showing the latest value
  (labels rendered as today's rows do), with the meta line noting `latest of {n} points`.
  No small-multiples in v1.
- **Query block** appends the window in faint text: `· range 00:52 → 01:22, step 30s`
  (times formatted client-side from the response `window` + `elapsed`).
- **Trace card** execute row shows `query_range · 30 min`, and the explanatory note becomes:
  "The window came from the picker, not the model — the model wrote the expression, the range
  was applied by the engine." (Instant asks keep the current note.)

### B5. Files touched (Phase B)

| File | Change |
|---|---|
| `src/queryglot/backends/__init__.py` | `execute_range` in Protocol |
| `src/queryglot/backends/prometheus.py` | `query_range` implementation |
| `src/queryglot/backends/elastic.py`, `openapi.py` | `execute_range` → `NotImplementedError` |
| `src/queryglot/graph.py` | window in state, execute node branch |
| `src/queryglot/engine.py` | `window_minutes` param, step computation, `window` in answer dict |
| `src/queryglot/server.py` | `window_minutes` validation + cache key, matrix downsample for summary |
| `tests/` | backend wire-format test (fake transport), graph window test, serve validation + cache-key tests |
| `frontend/src/lib/api.ts` | `window_minutes` param, `window` response field |
| `frontend/src/lib/resultData.ts` | `parseMatrix` |
| `frontend/src/playground/TimeRange.tsx` | new — segmented control + popover |
| `frontend/src/playground/Histogram.tsx` | new |
| `frontend/src/playground/App.tsx`, `TopBar.tsx` | wire time state through asks |
| `frontend/src/playground/TracePanel.tsx` | range-aware execute row + note |

---

## Testing

- **Backend (pytest):** structured `/api/schema` fields mirror `items`; `fresh: true` bypasses
  a warm cache and re-stores; `cache_age_s` present only on cache hits; `window_minutes`
  outside presets → 400; cache key separates windows; Prometheus `execute_range` sends
  `query_range` with correct params (fake `Transport`); engine falls back to `execute()` on
  `NotImplementedError`; graph passes window only to the execute node (ScriptedLLM sees an
  unchanged prompt — parity guard).
- **Frontend (vitest):** rail groups by prefix with counts and collapses by default; type
  chips filter; IN LAST ANSWER renders `schema_used`; expanded card shows labels/help;
  chart/rows toggle falls back to rows for single-row and non-vector results; refresh calls
  `search` with `fresh`; time presets pass `window_minutes`; single-series matrix renders the
  histogram, multi-series falls back to rows.
- **Budget gate:** `build:all` output asserts widget gzip < 60 KB (existing script), with a
  manual check that Phase A leaves it within ~1 KB of 13.7 KB.
- **E2E (chrome-devtools):** both phases verified in the live playground before merge, both
  themes, zero console messages.

## Rollout

Phase A ships first (one plan), Phase B second (one plan) — each independently mergeable and
CI-green. Phase B's serve/API changes are additive on top of Phase A's.
