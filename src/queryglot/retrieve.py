"""Schema retrieval — the RAG half of the system.

Deliberately lexical: BM25 over tokenised names and help text, with exact and
substring boosts on names. Schema retrieval is a vocabulary-matching problem
("latency" -> `*_duration_seconds`), not a deep-semantics one, and a
deterministic ranker means retrieval failures are debuggable and the eval is
reproducible with zero model calls. The interface leaves room for an embedding
reranker; add one only when the eval shows lexical recall actually failing.
"""

from __future__ import annotations

import math
import re
from collections import Counter

from .catalog import Catalog, SchemaItem

_TOKEN = re.compile(r"[a-z0-9]+")

# Domain synonyms: the vocabulary gap between how people ask and how
# exporters name things. Small, auditable, and grown from eval failures —
# not a taxonomy imported wholesale.
SYNONYMS: dict[str, list[str]] = {
    "latency": ["duration", "seconds", "time"],
    "slow": ["duration", "seconds", "latency"],
    "errors": ["failed", "errors", "error", "5xx", "exceptions"],
    "failures": ["failed", "errors", "error"],
    "traffic": ["requests", "http", "rate"],
    "throughput": ["requests", "rate", "total"],
    "memory": ["memory", "bytes", "heap", "resident"],
    "cpu": ["cpu", "process", "cores"],
    "disk": ["disk", "filesystem", "bytes"],
    "restarts": ["restarts", "restart", "started"],
    "queue": ["queue", "pending", "backlog"],
    "connections": ["connections", "open", "sockets"],
}


def tokenize(text: str) -> list[str]:
    return _TOKEN.findall(text.lower().replace("_", " ").replace(":", " "))


def expand(tokens: list[str]) -> list[str]:
    out = list(tokens)
    for token in tokens:
        out.extend(SYNONYMS.get(token, []))
    return out


class SchemaRetriever:
    """BM25 with name boosts over a Catalog."""

    def __init__(self, catalog: Catalog, k1: float = 1.5, b: float = 0.75):
        self.catalog = catalog
        self.k1, self.b = k1, b
        self._docs = [tokenize(f"{i.name} {i.help} {' '.join(i.labels)}") for i in catalog.items]
        self._doc_freq: Counter[str] = Counter()
        for doc in self._docs:
            self._doc_freq.update(set(doc))
        self._avg_len = (sum(len(d) for d in self._docs) / len(self._docs)) if self._docs else 0.0

    def _bm25(self, query_tokens: list[str], index: int) -> float:
        doc = self._docs[index]
        if not doc:
            return 0.0
        counts = Counter(doc)
        n_docs = len(self._docs)
        score = 0.0
        for token in query_tokens:
            tf = counts.get(token, 0)
            if not tf:
                continue
            df = self._doc_freq[token]
            idf = math.log(1 + (n_docs - df + 0.5) / (df + 0.5))
            score += (
                idf
                * (tf * (self.k1 + 1))
                / (tf + self.k1 * (1 - self.b + self.b * len(doc) / self._avg_len))
            )
        return score

    def search(
        self, question: str, *, backend: str | None = None, k: int = 8
    ) -> list[tuple[SchemaItem, float]]:
        q_tokens = expand(tokenize(question))
        q_lower = question.lower()
        scored: list[tuple[SchemaItem, float]] = []
        for idx, item in enumerate(self.catalog.items):
            if backend and item.backend != backend:
                continue
            score = self._bm25(q_tokens, idx)
            # Exact-name mention is the strongest possible signal.
            if item.name.lower() in q_lower:
                score += 10.0
            if score > 0:
                scored.append((item, score))
        scored.sort(key=lambda pair: (-pair[1], pair[0].name))
        return scored[:k]
