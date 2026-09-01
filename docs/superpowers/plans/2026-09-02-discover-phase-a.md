# Discover Playground Phase A Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Restyle the playground schema rail Elastic-Discover-style (type badges, prefix groups, IN LAST ANSWER), add a playground-only result bar chart behind a Panel slot, and add re-run with cache bypass.

**Architecture:** The serve layer gains additive fields (`fields` on `/api/schema`; `fresh`/`cache_age_s` on `/api/search`). The frontend moves result parsing into a shared `resultData.ts`, rebuilds `SchemaRail` from structured fields, and threads an optional `resultView` render slot through `Panel` so chart code exists only in the playground bundle.

**Tech Stack:** FastAPI + pytest (serve); React 18 + Vite + vitest + Tailwind-utility classes in playground files, inline styles in widget files (existing split).

**Spec:** `docs/superpowers/specs/2026-09-02-discover-playground-design.md` (Phase A sections A1–A5 + Binding constraints)

## Global Constraints

- `prompts.SYSTEM` / `compile_prompt()` untouched (no compile-path changes at all in this plan).
- Widget budget: `widget.js` gzip < 60 KB hard ceiling, target within ~1 KB of 13.7 KB. Chart code must not be imported by `frontend/src/widget/embed.tsx`'s module graph except via the unused-prop path (slot left unset), which Rollup tree-shakes.
- All API changes additive; existing response fields keep exact shapes (`items: string[]` stays).
- Abstained/failed UI untouched. Rows stay one toggle away from any chart.
- No new runtime deps, no lint suppressions, ruff line-length 100.
- No emoji icons — inline SVG, 1.5px stroke, matching existing icons.
- Backend gates: `poetry run pytest && poetry run ruff check . && poetry run ruff format --check . && poetry run mypy src/queryglot --ignore-missing-imports`. Frontend gates (from `frontend/`): `npm test -- --run && npm run lint && npm run build:all`.

---

### Task 1: Structured `fields` on `/api/schema`

**Files:**
- Modify: `src/queryglot/server.py` (the `schema` route, currently ~line 154)
- Test: `tests/test_server.py`

**Interfaces:**
- Produces: `GET /api/schema` response gains `"fields": [{"name", "type", "kind", "labels", "help", "backend"}, …]`, index-aligned with the existing `"items"` list. Task 4 (frontend `SchemaField`) mirrors this shape exactly.

- [ ] **Step 1: Write the failing test** — append to `tests/test_server.py`:

```python
def test_schema_returns_structured_fields_alongside_items():
    """The rail needs structure; the widget keeps the rendered strings.
    Same filter, same limit, same order — items[i] and fields[i] agree."""
    engine = Engine([IntrospectingBackend(valid={"GOOD"})], llm=ScriptedLLM("GOOD"))
    client = TestClient(create_app(engine))
    body = client.get("/api/schema").json()
    assert len(body["fields"]) == len(body["items"])
    first = body["fields"][0]
    assert first["name"] == "http_server_request_duration_seconds"
    assert first["type"] == "histogram"
    assert first["kind"] == "metric"
    assert isinstance(first["labels"], list)
    assert first["backend"] == "prometheus"
    assert "help" in first
    # the rendered string for the same index names the same item
    assert body["items"][0].startswith(first["name"])
```

- [ ] **Step 2: Run test to verify it fails**

Run: `poetry run pytest tests/test_server.py::test_schema_returns_structured_fields_alongside_items -v`
Expected: FAIL with `KeyError: 'fields'`

- [ ] **Step 3: Implement** — in `src/queryglot/server.py`, replace the `schema` route body's return:

```python
    @app.get("/api/schema")
    def schema(query: str = "", limit: int = 20) -> dict:
        items = engine.catalog.items
        if query:
            needle = query.lower()
            items = [i for i in items if needle in i.name.lower() or needle in i.help.lower()]
        sliced = items[:limit]
        return {
            "items": [item.render() for item in sliced],
            "fields": [
                {
                    "name": item.name,
                    "type": item.type,
                    "kind": item.kind,
                    "labels": list(item.labels),
                    "help": item.help,
                    "backend": item.backend,
                }
                for item in sliced
            ],
        }
```

- [ ] **Step 4: Run the full server suite**

Run: `poetry run pytest tests/test_server.py -q`
Expected: all pass

- [ ] **Step 5: Commit**

```bash
git add tests/test_server.py src/queryglot/server.py
git commit -m "feat(serve): structured fields on /api/schema"
```

---

### Task 2: `fresh` cache bypass + `cache_age_s`

**Files:**
- Modify: `src/queryglot/server.py` (`SearchRequest` model + `search` route)
- Test: `tests/test_server.py`

**Interfaces:**
- Consumes: the existing `search_cache` dict `{(question, backend): (monotonic_stored, payload)}` and `cache_key(request)` helper inside `create_app`.
- Produces: `POST /api/search` accepts optional `"fresh": true`; cached responses carry `"cached": true` **and** `"cache_age_s": <int>`. Task 4 mirrors both in the TS client.

- [ ] **Step 1: Write the failing tests** — append to `tests/test_server.py`:

```python
def test_fresh_true_bypasses_cache_and_restores():
    llm = CountingLLM("GOOD")
    engine = Engine([IntrospectingBackend(valid={"GOOD"})], llm=llm)
    client = TestClient(create_app(engine))
    client.post("/api/search", json={"question": "p95 latency by route"})
    calls_after_first = len(llm.calls)
    fresh = client.post(
        "/api/search", json={"question": "p95 latency by route", "fresh": True}
    ).json()
    assert "cached" not in fresh  # a bypassed read is a live answer
    assert len(llm.calls) > calls_after_first  # the model really ran again
    # ...and the fresh run re-primed the cache
    hit = client.post("/api/search", json={"question": "p95 latency by route"}).json()
    assert hit["cached"] is True


def test_cache_hit_reports_age_in_seconds():
    llm = CountingLLM("GOOD")
    engine = Engine([IntrospectingBackend(valid={"GOOD"})], llm=llm)
    client = TestClient(create_app(engine))
    client.post("/api/search", json={"question": "p95 latency by route"})
    hit = client.post("/api/search", json={"question": "p95 latency by route"}).json()
    assert hit["cached"] is True
    assert isinstance(hit["cache_age_s"], int)
    assert hit["cache_age_s"] >= 0
```

