"""The compile pipeline: retrieve -> compile -> validate -> (repair) -> execute.

Same discipline as any production agent graph:
- validation is the backend's own parser, never the model's self-assessment
- the repair loop is BOUNDED, and every attempt is kept as an audit trail
- when retrieval finds nothing relevant, the system ABSTAINS rather than
  letting the model invent a metric name. Wrong-but-plausible is the failure
  mode that matters; "I can't answer from this schema" is a correct answer.
"""

from __future__ import annotations

from operator import add
from typing import Annotated, Literal, TypedDict

from langgraph.graph import END, START, StateGraph

from .backends import Backend
from .catalog import SchemaItem
from .llm import LLM, extract_query
from .prompts import SYSTEM, compile_prompt
from .rerank import rerank as rerank_hits
from .retrieve import SchemaRetriever

MAX_REPAIRS = 2
MIN_RETRIEVAL_SCORE = 0.35


class Attempt(TypedDict):
    query: str
    error: str


class SearchState(TypedDict, total=False):
    question: str
    schema: list[SchemaItem]
    top_score: float
    query: str
    attempts: Annotated[list[Attempt], add]  # audit trail: accumulates
    validation_error: str
    result: object
    outcome: Literal["answered", "abstained", "failed"]
    reason: str


def build_graph(
    backend: Backend,
    retriever: SchemaRetriever | None,
    llm: LLM,
    checkpointer=None,
    rerank: bool = False,
):
    system = SYSTEM.format(language=backend.language, backend=backend.name)

    def retrieve(state: SearchState) -> dict:
        if retriever is None:  # no-retrieval arm: the model gets no schema slice
            return {"schema": [], "top_score": 0.0}
        hits = retriever.search(state["question"], backend=backend.name)
        top_score = hits[0][1] if hits else 0.0
        if rerank and top_score >= MIN_RETRIEVAL_SCORE:
            # judgment over a closed set; the gate runs on the lexical score,
            # so refusals never reach this call
            hits = rerank_hits(llm, state["question"], hits)
        return {
            "schema": [item for item, _ in hits],
            "top_score": top_score,
        }

    def compile_query(state: SearchState) -> dict:
        previous = state.get("attempts") or []
        failed = previous[-1] if previous else None
        prompt = compile_prompt(
            state["question"],
            state["schema"],
            backend.name,
            failed_query=failed["query"] if failed else "",
            error=failed["error"] if failed else "",
        )
        return {"query": extract_query(llm.complete(system, prompt))}

    def validate(state: SearchState) -> dict:
        verdict = backend.validate(state["query"])
        if verdict.ok:
            return {"validation_error": ""}
        return {
            "validation_error": verdict.error,
            "attempts": [{"query": state["query"], "error": verdict.error}],
        }

    def execute(state: SearchState) -> dict:
        run = backend.execute(state["query"])
        if run.ok:
            return {"result": run.data, "outcome": "answered"}
        return {"outcome": "failed", "reason": f"execution error: {run.error}"}

    def abstain(state: SearchState) -> dict:
        # Attempts distinguish the two abstention paths: exhausted repairs
        # always leave a trail; the retrieval gate abstains before any compile.
        if not state.get("attempts"):
            reason = (
                "nothing in this backend's schema matches the question — "
                "refusing to guess a metric name"
            )
        else:
            tried = "; ".join(a["query"] for a in state.get("attempts", []))
            reason = f"could not produce a valid query after {MAX_REPAIRS + 1} attempts ({tried})"
        return {"outcome": "abstained", "reason": reason}

    def route_after_retrieve(state: SearchState) -> str:
        if retriever is None:  # no gate: abstention is retrieval-based by definition
            return "compile"
        return "compile" if state["top_score"] >= MIN_RETRIEVAL_SCORE else "abstain"

    def route_after_validate(state: SearchState) -> str:
        if not state["validation_error"]:
            return "execute"
        if len(state.get("attempts", [])) > MAX_REPAIRS:
            return "abstain"
        return "compile"

    graph = StateGraph(SearchState)
    graph.add_node("retrieve", retrieve)
    graph.add_node("compile", compile_query)
    graph.add_node("validate", validate)
    graph.add_node("execute", execute)
    graph.add_node("abstain", abstain)

    graph.add_edge(START, "retrieve")
    graph.add_conditional_edges(
        "retrieve", route_after_retrieve, {"compile": "compile", "abstain": "abstain"}
    )
    graph.add_edge("compile", "validate")
    graph.add_conditional_edges(
        "validate",
        route_after_validate,
        {"execute": "execute", "compile": "compile", "abstain": "abstain"},
    )
    graph.add_edge("execute", END)
    graph.add_edge("abstain", END)
    return graph.compile(checkpointer=checkpointer)
