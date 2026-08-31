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
