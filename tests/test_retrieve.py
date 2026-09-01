"""Retrieval: the vocabulary gap is the whole test."""

from queryglot.catalog import Catalog, SchemaItem
from queryglot.retrieve import SchemaRetriever, tokenize


def names(hits):
    return [item.name for item, _ in hits]


def test_latency_finds_duration_metric(catalog):
    """'latency' appears nowhere in the metric name — synonym expansion must
    bridge it to *_duration_seconds."""
    hits = SchemaRetriever(catalog).search("p95 latency by route", backend="prometheus")
    assert names(hits)[0] == "http_server_request_duration_seconds"


def test_memory_question_finds_memory_gauge(catalog):
    hits = SchemaRetriever(catalog).search("how much memory is the app using", backend="prometheus")
    assert names(hits)[0] == "process_resident_memory_bytes"


def test_exact_name_mention_dominates(catalog):
    hits = SchemaRetriever(catalog).search("graph orders_queue_depth for me", backend="prometheus")
    assert names(hits)[0] == "orders_queue_depth"


def test_backend_filter_is_respected(catalog):
    hits = SchemaRetriever(catalog).search("error logs", backend="elasticsearch")
    assert all(item.backend == "elasticsearch" for item, _ in hits)


def test_no_match_returns_empty_not_garbage(catalog):
    hits = SchemaRetriever(catalog).search("blockchain wallet balance", backend="prometheus")
    assert hits == [] or hits[0][1] < 1.0


def test_tokenizer_splits_snake_case():
    assert tokenize("http_requests_total") == ["http", "requests", "total"]


# --- completion parsing (lives here to avoid a new test module) -------------


def test_parse_completion_normal():
    from queryglot.llm import parse_completion

    body = {"choices": [{"message": {"content": "rate(x_total[5m])", "reasoning": "..."}}]}
    assert parse_completion(body) == "rate(x_total[5m])"


def test_parse_completion_reasoning_only_returns_empty():
    """Qwen3.5 burned the whole budget thinking: message has NO content key.
    This crashed the eval with KeyError before the fix."""
    from queryglot.llm import parse_completion

    body = {"choices": [{"message": {"reasoning": "thinking forever..."}}]}
    assert parse_completion(body) == ""


def test_parse_completion_null_content_and_malformed():
    from queryglot.llm import parse_completion

    assert parse_completion({"choices": [{"message": {"content": None}}]}) == ""
    assert parse_completion({"choices": []}) == ""
    assert parse_completion({}) == ""


def test_endpoint_synonym_beats_label_coincidence():
    """Observed failure: 'endpoint' matched the Consul SD metric's label and
    outranked the http duration metric (labels: handler). The synonym entry
    must steer 'endpoint' questions to handler/route-labeled metrics."""
    c = Catalog()
    c.add(
        SchemaItem(
            name="prometheus_http_request_duration_seconds",
            backend="prometheus",
            kind="metric",
            type="histogram",
            help="Histogram of latencies for HTTP requests",
            labels=("handler",),
        ),
        SchemaItem(
            name="prometheus_sd_consul_rpc_duration_seconds",
            backend="prometheus",
            kind="metric",
            type="summary",
            help="The duration of a Consul RPC call in seconds.",
            labels=("call", "endpoint"),
        ),
    )
    hits = SchemaRetriever(c).search("which endpoint is causing the max latency?")
    assert hits[0][0].name == "prometheus_http_request_duration_seconds"


def test_default_suggestion_vocabulary_clears_the_gate():
    """The playground ships three default suggestions — every one must rank a
    sensible metric on a realistic self-scraping-Prometheus catalog. Observed
    live: 'slowest routes today' abstained and 'error rate' hit a queue metric."""
    c = Catalog()
    c.add(
        SchemaItem(
            name="prometheus_http_request_duration_seconds",
            backend="prometheus",
            kind="metric",
            type="histogram",
            help="Histogram of latencies for HTTP requests",
            labels=("handler",),
        ),
        SchemaItem(
            name="prometheus_sd_http_failures_total",
            backend="prometheus",
            kind="metric",
            type="counter",
            help="Number of HTTP service discovery refresh failures",
            labels=("name",),
        ),
        SchemaItem(
            name="prometheus_notifications_queue_length",
            backend="prometheus",
            kind="metric",
            type="gauge",
            help="The capacity of the alert notifications queue",
            labels=(),
        ),
    )
    retriever = SchemaRetriever(c)

    slowest = retriever.search("slowest routes today")
    assert slowest and slowest[0][0].name == "prometheus_http_request_duration_seconds"

    errors = retriever.search("error rate in the last hour")
    assert errors and errors[0][0].name == "prometheus_sd_http_failures_total"
