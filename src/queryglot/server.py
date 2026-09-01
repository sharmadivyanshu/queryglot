"""queryglot as an HTTP JSON API — what the ask-widget and playground call.

Engine outcomes are payloads, never HTTP errors: an abstention is a correct
answer and arrives as a 200. Error codes are reserved for transport-level
faults (bad request, bad token). The app factory takes the Engine so tests
inject fakes; the console script (main) builds one from env/flags exactly
like mcp_server.py.
"""

from __future__ import annotations

import hmac
import json
import logging
import os
import time
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import __version__
from .engine import Engine
from .llm import LLM, OpenAICompatibleLLM

logger = logging.getLogger("queryglot.server")


class SearchRequest(BaseModel):
    question: str
    backend: str | None = None


class SummaryRequest(BaseModel):
    question: str
    query: str
    result: object = None


SUMMARY_SYSTEM = (
    "You summarize observability query results conversationally, in one or "
    "two short sentences. Use ONLY numbers and label values present in the "
    "provided data — never invent, compute, or speculate, and never add "
    "units (%, ms, s) that are not in the data. No advice."
)

CACHE_TTL_SECONDS = 60.0
CACHE_MAX_ENTRIES = 256


def create_app(
    engine: Engine,
    cors_origins: list[str] | None = None,
    static_dir: Path | None = None,
    summary_llm: LLM | None = None,
) -> FastAPI:
    app = FastAPI(title="queryglot", version=__version__)
    if not engine.catalog.items:
        engine.refresh_schema()

    if cors_origins:
        from fastapi.middleware.cors import CORSMiddleware

        app.add_middleware(
            CORSMiddleware,
            allow_origins=cors_origins,
            allow_methods=["GET", "POST"],
            allow_headers=["Authorization", "Content-Type"],
        )

    @app.middleware("http")
    async def bearer_guard(request, call_next):  # env read per request so tests can monkeypatch
        # OPTIONS requests exempt from bearer check (CORS preflights carry no Authorization)
        if request.method == "OPTIONS":
            return await call_next(request)

        token = os.getenv("QUERYGLOT_SERVE_TOKEN", "")
        if token and request.url.path.startswith("/api/"):
            supplied = request.headers.get("authorization", "")
            expected = f"Bearer {token}"
            # Starlette decodes headers as latin-1; compare_digest needs
            # matching types (and rejects non-ASCII str input outright), so
            # compare bytes rather than str.
            supplied_bytes = supplied.encode("latin-1", "ignore")
            expected_bytes = expected.encode("latin-1", "ignore")
            if not hmac.compare_digest(supplied_bytes, expected_bytes):
                response = JSONResponse(
                    {"detail": "invalid or missing bearer token"}, status_code=401
                )
                # The guard runs outside CORSMiddleware, so a 401 short-circuit
                # would otherwise skip CORS headers entirely and cross-origin
                # widgets would see an opaque CORS failure instead of a 401.
                origin = request.headers.get("origin")
                if origin and cors_origins and origin in cors_origins:
                    response.headers["Access-Control-Allow-Origin"] = origin
                    response.headers["Vary"] = "Origin"
                return response
        return await call_next(request)

    @app.post("/api/refresh")
    def refresh() -> dict:
        search_cache.clear()
        try:
            return engine.refresh_schema()
        except Exception as exc:
            logger.exception("refresh failed")
            return {
                "outcome": "failed",
                "reason": f"engine error ({type(exc).__name__}) — details in server logs",
            }

    @app.get("/api/status")
    def status() -> dict:
        counts = {name: len(engine.catalog.by_backend(name)) for name in engine.backends}
        return {"backends": counts, "version": __version__}

    search_cache: dict[tuple[str, str], tuple[float, dict]] = {}

    def cache_key(request: SearchRequest) -> tuple[str, str]:
        return (" ".join(request.question.lower().split()), request.backend or "")

    @app.post("/api/search")
    def search(request: SearchRequest) -> dict:
        if not request.question.strip():
            raise HTTPException(status_code=400, detail="question must be non-empty")
        key = cache_key(request)
        hit = search_cache.get(key)
        if hit and time.monotonic() - hit[0] < CACHE_TTL_SECONDS:
            return {**hit[1], "cached": True}
        started = time.monotonic()
        try:
            answer = engine.search(request.question, backend=request.backend)
            payload = answer.as_dict()
        except Exception as exc:
            logger.exception("search failed")
            payload = {
                "outcome": "failed",
                "backend": request.backend or "",
                "query": "",
                "result": None,
                "reason": f"engine error ({type(exc).__name__}) — details in server logs",
                "schema_used": [],
                "attempts": 0,
            }
        payload["elapsed_ms"] = int((time.monotonic() - started) * 1000)
        if payload["outcome"] == "answered":
            if len(search_cache) >= CACHE_MAX_ENTRIES:
                search_cache.clear()
            search_cache[key] = (time.monotonic(), payload)
        return payload

    @app.get("/api/schema")
    def schema(query: str = "", limit: int = 20) -> dict:
        items = engine.catalog.items
        if query:
            needle = query.lower()
            items = [i for i in items if needle in i.name.lower() or needle in i.help.lower()]
        return {"items": [item.render() for item in items[:limit]]}

    static_dir = static_dir if static_dir is not None else Path(__file__).parent / "_static"

    @app.get("/favicon.svg", include_in_schema=False)
    def favicon() -> FileResponse:
        icon = static_dir / "favicon.svg"
        if not icon.exists():
            raise HTTPException(
                status_code=404, detail="favicon not built — see frontend/README.md"
            )
        return FileResponse(icon, media_type="image/svg+xml")

    @app.post("/api/summary")
    def summary(request: SummaryRequest) -> dict:
        if summary_llm is None:
            return {"summary": ""}
        data = json.dumps(request.result, default=str)[:1500]
        prompt = (
            f"Question: {request.question}\n"
            f"Query that ran: {request.query}\n"
            f"Result data: {data}\n"
            "Conversational summary:"
        )
        try:
            text = summary_llm.complete(SUMMARY_SYSTEM, prompt).strip()
        except Exception:
            logger.exception("summary failed")
            return {"summary": ""}
        return {"summary": text}

    @app.get("/widget.js", include_in_schema=False)
    def widget_js() -> FileResponse:
        bundle = static_dir / "widget.js"
        if not bundle.exists():
            raise HTTPException(status_code=404, detail="widget not built — see frontend/README.md")
        return FileResponse(
            bundle,
            media_type="text/javascript",
            headers={"Cache-Control": "no-cache"},
        )

    @app.get("/", include_in_schema=False)
    def index() -> FileResponse:
        page = static_dir / "index.html"
        if not page.exists():
            raise HTTPException(
                status_code=404, detail="playground not built — see frontend/README.md"
            )
        return FileResponse(page)

    if (static_dir / "assets").exists():
        app.mount("/assets", StaticFiles(directory=static_dir / "assets"), name="assets")

    return app


