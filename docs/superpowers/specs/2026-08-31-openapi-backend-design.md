# OpenAPI backend — design

Date: 2026-08-31. Status: approved (design discussion in-session).

## Why

The `Backend` protocol (introspect / validate / execute) is not
observability-specific. Pointed at an API's OpenAPI spec, the same
retrieve → compile → validate → repair → execute loop with abstention turns
any product API into something an agent can query *safely*. Existing
OpenAPI→MCP generators dump every endpoint as a tool — which measurably
degrades agents (arXiv 2411.15399) — and execute whatever the model asks.
This backend is the missing layer: schema-grounded retrieval over
operations, validation against the spec's own contract, refusal instead of
invention. Positioning: "Speakeasy makes your API callable by agents;
queryglot makes it safely answerable."

## Goals

- Third `Backend` implementation with ZERO changes to graph, engine,
  retrieval, or catalog — the demo is that the pipeline is already general.
- Read-only v1: questions compile into validated GET calls.
- Live-server discipline preserved: the spec is introspected from the
  running server, execute-gated tests and golden cases run against a real
  container.

## Non-goals (v1)

- Mutating operations (POST/PUT/PATCH/DELETE) — excluded entirely, see
  Safety.
- OAuth flows, multi-step auth — one static header set only.
- Response summarisation / answer synthesis — raw (truncated) response data,
  same as the other backends.
- Spec-file input (path on disk / URL to a static file) — the server serves
  its spec or the backend fails introspection loudly. Revisit only with a
  concrete need.

## Target environment

`swaggerapi/petstore3` (official Swagger Petstore v3 image) joins
`eval/docker-compose.yml`. It serves its own spec at
`/api/v3/openapi.json`. Live tests and golden cases run against it, gated by
`QUERYGLOT_TEST_PETSTORE`, mirroring the Prometheus pattern.

## Design

### Safety model: absence, not guards

Only `GET` operations are introspected into the catalog. Mutating
operations are not refused at execution time — they do not exist in the
system's world: the model never sees them in a prompt slice, retrieval
cannot surface them, and the unknown-operation check rejects any invented
reference. Same principle as the unknown-metric check: the strongest safety
property is absence. The golden set demonstrates it ("delete all pets" must
abstain).

### Introspection → catalog

`OpenAPIBackend(base_url, spec_path="/api/v3/openapi.json", transport=None,
headers=None)` fetches `{base_url}{spec_path}` via the shared `Transport`.
Each GET operation becomes one `SchemaItem`:

| SchemaItem field | value |
|---|---|
| `name` | `operationId` (fallback: `get_<path>` slug when absent) |
| `backend` | `"openapi"` |
| `kind` | `"operation"` |
| `type` | `"GET"` |
| `help` | `summary` + `description`, joined |
| `labels` | parameter names (path + query) |
| `parent` | path template (`/pet/findByStatus`) |

One item per operation — the operation is the retrieval unit, as the metric
was. `render()` needs no changes. The backend retains
`self._ops: dict[operationId, <spec fragment>]` for validation/execution and
`self._known` for the unknown-operation check.

### Query representation

The model emits a structured call, never a URL:

```json
{"operationId": "findPetsByStatus", "parameters": {"status": "available"}}
```

`prompts.FEWSHOT["openapi"]` gets two examples (one no-parameter lookup, one
filtered query). No other prompt changes.

### Validation (spec-as-contract)

`validate()` checks in order, first failure returned verbatim to the repair
loop:

1. Parses as a JSON object with an `operationId` string; `parameters` is an
   object when present.
2. `operationId` is in `self._known` — else `unknown operation(s) [...] —
   not in this server's catalog; use only operations from the schema
   provided` (mirrors the Prometheus unknown-metric wording).
3. Every `required` parameter is present.
4. Each supplied parameter exists in the spec and its value satisfies the
   parameter's schema: `type` (string/integer/number/boolean/array) and
   `enum` membership, implemented directly from the spec dict — no new
   dependency. Unknown parameter names are errors.

This is client-side, unlike Prometheus/ES where the server's parser rules —
but the spec IS the server's published contract, fetched from the server
itself, so "the backend owns truth" holds. Where the spec is incomplete the
server still gets the final word at execution (below).

### Execution

`execute()` binds path parameters into the template
(`/pet/{petId}` + `{"petId": 5}` → `/pet/5`, URL-encoded), sends remaining
parameters as query string, GETs with the configured headers. Non-2xx →
`Execution(ok=False, error=<status + response body, truncated ~400 chars>)`
— server-side 400s feed the repair loop, closing the gap client-side
validation cannot cover. 2xx → `Execution(ok=True, data=<parsed JSON, or
raw text when not JSON>)`.

### Auth

`QUERYGLOT_OPENAPI_HEADERS` — optional JSON object of header name→value,
passed on every spec fetch and execution. Constructor arg `headers` for
library use. No per-operation auth logic in v1.

### Wiring

- `cli.py`: `--openapi <base_url>` / env `QUERYGLOT_OPENAPI`.
- `mcp_server.py`: `QUERYGLOT_OPENAPI` env, same lazy-engine pattern.
- `__init__.py`: export `OpenAPIBackend`.
- Backend auto-routing: unchanged — retrieval-strength routing already
  covers a third backend.

## Error handling

- Spec unreachable / not JSON / no `paths` key → `introspect()` raises
  `ConnectionError` with the URL (loud startup failure, matching
  `get_json`'s behaviour).
- Malformed model output (non-JSON, missing operationId) → validation error
  into the repair loop, like every other bad attempt.
- Execution transport errors → `Execution(ok=False, ...)` — the graph's
  `failed` outcome, not an exception.

## Testing

- `tests/test_openapi.py` — unit, via fake `Transport` and an inline spec
  fixture (~4 operations incl. path-param, enum-param, required-param, and a
  POST that must NOT be introspected). Covers: introspection filtering,
  every validation rule, path binding, query encoding, error surfacing,
  graph integration with `ScriptedLLM` (compile→validate→repair→execute and
  the abstention path).
- `tests/test_petstore_live.py` — behind `QUERYGLOT_TEST_PETSTORE`: real
  spec introspects (>5 operations), real validate/execute round-trip, real
  4xx feeds repair.
- CI: petstore3 service added to the workflow matrix alongside Prometheus.

## Eval

~6 golden cases, `backend: "openapi"`:
- answered: find available pets; pet by id; store inventory; order by id —
  each with `must_reference` on the operationId.
- abstained: "delete all pets" (mutating — absent from catalog);
  "bitcoin wallet balance" (off-schema).

Scoring machinery unchanged — `must_reference` matches operationIds inside
the emitted JSON exactly as it matches metric names inside PromQL.

## Files

New: `src/queryglot/backends/openapi.py` (~150 lines),
`tests/test_openapi.py`, `tests/test_petstore_live.py`.
Touched: `prompts.py`, `cli.py`, `mcp_server.py`, `src/queryglot/__init__.py`,
`eval/docker-compose.yml`, `eval/golden.jsonl`, `.github/workflows/ci.yml`,
`README.md` (status + backends list).
