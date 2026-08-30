# OpenAPI Backend Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Third `Backend` implementation: questions compile into validated, read-only OpenAPI calls against a live server, with zero changes to graph/engine/retrieval.

**Architecture:** `OpenAPIBackend` implements the existing `Backend` protocol (introspect/validate/execute). Introspection fetches the server's own spec and catalogs ONLY GET operations (safety by absence). The model emits structured JSON calls (`{"operationId": ..., "parameters": {...}}`); validation checks them against the spec's own contract; execution binds path templates and GETs. Server 4xx responses feed the existing repair loop.

**Tech Stack:** Python 3.11+ stdlib only (json, urllib) — no new dependencies. Existing seams: `Transport`, `SchemaItem`, `Validation`/`Execution`.

**Spec:** `docs/superpowers/specs/2026-08-31-openapi-backend-design.md`

## Global Constraints

- No new runtime dependencies (langgraph, pydantic, mcp only); HTTP via stdlib.
- No lint suppressions (`# noqa`, `# type: ignore`) — fix root causes.
- ruff line-length 100, rules E,F,I,UP,B,SIM; `from __future__ import annotations` in every src module.
- Gate before every commit: `poetry run pytest -q && poetry run ruff check . && poetry run ruff format --check . && poetry run mypy src/queryglot --ignore-missing-imports`.
- Module docstrings explain WHY the design is this way, matching the register of `backends/prometheus.py`.
- Commit messages: no AI attribution of any kind.
- Only GET operations may ever enter the catalog — mutating operations must be absent, not guarded.

---

### Task 1: Introspection — GET operations become SchemaItems

**Files:**
- Create: `src/queryglot/backends/openapi.py`
- Create: `tests/test_openapi.py`

**Interfaces:**
- Consumes: `SchemaItem` (`catalog.py`), `Transport`/`urllib_transport` (`backends/http.py`), `Validation`/`Execution` (`backends/__init__.py`)
- Produces: `OpenAPIBackend(base_url, spec_path="/openapi.json", transport=None, headers=None)` with `name="openapi"`, `language='OpenAPI call (JSON: {"operationId": ..., "parameters": {...}})'`, `introspect() -> list[SchemaItem]`, and internal `self._ops: dict[str, dict]` (operationId -> {"path": str, "parameters": list}) that Tasks 2-3 rely on.

- [ ] **Step 1: Write the failing tests**

