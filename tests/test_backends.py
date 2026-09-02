"""Backend units with fake transports; wire formats pinned exactly."""

import json

import pytest

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
            "/api/v1/series": (200, {"status": "success", "data": [{"__name__": "m", "job": "j"}]}),
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
            "/api/v1/series": (200, {"status": "success", "data": [{"__name__": "m", "job": "j"}]}),
            "/api/v1/format_query": (200, {"status": "success", "data": "ok"}),
        }
    )
    backend.introspect()
    assert backend.validate("rate(req_duration_bucket[5m])").ok
    assert backend.validate("rate(req_duration_sum[5m])").ok
    assert not backend.validate("rate(other_bucket[5m])").ok


def test_validate_rejects_grouping_by_unknown_label():
    """Absent-label grouping is valid PromQL (it silently collapses groups),
    so the server can't catch it — the catalog can. Observed live: the model
    grouped by (endpoint) on a metric whose label is handler."""
    backend = PrometheusBackend(
        "http://prom",
        transport=Recorder(
            {
                "/api/v1/metadata": (
                    200,
                    {
                        "status": "success",
                        "data": {
                            "prometheus_http_request_duration_seconds": [
                                {"type": "histogram", "help": "latencies"}
                            ]
                        },
                    },
                ),
                "/api/v1/series": (
                    200,
                    {
                        "status": "success",
                        "data": [{"__name__": "x", "handler": "/", "instance": "i", "job": "j"}],
                    },
                ),
                "/api/v1/format_query": (200, {"status": "success", "data": "ok"}),
            }
        ),
    )
    backend.introspect()
    verdict = backend.validate(
        "topk(5, sum by (endpoint) (rate(prometheus_http_request_duration_seconds_bucket[5m])))"
    )
    assert not verdict.ok
    assert "endpoint" in verdict.error and "handler" in verdict.error
    # the SYNONYMS table powers a deterministic suggestion
    assert "did you mean" in verdict.error

    # known label + the histogram-synthetic le are both fine
    assert backend.validate(
        "histogram_quantile(0.95, sum by (le, handler) "
        "(rate(prometheus_http_request_duration_seconds_bucket[5m])))"
    ).ok


def test_validate_skips_label_check_when_labels_unknown():
    backend = PrometheusBackend(
        "http://prom",
        transport=Recorder(
            {
                "/api/v1/metadata": (
                    200,
                    {
                        "status": "success",
                        "data": {"some_metric": [{"type": "counter", "help": ""}]},
                    },
                ),
                "/api/v1/format_query": (200, {"status": "success", "data": "ok"}),
            }
        ),
        label_lookup_limit=0,
    )
    backend.introspect()
    assert backend.validate("sum by (anything) (rate(some_metric[5m]))").ok


def test_histogram_labels_come_from_bucket_series():
    """Histograms have no series under the base name — only _bucket/_sum/_count.
    Label introspection must fall back to the bucket series, or every
    histogram has unknown labels and the grouping check never fires."""

    def transport(method, url, body, headers):
        if "/api/v1/metadata" in url:
            return 200, json.dumps(
                {"status": "success", "data": {"h_seconds": [{"type": "histogram", "help": ""}]}}
            )
        if "/api/v1/series" in url and "h_seconds_bucket" in url:
            return 200, json.dumps(
                {
                    "status": "success",
                    "data": [{"__name__": "h_seconds_bucket", "handler": "/", "le": "0.5"}],
                }
            )
        if "/api/v1/series" in url:
            return 200, json.dumps({"status": "success", "data": []})
        return 200, json.dumps({"status": "success", "data": "ok"})

    backend = PrometheusBackend("http://prom", transport=transport)
    items = backend.introspect()
    assert items[0].labels == ("handler", "le")
    verdict = backend.validate("sum by (endpoint) (rate(h_seconds_bucket[5m]))")
    assert not verdict.ok and "endpoint" in verdict.error


