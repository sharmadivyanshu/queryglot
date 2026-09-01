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


def test_cors_preflight_works_with_bearer_token(monkeypatch):
    monkeypatch.setenv("QUERYGLOT_SERVE_TOKEN", "sekrit")
    engine = Engine([FakeBackend()], llm=ScriptedLLM("GOOD"))
    app = create_app(engine, cors_origins=["https://customer.example"])
    client = TestClient(app)

    # OPTIONS preflight carries no Authorization header and must not be 401'd
    preflight_response = client.options(
        "/api/search",
        headers={
            "Origin": "https://customer.example",
            "Access-Control-Request-Method": "POST",
        },
    )
    assert preflight_response.status_code == 200
    assert preflight_response.headers["access-control-allow-origin"] == "https://customer.example"

    # Plain GET without bearer still 401s
    status_response = client.get("/api/status")
    assert status_response.status_code == 401


def test_widget_js_404_hints_when_unbuilt():
    response = client_for().get("/widget.js")
    assert response.status_code == 404
    assert "frontend" in response.json()["detail"]


def test_root_404_hints_when_unbuilt():
    response = client_for().get("/")
    assert response.status_code == 404
    assert "frontend" in response.json()["detail"]


def test_401_includes_cors_headers_for_configured_origin(monkeypatch):
    monkeypatch.setenv("QUERYGLOT_SERVE_TOKEN", "sekrit")
    engine = Engine([FakeBackend()], llm=ScriptedLLM("GOOD"))
    app = create_app(engine, cors_origins=["https://customer.example"])
    client = TestClient(app)

    response = client.get("/api/status", headers={"Origin": "https://customer.example"})

    assert response.status_code == 401
    assert response.headers["access-control-allow-origin"] == "https://customer.example"


def test_non_ascii_authorization_header_is_401_not_500(monkeypatch):
    monkeypatch.setenv("QUERYGLOT_SERVE_TOKEN", "sekrit")
    c = client_for()

    # httpx encodes str header values as ascii; send the raw latin-1 bytes
    # directly so the wire header actually carries the non-ASCII byte, same
    # as what Starlette would decode back into "Bearer café" server-side.
    response = c.get("/api/status", headers={"Authorization": "Bearer café".encode("latin-1")})

    assert response.status_code == 401


class RaisingLLM:
    def complete(self, system: str, prompt: str) -> str:
        raise OSError("connection refused: LLM endpoint down")


class IntrospectingBackend(FakeBackend):
    """FakeBackend whose introspect() actually returns schema, so retrieval
    clears the gate and the graph reaches compile (i.e. calls the LLM)."""

    def introspect(self):
        from queryglot.catalog import SchemaItem

        return [
            SchemaItem(
                name="http_server_request_duration_seconds",
                backend="prometheus",
                kind="metric",
                type="histogram",
                help="HTTP request latency",
                labels=("route", "method", "status"),
            )
        ]


def test_search_engine_exception_returns_failed_outcome_not_500():
    engine = Engine([IntrospectingBackend()], llm=RaisingLLM())
    response = TestClient(create_app(engine)).post(
        "/api/search", json={"question": "p95 latency by route"}
    )
    assert response.status_code == 200
    body = response.json()
    assert body["outcome"] == "failed"
    # exception class name is fine to expose; the raw exception text is not
    # (e.g. urllib error messages embed the internal LLM endpoint URL)
    assert "OSError" in body["reason"]
    assert "connection refused" not in body["reason"]
    assert isinstance(body["elapsed_ms"], int)
