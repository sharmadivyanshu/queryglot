"""Fine-tune dataset generator: NL->PromQL pairs from a LIVE schema.

Design rules, each load-bearing:

1. **Every pair is machine-verified.** A candidate query must parse
   (format_query) AND execute against the live backend, or it is discarded —
   never hand-fixed. A training set with invalid targets teaches invalid
   syntax; verification makes that structurally impossible.

2. **Training prompts are the engine's prompts.** Each example is rendered
   with `prompts.compile_prompt` over a real retrieval slice — the exact
   text the model will see inside queryglot at inference. Train/serve skew
   is the quiet killer of fine-tunes.

3. **Pairs where retrieval cannot find the target metric are dropped**, and
   counted. If retrieval can't surface the metric, the deployed system could
   never answer that question either — keeping the pair would teach the
   model to answer AROUND the provided schema, i.e. to hallucinate.

4. **Split by metric, never by row.** Paraphrases of one question must not
   straddle train/test, and held-out METRICS measure generalisation to
   unseen schema rather than memorisation of seen names. The split is a
   deterministic hash of the metric name — reproducible without a seed file.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path

from .backends.prometheus import PrometheusBackend
from .catalog import Catalog, SchemaItem
from .prompts import SYSTEM, compile_prompt
from .retrieve import SchemaRetriever

RETRIEVAL_K = 8  # must match the engine's k — rule 2


def subject_phrase(metric: str) -> str:
    """A human-ish phrase for a metric name: go_goroutines -> 'go goroutines'."""
    phrase = re.sub(r"_(total|sum|count|bucket|seconds|bytes)$", "", metric)
    return phrase.replace("_", " ").replace(":", " ").strip()


@dataclass(frozen=True)
class Template:
    family: str
    question: str  # format fields: subject, metric, label, quantile
    query: str


COUNTER_TEMPLATES = [
    Template("rate", "what is the per-second rate of {subject}?", "rate({metric}[5m])"),
    Template("rate", "how fast is {subject} increasing?", "rate({metric}[5m])"),
    Template("rate", "{subject} rate over the last 5 minutes", "rate({metric}[5m])"),
    Template("increase", "how much did {subject} grow in the last hour?", "increase({metric}[1h])"),
    Template("increase", "total increase of {subject} over 1h", "increase({metric}[1h])"),
    Template("total", "cumulative {subject} so far", "{metric}"),
]
COUNTER_BY_LABEL = [
    Template(
        "rate_by", "rate of {subject}, split by {label}", "sum by ({label}) (rate({metric}[5m]))"
    ),
    Template(
        "rate_by",
        "which {label} has the most {subject}?",
        "topk(5, sum by ({label}) (rate({metric}[5m])))",
    ),
]
GAUGE_TEMPLATES = [
    Template("current", "what is the current value of {subject}?", "{metric}"),
    Template("current", "how much {subject} right now?", "{metric}"),
    Template(
        "avg_over", "average {subject} over the last 10 minutes", "avg_over_time({metric}[10m])"
    ),
    Template("max_over", "peak {subject} in the last hour", "max_over_time({metric}[1h])"),
]
HISTOGRAM_TEMPLATES = [
    Template(
        "quantile",
        "p{qpct} {subject}",
        "histogram_quantile(0.{q}, sum by (le) (rate({metric}[5m])))",
    ),
    Template(
        "quantile",
        "{qpct}th percentile of {subject}",
        "histogram_quantile(0.{q}, sum by (le) (rate({metric}[5m])))",
    ),
]
QUANTILES = ["50", "90", "95", "99"]


@dataclass
class Pair:
    question: str
    query: str
    metric: str
    family: str
    split: str = ""


def split_for(metric: str) -> str:
    """Deterministic 80/10/10 by metric-name hash."""
    bucket = int(hashlib.md5(metric.encode()).hexdigest(), 16) % 10
    return "train" if bucket < 8 else ("valid" if bucket == 8 else "test")


def candidates(items: list[SchemaItem]) -> Iterator[Pair]:
    for item in items:
        if item.kind != "metric":
            continue
        subject = subject_phrase(item.name)
        fields = {"subject": subject, "metric": item.name}

        if item.type == "histogram":
            # Metadata lists the base name; PromQL addresses {base}_bucket.
            for template in HISTOGRAM_TEMPLATES:
                for quantile in QUANTILES:
                    yield Pair(
                        question=template.question.format(subject=subject, qpct=quantile),
                        query=template.query.format(metric=f"{item.name}_bucket", q=quantile),
                        metric=item.name,
                        family=template.family,
                    )
            yield Pair(
                f"average {subject}",
                f"rate({item.name}_sum[5m]) / rate({item.name}_count[5m])",
                item.name,
                "hist_avg",
            )
        elif item.type == "summary":
            yield Pair(
                f"average {subject}",
                f"rate({item.name}_sum[5m]) / rate({item.name}_count[5m])",
                item.name,
                "summary_avg",
            )
        elif item.type == "counter" or item.name.endswith("_total"):
            for template in COUNTER_TEMPLATES:
                yield Pair(
                    template.question.format(**fields),
                    template.query.format(**fields),
                    item.name,
                    template.family,
                )
            for label in item.labels[:2]:
                for template in COUNTER_BY_LABEL:
                    yield Pair(
                        template.question.format(label=label, **fields),
                        template.query.format(label=label, **fields),
                        item.name,
                        template.family,
                    )
        elif item.type == "gauge":
            for template in GAUGE_TEMPLATES:
                yield Pair(
                    template.question.format(**fields),
                    template.query.format(**fields),
                    item.name,
                    template.family,
                )


@dataclass
class Report:
    kept: int = 0
    failed_validation: int = 0
    failed_execution: int = 0
    retrieval_miss: int = 0
    per_split: dict[str, int] = field(default_factory=lambda: {"train": 0, "valid": 0, "test": 0})

    def as_dict(self) -> dict:
        return {
            "kept": self.kept,
            "failed_validation": self.failed_validation,
            "failed_execution": self.failed_execution,
            "retrieval_miss": self.retrieval_miss,
            "per_split": self.per_split,
        }


def generate(
    backend: PrometheusBackend, out_dir: Path, include_schema: bool = True, limit: int | None = None
) -> Report:
    items = backend.introspect()
    catalog = Catalog()
    catalog.add(*items)
    retriever = SchemaRetriever(catalog)
    system = SYSTEM.format(language=backend.language, backend=backend.name)

    report = Report()
    rows: dict[str, list[dict]] = {"train": [], "valid": [], "test": []}

    for pair in candidates(items):
        if limit and report.kept >= limit:
            break

        verdict = backend.validate(pair.query)
        if not verdict.ok:
            report.failed_validation += 1
            continue
        if not backend.execute(pair.query).ok:
            report.failed_execution += 1
            continue

        hits = retriever.search(pair.question, backend=backend.name, k=RETRIEVAL_K)
        slice_items = [item for item, _ in hits]
        if pair.metric not in {i.name for i in slice_items}:
            report.retrieval_miss += 1  # rule 3
            continue

        # Empty schema renders the bare Q/A prompt — the same code path the
        # no-retrieval arm serves, so train/serve parity holds for BOTH arms.
        prompt = compile_prompt(pair.question, slice_items if include_schema else [], backend.name)
        pair.split = split_for(pair.metric)
        rows[pair.split].append(
            {
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": prompt},
                    {"role": "assistant", "content": pair.query},
                ],
                "metadata": {"metric": pair.metric, "family": pair.family},
            }
        )
        report.kept += 1
        report.per_split[pair.split] += 1

    out_dir.mkdir(parents=True, exist_ok=True)
    for split, split_rows in rows.items():
        with (out_dir / f"{split}.jsonl").open("w") as handle:
            for row in split_rows:
                handle.write(json.dumps(row) + "\n")
    (out_dir / "report.json").write_text(json.dumps(report.as_dict(), indent=2))
    return report


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prometheus", default="http://127.0.0.1:9090")
    parser.add_argument("--out", default="finetune/data")
    parser.add_argument(
        "--no-schema",
        action="store_true",
        help="emit the FT-only variant (no schema slice in prompts)",
    )
    parser.add_argument("--limit", type=int, default=None)
    args = parser.parse_args()

    backend = PrometheusBackend(args.prometheus)
    report = generate(backend, Path(args.out), include_schema=not args.no_schema, limit=args.limit)
    print(json.dumps(report.as_dict(), indent=2))
    if report.kept == 0:
        print("nothing kept — is the backend reachable and scraped?")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
