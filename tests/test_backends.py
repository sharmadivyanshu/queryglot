"""Backend units with fake transports; wire formats pinned exactly."""

import json

from queryglot.backends.elastic import ElasticBackend, flatten_mapping
from queryglot.backends.prometheus import PrometheusBackend, metric_candidates


class Recorder:
    """Scripted transport: url-substring -> (status, body)."""

    def __init__(self, routes: dict[str, tuple[int, dict]]):
        self.routes = routes
        self.requests: list[tuple[str, str, bytes | None]] = []

    def __call__(self, method, url, body, headers):
        self.requests.append((method, url, body))
        for needle, (status, payload) in self.routes.items():
            if needle in url:
                return status, json.dumps(payload)
        raise AssertionError(f"unrouted request: {url}")


# ---- PromQL identifier extraction ------------------------------------------


def test_metric_candidates_ignores_functions_and_labels():
    query = 'sum by (handler) (rate(http_requests_total{job="api",code=~"5.."}[5m]))'
    assert metric_candidates(query) == {"http_requests_total"}


def test_metric_candidates_multiple_metrics():
    query = "a_total / on() b_total"
    assert metric_candidates(query) == {"a_total", "b_total"}


def test_metric_candidates_histogram_quantile():
    query = "histogram_quantile(0.95, sum by (le) (rate(req_duration_bucket[5m])))"
    assert metric_candidates(query) == {"req_duration_bucket"}


# ---- Prometheus backend ----------------------------------------------------


def prom(routes) -> PrometheusBackend:
    return PrometheusBackend("http://x:9090", transport=Recorder(routes))


def test_prometheus_introspect_builds_items():
    backend = prom(
        {
            "/api/v1/metadata": (
                200,
                {
                    "status": "success",
                    "data": {
                        "up": [{"type": "gauge", "help": "target is up"}],
                    },
                },
            ),
            "/api/v1/series": (
                200,
                {
                    "status": "success",
                    "data": [
                        {"__name__": "up", "job": "api", "instance": "i1"},
                    ],
                },
            ),
        }
    )
    items = backend.introspect()
    assert [i.name for i in items] == ["up"]
    assert items[0].labels == ("instance", "job")
    assert items[0].type == "gauge"


def test_prometheus_validate_flags_unknown_metric():
    backend = prom(
        {
            "/api/v1/metadata": (
                200,
                {"status": "success", "data": {"up": [{"type": "gauge", "help": ""}]}},
            ),
            "/api/v1/series": (200, {"status": "success", "data": []}),
            "/api/v1/format_query": (
                200,
                {"status": "success", "data": "rate(imaginary_total[5m])"},
            ),
        }
    )
    backend.introspect()
    verdict = backend.validate("rate(imaginary_total[5m])")
    assert not verdict.ok
    assert "imaginary_total" in verdict.error


def test_prometheus_validate_surfaces_parse_error():
    backend = prom(
        {
            "/api/v1/format_query": (
                400,
                {
                    "status": "error",
                    "error": "1:11: parse error: unexpected character",
                },
            ),
        }
    )
    verdict = backend.validate("rate(bad{[5m])")
    assert not verdict.ok and "parse error" in verdict.error


# ---- Elasticsearch backend -------------------------------------------------


def test_flatten_mapping_handles_nesting():
    properties = {
        "service": {"type": "keyword"},
        "http": {"properties": {"status": {"type": "integer"}}},
    }
    assert flatten_mapping(properties) == [("http.status", "integer"), ("service", "keyword")]


def test_elastic_introspect_and_validate():
    backend = ElasticBackend(
        "http://x:9200",
        "app-logs",
        transport=Recorder(
            {
                "_mapping": (
                    200,
                    {
                        "app-logs": {
                            "mappings": {
                                "properties": {
                                    "level": {"type": "keyword"},
                                }
                            }
                        }
                    },
                ),
                "_validate/query": (200, {"valid": True}),
            }
        ),
    )
    items = backend.introspect()
    assert items[0].name == "level" and items[0].parent == "app-logs"
    assert backend.validate('{"query": {"term": {"level": "error"}}}').ok


def test_elastic_invalid_json_is_caught_locally():
    backend = ElasticBackend("http://x:9200", transport=Recorder({}))
    verdict = backend.validate("{not json")
    assert not verdict.ok and "JSON" in verdict.error


def test_elastic_invalid_query_reports_reason():
    backend = ElasticBackend(
        "http://x:9200",
        "logs",
        transport=Recorder(
            {
                "_validate/query": (
                    200,
                    {
                        "valid": False,
                        "explanations": [
                            {"error": "no such field [levl]"},
                        ],
                    },
                ),
            }
        ),
    )
    verdict = backend.validate('{"query": {"term": {"levl": "error"}}}')
    assert not verdict.ok and "levl" in verdict.error


def test_prometheus_validate_accepts_histogram_series_suffixes():
    """Metadata knows `req_duration`; PromQL addresses `req_duration_bucket`.
    The suffix must resolve to the known base — the dataset audit caught this."""
    backend = prom(
        {
            "/api/v1/metadata": (
                200,
                {
                    "status": "success",
                    "data": {"req_duration": [{"type": "histogram", "help": ""}]},
                },
            ),
            "/api/v1/series": (200, {"status": "success", "data": []}),
            "/api/v1/format_query": (200, {"status": "success", "data": "ok"}),
        }
    )
    backend.introspect()
    assert backend.validate("rate(req_duration_bucket[5m])").ok
    assert backend.validate("rate(req_duration_sum[5m])").ok
    assert not backend.validate("rate(other_bucket[5m])").ok
