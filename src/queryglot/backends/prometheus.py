"""Prometheus backend.

Introspection: /api/v1/metadata (types + help) joined with per-metric label
keys from /api/v1/series over a recent window.

Validation: /api/v1/format_query — Prometheus's own parser. If it round-trips,
the query is syntactically valid PromQL for THIS server's version. Parse
errors come back verbatim and feed the repair loop.
"""

from __future__ import annotations

import re
import urllib.parse

from ..catalog import SchemaItem
from . import Execution, Validation
from .http import Transport, get_json, post_form, urllib_transport

# PromQL identifiers that look like metrics but aren't. Used only for the
# unknown-metric check, never for syntax (the server owns syntax).
_PROMQL_KEYWORDS = frozenset(
    [
        "sum",
        "min",
        "max",
        "avg",
        "count",
        "count_values",
        "stddev",
        "stdvar",
        "topk",
        "bottomk",
        "quantile",
        "group",
        "by",
        "without",
        "on",
        "ignoring",
        "offset",
        "bool",
        "and",
        "or",
        "unless",
        "rate",
        "irate",
        "increase",
        "delta",
        "idelta",
        "deriv",
        "predict_linear",
        "histogram_quantile",
        "histogram_avg",
        "histogram_count",
        "histogram_sum",
        "label_replace",
        "label_join",
        "vector",
        "scalar",
        "time",
        "timestamp",
        "clamp",
        "clamp_max",
        "clamp_min",
        "abs",
        "absent",
        "absent_over_time",
        "ceil",
        "floor",
        "round",
        "exp",
        "ln",
        "log2",
        "log10",
        "sqrt",
        "sgn",
        "sort",
        "sort_desc",
        "changes",
        "resets",
        "day_of_month",
        "day_of_week",
        "day_of_year",
        "days_in_month",
        "hour",
        "minute",
        "month",
        "year",
        "avg_over_time",
        "min_over_time",
        "max_over_time",
        "sum_over_time",
        "count_over_time",
        "quantile_over_time",
        "stddev_over_time",
        "stdvar_over_time",
        "last_over_time",
        "present_over_time",
        "mad_over_time",
        "group_left",
        "group_right",
    ]
)
_IDENT = re.compile(r"\b[a-zA-Z_:][a-zA-Z0-9_:]*\b")


def metric_candidates(query: str) -> set[str]:
    """Identifiers in a query that plausibly reference metrics.

    Best-effort by design: label NAMES inside {} are excluded by stripping
    brace bodies; keywords and functions are filtered. Used to produce a
    helpful 'unknown metric' error, not as a security boundary.
    """
    stripped = re.sub(r"\{[^}]*\}", "", query)  # label matchers
    stripped = re.sub(r"\[[^\]]*\]", "", stripped)  # range selectors
    stripped = re.sub(r'"[^"]*"', "", stripped)  # string literals
    # grouping/matching clauses hold LABEL names, not metrics:
    #   by (handler), without (le), on (job), ignoring (code), group_left (x)
    stripped = re.sub(
        r"\b(?:by|without|on|ignoring|group_left|group_right)\s*\([^)]*\)",
        " ",
        stripped,
    )
    return {
        ident
        for ident in _IDENT.findall(stripped)
        if ident not in _PROMQL_KEYWORDS and not ident.isdigit()
    }


_GROUPING = re.compile(r"\b(?:by|without)\s*\(([^)]*)\)")

# Labels synthesized by PromQL itself, never present in series metadata.
_SYNTHETIC_LABELS = frozenset(["le", "quantile"])


def grouping_labels(query: str) -> set[str]:
    """Label names inside by (...) / without (...) clauses."""
    labels: set[str] = set()
    for group in _GROUPING.findall(query):
        labels.update(part.strip() for part in group.split(",") if part.strip())
    return labels


