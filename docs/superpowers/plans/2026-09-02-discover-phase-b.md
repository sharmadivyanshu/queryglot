# Discover Playground Phase B Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a global time window: `execute_range` on the Backend Protocol, `window_minutes` through engine and serve, a top-bar time-range picker, and a range histogram in the playground.

**Architecture:** The window is applied ONLY at the execute node — retrieve/compile/validate never see it, keeping prompt parity with the trained adapters. Prometheus implements `query_range`; other backends raise `NotImplementedError` and the engine falls back to instant `execute()`. The playground threads a preset picker through every ask and renders single-series matrices as a histogram via the existing `resultView` slot.

**Tech Stack:** Python 3.11 stdlib-HTTP backends + LangGraph state; React/Vite playground.

**Spec:** `docs/superpowers/specs/2026-09-02-discover-playground-design.md` (Phase B sections B1–B5 + Binding constraints)

**Depends on:** Phase A plan merged (`resultView` slot, `resultData.ts`, `fresh` support, structured rail).

## Global Constraints

- `prompts.SYSTEM` / `compile_prompt()` byte-identical before and after this plan (parity guard test in Task 3 enforces it).
- Widget bundle untouched: no time control, no histogram in the widget; gzip stays < 15 KB.
- All API changes additive. `window_minutes` presets: exactly `{5, 15, 30, 60, 180, 360, 1440}`; anything else → HTTP 400.
- Step formula: `step = max(15.0, (end - start) / 120)` — ≤ ~120 points.
- Cache key includes the window; `Instant` (no window) keys as `0`.
- No new runtime deps; charts are hand-rolled; ruff line-length 100, no suppressions.
- Gates identical to Phase A's Task 9.

---

### Task 1: `execute_range` — Protocol + Prometheus

**Files:**
- Modify: `src/queryglot/backends/__init__.py` (Protocol, ~line 35)
- Modify: `src/queryglot/backends/prometheus.py` (next to `execute`, ~line 302)
- Test: `tests/test_backends.py`

**Interfaces:**
- Produces: `Backend.execute_range(query: str, start: float, end: float, step: float) -> Execution`. Prometheus hits `POST {base}/api/v1/query_range` with form fields `query`, `start`, `end`, `step` (floats rendered via `str()`). Tasks 2–4 rely on the exact signature.

