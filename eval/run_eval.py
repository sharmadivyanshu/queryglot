"""Golden-question eval: deterministic scoring, no LLM judge.

A question scores correct when the outcome matches, every `must_reference`
entry appears in the final query (an entry may be a list of alternatives —
any one satisfies), AND (for answered) the query executed against the live
backend. Abstention questions score correct only when the system refuses —
punishing confident invention is the point of the eval.

The header block prints which server/model/adapter actually answered, so an
arm label can never silently disagree with reality: the arm-3 runs that were
really arm 1 (mlx-lm 0.31.3 ignores --adapter-path; see HANDOFF.md) are the
argument for it.

    QUERYGLOT_TEST_PROM=http://localhost:9090 \
    QUERYGLOT_LLM_URL=http://127.0.0.1:8080/v1 QUERYGLOT_LLM_MODEL=<model> \
    QUERYGLOT_LLM_ADAPTERS=finetune/adapters \
    python eval/run_eval.py                     # arm 3;  --no-retrieval = arm 2
"""

from __future__ import annotations

import argparse
import json
import os
import pathlib
import sys
import urllib.error
import urllib.request

sys.path.insert(0, str(pathlib.Path(__file__).parent.parent / "src"))

from queryglot import Engine, OpenAICompatibleLLM, PrometheusBackend  # noqa: E402


def satisfied(query: str, must_reference: list) -> bool:
    """Every entry must appear; a list entry is satisfied by any alternative."""
    return all(
        any(alt in query for alt in ([ref] if isinstance(ref, str) else ref))
        for ref in must_reference
    )


def fingerprint(llm: OpenAICompatibleLLM) -> list[str]:
    """What is actually being evaluated. Printed into the tee'd results file."""
    try:
        with urllib.request.urlopen(f"{llm.base_url}/models", timeout=10) as response:
            served = [m.get("id", "?") for m in json.loads(response.read()).get("data", [])]
    except (urllib.error.URLError, OSError, ValueError) as exc:
        served = [f"unreachable: {exc}"]
    return [
        f"llm url    : {llm.base_url}",
        f"model sent : {llm.model}",
        f"adapters   : {llm.adapters or '(none — base model)'}",
        f"server has : {', '.join(served)}",
    ]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--no-retrieval",
        action="store_true",
        help="arm 2: bare Q/A prompts, no schema slice, no abstention gate",
    )
    args = parser.parse_args()

    prom = os.getenv("QUERYGLOT_TEST_PROM", "http://127.0.0.1:9090")
    llm = OpenAICompatibleLLM()
    engine = Engine([PrometheusBackend(prom)], llm=llm, use_retrieval=not args.no_retrieval)
    engine.refresh_schema()

    print(f"retrieval  : {'OFF (arm 2 mode)' if args.no_retrieval else 'on'}")
    for line in fingerprint(llm):
        print(line)
    print()

    golden = [
        json.loads(line)
        for line in (pathlib.Path(__file__).parent / "golden.jsonl").read_text().splitlines()
        if line.strip()
    ]

    correct = 0
    for case in golden:
        answer = engine.search(case["question"], backend=case["backend"])
        ok = answer.outcome == case["expect"] and satisfied(answer.query, case["must_reference"])
        correct += ok
        mark = "PASS" if ok else "FAIL"
        print(f"[{mark}] {case['question']}")
        print(f"       -> {answer.outcome}: {answer.query or answer.reason}")

    print(f"\n{correct}/{len(golden)} correct")
    return 0 if correct == len(golden) else 1


if __name__ == "__main__":
    raise SystemExit(main())
