"""Compile prompts. Everything the model needs, nothing it can hallucinate.

The schema slice comes from retrieval — the model is told, explicitly, that
metrics/fields outside the list do not exist. Repair turns the backend's own
parse error into the next attempt's constraint.
"""

from __future__ import annotations

from .catalog import SchemaItem

SYSTEM = (
    "You translate questions about observability data into {language} for a "
    "{backend} backend. Output ONLY the query — no prose, no explanation, no "
    "code fences. Use ONLY the metrics/fields listed in the schema; anything "
    "not listed does not exist on this server."
)

FEWSHOT = {
    "prometheus": (
        "Q: how many http requests per second, by handler?\n"
        "A: sum by (handler) (rate(prometheus_http_requests_total[5m]))\n"
        "Q: p95 request duration over the last 15 minutes\n"
        "A: histogram_quantile(0.95, sum by (le) "
        "(rate(prometheus_http_request_duration_seconds_bucket[15m])))\n"
        "Q: how much memory is the process using right now?\n"
        "A: process_resident_memory_bytes\n"
    ),
    "elasticsearch": (
        "Q: errors in the last hour\n"
        'A: {"query": {"bool": {"filter": [{"term": {"level": "error"}}, '
        '{"range": {"@timestamp": {"gte": "now-1h"}}}]}}}\n'
        "Q: how many requests per service?\n"
        'A: {"size": 0, "aggs": {"per_service": {"terms": {"field": "service"}}}}\n'
    ),
}


def compile_prompt(
    question: str, schema: list[SchemaItem], backend: str, failed_query: str = "", error: str = ""
) -> str:
    if schema:
        lines = ["Schema (the only metrics/fields that exist):"]
        lines += [f"- {item.render()}" for item in schema]
        lines += ["", "Examples:", FEWSHOT.get(backend, ""), f"Q: {question}", "A:"]
    else:
        # No-retrieval arm: byte-identical to the --no-schema training rows.
        lines = [f"Q: {question}", "A:"]
    if failed_query:
        # Replace the trailing "Q: ...", "A:" pair — the repair block restates
        # the question itself.
        lines[-2:] = [
            f"Q: {question}",
            f"Your previous attempt failed. Query: {failed_query}",
            f"Backend parser said: {error}",
            "Fix it. A:",
        ]
    return "\n".join(lines)
