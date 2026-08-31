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
