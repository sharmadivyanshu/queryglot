"""Prompt construction: the with-schema shape is frozen (training data parity);
the no-schema shape must match the --no-schema dataset variant exactly."""

from queryglot.catalog import SchemaItem
from queryglot.prompts import compile_prompt

ITEM = SchemaItem(
    name="http_requests_total",
    backend="prometheus",
    kind="metric",
    type="counter",
    labels=("route",),
)


def test_with_schema_shape_is_unchanged():
    """Guard: 1651 training rows were rendered with this exact layout."""
    prompt = compile_prompt("rate of requests?", [ITEM], "prometheus")
    assert prompt.startswith("Schema (the only metrics/fields that exist):")
    assert "- http_requests_total (counter) — labels: route" in prompt
    assert "Examples:" in prompt
    assert prompt.endswith("Q: rate of requests?\nA:")


def test_no_schema_prompt_is_bare_qa():
    """Arm-2 serve prompt must equal the --no-schema training prompt."""
    assert compile_prompt("rate of requests?", [], "prometheus") == "Q: rate of requests?\nA:"


def test_no_schema_repair_still_carries_the_parser_error():
    prompt = compile_prompt(
        "rate of requests?", [], "prometheus", failed_query="rate(", error="unclosed paren"
    )
    assert "rate(" in prompt
    assert "unclosed paren" in prompt
    assert "Schema (" not in prompt


def test_repair_prompt_states_the_question_once():
    prompt = compile_prompt(
        "rate of requests?", [ITEM], "prometheus", failed_query="rate(", error="unclosed paren"
    )
    assert prompt.count("Q: rate of requests?") == 1
