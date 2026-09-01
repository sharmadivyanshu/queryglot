"""LLM-as-reranker over a CLOSED candidate set.

Lexical retrieval owns recall; the reranker owns preference. The boundary it
exists for (DESIGN_NOTES bug 17): "which endpoint has max latency" prefers a
live Consul SD summary whose label is literally `endpoint` over the HTTP
histogram a human means — a judgment call no lexical ranker can make.

The contract keeps the credo intact: the model may only REORDER names that
retrieval surfaced (parse is strict; invented names are dropped), anything
unparseable or any transport failure falls back to the lexical order, and
the abstention gate runs on the lexical score BEFORE this step — refusals
never spend a model call.
"""

from __future__ import annotations

from .catalog import SchemaItem
from .llm import LLM

RERANK_SYSTEM = (
    "You rank observability schema items by how well they answer a question. "
    "Reply with ONLY the item names, best match first, comma-separated. "
    "Use only names from the provided list."
)


def rerank_prompt(question: str, items: list[SchemaItem]) -> str:
    lines = [f"Question: {question}", "", "Items:"]
    lines += [f"- {item.render()}" for item in items]
    lines += ["", "Best-matching item names, comma-separated:"]
    return "\n".join(lines)


def parse_rerank(reply: str, names: list[str]) -> list[str]:
    """Names from the reply that are real candidates, in reply order."""
    valid = set(names)
    ordered: list[str] = []
    for token in reply.replace("\n", ",").split(","):
        name = token.strip().strip("`'\"")
        if name in valid and name not in ordered:
            ordered.append(name)
    return ordered


def rerank(
    llm: LLM, question: str, hits: list[tuple[SchemaItem, float]]
) -> list[tuple[SchemaItem, float]]:
    if len(hits) < 2:
        return hits
    names = [item.name for item, _ in hits]
    try:
        reply = llm.complete(RERANK_SYSTEM, rerank_prompt(question, [i for i, _ in hits]))
    except Exception:
        return hits
    preferred = parse_rerank(reply, names)
    if not preferred:
        return hits
    by_name = {item.name: (item, score) for item, score in hits}
    ordered = [by_name[n] for n in preferred]
    ordered += [pair for pair in hits if pair[0].name not in preferred]
    return ordered
