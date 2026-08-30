"""Unified schema catalog.

Every backend introspects into the same shape, so retrieval and prompting are
backend-agnostic. The catalog IS the RAG corpus: the hard part of
text-to-query is not syntax, it is knowing that YOUR latency metric is called
`http_server_request_duration_seconds` and carries a `route` label — facts no
base model can know and no fine-tune should memorise (they change per
environment, per deploy).
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class SchemaItem:
    """One searchable unit of schema: a metric, an index field, a label."""

    name: str
    backend: str  # "prometheus" | "elasticsearch" | ...
    kind: str  # "metric" | "field" | "label"
    type: str = ""  # counter | gauge | histogram | keyword | date | ...
    help: str = ""  # human description when the backend provides one
    labels: tuple[str, ...] = ()  # for metrics: known label keys
    parent: str = ""  # for fields: the index they belong to

    def render(self) -> str:
        """How this item appears in a compile prompt. Compact but complete."""
        bits = [f"{self.name} ({self.type or self.kind})"]
        if self.labels:
            bits.append(f"labels: {', '.join(self.labels)}")
        if self.parent:
            bits.append(f"index: {self.parent}")
        if self.help:
            bits.append(self.help.strip().rstrip("."))
        return " — ".join(bits)


@dataclass
class Catalog:
    items: list[SchemaItem] = field(default_factory=list)

    def add(self, *items: SchemaItem) -> None:
        self.items.extend(items)

    def names(self, backend: str | None = None) -> set[str]:
        return {i.name for i in self.items if backend is None or i.backend == backend}

    def by_backend(self, backend: str) -> list[SchemaItem]:
        return [i for i in self.items if i.backend == backend]

    def __len__(self) -> int:
        return len(self.items)
