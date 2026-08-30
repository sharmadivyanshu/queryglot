"""OpenAPI backend.

Introspection: the server's OWN spec (GET {base_url}{spec_path}) flattened
into one SchemaItem per GET operation. Mutating operations are not guarded
against — they are ABSENT: never introspected, never retrievable, never in
a prompt. Safety by absence, the same principle as the unknown-metric check.

Validation: the spec is the server's published contract, fetched from the
server itself; checks (operation exists, required params, type, enum) are
implemented directly from the spec dict. Where the spec is incomplete, the
server's own 4xx at execution feeds the repair loop.

Queries are structured calls: {"operationId": ..., "parameters": {...}} —
the model never writes a URL.
"""

from __future__ import annotations

import json

from ..catalog import SchemaItem
from .http import Transport, urllib_transport


class OpenAPIBackend:
    name = "openapi"
    language = 'OpenAPI call (JSON: {"operationId": ..., "parameters": {...}})'

    def __init__(
        self,
        base_url: str,
        spec_path: str = "/openapi.json",
        transport: Transport | None = None,
        headers: dict[str, str] | None = None,
    ):
        self.base_url = base_url.rstrip("/")
        self.spec_path = spec_path
        self.transport = transport or urllib_transport
        self.headers = dict(headers or {})
        self._ops: dict[str, dict] = {}

    def _get(self, url: str) -> tuple[int, str]:
        return self.transport("GET", url, None, self.headers)

    def introspect(self) -> list[SchemaItem]:
        url = f"{self.base_url}{self.spec_path}"
        status, text = self._get(url)
        if status >= 400:
            raise ConnectionError(f"GET {url} -> {status}: {text[:200]}")
        try:
            spec = json.loads(text)
        except ValueError as exc:
            raise ConnectionError(f"spec at {url} is not JSON: {exc}") from exc
        paths = spec.get("paths")
        if not isinstance(paths, dict):
            raise ConnectionError(f"spec at {url} has no 'paths' object")

        items: list[SchemaItem] = []
        self._ops = {}
        for path, methods in sorted(paths.items()):
            operation = methods.get("get")
            if not operation:
                continue  # mutating operations stay absent by design
            op_id = operation.get("operationId") or "get_" + path.strip("/").replace(
                "/", "_"
            ).replace("{", "").replace("}", "")
            params = operation.get("parameters", [])
            help_text = " ".join(
                bit.strip()
                for bit in (operation.get("summary", ""), operation.get("description", ""))
                if bit and bit.strip()
            )
            items.append(
                SchemaItem(
                    name=op_id,
                    backend=self.name,
                    kind="operation",
                    type="GET",
                    help=help_text,
                    labels=tuple(p["name"] for p in params),
                    parent=path,
                )
            )
            self._ops[op_id] = {"path": path, "parameters": params}
        return items
