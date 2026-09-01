"""LLM-as-reranker: judgment over a CLOSED candidate set. The model can only
reorder what lexical retrieval surfaced — never introduce a name — and any
unparseable reply falls back to the lexical order untouched."""

from queryglot.catalog import SchemaItem
from queryglot.rerank import parse_rerank, rerank
from tests.conftest import ScriptedLLM


def items(*names):
    return [
        SchemaItem(name=n, backend="prometheus", kind="metric", type="gauge", help=h)
        for n, h in names
    ]


HITS = [
    (i, 2.0 - k)
    for k, i in enumerate(
        items(
            ("prometheus_sd_consul_rpc_duration_seconds", "Consul RPC call duration"),
            ("prometheus_http_request_duration_seconds", "latencies for HTTP requests"),
            ("go_goroutines", "goroutine count"),
        )
    )
]


def test_parse_keeps_only_candidate_names_in_reply_order():
    names = [i.name for i, _ in HITS]
    reply = (
        "prometheus_http_request_duration_seconds, made_up_metric,\n"
        "prometheus_sd_consul_rpc_duration_seconds"
    )
    assert parse_rerank(reply, names) == [
        "prometheus_http_request_duration_seconds",
        "prometheus_sd_consul_rpc_duration_seconds",
    ]


def test_rerank_reorders_and_appends_unmentioned():
    llm = ScriptedLLM("prometheus_http_request_duration_seconds")
    reranked = rerank(llm, "which endpoint has max latency?", HITS)
    assert [i.name for i, _ in reranked] == [
        "prometheus_http_request_duration_seconds",
        "prometheus_sd_consul_rpc_duration_seconds",
        "go_goroutines",
    ]
    # the model saw the question and every candidate
    assert "which endpoint has max latency?" in llm.calls[0]
    assert "go_goroutines" in llm.calls[0]


def test_garbage_reply_falls_back_to_lexical_order():
    llm = ScriptedLLM("rate(nonsense_total[5m])")
    reranked = rerank(llm, "q", HITS)
    assert [i.name for i, _ in reranked] == [i.name for i, _ in HITS]


def test_llm_exception_falls_back_to_lexical_order():
    class Exploding:
        def complete(self, system, prompt):
            raise ConnectionError("down")

    reranked = rerank(Exploding(), "q", HITS)
    assert [i.name for i, _ in reranked] == [i.name for i, _ in HITS]