- [ ] **Step 2: Run to verify both fail**

Run: `poetry run pytest tests/test_server.py -q -k "fresh_true or reports_age"`
Expected: 2 FAIL (first: `cached` present / LLM not re-called; second: `KeyError: 'cache_age_s'`)

- [ ] **Step 3: Implement** — in `src/queryglot/server.py`:

Add the field to the request model:

```python
class SearchRequest(BaseModel):
    question: str
    backend: str | None = None
    fresh: bool = False
```

In the `search` route, replace the cache-hit block:

```python
        key = cache_key(request)
        hit = None if request.fresh else search_cache.get(key)
        if hit and time.monotonic() - hit[0] < CACHE_TTL_SECONDS:
            return {**hit[1], "cached": True, "cache_age_s": int(time.monotonic() - hit[0])}
```

(The store path is unchanged — a `fresh` run still writes `search_cache[key]` on an answered outcome, which the existing code already does.)

- [ ] **Step 4: Run the server suite**

Run: `poetry run pytest tests/test_server.py -q`
Expected: all pass

- [ ] **Step 5: Commit**

```bash
git add tests/test_server.py src/queryglot/server.py
git commit -m "feat(serve): fresh cache bypass and cache_age_s on hits"
```

---

### Task 3: Shared result parsing — `resultData.ts`

**Files:**
- Create: `frontend/src/lib/resultData.ts`
- Create: `frontend/src/lib/resultData.test.ts`
- Modify: `frontend/src/widget/ResultRows.tsx` (delete its local copies, import the shared ones)

**Interfaces:**
- Produces (Tasks 6 and 7 and Phase B consume these exact names):

```ts
export interface VectorRow { label: string; value: number; raw: string }
/** Unwraps {resultType:"vector",result:[…]} and parses instant-vector samples.
 *  Returns null when the result is not an instant vector (caller falls back). */
export function parseVector(result: unknown): VectorRow[] | null
/** 3 sig figs, no invented unit; non-numeric raw strings pass through. */
export function formatValue(raw: string): string
```

- [ ] **Step 1: Write the failing tests** — `frontend/src/lib/resultData.test.ts`:

```ts
import { describe, expect, it } from 'vitest'
import { formatValue, parseVector } from './resultData'

const sample = (labels: Record<string, string>, v: string) => ({ metric: labels, value: [1, v] })

describe('parseVector', () => {
  it('unwraps the prometheus envelope and sorts descending', () => {
    const result = {
      resultType: 'vector',
      result: [sample({ handler: '/metrics' }, '0.7'), sample({ handler: '/api' }, '26.8')],
    }
    const rows = parseVector(result)
    expect(rows).not.toBeNull()
    expect(rows![0]).toEqual({ label: '/api', value: 26.8, raw: '26.8' })
    expect(rows![1].label).toBe('/metrics')
  })

  it('joins multi-label metrics with spaces and defaults empty labels', () => {
    const rows = parseVector([sample({ a: 'x', b: 'y' }, '1'), sample({}, '2')])
    expect(rows![1].label).toBe('x y')
    expect(rows![0].label).toBe('(no labels)')
  })

  it('returns null for scalars, matrices, and garbage', () => {
    expect(parseVector({ resultType: 'matrix', result: [] })).toBeNull()
    expect(parseVector(42)).toBeNull()
    expect(parseVector('nope')).toBeNull()
  })

  it('returns an empty array for an empty vector (caller shows the empty state)', () => {
    expect(parseVector({ resultType: 'vector', result: [] })).toEqual([])
  })
})

describe('formatValue', () => {
  it('rounds to 3 significant figures', () => {
    expect(formatValue('26.8421')).toBe('26.8')
    expect(formatValue('0.010370076')).toBe('0.0104')
  })
  it('passes zero and non-numeric through', () => {
    expect(formatValue('0')).toBe('0')
    expect(formatValue('NaN-ish')).toBe('NaN-ish')
  })
})
```

- [ ] **Step 2: Run to verify failure**

Run (from `frontend/`): `npm test -- --run src/lib/resultData.test.ts`
Expected: FAIL — module not found

- [ ] **Step 3: Implement** — `frontend/src/lib/resultData.ts`. Move the logic currently in `ResultRows.tsx` (`unwrap`, `isInstantVector`, `formatValue`, `numeric`) here, reshaped to the interface:

```ts
/**
 * Shared parsing for Prometheus result payloads. Lives in lib/ (not widget/)
 * because both the widget's ResultRows and the playground's chart renderers
 * consume it — the chart code itself must never enter the widget bundle,
 * but this parsing is shared and tiny.
 */

interface InstantVectorSample {
  metric: Record<string, string>
  value: [number | string, string]
}

export interface VectorRow {
  label: string
  value: number
  raw: string
}

function unwrap(result: unknown, resultType: string): unknown | null {
  if (
    typeof result === 'object' &&
    result !== null &&
    'resultType' in result &&
    (result as { resultType: unknown }).resultType === resultType &&
    'result' in result
  ) {
    return (result as { result: unknown }).result
  }
  return result
}

function isInstantVector(result: unknown): result is InstantVectorSample[] {
  return (
    Array.isArray(result) &&
    result.every(
      (item) =>
        typeof item === 'object' &&
        item !== null &&
        'metric' in item &&
        typeof (item as { metric: unknown }).metric === 'object' &&
        'value' in item &&
        Array.isArray((item as { value: unknown }).value),
    )
  )
}

export function formatValue(raw: string): string {
  const n = Number(raw)
  if (!Number.isFinite(n)) return raw
  if (n === 0) return '0'
  return Number(n.toPrecision(3)).toString()
}

export function parseVector(result: unknown): VectorRow[] | null {
  const inner = unwrap(result, 'vector')
  if (!isInstantVector(inner)) return null
  return inner
    .map((sample) => {
      const parsed = Number(sample.value[1])
      return {
        label: Object.values(sample.metric).join(' ') || '(no labels)',
        value: Number.isFinite(parsed) ? parsed : Number.NEGATIVE_INFINITY,
        raw: String(sample.value[1]),
      }
    })
    .sort((a, b) => b.value - a.value)
}
```