def test_introspect_drops_metrics_with_no_live_series():
    """Metadata lists every metric the server has EVER known; dead ones (no
    series) can't answer anything, evade the label check, and return empty
    'successes'. When the series probe ran and found nothing, drop the metric."""

    def transport(method, url, body, headers):
        if "/api/v1/metadata" in url:
            return 200, json.dumps(
                {
                    "status": "success",
                    "data": {
                        "alive_total": [{"type": "counter", "help": ""}],
                        "dead_rpc_seconds": [{"type": "summary", "help": ""}],
                    },
                }
            )
        if "/api/v1/series" in url and "alive_total" in url:
            return 200, json.dumps(
                {"status": "success", "data": [{"__name__": "alive_total", "job": "j"}]}
            )
        return 200, json.dumps({"status": "success", "data": []})

    backend = PrometheusBackend("http://prom", transport=transport)
    names = {i.name for i in backend.introspect()}
    assert names == {"alive_total"}


def test_introspect_keeps_metrics_when_probe_was_skipped():
    def transport(method, url, body, headers):
        if "/api/v1/metadata" in url:
            return 200, json.dumps(
                {"status": "success", "data": {"unprobed_total": [{"type": "counter", "help": ""}]}}
            )
        return 200, json.dumps({"status": "success", "data": []})

    backend = PrometheusBackend("http://prom", transport=transport, label_lookup_limit=0)
    names = {i.name for i in backend.introspect()}
    assert names == {"unprobed_total"}


def test_validate_rejects_bucket_suffix_on_summary():
    """_bucket series exist only for histograms. A summary's _bucket query is
    valid PromQL that always returns empty — observed live on the self-exported
    consul SD summary. The metadata knows the type; validation should use it."""

    def transport(method, url, body, headers):
        if "/api/v1/metadata" in url:
            return 200, json.dumps(
                {"status": "success", "data": {"rpc_seconds": [{"type": "summary", "help": ""}]}}
            )
        if "/api/v1/series" in url:
            return 200, json.dumps(
                {"status": "success", "data": [{"__name__": "rpc_seconds", "endpoint": "catalog"}]}
            )
        return 200, json.dumps({"status": "success", "data": "ok"})

    backend = PrometheusBackend("http://prom", transport=transport)
    backend.introspect()
    verdict = backend.validate("sum by (endpoint) (rate(rpc_seconds_bucket[5m]))")
    assert not verdict.ok
    assert "summary" in verdict.error and "_bucket" in verdict.error
    # the summary's real series remain fine
    assert backend.validate("rate(rpc_seconds_count[5m])").ok
    assert backend.validate('rpc_seconds{quantile="0.5"}').ok


def test_prometheus_execute_range_hits_query_range_with_window():
    recorder = Recorder(
        {
            "/api/v1/query_range": (
                200,
                {"status": "success", "data": {"resultType": "matrix", "result": []}},
            ),
        }
    )
    backend = PrometheusBackend("http://x:9090", transport=recorder)
    run = backend.execute_range("rate(up[1m])", start=1000.0, end=2800.0, step=30.0)
    assert run.ok
    method, url, body = recorder.requests[0]
    assert "query_range" in url
    from urllib.parse import parse_qs

    sent = parse_qs(body.decode())
    assert sent["query"] == ["rate(up[1m])"]
    assert sent["start"] == ["1000.0"]
    assert sent["end"] == ["2800.0"]
    assert sent["step"] == ["30.0"]


def test_prometheus_execute_range_surfaces_errors():
    backend = prom({"/api/v1/query_range": (400, {"status": "error", "error": "bad step"})})
    run = backend.execute_range("up", start=0.0, end=1.0, step=0.0)
    assert not run.ok and "bad step" in run.error


def test_elastic_execute_range_is_not_implemented():
    backend = ElasticBackend("http://x:9200", transport=Recorder({}))
    with pytest.raises(NotImplementedError):
        backend.execute_range("{}", 0.0, 1.0, 15.0)
