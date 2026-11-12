"""Security headers the app sets on its own responses.

Traefik adds only HSTS in front of this app: ``/embed/*`` is framed by other
sites, so a router-wide ``X-Frame-Options`` would break it. Framing policy and
the rest therefore live here, where the path is known:

- ``X-Content-Type-Options: nosniff`` on every response.
- ``Content-Security-Policy: frame-ancestors 'self'`` on everything except
  ``/embed/*``, which sends its own ``frame-ancestors *`` (routes/embed.py).
- ``Content-Security-Policy-Report-Only`` with the full policy, also except
  ``/embed/*``. Report-Only blocks nothing; violations show in the browser
  console. It becomes the enforced policy once a soak shows none.

``setdefault`` throughout, so a route that sets one of these keeps its value.
"""
from __future__ import annotations

from starlette.datastructures import MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

# Google Analytics 4: gtag.js, and its hits (stats.g.doubleclick.net with
# Google signals on).
_GA_SCRIPT = "https://*.googletagmanager.com"
_GA_HITS = (
    "https://*.google-analytics.com https://analytics.google.com "
    "https://*.analytics.google.com https://*.googletagmanager.com "
    "https://*.g.doubleclick.net"
)
# Raster map tiles (lib/themeColors.ts TILE_LAYERS): <img> in LocationMap,
# fetch() in the MapLibre maps; MapLibre also fetches glyphs from openfreemap.
_TILES = "https://*.tile.openstreetmap.org https://*.basemaps.cartocdn.com"

# The SPA. 'unsafe-inline' scripts: the theme bootstrap and gtag snippet in
# index.html; styles: React style="" attributes.
SITE_CSP = "; ".join(
    [
        "default-src 'self'",
        f"script-src 'self' 'unsafe-inline' {_GA_SCRIPT}",
        "style-src 'self' 'unsafe-inline'",
        f"img-src 'self' data: blob: {_TILES} {_GA_HITS}",
        "font-src 'self' data:",
        f"connect-src 'self' {_TILES} https://tiles.openfreemap.org {_GA_HITS}",
        "worker-src 'self' blob:",
        # The embed dialog previews /embed/* in an iframe.
        "frame-src 'self'",
        "object-src 'none'",
        "base-uri 'self'",
        "form-action 'self'",
        "frame-ancestors 'self'",
    ]
)

# FastAPI's Swagger UI (/docs) and ReDoc (/redoc) pages load their bundles from
# cdn.jsdelivr.net; ReDoc also uses Google Fonts and a blob: worker.
DOCS_CSP = "; ".join(
    [
        "default-src 'self'",
        "script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net",
        "style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net https://fonts.googleapis.com",
        "img-src 'self' data: https://fastapi.tiangolo.com https://cdn.redoc.ly",
        "font-src 'self' https://fonts.gstatic.com",
        "worker-src 'self' blob:",
        "object-src 'none'",
        "base-uri 'self'",
        "form-action 'self'",
        "frame-ancestors 'self'",
    ]
)

_EMBED_PREFIX = "/embed/"


def _policy_for(path: str) -> str | None:
    if path.startswith(_EMBED_PREFIX):
        return None
    if path in ("/docs", "/redoc") or path.startswith("/docs/"):
        return DOCS_CSP
    return SITE_CSP


class SecurityHeadersMiddleware:
    """Plain ASGI, like CanonicalHostMiddleware: it only edits the response
    start message, so streamed responses pass through untouched."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        policy = _policy_for(scope["path"])

        async def send_with_headers(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = MutableHeaders(scope=message)
                headers.setdefault("X-Content-Type-Options", "nosniff")
                if policy is not None:
                    headers.setdefault("Content-Security-Policy", "frame-ancestors 'self'")
                    headers.setdefault("Content-Security-Policy-Report-Only", policy)
            await send(message)

        await self.app(scope, receive, send_with_headers)