Then rewrite `frontend/src/widget/ResultRows.tsx` to consume it — delete its local `unwrap`, `isInstantVector`, `formatValue`, `numeric`, and `InstantVectorSample`; keep its styles and empty/JSON fallbacks:

```tsx
import type { CSSProperties } from 'react'
import { formatValue, parseVector } from '../lib/resultData'
```

and its body becomes:

```tsx
export function ResultRows({ result: rawResult }: { result: unknown }) {
  const rows = parseVector(rawResult)
  if (rows !== null && rows.length === 0) {
    return (
      <div style={emptyStyle}>
        The query ran and was valid, but returned no data on your server.
      </div>
    )
  }
  if (rows !== null) {
    return (
      <div style={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
        {rows.map((row, i) => (
          <div key={i} className="krow" style={{ background: i % 2 === 0 ? 'var(--qg-surface2)' : 'transparent' }}>
            <span className="mono" style={rowLabelStyle}>
              {row.label}
            </span>
            <span
              className="mono"
              style={
                i === 0 && rows.length > 1
                  ? { ...rowValueStyle, color: 'var(--qg-accent)', fontWeight: 600 }
                  : rowValueStyle
              }
            >
              {formatValue(row.raw)}
            </span>
          </div>
        ))}
      </div>
    )
  }
  return <pre style={preStyle}>{JSON.stringify(rawResult, null, 2)}</pre>
}
```

Note one behavior change to preserve: the old code pretty-printed the *unwrapped* result in the JSON fallback; the new code prints `rawResult`. That is acceptable — a non-vector envelope (e.g. matrix) is MORE readable with its `resultType` visible. Mention this in the commit body.

- [ ] **Step 4: Run the frontend suite** (ResultRows tests in `Panel.test.tsx`/`embed.test.tsx` must still pass)

Run: `npm test -- --run`
Expected: all pass

- [ ] **Step 5: Commit**

```bash
git add src/lib/resultData.ts src/lib/resultData.test.ts src/widget/ResultRows.tsx
git commit -m "refactor(frontend): shared result parsing in lib/resultData"
```

---

### Task 4: TS client — `fields`, `fresh`, `cache_age_s`, `ask` options

**Files:**
- Modify: `frontend/src/lib/api.ts`
- Modify: `frontend/src/lib/useAsk.ts`
- Test: `frontend/src/lib/api.test.ts` (create if absent; check first — `ls frontend/src/lib/`)

**Interfaces:**
- Consumes: Task 1's `fields` shape, Task 2's `fresh`/`cache_age_s`.
- Produces (Tasks 5–8 consume): `SchemaField` type; `SchemaResponse.fields: SchemaField[]`; `SearchResponse.cached?: boolean`, `SearchResponse.cache_age_s?: number`; `Client.search(question, backend?, fresh?)`; `useAsk`'s `ask(question, opts?: { fresh?: boolean })`.

- [ ] **Step 1: Write the failing test** — `frontend/src/lib/api.test.ts`:

```ts
import { afterEach, describe, expect, it, vi } from 'vitest'
import { createClient } from './api'

function mockFetch(body: unknown) {
  const fn = vi.fn().mockResolvedValue({ ok: true, json: () => Promise.resolve(body) })
  vi.stubGlobal('fetch', fn)
  return fn
}

afterEach(() => vi.unstubAllGlobals())

describe('client.search', () => {
  it('sends fresh only when requested', async () => {
    const fetchFn = mockFetch({ outcome: 'answered' })
    const client = createClient({ api: '' })
    await client.search('q')
    expect(JSON.parse(fetchFn.mock.calls[0][1].body as string)).toEqual({
      question: 'q',
      backend: undefined,
    })
    await client.search('q', undefined, true)
    expect(JSON.parse(fetchFn.mock.calls[1][1].body as string).fresh).toBe(true)
  })
})

describe('client.schema', () => {
  it('exposes structured fields', async () => {
    mockFetch({ items: ['up (gauge)'], fields: [{ name: 'up', type: 'gauge', kind: 'metric', labels: [], help: '', backend: 'prometheus' }] })
    const client = createClient({ api: '' })
    const response = await client.schema()
    expect(response.fields[0].name).toBe('up')
  })
})
```

- [ ] **Step 2: Run to verify failure**

Run: `npm test -- --run src/lib/api.test.ts`
Expected: FAIL — `fresh` not sent / `fields` type missing (TS compile error surfaces in vitest)

- [ ] **Step 3: Implement** — in `frontend/src/lib/api.ts`:

```ts
export interface SchemaField {
  name: string
  type: string
  kind: string
  labels: string[]
  help: string
  backend: string
}
```

Extend the existing interfaces (add fields, do not reshape):

```ts
export interface SearchResponse {
  // …existing fields unchanged…
  cached?: boolean
  cache_age_s?: number
}

export interface SchemaResponse {
  items: string[]
  fields: SchemaField[]
}

export interface Client {
  search(question: string, backend?: string, fresh?: boolean): Promise<SearchResponse>
  // …schema/status/summary unchanged…
}
```

and in `createClient`:

```ts
    search(question, backend, fresh) {
      return request<SearchResponse>(`${api}/api/search`, token, {
        method: 'POST',
        body: JSON.stringify(fresh ? { question, backend, fresh: true } : { question, backend }),
      })
    },
```

In `frontend/src/lib/useAsk.ts`, change the `ask` signature (the summary/abstain wiring inside is untouched — only the search call and signature change):

```ts
export interface UseAskResult {
  state: AskState
  ask: (question: string, opts?: { fresh?: boolean }) => void
  reset: () => void
}
```

```ts
  const ask = useCallback(
    (question: string, opts?: { fresh?: boolean }) => {
      // …existing body, with the search call becoming:
      client
        .search(question, backend, opts?.fresh)
      // …
    },
    [client, backend, clearTimer],
  )
```

Existing callers (`Panel`, `App`, `embed`) pass `(question)` — no call-site changes needed.

- [ ] **Step 4: Run the frontend suite + lint** (lint catches TS breaks in callers)