```python
"""OpenAPI backend: introspection filters to GET, validation is the spec's
own contract, execution binds path templates. All through a fake Transport."""

import json

import pytest

from queryglot.backends.openapi import OpenAPIBackend

SPEC = {
    "paths": {
        "/pet/findByStatus": {
            "get": {
                "operationId": "findPetsByStatus",
                "summary": "Finds pets by status",
                "parameters": [
                    {
                        "name": "status",
                        "in": "query",
                        "required": True,
                        "schema": {"type": "string", "enum": ["available", "pending", "sold"]},
                    }
                ],
            }
        },
        "/pet/{petId}": {
            "get": {
                "operationId": "getPetById",
                "summary": "Find pet by ID",
                "parameters": [
                    {
                        "name": "petId",
                        "in": "path",
                        "required": True,
                        "schema": {"type": "integer"},
                    }
                ],
            },
            "delete": {"operationId": "deletePet", "summary": "Deletes a pet"},
        },
        "/store/inventory": {
            "get": {"operationId": "getInventory", "summary": "Pet inventories by status"}
        },
        "/pet": {"post": {"operationId": "addPet", "summary": "Add a new pet"}},
        "/user/login": {
            "get": {
                "summary": "Logs user into the system",
                "parameters": [
                    {"name": "username", "in": "query", "schema": {"type": "string"}}
                ],
            }
        },
    }
}


class SpecTransport:
    """Serves SPEC at /openapi.json; records every other GET, returns canned data."""

    def __init__(self, data='{"ok": true}', status=200):
        self.data, self.status = data, status
        self.requests: list[str] = []

    def __call__(self, method, url, body, headers):
        assert method == "GET"
        if url.endswith("/openapi.json"):
            return 200, json.dumps(SPEC)
        self.requests.append(url)
        return self.status, self.data


@pytest.fixture
def backend():
    b = OpenAPIBackend("http://api.example/v3", transport=SpecTransport())
    b.introspect()
    return b


def test_introspects_only_get_operations():
    b = OpenAPIBackend("http://api.example/v3", transport=SpecTransport())
    items = b.introspect()
    names = {i.name for i in items}
    assert names == {"findPetsByStatus", "getPetById", "getInventory", "get_user_login"}
    assert "deletePet" not in names and "addPet" not in names  # absent, not guarded


def test_schema_item_shape():
    b = OpenAPIBackend("http://api.example/v3", transport=SpecTransport())
    by_name = {i.name: i for i in b.introspect()}
    item = by_name["findPetsByStatus"]
    assert item.backend == "openapi" and item.kind == "operation" and item.type == "GET"
    assert item.labels == ("status",)
    assert item.parent == "/pet/findByStatus"
    assert "status" in item.help.lower()


def test_missing_operation_id_gets_path_slug():
    b = OpenAPIBackend("http://api.example/v3", transport=SpecTransport())
    names = {i.name for i in b.introspect()}
    assert "get_user_login" in names


def test_unreachable_spec_raises_connection_error():
    def down(method, url, body, headers):
        return 503, "unavailable"

    with pytest.raises(ConnectionError):
        OpenAPIBackend("http://api.example/v3", transport=down).introspect()


def test_spec_without_paths_raises_connection_error():
    def empty(method, url, body, headers):
        return 200, "{}"

    with pytest.raises(ConnectionError):
        OpenAPIBackend("http://api.example/v3", transport=empty).introspect()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `poetry run pytest tests/test_openapi.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'queryglot.backends.openapi'`

- [ ] **Step 3: Write the implementation**

```python
"""OpenAPI backend.

Introspection: the server's OWN spec (GET {base_url}{spec_path}) flattened
into one SchemaItem per GET operation. Mutating operations are not guarded
against — they are ABSENT: never introspected, never retrievable, never in
a prompt. Safety by absence, the same principle as the unknown-metric check.

Validation: the spec is the server's published contract, fetched from the
server itself; checks (operation exists, required params, type, enum) are
implemented directly from the spec dict. Where the spec is incomplete, the
server's own 4xx at execution feeds the repair loop.

Queries are structured calls: {"operationId": ..., "parameters": {...}} —
the model never writes a URL.
"""

from __future__ import annotations

import json
import urllib.parse

from ..catalog import SchemaItem
from . import Execution, Validation
from .http import Transport, urllib_transport


class OpenAPIBackend:
    name = "openapi"
    language = 'OpenAPI call (JSON: {"operationId": ..., "parameters": {...}})'

    def __init__(
        self,
        base_url: str,
        spec_path: str = "/openapi.json",
        transport: Transport | None = None,
        headers: dict[str, str] | None = None,
    ):
        self.base_url = base_url.rstrip("/")
        self.spec_path = spec_path
        self.transport = transport or urllib_transport
        self.headers = dict(headers or {})
        self._ops: dict[str, dict] = {}

    def _get(self, url: str) -> tuple[int, str]:
        return self.transport("GET", url, None, self.headers)

    def introspect(self) -> list[SchemaItem]:
        url = f"{self.base_url}{self.spec_path}"
        status, text = self._get(url)
        if status >= 400:
            raise ConnectionError(f"GET {url} -> {status}: {text[:200]}")
        try:
            spec = json.loads(text)
        except ValueError as exc:
            raise ConnectionError(f"spec at {url} is not JSON: {exc}") from exc
        paths = spec.get("paths")
        if not isinstance(paths, dict):
            raise ConnectionError(f"spec at {url} has no 'paths' object")

        items: list[SchemaItem] = []
        self._ops = {}
        for path, methods in sorted(paths.items()):
            operation = methods.get("get")
            if not operation:
                continue  # mutating operations stay absent by design
            op_id = operation.get("operationId") or "get_" + path.strip("/").replace(
                "/", "_"
            ).replace("{", "").replace("}", "")
            params = operation.get("parameters", [])
            help_text = " ".join(
                bit.strip()
                for bit in (operation.get("summary", ""), operation.get("description", ""))
                if bit and bit.strip()
            )
            items.append(
                SchemaItem(
                    name=op_id,
                    backend=self.name,
                    kind="operation",
                    type="GET",
                    help=help_text,
                    labels=tuple(p["name"] for p in params),
                    parent=path,
                )
            )
            self._ops[op_id] = {"path": path, "parameters": params}
        return items
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `poetry run pytest tests/test_openapi.py -q`
Expected: 5 passed

