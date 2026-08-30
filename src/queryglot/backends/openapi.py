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
import os
import urllib.parse

from ..catalog import SchemaItem
from . import Execution, Validation
from .http import Transport, urllib_transport


def headers_from_env() -> dict[str, str]:
    """QUERYGLOT_OPENAPI_HEADERS is a JSON object of header name -> value."""
    raw = os.getenv("QUERYGLOT_OPENAPI_HEADERS", "")
    return json.loads(raw) if raw else {}


_LOCAL_PARAM_REF = "#/components/parameters/"


def _resolve_param(raw: dict, components_parameters: dict) -> dict | None:
    """Resolve a parameter object, following a local `#/components/parameters/*`
    $ref against the spec's own components. Any other $ref shape (external
    file, nested pointer) is unresolvable and signalled with None — the
    caller drops the whole operation, never crashes."""
    ref = raw.get("$ref")
    if ref is None:
        return raw
    if isinstance(ref, str) and ref.startswith(_LOCAL_PARAM_REF):
        resolved = components_parameters.get(ref[len(_LOCAL_PARAM_REF) :])
        if isinstance(resolved, dict):
            return resolved
    return None


def _query_value(value: object) -> object:
    """Booleans must serialize as lowercase true/false, never Python's True/False."""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, list):
        return [_query_value(v) for v in value]
    return value


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

        components_parameters = spec.get("components", {}).get("parameters", {})
        if not isinstance(components_parameters, dict):
            components_parameters = {}

        items: list[SchemaItem] = []
        self._ops = {}
        for path, methods in sorted(paths.items()):
            operation = methods.get("get")
            if not operation:
                continue  # mutating operations stay absent by design
            op_id = operation.get("operationId") or "get_" + path.strip("/").replace(
                "/", "_"
            ).replace("{", "").replace("}", "")

            # Path-item-level parameters are shared by every operation on the
            # path; operation-level parameters win on (name, in) collisions.
            raw_params = list(methods.get("parameters", [])) + list(operation.get("parameters", []))
            merged_params: dict[tuple[str, str], dict] = {}
            skip_operation = False
            for raw in raw_params:
                resolved = _resolve_param(raw, components_parameters)
                if resolved is None:
                    skip_operation = True
                    break
                key = (str(resolved.get("name", "")), str(resolved.get("in", "")))
                merged_params[key] = resolved
            if skip_operation:
                continue  # unresolvable $ref — absent, not a crash
            params = list(merged_params.values())

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

    _TYPE_CHECKS = {
        "string": lambda v: isinstance(v, str),
        "integer": lambda v: isinstance(v, int) and not isinstance(v, bool),
        "number": lambda v: isinstance(v, int | float) and not isinstance(v, bool),
        "boolean": lambda v: isinstance(v, bool),
        "array": lambda v: isinstance(v, list),
    }

    def _parse(self, query: str) -> tuple[dict | None, str]:
        try:
            body = json.loads(query)
        except json.JSONDecodeError as exc:
            return None, f"not valid JSON: {exc}"
        if not isinstance(body, dict) or not isinstance(body.get("operationId"), str):
            return None, 'call must be a JSON object with a string "operationId"'
        if not isinstance(body.get("parameters", {}), dict):
            return None, '"parameters" must be a JSON object'
        return body, ""

    def validate(self, query: str) -> Validation:
        body, error = self._parse(query)
        if body is None:
            return Validation(ok=False, error=error)
        op_id = body["operationId"]
        operation = self._ops.get(op_id)
        if operation is None:
            return Validation(
                ok=False,
                error=(
                    f"unknown operation {op_id!r} — not in this server's catalog; "
                    "use only operations from the schema provided"
                ),
            )
        supplied = body.get("parameters", {})
        spec_params = {p["name"]: p for p in operation["parameters"]}
        missing = sorted(
            name for name, p in spec_params.items() if p.get("required") and name not in supplied
        )
        if missing:
            return Validation(
                ok=False, error=f"missing required parameter(s) {missing} for {op_id}"
            )
        for name, value in supplied.items():
            spec_param = spec_params.get(name)
            if spec_param is None:
                return Validation(
                    ok=False,
                    error=f"unknown parameter {name!r} for {op_id}; known: {sorted(spec_params)}",
                )
            schema = spec_param.get("schema", {})
            check = self._TYPE_CHECKS.get(schema.get("type", ""))
            if check and not check(value):
                return Validation(
                    ok=False,
                    error=(
                        f"parameter {name!r} must be of type {schema['type']}, "
                        f"got {type(value).__name__}"
                    ),
                )
            if "enum" in schema and value not in schema["enum"]:
                return Validation(
                    ok=False,
                    error=f"parameter {name!r} must be one of {schema['enum']}, got {value!r}",
                )
        return Validation(ok=True)

    def execute(self, query: str) -> Execution:
        body, error = self._parse(query)
        if body is None:
            return Execution(ok=False, error=error)
        operation = self._ops.get(body["operationId"])
        if operation is None:
            return Execution(ok=False, error=f"unknown operation {body['operationId']!r}")
        path = operation["path"]
        spec_params = {p["name"]: p for p in operation["parameters"]}
        query_params: dict[str, object] = {}
        for name, value in body.get("parameters", {}).items():
            if spec_params.get(name, {}).get("in") == "path":
                path = path.replace("{" + name + "}", urllib.parse.quote(str(value), safe=""))
            else:
                query_params[name] = value
        url = f"{self.base_url}{path}"
        if query_params:
            encoded = {name: _query_value(value) for name, value in query_params.items()}
            url += "?" + urllib.parse.urlencode(encoded, doseq=True)
        status, text = self._get(url)
        if status >= 400:
            return Execution(ok=False, error=f"HTTP {status}: {text[:400]}")
        try:
            return Execution(ok=True, data=json.loads(text))
        except ValueError:
            return Execution(ok=True, data=text)