Run: `npm test -- --run && npm run lint`
Expected: pass (the 3 pre-existing react-refresh warnings are accepted)

- [ ] **Step 5: Commit**

```bash
git add src/lib/api.ts src/lib/api.test.ts src/lib/useAsk.ts
git commit -m "feat(frontend): client support for schema fields and fresh re-runs"
```

---

### Task 5: Badge/bar tokens + SchemaRail structure (badges, type chips, flat filtering)

**Files:**
- Modify: `frontend/src/ui/tokens.css`
- Modify: `frontend/src/playground/SchemaRail.tsx` (full rewrite)
- Modify: `frontend/src/playground/App.tsx` (fetch `fields`, raise limit)
- Test: `frontend/src/playground/SchemaRail.test.tsx` (create)

**Interfaces:**
- Consumes: `SchemaField` from Task 4.
- Produces: `SchemaRailProps` becomes `{ fields: SchemaField[]; total?: number; status: StatusResponse | null; unreachable: boolean; lastAnswerNames: string[]; onAskAbout: (name: string) => void }`. Task 6 builds grouping/expansion on this component. `SCHEMA_LIMIT` in `App.tsx` becomes `500`.

- [ ] **Step 1: Add tokens** — append inside BOTH blocks of `frontend/src/ui/tokens.css`:

In `.qg-light`:
```css
  --t-counter: #0284C7; --t-counter-bg: rgba(2,132,199,0.10);
  --t-gauge: #059669; --t-gauge-bg: rgba(5,150,105,0.10);
  --t-hist: #7C3AED; --t-hist-bg: rgba(124,58,237,0.10);
  --t-summ: #B45309; --t-summ-bg: rgba(217,119,6,0.10);
  --t-other: #78716C; --t-other-bg: rgba(120,113,108,0.10);
  --qg-bar: #6366F1; --qg-bar-soft: rgba(99,102,241,0.24);
```

In `.qg-dark`:
```css
  --t-counter: #38BDF8; --t-counter-bg: rgba(56,189,248,0.13);
  --t-gauge: #34D399; --t-gauge-bg: rgba(52,211,153,0.13);
  --t-hist: #A78BFA; --t-hist-bg: rgba(167,139,250,0.14);
  --t-summ: #FBBF24; --t-summ-bg: rgba(251,191,36,0.13);
  --t-other: #8B8B96; --t-other-bg: rgba(139,139,150,0.13);
  --qg-bar: #818CF8; --qg-bar-soft: rgba(129,140,248,0.28);
```

- [ ] **Step 2: Write the failing tests** — `frontend/src/playground/SchemaRail.test.tsx`:

```tsx
import { render, screen, fireEvent } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { SchemaRail } from './SchemaRail'
import type { SchemaField } from '../lib/api'

const f = (name: string, type: string, labels: string[] = [], help = ''): SchemaField => ({
  name, type, kind: 'metric', labels, help, backend: 'prometheus',
})

const FIELDS = [
  f('go_goroutines', 'gauge'),
  f('go_gc_duration_seconds', 'summary'),
  f('prometheus_http_requests_total', 'counter'),
  f('prometheus_http_request_duration_seconds', 'histogram', ['handler', 'le'], 'Latencies.'),
]

const noop = () => {}

describe('SchemaRail', () => {
  it('shows the field count and one type badge per row', () => {
    render(<SchemaRail fields={FIELDS} total={4} status={null} unreachable={false} lastAnswerNames={[]} onAskAbout={noop} />)
    expect(screen.getByText('4 fields')).toBeInTheDocument()
    expect(screen.getByText('H')).toBeInTheDocument()
    expect(screen.getByText('S')).toBeInTheDocument()
  })

  it('type chips filter the list', () => {
    render(<SchemaRail fields={FIELDS} total={4} status={null} unreachable={false} lastAnswerNames={[]} onAskAbout={noop} />)
    fireEvent.click(screen.getByRole('button', { name: /C 1/ }))
    expect(screen.getByText('prometheus_http_requests_total')).toBeInTheDocument()
    expect(screen.queryByText('go_goroutines')).not.toBeInTheDocument()
  })

  it('text filter flattens and narrows', () => {
    render(<SchemaRail fields={FIELDS} total={4} status={null} unreachable={false} lastAnswerNames={[]} onAskAbout={noop} />)
    fireEvent.change(screen.getByPlaceholderText('filter metrics…'), { target: { value: 'goroutines' } })
    expect(screen.getByText('go_goroutines')).toBeInTheDocument()
    expect(screen.queryByText('prometheus_http_requests_total')).not.toBeInTheDocument()
  })

  it('row accessible name includes the type word (badge is decoration)', () => {
    render(<SchemaRail fields={FIELDS} total={4} status={null} unreachable={false} lastAnswerNames={[]} onAskAbout={noop} />)
    expect(screen.getByRole('button', { name: /go_goroutines.*gauge/ })).toBeInTheDocument()
  })
})
```

- [ ] **Step 3: Run to verify failure**

Run: `npm test -- --run src/playground/SchemaRail.test.tsx`
Expected: FAIL — props mismatch / badges absent

- [ ] **Step 4: Rewrite `SchemaRail.tsx`.** Structure for this task (grouping and expansion land in Task 6 — this task renders a FLAT list; write it so Task 6 can wrap rows in groups):

```tsx
import { useMemo, useState } from 'react'
import type { SchemaField, StatusResponse } from '../lib/api'

const BADGES: Record<string, { letter: string; fg: string; bg: string }> = {
  counter: { letter: 'C', fg: 'var(--t-counter)', bg: 'var(--t-counter-bg)' },
  gauge: { letter: 'G', fg: 'var(--t-gauge)', bg: 'var(--t-gauge-bg)' },
  histogram: { letter: 'H', fg: 'var(--t-hist)', bg: 'var(--t-hist-bg)' },
  summary: { letter: 'S', fg: 'var(--t-summ)', bg: 'var(--t-summ-bg)' },
}

export function badgeFor(type: string) {
  return BADGES[type] ?? { letter: (type[0] ?? '?').toUpperCase(), fg: 'var(--t-other)', bg: 'var(--t-other-bg)' }
}

function TypeBadge({ type }: { type: string }) {
  const badge = badgeFor(type)
  return (
    <span
      aria-hidden="true"
      className="flex h-[18px] w-[18px] flex-shrink-0 items-center justify-center rounded-[5px] font-mono text-[9.5px] font-semibold"
      style={{ color: badge.fg, background: badge.bg }}
    >
      {badge.letter}
    </span>
  )
}

export interface SchemaRailProps {
  fields: SchemaField[]
  /** Total metric count from /api/status (may exceed fields.length when the fetch limit truncated). */
  total?: number
  status: StatusResponse | null
  unreachable: boolean
  /** schema_used names from the latest answered ask — drives IN LAST ANSWER (Task 6). */
  lastAnswerNames: string[]
  /** Focus the ask input pre-filled with this metric name. */
  onAskAbout: (name: string) => void
}
```

