"""warn_v2.api — read-only FastAPI service for WARN notice data."""
from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.gzip import GZipMiddleware
from prometheus_client import REGISTRY, make_asgi_app

from warn_v2.api.routes import (
    auth,
    companies,
    exports,
    keys,
    map_pins,
    notices,
    reports,
    runs,
    search,
    seo,
    stats,
    subscriptions,
)
from warn_v2.observability.collector import WarnCollector

log = logging.getLogger(__name__)


@asynccontextmanager
async def _lifespan(_app: FastAPI) -> AsyncIterator[None]:
    try:
        REGISTRY.register(WarnCollector())
        log.info("WarnCollector registered with Prometheus REGISTRY")
    except Exception:
        log.warning("could not register WarnCollector at startup", exc_info=True)
    yield


def create_app() -> FastAPI:
    app = FastAPI(
        title="WARN Scraper",
        version="2",
        description="Read-only API for WARN Act layoff notices, companies, and scraper audit logs.",
        lifespan=_lifespan,
    )

    # Compresses everything ≥1 KiB, including the SPA bundle served by the
    # StaticFiles mount below (~1 MB JS → ~300 KB) and large JSON like
    # /api/map-pins (~1 MB → ~150 KB). Level 6, not the default 9 — the pod
    # is CPU-limited and 9 buys ~1% extra ratio for noticeably more CPU.
    # Prometheus's /metrics app gzips its own responses when asked; Starlette
    # skips anything that already carries Content-Encoding.
    app.add_middleware(GZipMiddleware, minimum_size=1024, compresslevel=6)

    # --- health probe (readiness + liveness) ---
    @app.get("/healthz", tags=["health"], include_in_schema=False)
    def healthz() -> dict:
        return {"status": "ok"}

    # --- Prometheus metrics endpoint ---
    app.mount("/metrics", make_asgi_app())

    # --- domain routes (all under /api so they don't shadow SPA paths) ---
    app.include_router(auth.router, prefix="/api")
    app.include_router(keys.router, prefix="/api")
    # Export routes register before notices/companies so /api/notices/export and
    # /api/companies/export aren't swallowed by the parametric /{id} routes.
    app.include_router(exports.router, prefix="/api")
    app.include_router(notices.router, prefix="/api")
    app.include_router(companies.router, prefix="/api")
    app.include_router(runs.router, prefix="/api")
    app.include_router(stats.router, prefix="/api")
    app.include_router(reports.router, prefix="/api")
    app.include_router(map_pins.router, prefix="/api")
    app.include_router(search.router, prefix="/api")
    app.include_router(subscriptions.router, prefix="/api")

    # --- SEO + feeds (site root, not /api): sitemap.xml, robots.txt, RSS ---
    app.include_router(seo.router)

    # --- SPA static assets (mounted LAST so API routes take precedence) ---
    # In dev (no built bundle) the directory won't exist; skip silently.
    from pathlib import Path
    from typing import Any

    from fastapi.staticfiles import StaticFiles
    from starlette.responses import HTMLResponse, Response

    from warn_v2.api.seo import page_meta_for_path, render_index

    static_dir = Path(__file__).parent / "static"
    if static_dir.exists():

        class SPAStaticFiles(StaticFiles):
            """StaticFiles subclass that serves the React SPA's index.html with
            per-route SEO metadata injected.

            Two jobs:
            1. Client-side routing fallback — a hard refresh on /notices, /map,
               /states/CA, etc. has no file on disk, so we serve index.html
               instead of FastAPI's JSON 404.
            2. SEO — the served index.html gets its <title>/description and
               canonical/OG/JSON-LD tags rewritten for the requested path (see
               warn_v2.api.seo), so crawlers and unfurlers see correct per-page
               metadata despite the body being client-rendered.

            Real asset requests (.js/.css/.svg/...) are served untouched.

            Important: StaticFiles raises starlette.exceptions.HTTPException
            (the base class), not fastapi.HTTPException (its subclass), so we
            must catch the Starlette variant here.
            """

            def __init__(self, *args: Any, **kwargs: Any) -> None:
                super().__init__(*args, **kwargs)
                self._index_html = (Path(self.directory) / "index.html").read_text(
                    encoding="utf-8"
                )

            def _render_index(self, scope: Any) -> Response:
                meta = page_meta_for_path(scope.get("path", "/"))
                resp = HTMLResponse(render_index(self._index_html, meta))
                # Deploys must be picked up on the next navigation; no-cache
                # still allows conditional revalidation, just not blind reuse.
                resp.headers["Cache-Control"] = "no-cache"
                return resp

            async def get_response(self, path: str, scope: Any) -> Response:
                from starlette.exceptions import HTTPException as _StarletteHTTPException

                req_path = scope.get("path", "/")
                try:
                    resp = await super().get_response(path, scope)
                except _StarletteHTTPException as exc:
                    if exc.status_code == 404:
                        return self._render_index(scope)
                    raise
                # The root request resolves to index.html on disk; re-render it
                # with the homepage metadata so "/" gets canonical/OG tags too.
                if req_path == "/":
                    return self._render_index(scope)
                # Vite content-hashes every filename under /assets/, so those
                # responses can never go stale — cache them for a year.
                if req_path.startswith("/assets/"):
                    resp.headers["Cache-Control"] = "public, max-age=31536000, immutable"
                return resp

        app.mount("/", SPAStaticFiles(directory=static_dir, html=True), name="ui")

    return app


# Module-level app instance used by uvicorn ("warn_v2.api:app")
app = create_app()
