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


def test_rerank_reorders_the_prompt_slice(catalog):
    """With rerank on, the model's first call ranks candidates; the compile
    prompt then leads with the reranked winner. Gate still fires pre-rerank."""
    llm = ScriptedLLM("orders_queue_depth", "GOOD")
    graph = build_graph(FakeBackend(valid={"GOOD"}), SchemaRetriever(catalog), llm, rerank=True)
    final = graph.invoke({"question": "requests served and pending orders"})
    assert final["outcome"] == "answered"
    assert len(llm.calls) == 2
    assert "comma-separated" in llm.calls[0]  # first call was the rerank
    schema_lines = [ln for ln in llm.calls[1].splitlines() if ln.startswith("- ")]
    assert schema_lines[0].startswith("- orders_queue_depth")


def test_rerank_off_abstention_spends_no_calls(catalog):
    llm = ScriptedLLM("NEVER")
    graph = build_graph(FakeBackend(), SchemaRetriever(catalog), llm, rerank=True)
    final = graph.invoke({"question": "bitcoin wallet balance please"})
    assert final["outcome"] == "abstained"
    assert llm.calls == []


def test_rerank_skipped_when_lexical_is_confident(catalog):
    """Exact-name mentions (+10 boost) and dominant top hits skip the rerank
    call — only contested rankings pay for judgment."""
    llm = ScriptedLLM("GOOD")
    graph = build_graph(FakeBackend(valid={"GOOD"}), SchemaRetriever(catalog), llm, rerank=True)
    final = graph.invoke({"question": "orders_queue_depth versus the http requests rate"})
    assert final["outcome"] == "answered"
    assert len(llm.calls) == 1  # straight to compile — no rerank call
    assert "comma-separated" not in llm.calls[0]


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
