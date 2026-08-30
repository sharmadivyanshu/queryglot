"""Retrieval: the vocabulary gap is the whole test."""

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