- [ ] **Step 5: Full gate, then commit**

```bash
poetry run pytest -q && poetry run ruff check . && poetry run ruff format --check . && poetry run mypy src/queryglot --ignore-missing-imports
git add src/queryglot/backends/openapi.py tests/test_openapi.py
git commit -m "feat(openapi): introspect GET operations into the catalog"
```

---

### Task 2: Validation — the spec's own contract

**Files:**
- Modify: `src/queryglot/backends/openapi.py` (append methods to `OpenAPIBackend`)
- Modify: `tests/test_openapi.py` (append tests; reuse `backend` fixture)

**Interfaces:**
- Consumes: `self._ops` from Task 1; `Validation` dataclass.
- Produces: `validate(query: str) -> Validation`; `_parse(query: str) -> tuple[dict | None, str]` (Task 3 reuses `_parse`).

- [ ] **Step 1: Write the failing tests** (append to `tests/test_openapi.py`)

```python
def call(op_id, **params):
    return json.dumps({"operationId": op_id, "parameters": params})


def test_valid_call_passes(backend):
    assert backend.validate(call("findPetsByStatus", status="available")).ok
    assert backend.validate(call("getInventory")).ok


def test_not_json_fails(backend):
    verdict = backend.validate("GET /pet/findByStatus")
    assert not verdict.ok and "JSON" in verdict.error


def test_unknown_operation_fails_with_catalog_message(backend):
    verdict = backend.validate(call("deletePet"))
    assert not verdict.ok
    assert "deletePet" in verdict.error and "catalog" in verdict.error


def test_missing_required_parameter_fails(backend):
    verdict = backend.validate(call("findPetsByStatus"))
    assert not verdict.ok and "status" in verdict.error and "required" in verdict.error


def test_unknown_parameter_fails(backend):
    verdict = backend.validate(call("getInventory", limit=5))
    assert not verdict.ok and "limit" in verdict.error


def test_wrong_type_fails(backend):
    verdict = backend.validate(call("getPetById", petId="five"))
    assert not verdict.ok and "petId" in verdict.error and "integer" in verdict.error


def test_enum_violation_fails(backend):
    verdict = backend.validate(call("findPetsByStatus", status="happy"))
    assert not verdict.ok and "available" in verdict.error


def test_bool_is_not_an_integer(backend):
    verdict = backend.validate(call("getPetById", petId=True))
    assert not verdict.ok
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `poetry run pytest tests/test_openapi.py -q`
Expected: new tests FAIL — `AttributeError: 'OpenAPIBackend' object has no attribute 'validate'`

- [ ] **Step 3: Write the implementation** (append to the class)

```python
    _TYPE_CHECKS = {
        "string": lambda v: isinstance(v, str),
        "integer": lambda v: isinstance(v, int) and not isinstance(v, bool),
        "number": lambda v: isinstance(v, int | float) and not isinstance(v, bool),
        "boolean": lambda v: isinstance(v, bool),
        "array": lambda v: isinstance(v, list),
    }

    def _parse(self, query: str) -> tuple[dict | None, str]:
        try:
            body = json.loads(query)
        except json.JSONDecodeError as exc:
            return None, f"not valid JSON: {exc}"
        if not isinstance(body, dict) or not isinstance(body.get("operationId"), str):
            return None, 'call must be a JSON object with a string "operationId"'
        if not isinstance(body.get("parameters", {}), dict):
            return None, '"parameters" must be a JSON object'
        return body, ""

    def validate(self, query: str) -> Validation:
        body, error = self._parse(query)
        if body is None:
            return Validation(ok=False, error=error)
        op_id = body["operationId"]
        operation = self._ops.get(op_id)
        if operation is None:
            return Validation(
                ok=False,
                error=(
                    f"unknown operation {op_id!r} — not in this server's catalog; "
                    "use only operations from the schema provided"
                ),
            )
        supplied = body.get("parameters", {})
        spec_params = {p["name"]: p for p in operation["parameters"]}
        missing = sorted(
            name
            for name, p in spec_params.items()
            if p.get("required") and name not in supplied
        )
        if missing:
            return Validation(
                ok=False, error=f"missing required parameter(s) {missing} for {op_id}"
            )
        for name, value in supplied.items():
            spec_param = spec_params.get(name)
            if spec_param is None:
                return Validation(
                    ok=False,
                    error=f"unknown parameter {name!r} for {op_id}; known: {sorted(spec_params)}",
                )
            schema = spec_param.get("schema", {})
            check = self._TYPE_CHECKS.get(schema.get("type", ""))
            if check and not check(value):
                return Validation(
                    ok=False,
                    error=(
                        f"parameter {name!r} must be of type {schema['type']}, "
                        f"got {type(value).__name__}"
                    ),
                )
            if "enum" in schema and value not in schema["enum"]:
                return Validation(
                    ok=False,
                    error=f"parameter {name!r} must be one of {schema['enum']}, got {value!r}",
                )
        return Validation(ok=True)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `poetry run pytest tests/test_openapi.py -q`
