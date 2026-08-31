"""queryglot as an HTTP JSON API — what the ask-widget and playground call.

Engine outcomes are payloads, never HTTP errors: an abstention is a correct
answer and arrives as a 200. Error codes are reserved for transport-level
faults (bad request, bad token). The app factory takes the Engine so tests
inject fakes; the console script (main) builds one from env/flags exactly
like mcp_server.py.
"""

from __future__ import annotations

import os
import time

from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from . import __version__
from .engine import Engine


class SearchRequest(BaseModel):
    question: str
    backend: str | None = None


def create_app(engine: Engine, cors_origins: list[str] | None = None) -> FastAPI:
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
        token = os.getenv("QUERYGLOT_SERVE_TOKEN", "")
        if token and request.url.path.startswith("/api/"):
            supplied = request.headers.get("authorization", "")
            if supplied != f"Bearer {token}":
                return JSONResponse({"detail": "invalid or missing bearer token"}, status_code=401)
        return await call_next(request)

    @app.post("/api/refresh")
    def refresh() -> dict:
        return engine.refresh_schema()

    @app.get("/api/status")
    def status() -> dict:
        counts = {name: len(engine.catalog.by_backend(name)) for name in engine.backends}
        return {"backends": counts, "version": __version__}

    @app.post("/api/search")
    def search(request: SearchRequest) -> dict:
        if not request.question.strip():
            raise HTTPException(status_code=400, detail="question must be non-empty")
        started = time.monotonic()
        answer = engine.search(request.question, backend=request.backend)
        payload = answer.as_dict()
        payload["elapsed_ms"] = int((time.monotonic() - started) * 1000)
        return payload

    @app.get("/api/schema")
    def schema(query: str = "", limit: int = 20) -> dict:
        items = engine.catalog.items
        if query:
            needle = query.lower()
            items = [i for i in items if needle in i.name.lower() or needle in i.help.lower()]
        return {"items": [item.render() for item in items[:limit]]}

    return app
