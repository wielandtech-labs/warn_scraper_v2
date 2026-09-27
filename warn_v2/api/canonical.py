"""Permanent redirects from the site's secondary hostnames to the canonical one.

The ingress answers on several hostnames — the canonical apex, its ``www`` form,
a defensive ``.net`` registration, and the legacy ``warn.wielandtech.com`` that
older inbound links and already-delivered emails still point at. Exactly one of
them is canonical (``SITE_BASE_URL``, see :func:`warn_v2.api.seo.site_base_url`);
every other one redirects to it, so search engines consolidate on one origin and
old links keep working instead of 404ing.

Which hostnames redirect is configuration, never inference. Redirecting anything
that merely *isn't* the canonical host would break the kubelet readiness and
liveness probes and the Prometheus scrape: those reach the pod by IP, so they
arrive with a ``Host`` the app has never been told about, and a 3xx fails a probe
that expects 200.
"""
from __future__ import annotations

import os
from collections.abc import Iterable
from urllib.parse import urlsplit

from starlette.datastructures import Headers
from starlette.responses import RedirectResponse
from starlette.types import ASGIApp, Receive, Scope, Send

# cert-manager solves HTTP-01 with its own solver pod behind a more specific
# Ingress path, so in practice these requests never reach us. Exempting them
# anyway is two lines and removes a failure that would otherwise surface as a
# silently unrenewed certificate two months later.
_ACME_PREFIX = "/.well-known/acme-challenge/"


def redirect_hosts() -> frozenset[str]:
    """Hostnames to redirect, from the comma-separated ``REDIRECT_HOSTS`` env var.

    Empty (the default) disables the middleware entirely, which is what local
    development and the test suite want.
    """
    raw = os.getenv("REDIRECT_HOSTS", "")
    return frozenset(h.strip().lower() for h in raw.split(",") if h.strip())


class CanonicalHostMiddleware:
    """Redirect requests for ``hosts`` to the same path on ``canonical``.

    A plain ASGI middleware rather than a ``BaseHTTPMiddleware`` subclass: this
    is a header check that short-circuits or gets out of the way, and it should
    not pay for the extra task and stream plumbing on every single request.
    """

    def __init__(self, app: ASGIApp, hosts: Iterable[str], canonical: str) -> None:
        self.app = app
        self.canonical = canonical.rstrip("/")
        # A canonical host that also appears in REDIRECT_HOSTS would redirect to
        # itself forever. Drop it here rather than trust the configuration.
        own_host = (urlsplit(self.canonical).hostname or "").lower()
        self.hosts = frozenset(h.lower() for h in hosts) - {own_host}

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or not self.hosts:
            await self.app(scope, receive, send)
            return

        if scope["path"].startswith(_ACME_PREFIX):
            await self.app(scope, receive, send)
            return

        host = Headers(scope=scope).get("host", "").split(":")[0].lower()
        if host not in self.hosts:
            await self.app(scope, receive, send)
            return

        target = self.canonical + scope["path"]
        query = scope.get("query_string", b"")
        if query:
            target = f"{target}?{query.decode('latin-1')}"
        # 308 for anything that may carry a body: a 301 permits clients to
        # re-issue the request as a GET, silently dropping the payload. Keeps an
        # API client pointed at an old base URL working rather than half-working.
        status = 301 if scope.get("method") in ("GET", "HEAD") else 308
        await RedirectResponse(target, status_code=status)(scope, receive, send)
