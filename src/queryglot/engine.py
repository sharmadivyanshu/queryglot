"""Top-level engine: wires backends, retrieval and the graph together."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .backends import Backend
from .catalog import Catalog
from .graph import build_graph
from .llm import LLM, OpenAICompatibleLLM
from .retrieve import SchemaRetriever


@dataclass
class Answer:
    outcome: str  # answered | abstained | failed
    backend: str
    query: str = ""
    result: Any = None
    reason: str = ""
    schema_used: list[str] = field(default_factory=list)
    attempts: int = 0

    def as_dict(self) -> dict:
        return {
            "outcome": self.outcome,
            "backend": self.backend,
            "query": self.query,
            "result": self.result,
            "reason": self.reason,
            "schema_used": self.schema_used,
            "attempts": self.attempts,
        }


class Engine:
    def __init__(self, backends: list[Backend], llm: LLM | None = None, use_retrieval: bool = True):
        if not backends:
            raise ValueError("at least one backend is required")
        self.backends = {b.name: b for b in backends}
        self.llm = llm or OpenAICompatibleLLM()
        self.use_retrieval = use_retrieval
        self.catalog = Catalog()
        self._graphs: dict[str, Any] = {}

    def refresh_schema(self) -> dict[str, int]:
        """Re-introspect every backend. Call at startup and on demand —
        schemas drift as deploys add metrics and mappings."""
        self.catalog = Catalog()
        counts: dict[str, int] = {}
        for name, backend in self.backends.items():
            items = backend.introspect()
            self.catalog.add(*items)
            counts[name] = len(items)
        retriever = SchemaRetriever(self.catalog) if self.use_retrieval else None
        self._graphs = {
            name: build_graph(backend, retriever, self.llm)
            for name, backend in self.backends.items()
        }
        return counts

    def search(self, question: str, backend: str | None = None) -> Answer:
        if not self._graphs:
            self.refresh_schema()
        name = backend or self._pick_backend(question)
        if name not in self._graphs:
            return Answer(
                outcome="failed",
                backend=name or "?",
                reason=f"unknown backend {name!r}; have {sorted(self._graphs)}",
            )
        final = self._graphs[name].invoke({"question": question})
        return Answer(
            outcome=final.get("outcome", "failed"),
            backend=name,
            query=final.get("query", ""),
            result=final.get("result"),
            reason=final.get("reason", ""),
            schema_used=[item.name for item in final.get("schema", [])],
            attempts=len(final.get("attempts", [])) + (1 if final.get("query") else 0),
        )

    def _pick_backend(self, question: str) -> str:
        """Route by retrieval strength: ask every backend's schema who matches
        best. Deterministic, explainable, and no extra model call."""
        retriever = SchemaRetriever(self.catalog)
        best_name, best_score = next(iter(self.backends)), -1.0
        for name in self.backends:
            hits = retriever.search(question, backend=name, k=1)
            score = hits[0][1] if hits else 0.0
            if score > best_score:
                best_name, best_score = name, score
        return best_name
