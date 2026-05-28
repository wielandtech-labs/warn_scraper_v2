"""warn_v2.api — read-only FastAPI service for WARN notice data."""
from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from prometheus_client import make_asgi_app

from warn_v2.api.routes import companies, notices, runs, stats
from warn_v2.observability.metrics import enrichment_backlog

log = logging.getLogger(__name__)


def _seed_backlog() -> None:
    """Query the DB and update the enrichment_backlog Prometheus gauge."""
    try:
        from sqlalchemy import func, select

        from warn_v2.db.models import Company
        from warn_v2.db.session import get_session_factory

        with get_session_factory()() as session:
            n = session.scalar(select(func.count()).where(Company.enriched_at.is_(None)))
        enrichment_backlog.set(n or 0)
        log.info("enrichment_backlog seeded to %d", n or 0)
    except Exception:
        log.warning("could not seed enrichment_backlog at startup", exc_info=True)


@asynccontextmanager
async def _lifespan(_app: FastAPI) -> AsyncIterator[None]:
    _seed_backlog()
    yield


def create_app() -> FastAPI:
    app = FastAPI(
        title="WARN Scraper",
        version="2",
        description="Read-only API for WARN Act layoff notices, companies, and scraper audit logs.",
        lifespan=_lifespan,
    )

    # --- health probe (readiness + liveness) ---
    @app.get("/healthz", tags=["health"], include_in_schema=False)
    def healthz() -> dict:
        return {"status": "ok"}

    # --- Prometheus metrics endpoint ---
    app.mount("/metrics", make_asgi_app())

    # --- domain routes ---
    app.include_router(notices.router)
    app.include_router(companies.router)
    app.include_router(runs.router)
    app.include_router(stats.router)

    # --- SPA static assets (mounted LAST so API routes take precedence) ---
    # In dev (no built bundle) the directory won't exist; skip silently.
    from pathlib import Path
    from typing import Any

    from fastapi import HTTPException
    from fastapi.staticfiles import StaticFiles
    from starlette.requests import Request
    from starlette.responses import Response

    static_dir = Path(__file__).parent / "static"
    if static_dir.exists():

        class SPAStaticFiles(StaticFiles):
            """StaticFiles subclass that falls back to index.html for any path
            not found on disk — required for React client-side routing so that
            a hard refresh on /notices, /map, /stats, etc. returns the SPA
            rather than FastAPI's JSON 404 response."""

            async def get_response(self, path: str, scope: Any) -> Response:
                try:
                    return await super().get_response(path, scope)
                except HTTPException as exc:
                    if exc.status_code == 404:
                        return await super().get_response("index.html", scope)
                    raise

        app.mount("/", SPAStaticFiles(directory=static_dir, html=True), name="ui")

    return app


# Module-level app instance used by uvicorn ("warn_v2.api:app")
app = create_app()