def main() -> None:
    import argparse

    import uvicorn

    from .backends import Backend
    from .backends.elastic import ElasticBackend
    from .backends.openapi import OpenAPIBackend, headers_from_env
    from .backends.prometheus import PrometheusBackend

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prometheus", default=os.getenv("QUERYGLOT_PROMETHEUS"))
    parser.add_argument("--elastic", default=os.getenv("QUERYGLOT_ELASTIC"))
    parser.add_argument("--openapi", default=os.getenv("QUERYGLOT_OPENAPI"))
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument(
        "--cors-origin",
        action="append",
        default=None,
        help=(
            "allowed origin for embedding (repeatable); "
            "env QUERYGLOT_CORS_ORIGINS (comma-separated)"
        ),
    )
    args = parser.parse_args()

    backends: list[Backend] = []
    if args.prometheus:
        backends.append(PrometheusBackend(args.prometheus))
    if args.elastic:
        backends.append(ElasticBackend(args.elastic, os.getenv("QUERYGLOT_ELASTIC_INDEX", "*")))
    if args.openapi:
        backends.append(OpenAPIBackend(args.openapi, headers=headers_from_env()))
    if not backends:
        parser.error("configure at least one backend (--prometheus / --elastic / --openapi)")

    origins = args.cors_origin or [
        o.strip() for o in os.getenv("QUERYGLOT_CORS_ORIGINS", "").split(",") if o.strip()
    ]
    uvicorn.run(
        create_app(
            Engine(backends),
            cors_origins=origins or None,
            summary_llm=OpenAICompatibleLLM(max_tokens=80),
        ),
        host=args.host,
        port=args.port,
    )


if __name__ == "__main__":
    main()