Row rendering (each row is a `<button type="button">` for keyboard access; the accessible name carries the type):

```tsx
function FieldRow({ field, hot, onClick }: { field: SchemaField; hot: boolean; onClick: () => void }) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-label={`${field.name}, ${field.type || field.kind}`}
      className="flex w-full cursor-pointer items-center gap-2 rounded-lg px-1.5 py-[5px] text-left hover:bg-qg-surface2"
    >
      <TypeBadge type={field.type} />
      <span className={`truncate font-mono text-[12px] ${hot ? 'text-qg-text' : 'text-qg-text-mut'}`}>
        {field.name}
      </span>
    </button>
  )
}
```

Component body: header row (`YOUR SCHEMA` + `{total ?? fields.length} fields` count pill), the existing filter input, then a type-chip row, then the flat filtered list, then the existing `+N more, introspected live` footer (now `total - fields.length`) and the embed snippet card (kept verbatim). Filtering pipeline:

```tsx
  const [filter, setFilter] = useState('')
  const [typeFilter, setTypeFilter] = useState<string | null>(null)

  const typeCounts = useMemo(() => {
    const counts = new Map<string, number>()
    for (const field of fields) counts.set(field.type, (counts.get(field.type) ?? 0) + 1)
    return counts
  }, [fields])

  const visible = useMemo(() => {
    const query = filter.trim().toLowerCase()
    return fields.filter(
      (field) =>
        (typeFilter === null || field.type === typeFilter) &&
        (!query || field.name.toLowerCase().includes(query) || field.help.toLowerCase().includes(query)),
    )
  }, [fields, filter, typeFilter])
```

Type chips (hide zero-count; `all` first):

```tsx
      <div className="flex flex-wrap gap-1.5 px-0.5 pb-1">
        <button type="button" onClick={() => setTypeFilter(null)}
          className={`cursor-pointer rounded-[7px] border px-2 py-1 font-mono text-[10.5px] ${typeFilter === null ? 'border-qg-ok-border bg-qg-ok-bg text-qg-accent' : 'border-qg-border-soft bg-qg-surface text-qg-text-mut'}`}>
          all {fields.length}
        </button>
        {[...typeCounts.entries()].map(([type, count]) => (
          <button key={type} type="button" onClick={() => setTypeFilter(typeFilter === type ? null : type)}
            className={`cursor-pointer rounded-[7px] border px-2 py-1 font-mono text-[10.5px] ${typeFilter === type ? 'border-qg-ok-border bg-qg-ok-bg text-qg-accent' : 'border-qg-border-soft bg-qg-surface text-qg-text-mut'}`}>
            {badgeFor(type).letter} {count}
          </button>
        ))}
      </div>
```

In `App.tsx`: `const SCHEMA_LIMIT = 500`; state becomes `const [schemaFields, setSchemaFields] = useState<SchemaField[]>([])` populated from `response.fields`; pass `fields={schemaFields}`, `total={status ? totalMetricsOf(status) : undefined}` (move/duplicate the small helper), `lastAnswerNames={[]}` and `onAskAbout={() => {}}` for now (Task 6 wires them). Keep `unreachable` wiring as-is.

- [ ] **Step 5: Run the tests + suite**

Run: `npm test -- --run`
Expected: all pass (including updated App tests if any referenced `items`)

- [ ] **Step 6: Commit**

```bash
git add src/ui/tokens.css src/playground/SchemaRail.tsx src/playground/SchemaRail.test.tsx src/playground/App.tsx
git commit -m "feat(playground): typed schema rail with badges and type filters"
```

---

### Task 6: Prefix groups, expansion card, IN LAST ANSWER

**Files:**
- Modify: `frontend/src/playground/SchemaRail.tsx`
- Modify: `frontend/src/playground/App.tsx`
- Test: `frontend/src/playground/SchemaRail.test.tsx`

**Interfaces:**
- Consumes: Task 5's `SchemaRailProps` (already includes `lastAnswerNames`, `onAskAbout`).
- Produces: App passes `lastAnswerNames={answer?.outcome === 'answered' ? answer.schema_used : []}` and `onAskAbout` that pre-fills + focuses the `#qg-ask` input.

- [ ] **Step 1: Write the failing tests** — append to `SchemaRail.test.tsx`:

```tsx
  it('groups by prefix, collapsed by default, expandable', () => {
    render(<SchemaRail fields={FIELDS} total={4} status={null} unreachable={false} lastAnswerNames={[]} onAskAbout={noop} />)
    expect(screen.getByText('go_*')).toBeInTheDocument()
    expect(screen.queryByText('go_goroutines')).not.toBeInTheDocument()  // collapsed
    fireEvent.click(screen.getByRole('button', { name: /go_\*/ }))
    expect(screen.getByText('go_goroutines')).toBeInTheDocument()
  })

  it('pins schema_used names in an expanded IN LAST ANSWER group', () => {
    render(
      <SchemaRail fields={FIELDS} total={4} status={null} unreachable={false}
        lastAnswerNames={['prometheus_http_request_duration_seconds']} onAskAbout={noop} />,
    )
    expect(screen.getByText('IN LAST ANSWER')).toBeInTheDocument()
    expect(screen.getByText('prometheus_http_request_duration_seconds')).toBeInTheDocument()
  })

  it('clicking a row expands a card with labels, help, and ask-about', () => {
    const onAskAbout = vi.fn()
    render(
      <SchemaRail fields={FIELDS} total={4} status={null} unreachable={false}
        lastAnswerNames={['prometheus_http_request_duration_seconds']} onAskAbout={onAskAbout} />,
    )
    fireEvent.click(screen.getByRole('button', { name: /duration_seconds.*histogram/ }))
    expect(screen.getByText('handler')).toBeInTheDocument()
    expect(screen.getByText('Latencies.')).toBeInTheDocument()
    fireEvent.click(screen.getByText(/ask about this metric/))
    expect(onAskAbout).toHaveBeenCalledWith('prometheus_http_request_duration_seconds')
  })

  it('an active filter flattens groups into one list', () => {
    render(<SchemaRail fields={FIELDS} total={4} status={null} unreachable={false} lastAnswerNames={[]} onAskAbout={noop} />)
    fireEvent.change(screen.getByPlaceholderText('filter metrics…'), { target: { value: 'go_' } })
    expect(screen.queryByText('go_*')).not.toBeInTheDocument()
    expect(screen.getByText('go_goroutines')).toBeInTheDocument()
  })
```