- [ ] **Step 1: Write the failing test** — append to `tests/test_backends.py` (uses the file's existing `Recorder` and `prom` helpers):

```python
def test_prometheus_execute_range_hits_query_range_with_window():
    recorder = Recorder(
        {
            "/api/v1/query_range": (
                200,
                {"status": "success", "data": {"resultType": "matrix", "result": []}},
            ),
        }
    )
    backend = PrometheusBackend("http://x:9090", transport=recorder)
    run = backend.execute_range("rate(up[1m])", start=1000.0, end=2800.0, step=30.0)
    assert run.ok
    method, url, body = recorder.requests[0]
    assert "query_range" in url
    from urllib.parse import parse_qs

    sent = parse_qs(body.decode())
    assert sent["query"] == ["rate(up[1m])"]
    assert sent["start"] == ["1000.0"]
    assert sent["end"] == ["2800.0"]
    assert sent["step"] == ["30.0"]


def test_prometheus_execute_range_surfaces_errors():
    backend = prom({"/api/v1/query_range": (400, {"status": "error", "error": "bad step"})})
    run = backend.execute_range("up", start=0.0, end=1.0, step=0.0)
    assert not run.ok and "bad step" in run.error
```

- [ ] **Step 2: Run to verify failure**

Run: `poetry run pytest tests/test_backends.py -q -k execute_range`
Expected: FAIL with `AttributeError: 'PrometheusBackend' object has no attribute 'execute_range'`

- [ ] **Step 3: Implement.**

`src/queryglot/backends/__init__.py` — add to the `Backend` Protocol after `execute`:

```python
    def execute_range(self, query: str, start: float, end: float, step: float) -> Execution:
        """Evaluate `query` over [start, end] epoch seconds at `step`-second
        resolution. Backends with no range concept raise NotImplementedError;
        the engine falls back to execute()."""
        ...
```

`src/queryglot/backends/prometheus.py` — after `execute`:

```python
    def execute_range(self, query: str, start: float, end: float, step: float) -> Execution:
        status, payload = post_form(
            self.transport,
            f"{self.base_url}/api/v1/query_range",
            {"query": query, "start": str(start), "end": str(end), "step": str(step)},
        )
        if payload.get("status") != "success":
            return Execution(ok=False, error=payload.get("error", f"HTTP {status}"))
        return Execution(ok=True, data=payload.get("data"))
```

- [ ] **Step 4: Run backends suite**

Run: `poetry run pytest tests/test_backends.py -q`
Expected: all pass

- [ ] **Step 5: Commit**

```bash
git add src/queryglot/backends/__init__.py src/queryglot/backends/prometheus.py tests/test_backends.py
git commit -m "feat(backends): execute_range on the Protocol, query_range for Prometheus"
```

---

### Task 2: Non-range backends raise; conftest fake gains ranges

**Files:**
- Modify: `src/queryglot/backends/elastic.py`, `src/queryglot/backends/openapi.py`
- Modify: `tests/conftest.py` (`FakeBackend`)
- Test: `tests/test_backends.py`

**Interfaces:**
- Produces: `ElasticBackend.execute_range` / `OpenAPIBackend.execute_range` raise `NotImplementedError("<name> backend has no range queries")`. `FakeBackend` gains `execute_range` recording `self.range_calls: list[tuple[str, float, float, float]]` and returning the same data as `execute` (so graph tests can assert which path ran). Set `FakeBackend.supports_range = True` attribute toggle: when `False`, `execute_range` raises `NotImplementedError`.

- [ ] **Step 1: Write the failing test** — append to `tests/test_backends.py`:

```python
import pytest


def test_elastic_execute_range_is_not_implemented():
    backend = ElasticBackend("http://x:9200", transport=Recorder({}))
    with pytest.raises(NotImplementedError):
        backend.execute_range("{}", 0.0, 1.0, 15.0)
```

- [ ] **Step 2: Run to verify failure**

Run: `poetry run pytest tests/test_backends.py::test_elastic_execute_range_is_not_implemented -v`
Expected: FAIL — `AttributeError`

- [ ] **Step 3: Implement.** In `elastic.py` (and identically in `openapi.py`, adjusting the name):

```python
    def execute_range(self, query: str, start: float, end: float, step: float) -> Execution:
        raise NotImplementedError("elasticsearch backend has no range queries")
```

In `tests/conftest.py`, add to `FakeBackend` (match its existing style — read the class first):

```python
    supports_range = True

    def execute_range(self, query: str, start: float, end: float, step: float) -> Execution:
        if not self.supports_range:
            raise NotImplementedError("fake backend range disabled")
        self.range_calls.append((query, start, end, step))
        return self.execute(query)
```

with `self.range_calls: list[tuple[str, float, float, float]] = []` initialised in `__init__`.

- [ ] **Step 4: Run the full backend + conftest-dependent suites**

Run: `poetry run pytest tests/test_backends.py tests/test_graph.py -q`
Expected: all pass

- [ ] **Step 5: Commit**

```bash
git add src/queryglot/backends/elastic.py src/queryglot/backends/openapi.py tests/conftest.py tests/test_backends.py
git commit -m "feat(backends): range unsupported markers + fake backend ranges"
```

---

### Task 3: Window through the graph (+ prompt-parity guard)

**Files:**
- Modify: `src/queryglot/graph.py` (`SearchState`, `execute` node)
- Test: `tests/test_graph.py`

**Interfaces:**
- Consumes: `FakeBackend.range_calls` / `supports_range` from Task 2.
- Produces: `SearchState` gains `window: dict` (`{"start": float, "end": float, "step": float}`); the execute node calls `backend.execute_range(...)` when `window` is in state, falling back to `backend.execute(...)` on `NotImplementedError`. Task 4 invokes the graph with `{"question": …, "window": …}`.

- [ ] **Step 1: Write the failing tests** — append to `tests/test_graph.py` (reuse its existing fixtures — read the file's imports/fixtures first; `catalog` + `ScriptedLLM` + `FakeBackend` conventions):

```python
def test_window_routes_execution_through_execute_range(catalog):
    backend = FakeBackend(valid={"GOOD"})
    graph = build_graph(backend, SchemaRetriever(catalog), ScriptedLLM("GOOD"))
    final = graph.invoke(
        {"question": "requests by handler", "window": {"start": 100.0, "end": 1900.0, "step": 30.0}}
    )
    assert final["outcome"] == "answered"
    assert backend.range_calls == [("GOOD", 100.0, 1900.0, 30.0)]


def test_window_on_rangeless_backend_falls_back_to_instant(catalog):
    backend = FakeBackend(valid={"GOOD"})
    backend.supports_range = False
    graph = build_graph(backend, SchemaRetriever(catalog), ScriptedLLM("GOOD"))
    final = graph.invoke(
        {"question": "requests by handler", "window": {"start": 100.0, "end": 1900.0, "step": 30.0}}
    )
    assert final["outcome"] == "answered"  # degraded gracefully, not failed


def test_window_never_reaches_the_compile_prompt(catalog):
    """Parity guard: the trained adapters saw prompts without any window text.
    The prompt for a windowed ask must be byte-identical to an instant ask's."""
    llm_instant, llm_windowed = ScriptedLLM("GOOD"), ScriptedLLM("GOOD")
    backend_a, backend_b = FakeBackend(valid={"GOOD"}), FakeBackend(valid={"GOOD"})
    build_graph(backend_a, SchemaRetriever(catalog), llm_instant).invoke(
        {"question": "requests by handler"}
    )
    build_graph(backend_b, SchemaRetriever(catalog), llm_windowed).invoke(
        {"question": "requests by handler", "window": {"start": 0.0, "end": 60.0, "step": 15.0}}
    )
    assert llm_instant.prompts == llm_windowed.prompts
```

(If `ScriptedLLM` does not record prompts, add `self.prompts: list[tuple[str, str]] = []` and an append in its `complete` — check `tests/conftest.py` first; it may already record.)

- [ ] **Step 2: Run to verify failure**

Run: `poetry run pytest tests/test_graph.py -q -k window`
Expected: FAIL (state key unknown / range_calls empty)

- [ ] **Step 3: Implement in `graph.py`.**

`SearchState` gains:

```python
    window: dict  # {"start": float, "end": float, "step": float} — execute-only
```

The `execute` node becomes:

```python
    def execute(state: SearchState) -> dict:
        window = state.get("window")
        if window:
            try:
                run = backend.execute_range(
                    state["query"], window["start"], window["end"], window["step"]
                )
            except NotImplementedError:
                run = backend.execute(state["query"])  # rangeless backend: degrade to instant
        else:
            run = backend.execute(state["query"])
        if run.ok:
            return {"result": run.data, "outcome": "answered"}
        return {"outcome": "failed", "reason": f"execution error: {run.error}"}
```

No other node changes — that absence IS the parity property the third test pins.

- [ ] **Step 4: Run graph suite**

Run: `poetry run pytest tests/test_graph.py -q`
Expected: all pass

- [ ] **Step 5: Commit**

```bash
git add src/queryglot/graph.py tests/test_graph.py tests/conftest.py
git commit -m "feat(graph): execute-only window with instant fallback and parity guard"
```

---

### Task 4: Engine `window_minutes` + `window` in the answer dict

**Files:**
- Modify: `src/queryglot/engine.py`
- Test: `tests/test_engine.py` (create if absent; check `ls tests/` — engine behavior may live in `tests/test_graph.py` or `tests/test_server.py`; put these in the file that already tests `Engine.search`, else create `tests/test_engine.py` importing conftest fixtures)

**Interfaces:**
- Consumes: graph `window` state key (Task 3).
- Produces: `Engine.search(question, backend=None, window_minutes: int | None = None) -> Answer`; `Answer.window: dict | None = None`; `as_dict()` includes `"window": {"minutes": m, "step_s": s}` ONLY when a window ran. Task 5 (serve) consumes both.

- [ ] **Step 1: Write the failing tests**:

```python
import time


def test_engine_window_minutes_builds_epoch_window_and_reports_it():
    backend = IntrospectingBackend(valid={"GOOD"})  # or FakeBackend if retrieval-gated: use the pattern the file's existing Engine tests use for an answered flow
    engine = Engine([backend], llm=ScriptedLLM("GOOD"))
    before = time.time()
    answer = engine.search("p95 latency by route", window_minutes=30)
    after = time.time()
    assert answer.outcome == "answered"
    (query, start, end, step) = backend.range_calls[0]
    assert before - 1 <= end <= after + 1          # end ≈ now
    assert abs((end - start) - 30 * 60) < 1e-6     # 30-minute span
    assert step == max(15.0, (30 * 60) / 120)      # the spec's step formula
    assert answer.as_dict()["window"] == {"minutes": 30, "step_s": step}


def test_engine_without_window_omits_the_field_and_runs_instant():
    backend = IntrospectingBackend(valid={"GOOD"})
    engine = Engine([backend], llm=ScriptedLLM("GOOD"))
    answer = engine.search("p95 latency by route")
    assert backend.range_calls == []
    assert "window" not in answer.as_dict() or answer.as_dict().get("window") is None
```

(`IntrospectingBackend` currently lives in `tests/test_server.py`; move it into `tests/conftest.py` as part of this task so both files share it, and update `test_server.py` imports. It must inherit `FakeBackend`'s new `range_calls`.)

- [ ] **Step 2: Run to verify failure**

Run: `poetry run pytest -q -k engine_window`
Expected: FAIL — unexpected keyword `window_minutes`

- [ ] **Step 3: Implement in `engine.py`.**

`Answer` gains a field and conditional dict entry:

```python
@dataclass
class Answer:
    # …existing fields…
    window: dict | None = None

    def as_dict(self) -> dict:
        payload = {
            # …existing keys unchanged…
        }
        if self.window is not None:
            payload["window"] = self.window
        return payload
```

`search` gains the parameter and window computation (`import time` at top):

```python
    def search(
        self, question: str, backend: str | None = None, window_minutes: int | None = None
    ) -> Answer:
        # …existing backend resolution unchanged…
        state: dict = {"question": question}
        window_info = None
        if window_minutes is not None:
            end = time.time()
            start = end - window_minutes * 60
            step = max(15.0, (end - start) / 120)
            state["window"] = {"start": start, "end": end, "step": step}
            window_info = {"minutes": window_minutes, "step_s": step}
        final = self._graphs[name].invoke(state)
        return Answer(
            # …existing kwargs unchanged…
            window=window_info,
        )
```

- [ ] **Step 4: Run the full backend suite**

Run: `poetry run pytest -q`
Expected: all pass

- [ ] **Step 5: Commit**

```bash
git add src/queryglot/engine.py tests/ 
git commit -m "feat(engine): window_minutes with step formula, window echoed in answers"
```

---

### Task 5: Serve — `window_minutes` validation, cache key, matrix-aware summary

**Files:**
- Modify: `src/queryglot/server.py`
- Test: `tests/test_server.py`

**Interfaces:**
- Consumes: `Engine.search(..., window_minutes=...)` (Task 4).
- Produces: `POST /api/search` accepts `"window_minutes"`; presets `WINDOW_PRESETS = {5, 15, 30, 60, 180, 360, 1440}` (module constant); cache key `(question, backend, window_minutes or 0)`; `/api/summary` downsamples matrix results. Task 6 mirrors the request field.

- [ ] **Step 1: Write the failing tests** — append to `tests/test_server.py`:

```python
def test_search_rejects_non_preset_windows():
    engine = Engine([IntrospectingBackend(valid={"GOOD"})], llm=ScriptedLLM("GOOD"))
    client = TestClient(create_app(engine))
    response = client.post("/api/search", json={"question": "q", "window_minutes": 7})
    assert response.status_code == 400
    assert "window" in response.json()["detail"]


def test_cache_keys_separate_windows():
    llm = CountingLLM("GOOD")
    engine = Engine([IntrospectingBackend(valid={"GOOD"})], llm=llm)
    client = TestClient(create_app(engine))
    client.post("/api/search", json={"question": "p95 latency by route"})
    calls = len(llm.calls)
    windowed = client.post(
        "/api/search", json={"question": "p95 latency by route", "window_minutes": 30}
    ).json()
    assert "cached" not in windowed          # different window → not a cache hit
    assert len(llm.calls) > calls
    hit = client.post(
        "/api/search", json={"question": "p95 latency by route", "window_minutes": 30}
    ).json()
    assert hit["cached"] is True             # same window → hit


def test_summary_downsamples_matrix_results():
    class RecordingLLM:
        def __init__(self):
            self.prompts: list[tuple[str, str]] = []

        def complete(self, system: str, prompt: str) -> str:
            self.prompts.append((system, prompt))
            return "peaked earlier."

    llm = RecordingLLM()
    engine = Engine([FakeBackend(valid={"GOOD"})], llm=ScriptedLLM("GOOD"))
    client = TestClient(create_app(engine, summary_llm=llm))
    matrix = {
        "resultType": "matrix",
        "result": [
            {"metric": {"handler": "/api"},
             "values": [[100, "1.0"], [130, "84.2"], [160, "31.5"]]},
        ],
    }
    body = client.post(
        "/api/summary",
        json={"question": "request rate", "query": "rate(x[1m])", "result": matrix},
    ).json()
    assert body["summary"] == "peaked earlier."
    prompt = llm.prompts[0][1]
    assert "84.2" in prompt and "31.5" in prompt      # peak + latest survive
    assert '"values"' not in prompt                    # raw matrix did not
```

- [ ] **Step 2: Run to verify failure**

Run: `poetry run pytest tests/test_server.py -q -k "preset or separate_windows or downsamples"`
Expected: 3 FAIL

- [ ] **Step 3: Implement in `server.py`.**

```python
WINDOW_PRESETS = {5, 15, 30, 60, 180, 360, 1440}


class SearchRequest(BaseModel):
    question: str
    backend: str | None = None
    fresh: bool = False
    window_minutes: int | None = None
```

`cache_key` and the search route:

```python
    def cache_key(request: SearchRequest) -> tuple[str, str, int]:
        return (
            " ".join(request.question.lower().split()),
            request.backend or "",
            request.window_minutes or 0,
        )
```

At the top of the `search` route body (before the cache lookup):

```python
        if request.window_minutes is not None and request.window_minutes not in WINDOW_PRESETS:
            raise HTTPException(
                status_code=400,
                detail=f"window_minutes must be one of {sorted(WINDOW_PRESETS)}",
            )
```

and pass it through: `engine.search(request.question, backend=request.backend, window_minutes=request.window_minutes)`.

Summary downsampling — a module-level helper + use in the summary route where `data` is built today:

```python
def _downsample_matrix(result: object) -> object:
    """Matrix payloads are too big for an 80-token summary prompt. Reduce each
    series to what a one-sentence answer can actually use: latest, peak, and
    when the peak happened. Non-matrix results pass through untouched."""
    if not (isinstance(result, dict) and result.get("resultType") == "matrix"):
        return result
    series_out = []
    for series in result.get("result", []):
        values = [(float(t), float(v)) for t, v in series.get("values", []) if v is not None]
        if not values:
            continue
        peak_t, peak_v = max(values, key=lambda tv: tv[1])
        series_out.append(
            {
                "labels": series.get("metric", {}),
                "latest": values[-1][1],
                "peak": peak_v,
                "peak_at_epoch_s": peak_t,
            }
        )
    return {"series": series_out}
```

In the summary route: `data = json.dumps(_downsample_matrix(request.result), default=str)[:1500]`.

- [ ] **Step 4: Run the server suite**

Run: `poetry run pytest tests/test_server.py -q`
Expected: all pass

- [ ] **Step 5: Commit**

```bash
git add src/queryglot/server.py tests/test_server.py
git commit -m "feat(serve): window presets, windowed cache keys, matrix summary downsample"
```

---

### Task 6: Frontend lib — `window_minutes` + `parseMatrix`

**Files:**
- Modify: `frontend/src/lib/api.ts`, `frontend/src/lib/useAsk.ts`
- Modify: `frontend/src/lib/resultData.ts`
- Test: `frontend/src/lib/resultData.test.ts`, `frontend/src/lib/api.test.ts`

**Interfaces:**
- Produces:

```ts
// api.ts
export interface WindowInfo { minutes: number; step_s: number }
// SearchResponse gains: window?: WindowInfo
// Client.search(question, backend?, fresh?, windowMinutes?)
// useAsk: ask(question, opts?: { fresh?: boolean }); useAsk(client, backend?, windowMinutes?)
//   — windowMinutes is a hook argument (playground state), applied to every ask.

// resultData.ts
export interface MatrixSeries { labels: Record<string, string>; points: [number, number][] }
export function parseMatrix(result: unknown): MatrixSeries[] | null
```

- [ ] **Step 1: Write the failing tests.**

Append to `resultData.test.ts`:

```ts
import { parseMatrix } from './resultData'

describe('parseMatrix', () => {
  it('parses matrix envelopes into typed series', () => {
    const matrix = {
      resultType: 'matrix',
      result: [{ metric: { handler: '/api' }, values: [[100, '1.5'], [130, '84.2']] }],
    }
    const series = parseMatrix(matrix)
    expect(series).toHaveLength(1)
    expect(series![0].labels).toEqual({ handler: '/api' })
    expect(series![0].points).toEqual([[100, 1.5], [130, 84.2]])
  })

  it('returns null for vectors and garbage', () => {
    expect(parseMatrix({ resultType: 'vector', result: [] })).toBeNull()
    expect(parseMatrix(null)).toBeNull()
  })
})
```

Append to `api.test.ts`:

```ts
  it('sends window_minutes when provided', async () => {
    const fetchFn = mockFetch({ outcome: 'answered' })
    const client = createClient({ api: '' })
    await client.search('q', undefined, false, 30)
    expect(JSON.parse(fetchFn.mock.calls[0][1].body as string).window_minutes).toBe(30)
  })
```

- [ ] **Step 2: Run to verify failure**

Run: `npm test -- --run src/lib/resultData.test.ts src/lib/api.test.ts`
Expected: FAIL

- [ ] **Step 3: Implement.**

`resultData.ts` (reuses the private `unwrap(result, 'matrix')` from Phase A):

```ts
export interface MatrixSeries {
  labels: Record<string, string>
  points: [number, number][]
}

interface MatrixSample {
  metric: Record<string, string>
  values: [number | string, string][]
}

function isMatrix(result: unknown): result is MatrixSample[] {
  return (
    Array.isArray(result) &&
    result.every(
      (item) =>
        typeof item === 'object' && item !== null &&
        'metric' in item && 'values' in item &&
        Array.isArray((item as { values: unknown }).values),
    )
  )
}

export function parseMatrix(result: unknown): MatrixSeries[] | null {
  if (typeof result !== 'object' || result === null || (result as { resultType?: unknown }).resultType !== 'matrix') {
    return null
  }
  const inner = unwrap(result, 'matrix')
  if (!isMatrix(inner)) return null
  return inner.map((series) => ({
    labels: series.metric,
    points: series.values.map(([t, v]) => [Number(t), Number(v)] as [number, number]),
  }))
}
```

`api.ts`: add `WindowInfo`, `window?: WindowInfo` on `SearchResponse`, and the fourth `search` param serialised as `window_minutes` only when set:

```ts
    search(question, backend, fresh, windowMinutes) {
      const body: Record<string, unknown> = { question, backend }
      if (fresh) body.fresh = true
      if (windowMinutes !== undefined) body.window_minutes = windowMinutes
      return request<SearchResponse>(`${api}/api/search`, token, {
        method: 'POST',
        body: JSON.stringify(body),
      })
    },
```

(Adjust Phase A's `api.test.ts` fresh-shape assertion if it pinned the exact body object — the no-options body is now `{question, backend}` still, so it should hold.)

`useAsk.ts`: signature `export function useAsk(client: Client, backend?: string, windowMinutes?: number)`; the search call becomes `client.search(question, backend, opts?.fresh, windowMinutes)`; add `windowMinutes` to the `ask` callback's dependency array.

- [ ] **Step 4: Run frontend suite + lint**

Run: `npm test -- --run && npm run lint`
Expected: pass

- [ ] **Step 5: Commit**

```bash
git add src/lib/api.ts src/lib/api.test.ts src/lib/useAsk.ts src/lib/resultData.ts src/lib/resultData.test.ts
git commit -m "feat(frontend): window_minutes plumbing and matrix parsing"
```

---

### Task 7: TimeRange control in the top bar

**Files:**
- Create: `frontend/src/playground/TimeRange.tsx`
- Create: `frontend/src/playground/TimeRange.test.tsx`
- Modify: `frontend/src/playground/TopBar.tsx`, `frontend/src/playground/App.tsx`

**Interfaces:**
- Consumes: `useAsk(client, backend?, windowMinutes?)` from Task 6.
- Produces:

```ts
export const WINDOW_PRESETS = [
  { minutes: undefined, label: 'Instant' },
  { minutes: 5, label: 'Last 5 minutes' },
  { minutes: 15, label: 'Last 15 minutes' },
  { minutes: 30, label: 'Last 30 minutes' },
  { minutes: 60, label: 'Last 1 hour' },
  { minutes: 180, label: 'Last 3 hours' },
  { minutes: 360, label: 'Last 6 hours' },
  { minutes: 1440, label: 'Last 24 hours' },
] as const

export interface TimeRangeProps {
  windowMinutes: number | undefined
  onChange: (minutes: number | undefined) => void
  onRefresh: () => void
}
export function TimeRange(props: TimeRangeProps): JSX.Element
```

- [ ] **Step 1: Write the failing tests** — `TimeRange.test.tsx`:

```tsx
import { render, screen, fireEvent } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { TimeRange } from './TimeRange'

describe('TimeRange', () => {
  it('shows the active preset and opens the menu', () => {
    render(<TimeRange windowMinutes={30} onChange={vi.fn()} onRefresh={vi.fn()} />)
    fireEvent.click(screen.getByRole('button', { name: /Last 30 minutes/ }))
    expect(screen.getByRole('menu')).toBeInTheDocument()
    expect(screen.getByRole('menuitem', { name: 'Instant' })).toBeInTheDocument()
  })

  it('selecting a preset fires onChange and closes', () => {
    const onChange = vi.fn()
    render(<TimeRange windowMinutes={undefined} onChange={onChange} onRefresh={vi.fn()} />)
    fireEvent.click(screen.getByRole('button', { name: /Instant/ }))
    fireEvent.click(screen.getByRole('menuitem', { name: 'Last 1 hour' }))
    expect(onChange).toHaveBeenCalledWith(60)
    expect(screen.queryByRole('menu')).not.toBeInTheDocument()
  })

  it('escape closes the menu; refresh fires onRefresh', () => {
    const onRefresh = vi.fn()
    render(<TimeRange windowMinutes={15} onChange={vi.fn()} onRefresh={onRefresh} />)
    fireEvent.click(screen.getByRole('button', { name: /Last 15 minutes/ }))
    fireEvent.keyDown(document, { key: 'Escape' })
    expect(screen.queryByRole('menu')).not.toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Refresh' }))
    expect(onRefresh).toHaveBeenCalled()
  })
})
```

- [ ] **Step 2: Run to verify failure**

Run: `npm test -- --run src/playground/TimeRange.test.tsx`
Expected: FAIL — module not found

- [ ] **Step 3: Implement `TimeRange.tsx`** — segmented control (clock icon + preset dropdown + Refresh), popover as an absolutely-positioned list under the control:

```tsx
import { useEffect, useRef, useState } from 'react'

export const WINDOW_PRESETS = [
  { minutes: undefined, label: 'Instant' },
  { minutes: 5, label: 'Last 5 minutes' },
  { minutes: 15, label: 'Last 15 minutes' },
  { minutes: 30, label: 'Last 30 minutes' },
  { minutes: 60, label: 'Last 1 hour' },
  { minutes: 180, label: 'Last 3 hours' },
  { minutes: 360, label: 'Last 6 hours' },
  { minutes: 1440, label: 'Last 24 hours' },
] as const

function ClockIcon() {
  return (
    <svg width="13" height="13" viewBox="0 0 16 16" fill="none" aria-hidden="true">
      <circle cx="8" cy="8" r="6" stroke="currentColor" strokeWidth="1.5" />
      <path d="M8 4.5V8l2.5 1.5" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
    </svg>
  )
}

function RefreshIcon() {
  return (
    <svg width="13" height="13" viewBox="0 0 16 16" fill="none" aria-hidden="true">
      <path d="M13.5 8a5.5 5.5 0 1 1-1.6-3.9M13.5 2.5v2.6h-2.6"
        stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  )
}

export interface TimeRangeProps {
  windowMinutes: number | undefined
  onChange: (minutes: number | undefined) => void
  onRefresh: () => void
}

export function TimeRange({ windowMinutes, onChange, onRefresh }: TimeRangeProps) {
  const [open, setOpen] = useState(false)
  const rootRef = useRef<HTMLDivElement>(null)
  const active = WINDOW_PRESETS.find((preset) => preset.minutes === windowMinutes) ?? WINDOW_PRESETS[0]

  useEffect(() => {
    if (!open) return
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') setOpen(false)
    }
    const onClick = (event: MouseEvent) => {
      if (rootRef.current && !rootRef.current.contains(event.target as Node)) setOpen(false)
    }
    document.addEventListener('keydown', onKey)
    document.addEventListener('mousedown', onClick)
    return () => {
      document.removeEventListener('keydown', onKey)
      document.removeEventListener('mousedown', onClick)
    }
  }, [open])

  return (
    <div ref={rootRef} className="relative">
      <div className="flex items-stretch overflow-hidden rounded-[10px] border border-qg-border bg-qg-surface2">
        <button type="button" onClick={() => setOpen((value) => !value)} aria-expanded={open} aria-haspopup="menu"
          className="flex cursor-pointer items-center gap-2 px-3 py-[7px] text-[12.5px] font-medium text-qg-text">
          <span className="text-qg-text-mut"><ClockIcon /></span>
          {active.label}
          <span aria-hidden="true" className="text-[10px] text-qg-text-faint">▾</span>
        </button>
        <button type="button" onClick={onRefresh} aria-label="Refresh"
          className="flex cursor-pointer items-center gap-1.5 border-l border-qg-border px-3 py-[7px] text-[12.5px] font-medium text-qg-accent">
          <RefreshIcon /> Refresh
        </button>
      </div>
      {open && (
        <div role="menu"
          className="absolute right-0 top-[calc(100%+6px)] z-20 flex min-w-[180px] flex-col rounded-[10px] border border-qg-border bg-qg-surface p-1 shadow-qg">
          {WINDOW_PRESETS.map((preset) => (
            <button key={preset.label} role="menuitem" type="button"
              onClick={() => { onChange(preset.minutes); setOpen(false) }}
              className={`cursor-pointer rounded-lg px-3 py-2 text-left text-[12.5px] ${preset.minutes === windowMinutes ? 'bg-qg-surface2 text-qg-text' : 'text-qg-text-mut hover:bg-qg-surface2'}`}>
              {preset.label}
            </button>
          ))}
        </div>
      )}
    </div>
  )
}
```

Wire it: `TopBar` gains `children?: ReactNode` rendered before the backend chips (or accept the three TimeRange props and render it — prefer `children` to keep TopBar dumb). In `App.tsx`:

```tsx
  const [windowMinutes, setWindowMinutes] = useState<number | undefined>(undefined)
  const { state, ask, reset } = useAsk(client, undefined, windowMinutes)
  const lastQuestion = useRef('')
  const askTracked = (question: string, opts?: { fresh?: boolean }) => { lastQuestion.current = question; ask(question, opts) }
  const refresh = () => { if (lastQuestion.current) ask(lastQuestion.current, { fresh: true }) }
  const changeWindow = (minutes: number | undefined) => {
    setWindowMinutes(minutes)
    // re-run the current question under the new window (spec B3) — the hook arg
    // updates on next render, so pass through a microtask:
    if (lastQuestion.current) setTimeout(() => ask(lastQuestion.current, { fresh: true }), 0)
  }
```

Replace `ask` with `askTracked` at the AskBar/Panel call sites, and render `<TimeRange windowMinutes={windowMinutes} onChange={changeWindow} onRefresh={refresh} />` inside TopBar's right cluster.

(Note the `setTimeout(0)` is a pragmatic re-run under the new hook arg; if flaky in tests, lift `windowMinutes` into a ref read inside `useAsk`'s ask — either is acceptable, pick one and test it.)

- [ ] **Step 4: Run the suite**

Run: `npm test -- --run && npm run lint`
Expected: pass

- [ ] **Step 5: Commit**

```bash
git add src/playground/TimeRange.tsx src/playground/TimeRange.test.tsx src/playground/TopBar.tsx src/playground/App.tsx
git commit -m "feat(playground): global time-range picker with refresh"
```

---

### Task 8: Histogram + range-aware query block and trace

**Files:**
- Create: `frontend/src/playground/Histogram.tsx`
- Create: `frontend/src/playground/Histogram.test.tsx`
- Modify: `frontend/src/playground/App.tsx` (resultView matrix branch)
- Modify: `frontend/src/widget/ResultRows.tsx` (multi-series matrix → latest-value rows, spec B4)
- Modify: `frontend/src/widget/QueryBlock.tsx` (optional range suffix)
- Modify: `frontend/src/playground/TracePanel.tsx`

**Interfaces:**
- Consumes: `parseMatrix`/`MatrixSeries` (Task 6), `resultView` slot (Phase A), `SearchResponse.window` (Task 6).
- Produces: `Histogram({ series, stepSeconds }: { series: MatrixSeries; stepSeconds: number })`; `QueryBlock` gains optional `suffix?: string`; TracePanel's execute row reads `query_range · Nm` when `answer.window` is present.

- [ ] **Step 1: Write the failing tests** — `Histogram.test.tsx`:

```tsx
import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { Histogram } from './Histogram'

const SERIES = {
  labels: { handler: '/api' },
  points: [[100, 10], [130, 84.2], [160, 31.5]] as [number, number][],
}

describe('Histogram', () => {
  it('renders one bar per point with a summary aria-label naming the peak', () => {
    render(<Histogram series={SERIES} stepSeconds={30} />)
    expect(document.querySelectorAll('[data-testid="qg-hist-bar"]')).toHaveLength(3)
    expect(screen.getByRole('img', { name: /3 points.*peak 84.2/ })).toBeInTheDocument()
  })

  it('notes the interval and point count', () => {
    render(<Histogram series={SERIES} stepSeconds={30} />)
    expect(screen.getByText(/interval: 30 s · 3 points · peak highlighted/)).toBeInTheDocument()
  })
})
```

TracePanel — append to a `TracePanel.test.tsx` (create if absent, matching TopBar.test.tsx conventions):

```tsx
  it('labels execution as query_range with the window', () => {
    const answer = { ...answeredResponse(), window: { minutes: 30, step_s: 15 } }
    render(<TracePanel answer={answer} />)
    expect(screen.getByText('query_range · 30 min')).toBeInTheDocument()
    expect(screen.getByText(/window came from the picker/)).toBeInTheDocument()
  })
```

- [ ] **Step 2: Run to verify failure**

Run: `npm test -- --run src/playground/Histogram.test.tsx src/playground/TracePanel.test.tsx`
Expected: FAIL

- [ ] **Step 3: Implement.**

`Histogram.tsx` (bars are divs; heights relative to the series max; cap at 120 points by slicing evenly):

```tsx
import { useState } from 'react'
import type { MatrixSeries } from '../lib/resultData'
import { formatValue } from '../lib/resultData'

function timeLabel(epochSeconds: number): string {
  const date = new Date(epochSeconds * 1000)
  return `${String(date.getHours()).padStart(2, '0')}:${String(date.getMinutes()).padStart(2, '0')}`
}

export function Histogram({ series, stepSeconds }: { series: MatrixSeries; stepSeconds: number }) {
  const points = series.points.length > 120
    ? series.points.filter((_, i) => i % Math.ceil(series.points.length / 120) === 0)
    : series.points
  const [hover, setHover] = useState<number | null>(null)
  const max = Math.max(...points.map(([, value]) => value), 0)
  const peakIndex = points.findIndex(([, value]) => value === max)
  const first = points[0]?.[0] ?? 0
  const last = points[points.length - 1]?.[0] ?? 0
  const mid = points[Math.floor(points.length / 2)]?.[0] ?? 0
  const summary = `histogram, ${points.length} points, peak ${formatValue(String(max))} at ${timeLabel(points[peakIndex]?.[0] ?? 0)}`
  const shown = hover ?? peakIndex

  return (
    <div role="img" aria-label={summary} className="relative flex flex-col gap-1.5">
      {points[shown] && (
        <span className="self-start rounded-lg border border-qg-border bg-qg-surface px-2.5 py-1.5 font-mono text-[10.5px] text-qg-text-mut">
          <b className="font-semibold text-qg-text">{formatValue(String(points[shown][1]))}</b> · {timeLabel(points[shown][0])}
        </span>
      )}
      <div className="flex h-[120px] items-end gap-[3px] border-b border-qg-border-soft px-0.5 pt-1">
        {points.map(([, value], i) => (
          <span key={i} data-testid="qg-hist-bar"
            onMouseEnter={() => setHover(i)} onMouseLeave={() => setHover(null)}
            className="min-w-[3px] flex-1 rounded-t-[3px]"
            style={{ height: `${max > 0 ? Math.max((value / max) * 100, 2) : 2}%`,
              background: i === peakIndex ? 'var(--qg-bar)' : 'var(--qg-bar-soft)' }} />
        ))}
      </div>
      <div className="flex justify-between px-0.5 font-mono text-[10px] text-qg-text-faint">
        <span>{timeLabel(first)}</span><span>{timeLabel(mid)}</span><span>{timeLabel(last)}</span>
      </div>
      <span className="text-[10.5px] text-qg-text-faint">
        interval: {stepSeconds} s · {points.length} points · peak highlighted
      </span>
    </div>
  )
}
```

`App.tsx` — extend the Phase A `resultView`:

```tsx
  const resultView = (answer: SearchResponse) => {
    const matrix = parseMatrix(answer.result)
    if (matrix && matrix.length === 1 && answer.window) {
      return <Histogram series={matrix[0]} stepSeconds={Math.round(answer.window.step_s)} />
    }
    const rows = parseVector(answer.result)
    if (!rows || rows.length < 2) return null   // multi-series matrix also lands here → ResultRows fallback
    return <BarChart rows={rows} />
  }
```

`ResultRows.tsx` — spec B4's multi-series fallback: "one row per series showing the latest
value, meta line noting latest of {n} points". Add a matrix branch before the JSON `<pre>`
fallback (parseMatrix comes from the already-imported shared lib, so this costs the widget only
bytes; add the test to `Panel.test.tsx` or a new `ResultRows.test.tsx`):

```tsx
  const series = parseMatrix(rawResult)
  if (series !== null && series.length > 0) {
    const rows = series
      .map((s) => ({
        label: Object.values(s.labels).join(' ') || '(no labels)',
        raw: String(s.points[s.points.length - 1]?.[1] ?? ''),
        points: s.points.length,
      }))
      .sort((a, b) => Number(b.raw) - Number(a.raw))
    return (
      <div style={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
        {rows.map((row, i) => (
          <div key={i} className="krow" style={{ background: i % 2 === 0 ? 'var(--qg-surface2)' : 'transparent' }}>
            <span className="mono" style={rowLabelStyle}>{row.label}</span>
            <span className="mono" style={i === 0 && rows.length > 1 ? { ...rowValueStyle, color: 'var(--qg-accent)', fontWeight: 600 } : rowValueStyle}>
              {formatValue(row.raw)}
            </span>
          </div>
        ))}
        <span style={{ fontSize: 11, color: 'var(--qg-text-faint)', padding: '4px 12px' }}>
          latest of {series[0].points.length} points per series
        </span>
      </div>
    )
  }
```

with a pinning test:

```tsx
  it('renders a matrix as latest-value rows with a points note', () => {
    const matrix = {
      resultType: 'matrix',
      result: [
        { metric: { handler: '/a' }, values: [[1, '2'], [2, '5']] },
        { metric: { handler: '/b' }, values: [[1, '9'], [2, '3']] },
      ],
    }
    render(<ResultRows result={matrix} />)
    expect(screen.getByText('/a')).toBeInTheDocument()
    expect(screen.getByText('5')).toBeInTheDocument()   // latest, not max
    expect(screen.getByText(/latest of 2 points/)).toBeInTheDocument()
  })
```

`QueryBlock.tsx` — add `suffix?: string` rendered after the query in `--qg-text-faint`; `Panel.tsx` computes and passes it in the answered branch:

```tsx
  const window = state.kind === 'answered' ? state.answer.window : undefined
  const suffix = window ? ` · range last ${window.minutes} min, step ${Math.round(window.step_s)}s` : undefined
  // <QueryBlock query={state.answer.query} suffix={suffix} />
```

(Spec B4 asked for absolute clock times; the response carries no start/end epoch — `last N min, step Ss` conveys the same fact honestly without inventing client-side clocks. Note this deviation in the commit body; if absolute times are wanted later, the serve layer can echo start/end.)

`TracePanel.tsx` — `buildStages` gains the window case, and the note switches:

```tsx
    { name: 'execute', metric: answer.window ? `query_range · ${answer.window.minutes} min` : `${Math.round(answer.elapsed_ms)} ms` },
```

```tsx
      <span className="border-t border-qg-border-soft pt-1 text-[11.5px] leading-[1.5] text-qg-text-faint">
        {answer?.window
          ? 'The window came from the picker, not the model — the model wrote the expression, the range was applied by the engine.'
          : "The model only wrote syntax. Your schema came from live introspection; your server's parser had the final word."}
      </span>
```

- [ ] **Step 4: Run the full frontend gates + budget**

Run: `npm test -- --run && npm run lint && npm run build:all`
Expected: pass; widget gzip unchanged (Histogram/TimeRange are playground-only modules)

- [ ] **Step 5: Commit**

```bash
git add src/playground/Histogram.tsx src/playground/Histogram.test.tsx src/playground/App.tsx src/playground/TracePanel.tsx src/playground/TracePanel.test.tsx src/widget/QueryBlock.tsx src/widget/Panel.tsx
git commit -m "feat(playground): range histogram, range-aware query block and trace"
```

---

### Task 9: Full gates + live E2E

**Files:** none (verification; fix regressions in place)

- [ ] **Step 1: Backend gates** — `poetry run pytest -q && poetry run ruff check . && poetry run ruff format --check . && poetry run mypy src/queryglot --ignore-missing-imports` → green.
- [ ] **Step 2: Frontend gates** — `npm test -- --run && npm run lint && npm run build:all` → green; widget gzip < 15 KB.
- [ ] **Step 3: Live E2E** (needs Prometheus on :9090, mlx on :8080, `queryglot-serve` on :8000; if mlx is down, note it and verify the 400-validation + picker UI only):
  - Pick "Last 30 minutes", ask "request rate to the API": histogram renders, tooltip on hover, peak highlighted, query block shows the range suffix, trace says `query_range · 30 min`.
  - Switch preset with an answer showing: it re-runs fresh under the new window.
  - Pick "Instant": behavior identical to Phase A (bar chart / rows).
  - `curl -s -X POST :8000/api/search -d '{"question":"x","window_minutes":7}'` → 400.
  - Zero console messages, both themes.
- [ ] **Step 4: Commit any fixes; do not push** (controller/user decides).
