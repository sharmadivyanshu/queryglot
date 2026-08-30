"""queryglot as an MCP server — the plug-and-play part.

Any MCP client (Claude Desktop, Cursor, your own LangGraph agents) gets a
`search` tool that speaks every configured backend's query language.

    queryglot-mcp --prometheus http://127.0.0.1:9090 --elastic http://127.0.0.1:9200
"""

from __future__ import annotations

import argparse
import os

from mcp.server.fastmcp import FastMCP

from .backends import Backend
from .backends.elastic import ElasticBackend
from .backends.openapi import OpenAPIBackend, headers_from_env
from .backends.prometheus import PrometheusBackend
from .engine import Engine

server = FastMCP("queryglot")
_engine: Engine | None = None


def get_engine() -> Engine:
    global _engine
    if _engine is None:
        backends: list[Backend] = []
        if url := os.getenv("QUERYGLOT_PROMETHEUS"):
            backends.append(PrometheusBackend(url))
        if url := os.getenv("QUERYGLOT_ELASTIC"):
            backends.append(ElasticBackend(url, os.getenv("QUERYGLOT_ELASTIC_INDEX", "*")))
        if url := os.getenv("QUERYGLOT_OPENAPI"):
            backends.append(OpenAPIBackend(url, headers=headers_from_env()))
        _engine = Engine(backends)
        _engine.refresh_schema()
    return _engine


@server.tool()
def search(question: str, backend: str = "") -> dict:
    """Answer a question about observability data (metrics, logs) by compiling
    it into the right backend's query language, validating it against the
    backend's own parser, and executing it. Returns the query used, the raw
    result, and the schema items consulted. May abstain rather than guess."""
    return get_engine().search(question, backend=backend or None).as_dict()


@server.tool()
def list_schema(query: str = "", limit: int = 20) -> list[str]:
    """Browse the discovered schema (metric/field names with types), optionally
    filtered by a search string."""
    engine = get_engine()
    items = engine.catalog.items
    if query:
        needle = query.lower()
        items = [i for i in items if needle in i.name.lower() or needle in i.help.lower()]
    return [item.render() for item in items[:limit]]


@server.tool()
def refresh_schema() -> dict:
    """Re-introspect all backends (schemas drift as services deploy)."""
    return get_engine().refresh_schema()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prometheus", help="Prometheus base URL")
    parser.add_argument("--elastic", help="Elasticsearch base URL")
    parser.add_argument("--elastic-index", default="*")
    parser.add_argument("--openapi", help="OpenAPI service base URL (API root)")
    args = parser.parse_args()
    if args.prometheus:
        os.environ["QUERYGLOT_PROMETHEUS"] = args.prometheus
    if args.elastic:
        os.environ["QUERYGLOT_ELASTIC"] = args.elastic
        os.environ["QUERYGLOT_ELASTIC_INDEX"] = args.elastic_index
    if args.openapi:
        os.environ["QUERYGLOT_OPENAPI"] = args.openapi
    server.run()


if __name__ == "__main__":
    main()