- [ ] **Step 2: Run to verify failure**

Run: `npm test -- --run src/playground/SchemaRail.test.tsx`
Expected: new tests FAIL

- [ ] **Step 3: Implement grouping in `SchemaRail.tsx`.** Grouping applies only when no text filter and no type chip is active (spec A2.5). Group key = first `_` token; groups sorted by descending count; expansion state is a `Set<string>`; one expanded field at a time:

```tsx
  const [openGroups, setOpenGroups] = useState<Set<string>>(new Set())
  const [expandedField, setExpandedField] = useState<string | null>(null)

  const filtering = filter.trim() !== '' || typeFilter !== null

  const lastAnswerFields = useMemo(
    () => lastAnswerNames
      .map((name) => fields.find((field) => field.name === name) ?? { name, type: '', kind: 'metric', labels: [], help: '', backend: '' })
      .filter((field, i, all) => all.findIndex((other) => other.name === field.name) === i),
    [fields, lastAnswerNames],
  )

  const groups = useMemo(() => {
    const map = new Map<string, SchemaField[]>()
    for (const field of visible) {
      const key = field.name.split('_')[0]
      const bucket = map.get(key)
      if (bucket) bucket.push(field)
      else map.set(key, [field])
    }
    return [...map.entries()].sort((a, b) => b[1].length - a[1].length)
  }, [visible])
```

Group header (a button; chevron ▸/▾ as text spans are fine — they are typography, not icons):

```tsx
function GroupHeader({ prefix, count, open, onToggle }: { prefix: string; count: number; open: boolean; onToggle: () => void }) {
  return (
    <button type="button" onClick={onToggle} aria-expanded={open}
      className="flex w-full cursor-pointer items-center gap-1.5 px-1.5 pb-1 pt-2 text-left text-[10.5px] font-semibold tracking-[0.08em] text-qg-text-faint">
      <span aria-hidden="true" className="text-[9px]">{open ? '▾' : '▸'}</span>
      {prefix}_* <span className="font-mono font-medium tracking-normal">{count}</span>
    </button>
  )
}
```

Expansion card rendered directly under its row when `expandedField === field.name`:

```tsx
function ExpandCard({ field, onAskAbout }: { field: SchemaField; onAskAbout: (name: string) => void }) {
  return (
    <div className="mx-1.5 mb-1.5 mt-0.5 flex flex-col gap-2 rounded-[11px] border border-qg-border bg-qg-surface p-3">
      <span className="break-all font-mono text-[12px] font-medium text-qg-text">{field.name}</span>
      {field.labels.length > 0 && (
        <div className="flex flex-wrap gap-1">
          {field.labels.map((label) => (
            <span key={label} className="rounded-full border border-qg-border-soft bg-qg-surface2 px-2 py-[3px] font-mono text-[10.5px] text-qg-text-mut">
              {label}
            </span>
          ))}
        </div>
      )}
      {field.help && <span className="text-[11.5px] leading-[1.5] text-qg-text-faint">{field.help}</span>}
      <button type="button" onClick={() => onAskAbout(field.name)}
        className="cursor-pointer text-left text-[11.5px] font-medium text-qg-accent">
        ↳ ask about this metric
      </button>
    </div>
  )
}
```

Render order in the list area: (1) IN LAST ANSWER group when `lastAnswerFields.length > 0` — header is a static label (`IN LAST ANSWER <count>`), always expanded, rows `hot`; (2) when `filtering`, the flat `visible` list from Task 5; (3) otherwise the prefix groups, rows only when `openGroups.has(prefix)`. Every row click toggles `expandedField` between `field.name` and `null`.

In `App.tsx`: wire the two live props —

```tsx
  const [seed, setSeed] = useState('')  // pre-fill for AskBar
  const lastAnswerNames = state.kind === 'answered' ? state.answer.schema_used : []
  const askAbout = (name: string) => {
    setSeed(name)
    document.getElementById('qg-ask')?.focus()
  }
```

`AskBar` gains a `seed` prop: `useEffect(() => { if (seed) setValue(seed) }, [seed])`. Pass `lastAnswerNames={lastAnswerNames}` and `onAskAbout={askAbout}` to the rail.

- [ ] **Step 4: Run the suite**

Run: `npm test -- --run`
Expected: all pass

- [ ] **Step 5: Commit**

```bash
git add src/playground/SchemaRail.tsx src/playground/SchemaRail.test.tsx src/playground/App.tsx
git commit -m "feat(playground): prefix groups, expansion cards, IN LAST ANSWER"
```

---

### Task 7: `resultView` slot + BarChart + chart/rows toggle

**Files:**
- Modify: `frontend/src/widget/Panel.tsx`
- Create: `frontend/src/playground/BarChart.tsx`
- Create: `frontend/src/playground/BarChart.test.tsx`
- Modify: `frontend/src/playground/App.tsx`
- Test: also extend `frontend/src/widget/Panel.test.tsx`

**Interfaces:**
- Consumes: `parseVector`/`formatValue` from Task 3.
- Produces (Phase B reuses both): `PanelProps.resultView?: (answer: SearchResponse) => ReactNode | null`; `BarChart({ rows }: { rows: VectorRow[] })`. The toggle lives INSIDE Panel and only renders when `resultView` returned non-null.

