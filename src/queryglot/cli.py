"""Direct CLI for humans: `queryglot "p95 latency by handler"`"""

from __future__ import annotations

import argparse
import json
import os

from .backends import Backend
from .backends.elastic import ElasticBackend
from .backends.prometheus import PrometheusBackend
from .engine import Engine


def main() -> int:
    parser = argparse.ArgumentParser(prog="queryglot", description=__doc__)
    parser.add_argument("question")
    parser.add_argument("--backend", default=None, help="prometheus | elasticsearch")
    parser.add_argument("--prometheus", default=os.getenv("QUERYGLOT_PROMETHEUS"))
    parser.add_argument("--elastic", default=os.getenv("QUERYGLOT_ELASTIC"))
    parser.add_argument("--json", action="store_true", help="machine-readable output")
    args = parser.parse_args()

    backends: list[Backend] = []
    if args.prometheus:
        backends.append(PrometheusBackend(args.prometheus))
    if args.elastic:
        backends.append(ElasticBackend(args.elastic))
    if not backends:
        parser.error("configure at least one backend (--prometheus / --elastic)")

    engine = Engine(backends)
    counts = engine.refresh_schema()
    answer = engine.search(args.question, backend=args.backend)

    if args.json:
        print(json.dumps(answer.as_dict(), indent=2, default=str))
        return 0 if answer.outcome == "answered" else 1

    print(f"schema     : {counts}")
    print(f"backend    : {answer.backend}")
    print(f"outcome    : {answer.outcome}")
    if answer.query:
        print(f"query      : {answer.query}")
    if answer.schema_used:
        print(f"consulted  : {', '.join(answer.schema_used[:6])}")
    if answer.reason:
        print(f"reason     : {answer.reason}")
    if answer.outcome == "answered":
        print(json.dumps(answer.result, indent=2, default=str)[:2000])
    return 0 if answer.outcome == "answered" else 1


if __name__ == "__main__":
    raise SystemExit(main())
