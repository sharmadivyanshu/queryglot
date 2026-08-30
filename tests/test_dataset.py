"""Dataset generator: verification gate, split discipline, prompt consistency."""

import json

from queryglot.catalog import SchemaItem
from queryglot.dataset import candidates, generate, split_for, subject_phrase


def item(name, type_, labels=()):
    return SchemaItem(
        name=name, backend="prometheus", kind="metric", type=type_, labels=tuple(labels)
    )


class VerifyingBackend:
    """Real PrometheusBackend shape, scripted verification."""

    name, language = "prometheus", "PromQL"

    def __init__(self, items, reject_substring=None):
        self._items = items
        self.reject = reject_substring

    def introspect(self):
        return self._items

    def validate(self, query):
        from queryglot.backends import Validation

        if self.reject and self.reject in query:
            return Validation(ok=False, error="scripted rejection")
        return Validation(ok=True)

    def execute(self, query):
        from queryglot.backends import Execution

        return Execution(ok=True, data={"result": []})


def test_subject_phrase_strips_suffixes():
    assert subject_phrase("http_requests_total") == "http requests"
    assert subject_phrase("process_resident_memory_bytes") == "process resident memory"


def test_split_is_deterministic_and_covers_all():
    assert split_for("some_metric") == split_for("some_metric")
    buckets = {split_for(f"m{i}") for i in range(200)}
    assert buckets == {"train", "valid", "test"}


def test_histogram_metadata_name_yields_bucket_queries():
    """The bug the first audit caught: metadata lists BASE names."""
    pairs = list(candidates([item("req_duration_seconds", "histogram")]))
    families = {p.family for p in pairs}
    assert "quantile" in families and "hist_avg" in families
    quantile = next(p for p in pairs if p.family == "quantile")
    assert "req_duration_seconds_bucket" in quantile.query
    assert quantile.metric == "req_duration_seconds"  # split key stays base


def test_counter_labels_produce_by_templates():
    pairs = list(candidates([item("jobs_done_total", "counter", labels=("queue",))]))
    assert any("sum by (queue)" in p.query for p in pairs)


def test_generate_writes_disjoint_splits(tmp_path):
    items = [item(f"metric_{i}_total", "counter") for i in range(40)]
    report = generate(VerifyingBackend(items), tmp_path)
    assert report.kept > 0 and report.failed_validation == 0

    seen: dict[str, str] = {}
    for split in ["train", "valid", "test"]:
        for line in (tmp_path / f"{split}.jsonl").read_text().splitlines():
            metric = json.loads(line)["metadata"]["metric"]
            assert seen.setdefault(metric, split) == split, "metric straddles splits"


def test_rejected_queries_are_dropped_not_written(tmp_path):
    items = [item("good_total", "counter"), item("bad_total", "counter")]
    report = generate(VerifyingBackend(items, reject_substring="bad_total"), tmp_path)
    assert report.failed_validation > 0
    rows = [
        json.loads(line)
        for split in ["train", "valid", "test"]
        for line in (tmp_path / f"{split}.jsonl").read_text().splitlines()
    ]
    # bad_total may appear in schema SLICES (it exists on the server) — but it
    # must never be a training TARGET, and never appear in an assistant turn.
    assert all(r["metadata"]["metric"] != "bad_total" for r in rows)
    assert all("bad_total" not in r["messages"][2]["content"] for r in rows)


def test_prompt_contains_target_metric_and_engine_format(tmp_path):
    generate(VerifyingBackend([item("cache_hits_total", "counter")]), tmp_path)
    rows = [
        json.loads(line)
        for s in ["train", "valid", "test"]
        for line in (tmp_path / f"{s}.jsonl").read_text().splitlines()
    ]
    assert rows
    user = rows[0]["messages"][1]["content"]
    assert "cache_hits_total" in user
    assert "Schema (the only" in user  # the engine's exact prompt shape
    assert rows[0]["messages"][2]["content"]  # assistant turn is the raw query


def test_no_schema_variant_for_ft_only_arm(tmp_path):
    generate(
        VerifyingBackend([item("cache_hits_total", "counter")]), tmp_path, include_schema=False
    )
    rows = [
        json.loads(line)
        for s in ["train", "valid", "test"]
        for line in (tmp_path / f"{s}.jsonl").read_text().splitlines()
    ]
    assert all("Schema (the only" not in r["messages"][1]["content"] for r in rows)