class PrometheusBackend:
    name = "prometheus"
    language = "PromQL"

    def __init__(
        self,
        base_url: str = "http://127.0.0.1:9090",
        transport: Transport | None = None,
        label_lookup_limit: int = 400,
    ):
        self.base_url = base_url.rstrip("/")
        self.transport = transport or urllib_transport
        self.label_lookup_limit = label_lookup_limit
        self._known: set[str] = set()
        self._known_labels: dict[str, tuple[str, ...]] = {}

    # ---- introspect --------------------------------------------------------

    def introspect(self) -> list[SchemaItem]:
        meta = get_json(self.transport, f"{self.base_url}/api/v1/metadata").get("data", {})
        items: list[SchemaItem] = []
        for metric_name, entries in sorted(meta.items()):
            entry = entries[0] if entries else {}
            items.append(
                SchemaItem(
                    name=metric_name,
                    backend=self.name,
                    kind="metric",
                    type=entry.get("type", ""),
                    help=entry.get("help", ""),
                    labels=self._label_keys(metric_name),
                )
            )
        self._known = {i.name for i in items}
        self._known_labels = {i.name: i.labels for i in items}
        return items

    def _label_keys(self, metric_name: str) -> tuple[str, ...]:
        if self.label_lookup_limit <= 0:
            return ()
        self.label_lookup_limit -= 1
        encoded = urllib.parse.quote(metric_name)
        try:
            series = get_json(
                self.transport,
                f"{self.base_url}/api/v1/series?match[]={encoded}&limit=5",
            ).get("data", [])
        except (ConnectionError, ValueError):
            return ()
        keys = {k for s in series for k in s if k != "__name__"}
        if not keys:
            # Histograms/summaries have no series under the base name — the
            # bucket series carry the real label set (plus the synthetic le).
            encoded_bucket = urllib.parse.quote(f"{metric_name}_bucket")
            try:
                series = get_json(
                    self.transport,
                    f"{self.base_url}/api/v1/series?match[]={encoded_bucket}&limit=5",
                ).get("data", [])
            except (ConnectionError, ValueError):
                return ()
            keys = {k for s in series for k in s if k != "__name__"}
        return tuple(sorted(keys))

    # ---- validate ----------------------------------------------------------

    def validate(self, query: str) -> Validation:
        status, payload = post_form(
            self.transport, f"{self.base_url}/api/v1/format_query", {"query": query}
        )
        if payload.get("status") != "success":
            return Validation(ok=False, error=payload.get("error", f"HTTP {status}"))

        if self._known:
            # Histogram/summary metadata lists the BASE name; the series that
            # PromQL actually addresses carry _bucket/_sum/_count suffixes.
            # A query over x_bucket is valid whenever x is known.
            def resolved(name: str) -> bool:
                if name in self._known:
                    return True
                base = re.sub(r"_(bucket|sum|count)$", "", name)
                return base != name and base in self._known

            unknown = {n for n in metric_candidates(query) if not resolved(n)}
            if unknown:
                return Validation(
                    ok=False,
                    error=(
                        f"unknown metric(s) {sorted(unknown)} — not in this server's "
                        "catalog; use only metrics from the schema provided"
                    ),
                )

            # Grouping by an ABSENT label is valid PromQL — it silently
            # collapses every series into one group, which reads as an answer
            # while answering nothing. The server cannot catch it; the
            # introspected label sets can, best-effort: only enforced when
            # every referenced metric has known labels.
            def base(name: str) -> str:
                stripped = re.sub(r"_(bucket|sum|count)$", "", name)
                return stripped if stripped in self._known else name

            referenced = {base(n) for n in metric_candidates(query)}
            known_label_sets = [self._known_labels.get(n, ()) for n in referenced]
            if referenced and all(known_label_sets):
                allowed = _SYNTHETIC_LABELS.union(*known_label_sets)
                bad = {g for g in grouping_labels(query) if g not in allowed}
                if bad:
                    from ..retrieve import expand

                    hints = [
                        f"did you mean {hit!r} instead of {g!r}?"
                        for g in sorted(bad)
                        for hit in [next((s for s in expand([g]) if s in allowed), None)]
                        if hit
                    ]
                    hint = f" {' '.join(hints)}" if hints else ""
                    return Validation(
                        ok=False,
                        error=(
                            f"unknown grouping label(s) {sorted(bad)} for the metrics in "
                            f"this query — known labels: "
                            f"{sorted(set(allowed) - _SYNTHETIC_LABELS)}.{hint}"
                        ),
                    )
        return Validation(ok=True)

    # ---- execute -----------------------------------------------------------

    def execute(self, query: str) -> Execution:
        status, payload = post_form(
            self.transport, f"{self.base_url}/api/v1/query", {"query": query}
        )
        if payload.get("status") != "success":
            return Execution(ok=False, error=payload.get("error", f"HTTP {status}"))
        return Execution(ok=True, data=payload.get("data"))
