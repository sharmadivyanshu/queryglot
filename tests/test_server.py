"""Serve layer: HTTP wrapper over Engine. Outcomes are payloads, not errors."""

from fastapi.testclient import TestClient

from queryglot import __version__
from queryglot.engine import Engine
from queryglot.server import create_app
from tests.conftest import FakeBackend, IntrospectingBackend, ScriptedLLM


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
    assert response.json() == {"items": [], "fields": []}


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


def test_widget_js_404_hints_when_unbuilt(tmp_path):
    empty = tmp_path / "empty"
    empty.mkdir()
    engine = Engine([FakeBackend(valid={"GOOD"})], llm=ScriptedLLM("GOOD"))
    app = create_app(engine, static_dir=empty)
    response = TestClient(app).get("/widget.js")
    assert response.status_code == 404
    assert "frontend" in response.json()["detail"]


def test_root_404_hints_when_unbuilt(tmp_path):
    empty = tmp_path / "empty"
    empty.mkdir()
    engine = Engine([FakeBackend(valid={"GOOD"})], llm=ScriptedLLM("GOOD"))
    app = create_app(engine, static_dir=empty)
    response = TestClient(app).get("/")
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


class CountingLLM:
    """ScriptedLLM that also counts calls — for cache/summary assertions."""

    def __init__(self, *completions):
        self.completions = list(completions)
        self.calls = []

    def complete(self, system, prompt):
        self.calls.append((system, prompt))
        if len(self.completions) > 1:
            return self.completions.pop(0)
        return self.completions[0]


def test_repeat_question_is_served_from_cache():
    llm = CountingLLM("GOOD")
    engine = Engine([IntrospectingBackend(valid={"GOOD"})], llm=llm)
    client = TestClient(create_app(engine))
    first = client.post("/api/search", json={"question": "p95 latency by route"}).json()
    calls_after_first = len(llm.calls)
    second = client.post("/api/search", json={"question": "  P95 latency  by route "}).json()
    assert len(llm.calls) == calls_after_first  # no new model calls
    assert second["cached"] is True
    assert first.get("cached") is not True
    assert second["query"] == first["query"]


def test_refresh_clears_the_cache():
    llm = CountingLLM("GOOD")
    engine = Engine([IntrospectingBackend(valid={"GOOD"})], llm=llm)
    client = TestClient(create_app(engine))
    client.post("/api/search", json={"question": "p95 latency by route"})
    calls_before = len(llm.calls)
    client.post("/api/refresh")
    client.post("/api/search", json={"question": "p95 latency by route"})
    assert len(llm.calls) > calls_before


def test_summary_endpoint_grounds_on_provided_data():
    engine = Engine([FakeBackend(valid={"GOOD"})], llm=CountingLLM("GOOD"))
    summary_llm = CountingLLM("Your slowest handler is /metrics at 0.67s.")
    client = TestClient(create_app(engine, summary_llm=summary_llm))
    response = client.post(
        "/api/summary",
        json={
            "question": "which endpoint is slow?",
            "query": "topk(5, ...)",
            "result": {
                "resultType": "vector",
                "result": [{"metric": {"handler": "/metrics"}, "value": [0, "0.667"]}],
            },
        },
    )
    assert response.status_code == 200
    assert "slowest handler" in response.json()["summary"]
    system, prompt = summary_llm.calls[0]
    assert "ONLY" in system  # grounding instruction
    assert "/metrics" in prompt and "0.667" in prompt


def test_summary_endpoint_degrades_to_empty_without_llm():
    engine = Engine([FakeBackend(valid={"GOOD"})], llm=CountingLLM("GOOD"))
    client = TestClient(create_app(engine))
    response = client.post("/api/summary", json={"question": "q", "query": "up", "result": []})
    assert response.status_code == 200
    assert response.json() == {"summary": ""}


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
    assert "cached" not in windowed  # different window → not a cache hit
    assert len(llm.calls) > calls
    hit = client.post(
        "/api/search", json={"question": "p95 latency by route", "window_minutes": 30}
    ).json()
    assert hit["cached"] is True  # same window → hit


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
            {"metric": {"handler": "/api"}, "values": [[100, "1.0"], [130, "84.2"], [160, "31.5"]]},
        ],
    }
    body = client.post(
        "/api/summary",
        json={"question": "request rate", "query": "rate(x[1m])", "result": matrix},
    ).json()
    assert body["summary"] == "peaked earlier."
    prompt = llm.prompts[0][1]
    assert "84.2" in prompt and "31.5" in prompt  # peak + latest survive
    assert '"values"' not in prompt  # raw matrix did not


def test_summary_handles_non_numeric_matrix_values():
    """Non-numeric value strings should be skipped without crashing."""

    class RecordingLLM:
        def __init__(self):
            self.prompts: list[tuple[str, str]] = []

        def complete(self, system: str, prompt: str) -> str:
            self.prompts.append((system, prompt))
            return "request rate was high."

    llm = RecordingLLM()
    engine = Engine([FakeBackend(valid={"GOOD"})], llm=ScriptedLLM("GOOD"))
    client = TestClient(create_app(engine, summary_llm=llm))
    matrix = {
        "resultType": "matrix",
        "result": [
            {
                "metric": {"handler": "/api"},
                "values": [[100, "1.0"], [130, "not_a_number"], [160, "31.5"]],
            },
        ],
    }
    body = client.post(
        "/api/summary",
        json={"question": "request rate", "query": "rate(x[1m])", "result": matrix},
    ).json()
    # Should return 200 with a summary, not 500
    assert body["summary"] == "request rate was high."
    prompt = llm.prompts[0][1]
    # Bad point is skipped; latest (31.5) and peak (31.5) are reported
    assert "31.5" in prompt
    assert "not_a_number" not in prompt


def test_summary_handles_nan_in_matrix_values():
    """NaN samples should be skipped; peak is the max FINITE value.

    NaN becomes the initial max() candidate when first in the list, making
    it the unchallenged peak without explicit isnan filtering."""

    class RecordingLLM:
        def __init__(self):
            self.prompts: list[tuple[str, str]] = []

        def complete(self, system: str, prompt: str) -> str:
            self.prompts.append((system, prompt))
            return "peak was high."

    llm = RecordingLLM()
    engine = Engine([FakeBackend(valid={"GOOD"})], llm=ScriptedLLM("GOOD"))
    client = TestClient(create_app(engine, summary_llm=llm))
    matrix = {
        "resultType": "matrix",
        "result": [
            {
                "metric": {"handler": "/api"},
                # NaN as first element becomes unchallenged initial candidate
                # in max(); isnan check must filter it out
                "values": [[100, "NaN"], [130, "50.0"], [160, "25.0"]],
            },
        ],
    }
    body = client.post(
        "/api/summary",
        json={"question": "request rate", "query": "rate(x[1m])", "result": matrix},
    ).json()
    # Should return 200 with a summary, not 500
    assert body["summary"] == "peak was high."
    prompt = llm.prompts[0][1]
    # Peak is 50.0 (not NaN); latest is 25.0
    assert "50.0" in prompt and "25.0" in prompt
    assert "NaN" not in prompt