- [ ] **Step 1: Write the failing tests.**

`frontend/src/playground/BarChart.test.tsx`:

```tsx
import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { BarChart } from './BarChart'

const ROWS = [
  { label: '/api/v1/series', value: 26.8, raw: '26.842' },
  { label: '/metrics', value: 0.667, raw: '0.667' },
]

describe('BarChart', () => {
  it('renders one labelled bar per row with a summary aria-label', () => {
    render(<BarChart rows={ROWS} />)
    expect(screen.getByText('/api/v1/series')).toBeInTheDocument()
    expect(screen.getByText('26.8')).toBeInTheDocument()
    expect(screen.getByRole('img', { name: /2 rows.*\/api\/v1\/series.*26.8/ })).toBeInTheDocument()
  })

  it('scales bar widths against the max', () => {
    render(<BarChart rows={ROWS} />)
    const fills = document.querySelectorAll('[data-testid="qg-bar-fill"]')
    expect((fills[0] as HTMLElement).style.width).toBe('100%')
    expect(parseFloat((fills[1] as HTMLElement).style.width)).toBeLessThan(5)
  })
})
```

Append to `frontend/src/widget/Panel.test.tsx` (match its existing render helpers/style):

```tsx
  it('renders resultView output with a chart/rows toggle, and rows when toggled', () => {
    const answer = answeredResponse()  // reuse the file's existing answered fixture builder
    render(
      <Panel state={{ kind: 'answered', answer }} onAsk={noop} onClose={noop} suggestions={[]}
        resultView={() => <div data-testid="custom-chart" />} />,
    )
    expect(screen.getByTestId('custom-chart')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'rows' }))
    expect(screen.queryByTestId('custom-chart')).not.toBeInTheDocument()
  })

  it('shows no toggle and plain rows when resultView is absent or returns null', () => {
    const answer = answeredResponse()
    render(
      <Panel state={{ kind: 'answered', answer }} onAsk={noop} onClose={noop} suggestions={[]}
        resultView={() => null} />,
    )
    expect(screen.queryByRole('button', { name: 'chart' })).not.toBeInTheDocument()
  })
```

(If the file has no `answeredResponse` helper, add one returning a full `SearchResponse` with `outcome: 'answered'` and a two-row vector result.)

- [ ] **Step 2: Run to verify failure**

Run: `npm test -- --run src/playground/BarChart.test.tsx src/widget/Panel.test.tsx`
Expected: FAIL

- [ ] **Step 3: Implement.**

`frontend/src/playground/BarChart.tsx`:

```tsx
import type { VectorRow } from '../lib/resultData'
import { formatValue } from '../lib/resultData'

/**
 * Hand-rolled horizontal bar chart for instant vectors. Playground-only —
 * reaches the shared Panel through its resultView slot so the widget bundle
 * never imports it. Rows arrive pre-sorted descending from parseVector.
 */
export function BarChart({ rows }: { rows: VectorRow[] }) {
  const max = rows[0]?.value ?? 0
  const summary = `bar chart, ${rows.length} rows, max ${rows[0]?.label ?? ''} at ${formatValue(rows[0]?.raw ?? '')}`
  return (
    <div role="img" aria-label={summary} className="flex flex-col gap-[7px]">
      {rows.map((row, i) => {
        const width = max > 0 ? `${Math.max((row.value / max) * 100, 1.5)}%` : '1.5%'
        return (
          <div key={i} className="grid grid-cols-[168px_1fr_64px] items-center gap-2.5">
            <span className="truncate text-right font-mono text-[11.5px] text-qg-text-mut">{row.label}</span>
            <span className="h-4 overflow-hidden rounded-[5px] bg-qg-surface2">
              <span
                data-testid="qg-bar-fill"
                className="block h-full rounded-[5px]"
                style={{ width, background: i === 0 ? 'var(--qg-bar)' : 'var(--qg-bar-soft)' }}
              />
            </span>
            <span className={`font-mono text-[11.5px] ${i === 0 ? 'font-semibold text-qg-accent' : 'font-medium text-qg-text-mut'}`}>
              {formatValue(row.raw)}
            </span>
          </div>
        )
      })}
    </div>
  )
}
```

`Panel.tsx` — add to `PanelProps`:

```tsx
import type { ReactNode } from 'react'
// …
  /** Playground-only alternative renderer for an answered result. Receives the
   *  raw answer; returning null falls back to ResultRows, so the slot never
   *  has to handle shapes it doesn't recognise. Widget builds leave it unset
   *  and the chart code is tree-shaken out of the bundle. */
  resultView?: (answer: SearchResponse) => ReactNode | null
```

Inside the answered branch (state resets per answer via the existing `key={state.kind}` remount plus a `useEffect` on `state`):

```tsx
  const [view, setView] = useState<'chart' | 'rows'>('chart')
  useEffect(() => setView('chart'), [state])
  // in the answered JSX:
  const chart = state.kind === 'answered' && resultView ? resultView(state.answer) : null
```

RESULT label row gains the toggle only when `chart !== null`:

```tsx
            <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
              <span style={sectionLabelStyle}>RESULT</span>
              {chart !== null && (
                <span style={{ marginLeft: 'auto', display: 'inline-flex', border: '1px solid var(--qg-border-soft)', borderRadius: 8, overflow: 'hidden' }}>
                  {(['chart', 'rows'] as const).map((mode) => (
                    <button key={mode} type="button" onClick={() => setView(mode)}
                      style={{ fontSize: '10.5px', fontWeight: 500, padding: '4px 10px', border: 'none', cursor: 'pointer',
                        background: view === mode ? 'var(--qg-surface2)' : 'transparent',
                        color: view === mode ? 'var(--qg-text)' : 'var(--qg-text-faint)' }}>
                      {mode}
                    </button>
                  ))}
                </span>
              )}
            </div>
            {chart !== null && view === 'chart' ? chart : <ResultRows result={state.answer.result} />}
```

`App.tsx` — pass the renderer (chart applicability rule from spec A3: vector, ≥2 rows):

