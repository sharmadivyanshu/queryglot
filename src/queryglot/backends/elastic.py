"""Elasticsearch backend.

Introspection: GET {index}/_mapping flattened into per-field SchemaItems.
Validation: the cluster's own parser via GET {index}/_validate/query?explain,
which returns the reason for invalid queries without executing them.
Queries are Query DSL as JSON strings (the model emits JSON).
"""

from __future__ import annotations

import json

from ..catalog import SchemaItem
from . import Execution, Validation
from .http import Transport, get_json, post_json, urllib_transport


def flatten_mapping(properties: dict, prefix: str = "") -> list[tuple[str, str]]:
    """{'a': {'properties': {'b': {'type': 'keyword'}}}} -> [('a.b', 'keyword')]"""
    fields: list[tuple[str, str]] = []
    for field_name, spec in sorted(properties.items()):
        path = f"{prefix}{field_name}"
        if "properties" in spec:
            fields.extend(flatten_mapping(spec["properties"], f"{path}."))
        else:
            fields.append((path, spec.get("type", "object")))
    return fields


class ElasticBackend:
    name = "elasticsearch"
    language = "Elasticsearch Query DSL (JSON)"

    def __init__(
        self,
        base_url: str = "http://127.0.0.1:9200",
        index: str = "*",
        transport: Transport | None = None,
    ):
        self.base_url = base_url.rstrip("/")
        self.index = index
        self.transport = transport or urllib_transport
        self._known: set[str] = set()

    def introspect(self) -> list[SchemaItem]:
        mappings = get_json(self.transport, f"{self.base_url}/{self.index}/_mapping")
        items: list[SchemaItem] = []
        for index_name, body in sorted(mappings.items()):
            properties = body.get("mappings", {}).get("properties", {})
            for path, field_type in flatten_mapping(properties):
                items.append(
                    SchemaItem(
                        name=path,
                        backend=self.name,
                        kind="field",
                        type=field_type,
                        parent=index_name,
                    )
                )
        self._known = {i.name for i in items}
        return items

    def _parse(self, query: str) -> tuple[dict | None, str]:
        try:
            body = json.loads(query)
        except json.JSONDecodeError as exc:
            return None, f"not valid JSON: {exc}"
        if not isinstance(body, dict):
            return None, "query must be a JSON object"
        return body, ""

    def validate(self, query: str) -> Validation:
        body, error = self._parse(query)
        if body is None:
            return Validation(ok=False, error=error)
        # _validate/query takes only the "query" clause, not aggs/size.
        clause = body.get("query", {"match_all": {}})
        _, payload = post_json(
            self.transport,
            f"{self.base_url}/{self.index}/_validate/query?explain=true",
            {"query": clause},
        )
        if not payload.get("valid", False):
            explanations = payload.get("explanations", [])
            reason = (
                "; ".join(e.get("error", "") for e in explanations if e.get("error"))
                or json.dumps(payload)[:300]
            )
            return Validation(ok=False, error=reason)
        return Validation(ok=True)

    def execute(self, query: str) -> Execution:
        body, error = self._parse(query)
        if body is None:
            return Execution(ok=False, error=error)
        body.setdefault("size", 10)
        status, payload = post_json(self.transport, f"{self.base_url}/{self.index}/_search", body)
        if status >= 400 or "error" in payload:
            return Execution(ok=False, error=json.dumps(payload.get("error", payload))[:400])
        return Execution(ok=True, data=payload)
