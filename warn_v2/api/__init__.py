"""warn_v2.api — read-only FastAPI service for WARN notice data."""
from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.middleware.gzip import GZipMiddleware
from prometheus_client import REGISTRY
from prometheus_client.exposition import choose_encoder
from starlette.responses import Response

from warn_v2.api import ratelimit
from warn_v2.api.routes import (
    auth,
    billing,
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
    usage,
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


def create_app(static_dir: Path | None = None) -> FastAPI:
    app = FastAPI(
        title="WARN Scraper",
        version="2",
        description=(
            "Read-only API for WARN Act layoff notices, companies, and scraper audit logs.\n\n"
            "**Authentication:** anonymous requests work at low rate limits. For "
            "programmatic access, create an account and send an API key as "
            "`X-API-Key: warn_...` or `Authorization: Bearer warn_...` — free keys get a "
            "daily quota; paid tiers add enriched company fields, bulk exports, and "
            "higher limits. Check your quota at `/api/usage`; keyed responses carry "
            "`X-RateLimit-*` headers."
        ),
        lifespan=_lifespan,
    )

    # Compresses everything ≥1 KiB, including the SPA bundle served by the
    # StaticFiles mount below (~1 MB JS → ~300 KB) and large JSON like
    # /api/map-pins (~1 MB → ~150 KB). Level 6, not the default 9 — the pod
    # is CPU-limited and 9 buys ~1% extra ratio for noticeably more CPU.
    app.add_middleware(GZipMiddleware, minimum_size=1024, compresslevel=6)

    # --- health probe (readiness + liveness) ---
    @app.get("/healthz", tags=["health"], include_in_schema=False)
    def healthz() -> dict:
        return {"status": "ok"}

    # --- Prometheus metrics endpoint ---
    # An explicit route, NOT app.mount("/metrics", make_asgi_app()): a Mount
    # only matches /metrics/... (Starlette appends "/{path:path}" to the
    # prefix), so the exact path /metrics fell through to the SPA mount at "/"
    # and Prometheus scraped the index HTML — target down since day one.
    @app.get("/metrics", include_in_schema=False)
    def metrics(request: Request) -> Response:
        # Internal-only: anything that traversed the ingress carries
        # X-Forwarded-For; Prometheus scrapes the pod directly and does not.
        if "x-forwarded-for" in request.headers:
            raise HTTPException(status_code=404)
        encoder, content_type = choose_encoder(request.headers.get("accept", ""))
        return Response(encoder(REGISTRY), media_type=content_type)

    # --- domain routes (all under /api so they don't shadow SPA paths) ---
    # auth/keys/usage/subscriptions stay outside the rate limiter: login and
    # key management must never 429 (they have their own protections), and the
    # usage endpoint is how a limited caller checks their quota.
    app.include_router(auth.router, prefix="/api")
    app.include_router(keys.router, prefix="/api")
    app.include_router(usage.router, prefix="/api")
    app.include_router(billing.router, prefix="/api")  # webhook must never 429
    limited = [Depends(ratelimit.enforce_limits)]
    # Export routes register before notices/companies so /api/notices/export and
    # /api/companies/export aren't swallowed by the parametric /{id} routes.
    app.include_router(exports.router, prefix="/api", dependencies=limited)
    app.include_router(notices.router, prefix="/api", dependencies=limited)
    app.include_router(companies.router, prefix="/api", dependencies=limited)
    app.include_router(runs.router, prefix="/api", dependencies=limited)
    app.include_router(stats.router, prefix="/api", dependencies=limited)
    app.include_router(reports.router, prefix="/api", dependencies=limited)
    app.include_router(map_pins.router, prefix="/api", dependencies=limited)
    app.include_router(search.router, prefix="/api", dependencies=limited)
    app.include_router(subscriptions.router, prefix="/api")

    # --- SEO + feeds (site root, not /api): sitemap.xml, robots.txt, RSS ---
    app.include_router(seo.router)

    # --- SPA static assets (mounted LAST so API routes take precedence) ---
    # In dev (no built bundle) the directory won't exist; skip silently.
    from typing import Any

    from fastapi.staticfiles import StaticFiles
    from starlette.responses import HTMLResponse

    from warn_v2.api.seo import page_meta_for_path, render_index

    if static_dir is None:
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
