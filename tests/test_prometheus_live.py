"""Integration against a real Prometheus.

Skipped unless QUERYGLOT_TEST_PROM is set — skips are visible, never silent
passes. CI and the sandbox run a real binary; see eval/README.md.
"""

import os

import pytest

PROM = os.getenv("QUERYGLOT_TEST_PROM")
pytestmark = pytest.mark.skipif(not PROM, reason="set QUERYGLOT_TEST_PROM to run")

from queryglot import Engine, PrometheusBackend, SchemaRetriever  # noqa: E402
from tests.conftest import ScriptedLLM  # noqa: E402


@pytest.fixture(scope="module")
def backend():
    b = PrometheusBackend(PROM, label_lookup_limit=30)
    b.introspect()
    return b


def test_introspection_finds_real_metrics(backend):
    items = backend.introspect()
    names = {i.name for i in items}
    assert len(names) > 100
    assert "prometheus_http_requests_total" in names
    assert "process_resident_memory_bytes" in names


def test_real_parser_accepts_valid_promql(backend):
    assert backend.validate("rate(prometheus_http_requests_total[5m])").ok


def test_real_parser_rejects_broken_promql(backend):
    verdict = backend.validate("rate(prometheus_http_requests_total[5m")
    assert not verdict.ok and "parse error" in verdict.error


def test_unknown_metric_rejected_even_when_syntax_is_valid(backend):
    """The check embeddings can't do: syntactically perfect, semantically
    nonexistent."""
    verdict = backend.validate("rate(totally_made_up_metric_total[5m])")
    assert not verdict.ok and "totally_made_up_metric_total" in verdict.error


def test_execute_returns_real_data(backend):
    run = backend.execute("process_resident_memory_bytes")
    assert run.ok
    assert run.data["result"], "self-scraped metric should have a sample"


def test_end_to_end_with_scripted_model():
    """Full engine pass over a live server, model scripted so the test is
    deterministic: retrieval -> compile -> real validation -> real execution."""
    engine = Engine(
        [PrometheusBackend(PROM, label_lookup_limit=0)],
        llm=ScriptedLLM("process_resident_memory_bytes"),
    )
    counts = engine.refresh_schema()
    assert counts["prometheus"] > 100

    answer = engine.search("how much memory is prometheus using?")
    assert answer.outcome == "answered"
    assert answer.query == "process_resident_memory_bytes"
    assert answer.result["result"]
    assert "process_resident_memory_bytes" in answer.schema_used


def test_end_to_end_repair_loop_against_real_parser():
    """First completion is broken PromQL; the REAL parser error drives the
    repair; second completion succeeds."""
    llm = ScriptedLLM(
        "rate(process_cpu_seconds_total[5m)",  # broken: missing ]
        "rate(process_cpu_seconds_total[5m])",
    )
    engine = Engine([PrometheusBackend(PROM, label_lookup_limit=0)], llm=llm)
    engine.refresh_schema()
    answer = engine.search("cpu usage rate")
    assert answer.outcome == "answered"
    assert len(llm.calls) == 2
    assert "parse error" in llm.calls[1]


def test_off_schema_question_abstains_live():
    engine = Engine(
        [PrometheusBackend(PROM, label_lookup_limit=0)],
        llm=ScriptedLLM("SHOULD_NOT_RUN"),
    )
    engine.refresh_schema()
    answer = engine.search("kubernetes pod restart count for the payments namespace")
    # prometheus self-scrape has no k8s metrics; either abstain (nothing
    # matches) or answer from a legitimately matching metric — never invent.
    if answer.outcome == "answered":
        assert answer.query != "SHOULD_NOT_RUN"
    retriever = SchemaRetriever(engine.catalog)
    assert retriever.search("blockchain wallet", backend="prometheus") == []