Expected: all pass

- [ ] **Step 5: Full gate, then commit**

```bash
poetry run pytest -q && poetry run ruff check . && poetry run ruff format --check . && poetry run mypy src/queryglot --ignore-missing-imports
git add src/queryglot/backends/openapi.py tests/test_openapi.py
git commit -m "feat(openapi): validate calls against the spec's own contract"
```

---

### Task 3: Execution — path binding and server truth

**Files:**
- Modify: `src/queryglot/backends/openapi.py` (append `execute`)
- Modify: `tests/test_openapi.py` (append tests)

**Interfaces:**
- Consumes: `_parse`, `self._ops`, `self._get` from Tasks 1-2; `Execution` dataclass.
- Produces: `execute(query: str) -> Execution` — completes the `Backend` protocol.

- [ ] **Step 1: Write the failing tests** (append)

```python
def test_execute_binds_path_and_query_params():
    transport = SpecTransport(data='[{"id": 1}]')
    b = OpenAPIBackend("http://api.example/v3", transport=transport)
    b.introspect()
    run = b.execute(call("getPetById", petId=5))
    assert run.ok and run.data == [{"id": 1}]
    assert transport.requests == ["http://api.example/v3/pet/5"]

    run = b.execute(call("findPetsByStatus", status="available"))
    assert run.ok
    assert transport.requests[-1] == "http://api.example/v3/pet/findByStatus?status=available"


def test_execute_url_encodes_path_params():
    transport = SpecTransport()
    b = OpenAPIBackend("http://api.example/v3", transport=transport)
    b.introspect()
    b.execute(call("getPetById", petId="a/b"))
    assert transport.requests == ["http://api.example/v3/pet/a%2Fb"]


def test_server_4xx_becomes_repair_fuel():
    b = OpenAPIBackend(
        "http://api.example/v3", transport=SpecTransport(data="Pet not found", status=404)
    )
    b.introspect()
    run = b.execute(call("getPetById", petId=99999))
    assert not run.ok and "404" in run.error and "Pet not found" in run.error


def test_non_json_2xx_body_is_returned_raw():
    b = OpenAPIBackend("http://api.example/v3", transport=SpecTransport(data="pong"))
    b.introspect()
    run = b.execute(call("getInventory"))
    assert run.ok and run.data == "pong"


def test_headers_are_sent_on_execute():
    seen = {}

    def spy(method, url, body, headers):
        if url.endswith("/openapi.json"):
            return 200, json.dumps(SPEC)
        seen.update(headers)
        return 200, "{}"

    b = OpenAPIBackend("http://api.example/v3", transport=spy, headers={"api_key": "k1"})
    b.introspect()
    b.execute(call("getInventory"))
    assert seen["api_key"] == "k1"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `poetry run pytest tests/test_openapi.py -q`
Expected: new tests FAIL — `AttributeError: ... no attribute 'execute'`

- [ ] **Step 3: Write the implementation** (append to the class)

```python
    def execute(self, query: str) -> Execution:
        body, error = self._parse(query)
        if body is None:
            return Execution(ok=False, error=error)
        operation = self._ops.get(body["operationId"])
        if operation is None:
            return Execution(ok=False, error=f"unknown operation {body['operationId']!r}")
        path = operation["path"]
        spec_params = {p["name"]: p for p in operation["parameters"]}
        query_params: dict[str, object] = {}
        for name, value in body.get("parameters", {}).items():
            if spec_params.get(name, {}).get("in") == "path":
                path = path.replace(
                    "{" + name + "}", urllib.parse.quote(str(value), safe="")
                )
            else:
                query_params[name] = value
        url = f"{self.base_url}{path}"
        if query_params:
            url += "?" + urllib.parse.urlencode(query_params)
        status, text = self._get(url)
        if status >= 400:
            return Execution(ok=False, error=f"HTTP {status}: {text[:400]}")
        try:
            return Execution(ok=True, data=json.loads(text))
        except ValueError:
            return Execution(ok=True, data=text)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `poetry run pytest tests/test_openapi.py -q`
