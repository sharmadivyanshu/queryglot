"""Graph behaviour: repair loop, abstention, audit trail."""

from queryglot.graph import MAX_REPAIRS, build_graph
from queryglot.retrieve import SchemaRetriever
from tests.conftest import FakeBackend, ScriptedLLM


def run(catalog, backend, llm, question="p95 latency by route"):
    graph = build_graph(backend, SchemaRetriever(catalog), llm)
    return graph.invoke({"question": question})


def test_valid_query_executes_first_try(catalog):
    backend = FakeBackend(valid={"GOOD"})
    final = run(catalog, backend, ScriptedLLM("GOOD"))
    assert final["outcome"] == "answered"
    assert final["result"] == "DATA"
    assert backend.executed == ["GOOD"]


def test_parse_error_feeds_repair_loop(catalog):
    """First attempt fails; the parser's error must reach the second prompt."""
    llm = ScriptedLLM("BAD", "GOOD")
    final = run(catalog, FakeBackend(valid={"GOOD"}), llm)
    assert final["outcome"] == "answered"
    assert len(llm.calls) == 2
    assert "BAD" in llm.calls[1] and "parse error" in llm.calls[1]
    assert [a["query"] for a in final["attempts"]] == ["BAD"]


def test_repairs_are_bounded_then_abstain(catalog):
    llm = ScriptedLLM("ALWAYS_BAD")
    final = run(catalog, FakeBackend(valid=set()), llm)
    assert final["outcome"] == "abstained"
    assert len(llm.calls) == MAX_REPAIRS + 1
    assert len(final["attempts"]) == MAX_REPAIRS + 1


def test_no_schema_match_abstains_without_calling_model(catalog):
    """The abstention that matters: off-topic question, zero model calls,
    zero invented metric names."""
    llm = ScriptedLLM("SHOULD_NEVER_RUN")
    final = run(catalog, FakeBackend(), llm, question="bitcoin wallet balance please")
    assert final["outcome"] == "abstained"
    assert "refusing to guess" in final["reason"]
    assert llm.calls == []


def test_execution_failure_is_failed_not_abstained(catalog):
    final = run(catalog, FakeBackend(valid={"GOOD"}, execute_ok=False), ScriptedLLM("GOOD"))
    assert final["outcome"] == "failed"
    assert "boom" in final["reason"]


def test_schema_reaches_the_prompt(catalog):
    llm = ScriptedLLM("GOOD")
    run(catalog, FakeBackend(valid={"GOOD"}), llm)
    assert "http_server_request_duration_seconds" in llm.calls[0]
    assert "labels: route, method, status" in llm.calls[0]


def test_no_retriever_compiles_bare_prompt(catalog):
    """Arm 2: retriever=None skips retrieval AND the abstention gate; the
    model sees the bare Q/A prompt with no schema slice."""
    llm = ScriptedLLM("GOOD")
    graph = build_graph(FakeBackend(valid={"GOOD"}), None, llm)
    final = graph.invoke({"question": "bitcoin wallet balance please"})
    assert final["outcome"] == "answered"
    assert llm.calls == ["Q: bitcoin wallet balance please\nA:"]


def test_no_retriever_still_bounds_repairs():
    llm = ScriptedLLM("ALWAYS_BAD")
    graph = build_graph(FakeBackend(valid=set()), None, llm)
    final = graph.invoke({"question": "anything"})
    assert final["outcome"] == "abstained"
    assert len(llm.calls) == MAX_REPAIRS + 1
    assert "attempts" in final["reason"]