```tsx
import { BarChart } from './BarChart'
import { parseVector } from '../lib/resultData'
// …
  const resultView = (answer: SearchResponse) => {
    const rows = parseVector(answer.result)
    if (!rows || rows.length < 2) return null
    return <BarChart rows={rows} />
  }
// …
  <Panel state={state} onAsk={ask} onClose={reset} suggestions={SUGGESTIONS} inline resultView={resultView} />
```

- [ ] **Step 4: Run the suite AND verify the widget budget**

Run: `npm test -- --run && npm run build:all`
Expected: all pass; the final line prints `widget.js gzipped: ~13.7 KB` — it must stay under 15 KB (spec: within ~1 KB of 13.7).

- [ ] **Step 5: Commit**

```bash
git add src/widget/Panel.tsx src/widget/Panel.test.tsx src/playground/BarChart.tsx src/playground/BarChart.test.tsx src/playground/App.tsx
git commit -m "feat(playground): result bar chart via Panel resultView slot"
```

---

### Task 8: Re-run button + cached-age meta line

**Files:**
- Modify: `frontend/src/widget/Panel.tsx`
- Test: `frontend/src/widget/Panel.test.tsx`

**Interfaces:**
- Consumes: `ask(question, {fresh})` from Task 4 — Panel's `onAsk` prop signature widens to `(question: string, opts?: { fresh?: boolean }) => void` (existing callers pass a compatible function since `useAsk.ask` already has this shape).

- [ ] **Step 1: Write the failing tests** — append to `Panel.test.tsx`:

```tsx
  it('re-runs the question fresh from the header refresh button', () => {
    const onAsk = vi.fn()
    // Panel keeps the asked question in local state: submit a suggestion while
    // idle, then rerender the same instance in the answered state.
    const { rerender } = render(
      <Panel state={{ kind: 'idle' }} onAsk={onAsk} onClose={noop} suggestions={['slowest routes today']} />,
    )
    fireEvent.click(screen.getByRole('button', { name: /slowest routes today/ }))
    rerender(
      <Panel state={{ kind: 'answered', answer: answeredResponse() }} onAsk={onAsk} onClose={noop} suggestions={[]} />,
    )
    fireEvent.click(screen.getByRole('button', { name: 're-run this question' }))
    expect(onAsk).toHaveBeenLastCalledWith('slowest routes today', { fresh: true })
  })

  it('hides the refresh button when no question was asked through the panel', () => {
    render(<Panel state={{ kind: 'answered', answer: answeredResponse() }} onAsk={noop} onClose={noop} suggestions={[]} />)
    expect(screen.queryByRole('button', { name: 're-run this question' })).not.toBeInTheDocument()
  })

  it('shows cache age on cached answers', () => {
    const answer = { ...answeredResponse(), cached: true, cache_age_s: 42 }
    render(<Panel state={{ kind: 'answered', answer }} onAsk={noop} onClose={noop} suggestions={[]} />)
    expect(screen.getByText(/cached 42s ago/)).toBeInTheDocument()
  })
```

- [ ] **Step 2: Run to verify failure**

Run: `npm test -- --run src/widget/Panel.test.tsx`
Expected: FAIL

- [ ] **Step 3: Implement in `Panel.tsx`.**

Widen the prop type:

```tsx
  onAsk: (question: string, opts?: { fresh?: boolean }) => void
```

Refresh icon-button in the answered header row (next to the ⌘K kbd; `question` is Panel's own state):

```tsx
function RefreshIcon() {
  return (
    <svg width="13" height="13" viewBox="0 0 16 16" fill="none" aria-hidden="true">
      <path d="M13.5 8a5.5 5.5 0 1 1-1.6-3.9M13.5 2.5v2.6h-2.6"
        stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  )
}
```

```tsx
          {state.kind === 'answered' && (
            <button type="button" aria-label="re-run this question"
              onClick={() => question && onAsk(question, { fresh: true })}
              style={{ width: 26, height: 26, borderRadius: 7, border: '1px solid var(--qg-border)',
                background: 'var(--qg-surface2)', color: 'var(--qg-text-mut)', cursor: 'pointer',
                display: 'inline-flex', alignItems: 'center', justifyContent: 'center' }}>
              <RefreshIcon />
            </button>
          )}
```

Meta line — extend the existing `grounded in …` span:

```tsx
              {state.answer.cached && state.answer.cache_age_s !== undefined && (
                <> · <span style={{ color: 'var(--qg-accent)' }}>cached {state.answer.cache_age_s}s ago</span></>
              )}
```

Decision (matches the tests above): the refresh button renders only when Panel's local `question` state is non-empty — `{state.kind === 'answered' && question && (<button …/>)}`. A Panel mounted directly into an answered state (only tests do this) simply shows no refresh button; the second test pins that.

- [ ] **Step 4: Run the suite + budget check**

Run: `npm test -- --run && npm run build:all`
Expected: pass; widget gzip still < 15 KB

- [ ] **Step 5: Commit**

```bash
git add src/widget/Panel.tsx src/widget/Panel.test.tsx
git commit -m "feat(widget): fresh re-run button and cache-age meta"
```

---

### Task 9: Full gates + E2E verification

**Files:** none (verification only; fix regressions in place)

- [ ] **Step 1: Backend gates**

Run: `poetry run pytest -q && poetry run ruff check . && poetry run ruff format --check . && poetry run mypy src/queryglot --ignore-missing-imports`
Expected: all green

- [ ] **Step 2: Frontend gates**

Run (from `frontend/`): `npm test -- --run && npm run lint && npm run build:all`
Expected: all green; note the printed widget gzip size in the ledger

- [ ] **Step 3: Live E2E** — requires `queryglot-serve` on :8000 (and the mlx server on :8080 for real answers; if mlx is down, verify rail + chart with a cached/failed answer and note it):
  - Load `http://127.0.0.1:8000`, both themes: rail shows badges, chips, groups; expanding `prometheus_*` works; filter flattens.
  - Ask "slowest routes today": bar chart renders, toggle to rows and back, IN LAST ANSWER appears.
  - Click refresh: response re-runs (no `cached` chip), then re-ask: `cached Ns ago` appears.
  - Zero console messages.

- [ ] **Step 4: Commit any fixes; do not push** (the controller/user decides the push).