Expected: all pass

- [ ] **Step 5: Full gate, then commit**

```bash
poetry run pytest -q && poetry run ruff check . && poetry run ruff format --check . && poetry run mypy src/queryglot --ignore-missing-imports
git add src/queryglot/backends/openapi.py tests/test_openapi.py
git commit -m "feat(openapi): execute validated calls, server errors feed repair"
```

---

### Task 4: Prompts + full-graph integration

**Files:**
- Modify: `src/queryglot/prompts.py` (add `FEWSHOT["openapi"]`)
- Modify: `tests/test_openapi.py` (append graph-level tests)

**Interfaces:**
- Consumes: `build_graph` (`graph.py`), `SchemaRetriever` (`retrieve.py`), `Catalog`, `ScriptedLLM` (`tests/conftest.py`), the complete `OpenAPIBackend`.
- Produces: `FEWSHOT["openapi"]` string — used automatically by `compile_prompt` via the existing `FEWSHOT.get(backend)` lookup.

- [ ] **Step 1: Write the failing tests** (append to `tests/test_openapi.py`)

```python
from queryglot.catalog import Catalog
from queryglot.graph import build_graph
from queryglot.prompts import FEWSHOT
from queryglot.retrieve import SchemaRetriever
from tests.conftest import ScriptedLLM


def graph_for(backend):
    catalog = Catalog()
    catalog.add(*backend.introspect())
    return build_graph(backend, SchemaRetriever(catalog), ScriptedLLM(""), None), catalog


def test_fewshot_examples_exist_and_are_valid_calls():
    for line in FEWSHOT["openapi"].splitlines():
        if line.startswith("A: "):
            parsed = json.loads(line[3:])
            assert "operationId" in parsed and "parameters" in parsed


def test_graph_compiles_validates_and_executes_openapi_call():
    backend = OpenAPIBackend(
        "http://api.example/v3", transport=SpecTransport(data='[{"id": 7}]')
    )
    catalog = Catalog()
    catalog.add(*backend.introspect())
    llm = ScriptedLLM(call("findPetsByStatus", status="available"))
    graph = build_graph(backend, SchemaRetriever(catalog), llm)
    final = graph.invoke({"question": "which pets are available by status?"})
    assert final["outcome"] == "answered"
    assert final["result"] == [{"id": 7}]


def test_graph_repairs_after_spec_violation():
    backend = OpenAPIBackend("http://api.example/v3", transport=SpecTransport())
    catalog = Catalog()
    catalog.add(*backend.introspect())
    llm = ScriptedLLM(
        call("findPetsByStatus", status="happy"),
        call("findPetsByStatus", status="available"),
    )
    graph = build_graph(backend, SchemaRetriever(catalog), llm)
    final = graph.invoke({"question": "which pets are available by status?"})
    assert final["outcome"] == "answered"
    assert "available" in llm.calls[1]  # the enum error reached the repair prompt


def test_mutating_request_abstains_because_operation_is_absent():
    backend = OpenAPIBackend("http://api.example/v3", transport=SpecTransport())
    catalog = Catalog()
    catalog.add(*backend.introspect())
    llm = ScriptedLLM("SHOULD_NEVER_RUN")
    graph = build_graph(backend, SchemaRetriever(catalog), llm)
    final = graph.invoke({"question": "wipe the database of every animal record"})
    assert final["outcome"] == "abstained"
    assert llm.calls == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `poetry run pytest tests/test_openapi.py -q`
Expected: `test_fewshot_examples_exist_and_are_valid_calls` FAILS with `KeyError: 'openapi'`; graph tests may fail on retrieval scores — verify the failure is the missing fewshot, then proceed.

- [ ] **Step 3: Write the implementation** — add to the `FEWSHOT` dict in `src/queryglot/prompts.py`:

```python
    "openapi": (
        "Q: how many pets are in the store inventory?\n"
        'A: {"operationId": "getInventory", "parameters": {}}\n'
        "Q: which pets are currently available?\n"
        'A: {"operationId": "findPetsByStatus", "parameters": {"status": "available"}}\n'
    ),
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `poetry run pytest tests/test_openapi.py -q`
Expected: all pass. If `test_mutating_request_abstains...` fails because BM25 scores the question above `MIN_RETRIEVAL_SCORE`, make the question more off-schema (it must share no tokens with any operation's name/help/labels) — do NOT lower the threshold.

- [ ] **Step 5: Full gate, then commit**

```bash
poetry run pytest -q && poetry run ruff check . && poetry run ruff format --check . && poetry run mypy src/queryglot --ignore-missing-imports
git add src/queryglot/prompts.py tests/test_openapi.py
git commit -m "feat(openapi): fewshot prompt + end-to-end graph coverage"
```

---

### Task 5: Wiring — export, CLI, MCP server

**Files:**
- Modify: `src/queryglot/__init__.py` (import + `__all__`)
- Modify: `src/queryglot/cli.py`
- Modify: `src/queryglot/mcp_server.py`
- Modify: `tests/test_openapi.py` (append wiring test)

**Interfaces:**
- Consumes: `OpenAPIBackend` complete.
- Produces: `queryglot.OpenAPIBackend` public export; CLI flag `--openapi` (env `QUERYGLOT_OPENAPI`); MCP env `QUERYGLOT_OPENAPI` + `QUERYGLOT_OPENAPI_HEADERS` (JSON object).

- [ ] **Step 1: Write the failing test** (append)

```python
def test_public_export():
    import queryglot

    assert queryglot.OpenAPIBackend is OpenAPIBackend
    assert "OpenAPIBackend" in queryglot.__all__
```

- [ ] **Step 2: Run test to verify it fails**

Run: `poetry run pytest tests/test_openapi.py::test_public_export -q`
Expected: FAIL — `AttributeError: module 'queryglot' has no attribute 'OpenAPIBackend'`

- [ ] **Step 3: Wire everything**

`src/queryglot/__init__.py` — add import and `__all__` entry (alphabetical):

```python
from .backends.openapi import OpenAPIBackend
```
and `"OpenAPIBackend",` in `__all__`.

`src/queryglot/cli.py` — in `main()` after the `--elastic` argument:

```python
    parser.add_argument("--openapi", default=os.getenv("QUERYGLOT_OPENAPI"))
```
after the elastic backend block:

```python
    if args.openapi:
        backends.append(OpenAPIBackend(args.openapi, headers=_openapi_headers()))
```
module-level helper (both cli.py and mcp_server.py need it; put it in
`src/queryglot/backends/openapi.py` as a function and import it):

```python
def headers_from_env() -> dict[str, str]:
    """QUERYGLOT_OPENAPI_HEADERS is a JSON object of header name -> value."""
    raw = os.getenv("QUERYGLOT_OPENAPI_HEADERS", "")
    return json.loads(raw) if raw else {}
```
(add `import os` to openapi.py; call sites use
`OpenAPIBackend(url, headers=headers_from_env())`; update `--backend` help
string to `"prometheus | elasticsearch | openapi"`).

`src/queryglot/mcp_server.py` — in `get_engine()` after the elastic block:

```python
        if url := os.getenv("QUERYGLOT_OPENAPI"):
            backends.append(OpenAPIBackend(url, headers=headers_from_env()))
```
and in `main()` an `--openapi` argument mirroring `--elastic`:

```python
    parser.add_argument("--openapi", help="OpenAPI service base URL (API root)")
    ...
    if args.openapi:
        os.environ["QUERYGLOT_OPENAPI"] = args.openapi
```
with imports `from .backends.openapi import OpenAPIBackend, headers_from_env` in both files.

- [ ] **Step 4: Run tests to verify they pass**

Run: `poetry run pytest -q`
Expected: all pass (wiring is exercised by the export test; CLI/MCP paths share the constructor).

- [ ] **Step 5: Full gate, then commit**

```bash
poetry run pytest -q && poetry run ruff check . && poetry run ruff format --check . && poetry run mypy src/queryglot --ignore-missing-imports
git add src/queryglot/__init__.py src/queryglot/cli.py src/queryglot/mcp_server.py src/queryglot/backends/openapi.py tests/test_openapi.py
git commit -m "feat(openapi): wire into CLI, MCP server, and public API"
```

---

### Task 6: Live petstore tests, compose, CI, golden set, README

**Files:**
- Create: `tests/test_petstore_live.py`
- Modify: `eval/docker-compose.yml`, `eval/golden.jsonl`, `eval/run_eval.py`, `.github/workflows/ci.yml`, `README.md`

**Interfaces:**
- Consumes: everything above.
- Produces: `QUERYGLOT_TEST_PETSTORE` convention (API-root URL, e.g. `http://localhost:8081/api/v3`); `run_eval.py` builds one engine over all configured backends and skips golden cases whose backend isn't configured.

- [ ] **Step 1: Write the live test file**

```python
"""Integration against a real Swagger Petstore (swaggerapi/petstore3).

Skipped unless QUERYGLOT_TEST_PETSTORE is set (API root, e.g.
http://localhost:8081/api/v3) — skips are visible, never silent passes.
"""

import json
import os

import pytest

PETSTORE = os.getenv("QUERYGLOT_TEST_PETSTORE")
pytestmark = pytest.mark.skipif(not PETSTORE, reason="set QUERYGLOT_TEST_PETSTORE to run")

from queryglot import OpenAPIBackend  # noqa: E402


@pytest.fixture(scope="module")
def backend():
    b = OpenAPIBackend(PETSTORE)
    b.introspect()
    return b


def test_real_spec_introspects_get_only(backend):
    items = backend.introspect()
    names = {i.name for i in items}
    assert len(names) > 5
    assert "findPetsByStatus" in names and "getInventory" in names
    assert "addPet" not in names and "deletePet" not in names


def test_real_validate_and_execute_roundtrip(backend):
    query = json.dumps(
        {"operationId": "findPetsByStatus", "parameters": {"status": "available"}}
    )
    assert backend.validate(query).ok
    run = backend.execute(query)
    assert run.ok and isinstance(run.data, list)


def test_real_server_error_feeds_repair(backend):
    query = json.dumps({"operationId": "getPetById", "parameters": {"petId": 999999999}})
    assert backend.validate(query).ok  # spec-valid…
    run = backend.execute(query)
    assert not run.ok  # …but the server has the final word
```

- [ ] **Step 2: Add the petstore service and run everything locally**

`eval/docker-compose.yml` — append (host port 8081 to avoid the mlx server on 8080):

```yaml
  petstore:
    image: swaggerapi/petstore3:unstable
    ports: ["8081:8080"]
    # Serves its own spec at /api/v3/openapi.json — introspection stays live.
```

Run:
```bash
docker compose -f eval/docker-compose.yml up -d petstore
sleep 5
QUERYGLOT_TEST_PETSTORE=http://localhost:8081/api/v3 poetry run pytest tests/test_petstore_live.py -q
```
Expected: 3 passed (not skipped). If `findPetsByStatus` 404s, check the API root: `curl -s http://localhost:8081/api/v3/openapi.json | head -c 200` must return JSON.

- [ ] **Step 3: Multi-backend eval + golden cases**

`eval/run_eval.py` — replace the engine construction in `main()`:

```python
    backends = [PrometheusBackend(os.getenv("QUERYGLOT_TEST_PROM", "http://127.0.0.1:9090"))]
    if petstore := os.getenv("QUERYGLOT_TEST_PETSTORE"):
        backends.append(OpenAPIBackend(petstore))
    llm = OpenAICompatibleLLM()
    engine = Engine(backends, llm=llm, use_retrieval=not args.no_retrieval)
```
(import `OpenAPIBackend` alongside the existing imports), and before the case
loop, filter with a visible count:

```python
    configured = set(engine.backends)
    runnable = [c for c in golden if c["backend"] in configured]
    skipped = len(golden) - len(runnable)
    if skipped:
        print(f"skipping {skipped} case(s) for unconfigured backends\n")
```
(iterate `runnable`, denominator `len(runnable)`).

`eval/golden.jsonl` — append:

```json
{"question": "which pets are available right now?", "backend": "openapi", "must_reference": ["findPetsByStatus"], "expect": "answered"}
{"question": "how many pets are in the inventory?", "backend": "openapi", "must_reference": ["getInventory"], "expect": "answered"}
{"question": "find pets tagged as friendly", "backend": "openapi", "must_reference": ["findPetsByTags"], "expect": "answered"}
{"question": "delete all pets", "backend": "openapi", "must_reference": [], "expect": "abstained"}
{"question": "what is the current stock price of Petco?", "backend": "openapi", "must_reference": [], "expect": "abstained"}
```

Run the unit suite: `poetry run pytest -q` — the scoring tests in
`tests/test_eval_scoring.py` must still pass (they load `run_eval.py`).

- [ ] **Step 4: CI + README**

`.github/workflows/ci.yml` — add to `services:`

```yaml
      petstore:
        image: swaggerapi/petstore3:unstable
        ports: ["8081:8080"]
```
and extend the test step env:

```yaml
          QUERYGLOT_TEST_PETSTORE: http://localhost:8081/api/v3
```

`README.md` — status section: change the unchecked backend line to

```markdown
- [x] OpenAPI backend — read-only, GET-only by construction; validated
      against the spec's own contract; petstore-verified in CI
- [ ] Loki (LogQL) backend; Datadog connector
```
and add `QUERYGLOT_OPENAPI` to the MCP config example env block.

- [ ] **Step 5: Full gate incl. live tests, then commit**

```bash
QUERYGLOT_TEST_PETSTORE=http://localhost:8081/api/v3 poetry run pytest -q \
  && poetry run ruff check . && poetry run ruff format --check . \
  && poetry run mypy src/queryglot --ignore-missing-imports
git add tests/test_petstore_live.py eval/ .github/workflows/ci.yml README.md
git commit -m "feat(openapi): live petstore integration, eval cases, CI service"
```

---

## Self-review notes

- Spec coverage: safety-by-absence (T1, T4 abstention test), introspection mapping (T1), structured call + validation rules (T2), execution/repair (T3), fewshot (T4), wiring incl. headers env (T5), live tests/compose/CI/golden/README (T6). Non-goals honored: no POST support, no spec-file input, no new deps.
- `headers_from_env` lives in `openapi.py` (single definition, both entry points import it).
- Petstore host port is 8081 everywhere (compose, CI, commands) — 8080 belongs to `mlx_lm.server` locally.
