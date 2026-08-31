# Serve Layer Implementation Plan (Ask Surfaces Phase A)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** HTTP JSON API (`queryglot-serve`) over the existing `Engine` — the endpoint the widget and playground call.

**Architecture:** `create_app(engine, cors_origins) -> FastAPI` app factory (testable with an injected fake-backed Engine); a module-level lazy engine for the console script, mirroring `mcp_server.py`. Engine outcomes are payloads, never HTTP errors. Static mounts for the future playground/widget builds.

**Tech Stack:** FastAPI + uvicorn as OPTIONAL extras (`queryglot[serve]`); httpx as dev dep for TestClient.

**Spec:** `docs/superpowers/specs/2026-09-01-ask-surfaces-design.md`

## Global Constraints

- Core runtime deps stay langgraph/pydantic/mcp — fastapi/uvicorn are `optional = true` main deps exposed through a `serve` extra (this satisfies BOTH `pip install queryglot[serve]` and `poetry install --extras serve`; the spec's "group serve" wording is superseded by this ruling — Poetry groups cannot back pip extras).
- Zero changes to graph/engine/retrieval/backends.
- No lint suppressions; ruff line-length 100, rules E,F,I,UP,B,SIM; `from __future__ import annotations`.
- Gate before every commit: `poetry run pytest -q && poetry run ruff check . && poetry run ruff format --check . && poetry run mypy src/queryglot --ignore-missing-imports`.
- Engine outcomes (`answered|abstained|failed`) are 200s; 400 only for a missing/empty question; 401 only for a bad bearer token; 500 only for genuine faults.
- Commit messages: no AI attribution.

---

### Task 1: App factory — /api/status, /api/search, /api/schema

**Files:**
- Create: `src/queryglot/server.py`
- Create: `tests/test_server.py`
- Modify: `pyproject.toml` (optional deps + extra + dev httpx)

**Interfaces:**
- Consumes: `Engine` (`engine.py`: `refresh_schema() -> dict[str,int]`, `search(question, backend=None) -> Answer`, `.catalog.items`, `.backends`), `__version__` from `queryglot`.
- Produces: `create_app(engine: Engine, cors_origins: list[str] | None = None) -> FastAPI` — Tasks 2-3 add routes/config to THIS factory; `queryglot-serve` script lands in Task 3.

- [ ] **Step 1: Add dependencies**

In `pyproject.toml` `[tool.poetry.dependencies]` add:

```toml
fastapi = { version = "^0.115", optional = true }
uvicorn = { version = "^0.32", optional = true }
```

Add after the dependencies table:

```toml
[tool.poetry.extras]
serve = ["fastapi", "uvicorn"]
```

In `[tool.poetry.group.dev.dependencies]` add `httpx = "^0.27"`.
Also update `.github/workflows/ci.yml`'s install step to
`poetry install --with dev --extras serve` (CI must have fastapi for the new tests).
Run: `poetry lock && poetry install --extras serve --with dev`

- [ ] **Step 2: Write the failing tests**

```python
"""Serve layer: HTTP wrapper over Engine. Outcomes are payloads, not errors."""

from fastapi.testclient import TestClient

from queryglot import __version__
from queryglot.engine import Engine
from queryglot.server import create_app
from tests.conftest import FakeBackend, ScriptedLLM


def client_for(llm=None, backend=None):
    engine = Engine([backend or FakeBackend(valid={"GOOD"})], llm=llm or ScriptedLLM("GOOD"))
    return TestClient(create_app(engine))


def test_status_reports_backends_and_version():
    response = client_for().get("/api/status")
    assert response.status_code == 200
    body = response.json()
    assert body["version"] == __version__
    assert body["backends"] == {"prometheus": 0}  # FakeBackend introspects []


def test_search_answers_with_elapsed_ms():
    response = client_for().post("/api/search", json={"question": "p95 latency by route"})
    assert response.status_code == 200
    body = response.json()
    assert body["outcome"] in {"answered", "abstained"}
    assert isinstance(body["elapsed_ms"], int)


def test_search_abstained_is_200_not_error():
    # ScriptedLLM never runs: FakeBackend has no schema, retrieval gate abstains.
    response = client_for(llm=ScriptedLLM("NEVER")).post(
        "/api/search", json={"question": "bitcoin wallet balance"}
    )
    assert response.status_code == 200
    assert response.json()["outcome"] == "abstained"


def test_search_empty_question_is_400():
    assert client_for().post("/api/search", json={"question": "  "}).status_code == 400
    assert client_for().post("/api/search", json={}).status_code in (400, 422)


def test_schema_lists_rendered_items():
    response = client_for().get("/api/schema")
    assert response.status_code == 200
    assert response.json() == {"items": []}
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `poetry run pytest tests/test_server.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'queryglot.server'`

- [ ] **Step 4: Write the implementation**

```python
"""queryglot as an HTTP JSON API — what the ask-widget and playground call.

Engine outcomes are payloads, never HTTP errors: an abstention is a correct
answer and arrives as a 200. Error codes are reserved for transport-level
faults (bad request, bad token). The app factory takes the Engine so tests
inject fakes; the console script (main) builds one from env/flags exactly
like mcp_server.py.
"""

from __future__ import annotations

import time

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from . import __version__
from .engine import Engine


class SearchRequest(BaseModel):
    question: str
    backend: str | None = None


def create_app(engine: Engine, cors_origins: list[str] | None = None) -> FastAPI:
    app = FastAPI(title="queryglot", version=__version__)
    if not engine.catalog.items:
        engine.refresh_schema()

    @app.get("/api/status")
    def status() -> dict:
        counts = {
            name: len(engine.catalog.by_backend(name)) for name in engine.backends
        }
        return {"backends": counts, "version": __version__}

    @app.post("/api/search")
    def search(request: SearchRequest) -> dict:
        if not request.question.strip():
            raise HTTPException(status_code=400, detail="question must be non-empty")
        started = time.monotonic()
        answer = engine.search(request.question, backend=request.backend)
        payload = answer.as_dict()
        payload["elapsed_ms"] = int((time.monotonic() - started) * 1000)
        return payload

    @app.get("/api/schema")
    def schema(query: str = "", limit: int = 20) -> dict:
        items = engine.catalog.items
        if query:
            needle = query.lower()
            items = [
                i for i in items if needle in i.name.lower() or needle in i.help.lower()
            ]
        return {"items": [item.render() for item in items[:limit]]}

    return app
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `poetry run pytest tests/test_server.py -q`
Expected: 5 passed

- [ ] **Step 6: Full gate, then commit**

```bash
poetry run pytest -q && poetry run ruff check . && poetry run ruff format --check . && poetry run mypy src/queryglot --ignore-missing-imports
git add pyproject.toml poetry.lock .github/workflows/ci.yml src/queryglot/server.py tests/test_server.py
git commit -m "feat(serve): app factory with status, search, schema routes"
```

Note for mypy: fastapi ships type stubs; if mypy errors on the optional import in environments without the extra, that is a real failure to fix by installing the extra in the dev env (Step 1), never by ignoring.

---

### Task 2: Refresh, bearer auth, CORS

**Files:**
- Modify: `src/queryglot/server.py`
- Modify: `tests/test_server.py` (append)

**Interfaces:**
- Consumes: Task 1's `create_app`.
- Produces: `POST /api/refresh`; bearer enforcement on all `/api/*` when `QUERYGLOT_SERVE_TOKEN` is set; CORSMiddleware wired from the factory's `cors_origins` param.

- [ ] **Step 1: Write the failing tests** (append)

```python
def test_refresh_reintrospects():
    response = client_for().post("/api/refresh")
    assert response.status_code == 200
    assert response.json() == {"prometheus": 0}


def test_bearer_required_when_token_set(monkeypatch):
    monkeypatch.setenv("QUERYGLOT_SERVE_TOKEN", "sekrit")
    c = client_for()
    assert c.get("/api/status").status_code == 401
    assert c.get("/api/status", headers={"Authorization": "Bearer wrong"}).status_code == 401
    assert c.get("/api/status", headers={"Authorization": "Bearer sekrit"}).status_code == 200


def test_no_token_means_open(monkeypatch):
    monkeypatch.delenv("QUERYGLOT_SERVE_TOKEN", raising=False)
    assert client_for().get("/api/status").status_code == 200


def test_cors_headers_when_origin_configured():
    engine = Engine([FakeBackend()], llm=ScriptedLLM("GOOD"))
    app = create_app(engine, cors_origins=["https://customer.example"])
    response = TestClient(app).options(
        "/api/search",
        headers={
            "Origin": "https://customer.example",
            "Access-Control-Request-Method": "POST",
        },
    )
    assert response.headers["access-control-allow-origin"] == "https://customer.example"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `poetry run pytest tests/test_server.py -q`
Expected: new tests FAIL (404 on /api/refresh; 200 where 401 expected; KeyError on CORS header)

- [ ] **Step 3: Implement** — in `create_app`, before the routes:

```python
    if cors_origins:
        from fastapi.middleware.cors import CORSMiddleware

        app.add_middleware(
            CORSMiddleware,
            allow_origins=cors_origins,
            allow_methods=["GET", "POST"],
            allow_headers=["Authorization", "Content-Type"],
        )

    @app.middleware("http")
    async def bearer_guard(request, call_next):  # env read per request so tests can monkeypatch
        token = os.getenv("QUERYGLOT_SERVE_TOKEN", "")
        if token and request.url.path.startswith("/api/"):
            supplied = request.headers.get("authorization", "")
            if supplied != f"Bearer {token}":
                return JSONResponse({"detail": "invalid or missing bearer token"}, status_code=401)
        return await call_next(request)
```

(imports: `import os`, `from fastapi.responses import JSONResponse`.) Add the route:

```python
    @app.post("/api/refresh")
    def refresh() -> dict:
        return engine.refresh_schema()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `poetry run pytest tests/test_server.py -q`
Expected: all pass

- [ ] **Step 5: Full gate, then commit**

```bash
poetry run pytest -q && poetry run ruff check . && poetry run ruff format --check . && poetry run mypy src/queryglot --ignore-missing-imports
git add src/queryglot/server.py tests/test_server.py
git commit -m "feat(serve): refresh route, bearer auth, CORS"
```

---

### Task 3: Static mounts + console script + live test + README

**Files:**
- Modify: `src/queryglot/server.py` (static routes + `main()`)
- Modify: `pyproject.toml` (`queryglot-serve` script)
- Modify: `tests/test_server.py`, `tests/test_prometheus_live.py` (append live serve test)
- Modify: `README.md`

**Interfaces:**
- Consumes: Tasks 1-2.
- Produces: `GET /` (playground) and `GET /widget.js` served from `src/queryglot/_static/` when present, 404 with a hint otherwise; `queryglot-serve` console script; `main() -> None`.

- [ ] **Step 1: Write the failing tests** (append to test_server.py)

```python
def test_widget_js_404_hints_when_unbuilt():
    response = client_for().get("/widget.js")
    assert response.status_code == 404
    assert "frontend" in response.json()["detail"]


def test_root_404_hints_when_unbuilt():
    response = client_for().get("/")
    assert response.status_code == 404
    assert "frontend" in response.json()["detail"]
```

And in `tests/test_prometheus_live.py` (inside the existing skip-guarded module):

```python
def test_serve_layer_end_to_end(backend):
    from fastapi.testclient import TestClient

    from queryglot.server import create_app
    from tests.conftest import ScriptedLLM

    engine = Engine([PrometheusBackend(PROM)], llm=ScriptedLLM("process_resident_memory_bytes"))
    client = TestClient(create_app(engine))
    body = client.post(
        "/api/search", json={"question": "how much memory is the process using right now?"}
    ).json()
    assert body["outcome"] == "answered"
    assert "process_resident_memory_bytes" in body["query"]
```

(ScriptedLLM keeps the live test deterministic — no live LLM needed.)

- [ ] **Step 2: Run tests to verify they fail**

Run: `poetry run pytest tests/test_server.py -q`
Expected: 404 tests fail — routes don't exist yet (FastAPI returns its own 404 JSON without "frontend" in detail)

- [ ] **Step 3: Implement** — append to `create_app` and module:

```python
    static_dir = Path(__file__).parent / "_static"

    @app.get("/widget.js", include_in_schema=False)
    def widget_js() -> FileResponse:
        bundle = static_dir / "widget.js"
        if not bundle.exists():
            raise HTTPException(
                status_code=404, detail="widget not built — see frontend/README.md"
            )
        return FileResponse(bundle, media_type="text/javascript", headers={"Cache-Control": "no-cache"})

    @app.get("/", include_in_schema=False)
    def index() -> FileResponse:
        page = static_dir / "index.html"
        if not page.exists():
            raise HTTPException(
                status_code=404, detail="playground not built — see frontend/README.md"
            )
        return FileResponse(page)

    if (static_dir / "assets").exists():
        app.mount("/assets", StaticFiles(directory=static_dir / "assets"), name="assets")

    return app


def main() -> None:
    import argparse

    import uvicorn

    from .backends import Backend
    from .backends.elastic import ElasticBackend
    from .backends.openapi import OpenAPIBackend, headers_from_env
    from .backends.prometheus import PrometheusBackend

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prometheus", default=os.getenv("QUERYGLOT_PROMETHEUS"))
    parser.add_argument("--elastic", default=os.getenv("QUERYGLOT_ELASTIC"))
    parser.add_argument("--openapi", default=os.getenv("QUERYGLOT_OPENAPI"))
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument(
        "--cors-origin", action="append", default=None,
        help="allowed origin for embedding (repeatable); env QUERYGLOT_CORS_ORIGINS (comma-separated)",
    )
    args = parser.parse_args()

    backends: list[Backend] = []
    if args.prometheus:
        backends.append(PrometheusBackend(args.prometheus))
    if args.elastic:
        backends.append(ElasticBackend(args.elastic, os.getenv("QUERYGLOT_ELASTIC_INDEX", "*")))
    if args.openapi:
        backends.append(OpenAPIBackend(args.openapi, headers=headers_from_env()))
    if not backends:
        parser.error("configure at least one backend (--prometheus / --elastic / --openapi)")

    origins = args.cors_origin or [
        o.strip() for o in os.getenv("QUERYGLOT_CORS_ORIGINS", "").split(",") if o.strip()
    ]
    uvicorn.run(create_app(Engine(backends), cors_origins=origins or None), host=args.host, port=args.port)


if __name__ == "__main__":
    main()
```

Module imports to add at top: `from pathlib import Path`, `from fastapi.responses import FileResponse`, `from fastapi.staticfiles import StaticFiles`. In `pyproject.toml` `[tool.poetry.scripts]`: `queryglot-serve = "queryglot.server:main"`. Create `src/queryglot/_static/.gitkeep` (empty) and add `src/queryglot/_static/*` except `.gitkeep` to `.gitignore`:

```
src/queryglot/_static/*
!src/queryglot/_static/.gitkeep
```

README: add `queryglot-serve` one-liner under the CLI section and `QUERYGLOT_SERVE_TOKEN`/`QUERYGLOT_CORS_ORIGINS` to the env list, with one sentence: no token = open, meant for localhost/demo.

- [ ] **Step 4: Run tests, incl. live**

Run: `poetry run pytest tests/test_server.py -q` then
`QUERYGLOT_TEST_PROM=http://localhost:9090 poetry run pytest tests/test_prometheus_live.py -q`
Expected: all pass (live: 5 passed with the new test)

- [ ] **Step 5: Full gate, then commit**

```bash
poetry run pytest -q && poetry run ruff check . && poetry run ruff format --check . && poetry run mypy src/queryglot --ignore-missing-imports
git add src/queryglot/server.py src/queryglot/_static/.gitkeep pyproject.toml .gitignore tests/ README.md
git commit -m "feat(serve): static mounts, queryglot-serve entry point"
```

---

## Self-review notes

- Spec coverage: all six routes (T1: status/search/schema, T2: refresh, T3: /, /widget.js), CORS + auth (T2), extras packaging + script + README posture note (T1/T3), live test (T3), error philosophy encoded in tests (T1). Non-goals respected: no streaming, no engine changes.
- Ruling recorded in Global Constraints: extras instead of a Poetry group (pip-compatibility), superseding the spec's wording.
- CI needs no changes: tests run inside the existing suite; the serve extra must be added to the CI install line — `poetry install --with dev` becomes `poetry install --with dev --extras serve` (fold into Task 1's commit).
