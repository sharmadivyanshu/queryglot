"""Backend protocol: introspect, validate, execute.

The contract that makes queryglot polyglot. `validate` must use the backend's
OWN parser (Prometheus format_query, Elasticsearch _validate/query) — never a
reimplementation, which would drift from the real grammar version by version.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from ..catalog import SchemaItem


@dataclass
class Validation:
    ok: bool
    error: str = ""


@dataclass
class Execution:
    ok: bool
    data: Any = None
    error: str = ""


class Backend(Protocol):
    name: str
    language: str  # "PromQL" | "Elasticsearch Query DSL" | ...

    def introspect(self) -> list[SchemaItem]: ...
    def validate(self, query: str) -> Validation: ...
    def execute(self, query: str) -> Execution: ...

    def execute_range(
        self, query: str, start: float, end: float, step: float
    ) -> Execution:
        """Evaluate `query` over [start, end] epoch seconds at `step`-second
        resolution. Backends with no range concept raise NotImplementedError;
        the engine falls back to execute()."""
        ...
