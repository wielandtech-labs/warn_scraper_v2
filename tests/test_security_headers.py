"""Tests for the app-level security headers (warn_v2.api.security_headers)."""
from __future__ import annotations

from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from fastapi.testclient import TestClient

from warn_v2.api.security_headers import DOCS_CSP, SITE_CSP, SecurityHeadersMiddleware


def _client() -> TestClient:
    app = FastAPI(docs_url=None, redoc_url=None)
    app.add_middleware(SecurityHeadersMiddleware)

    @app.get("/embed/notices/{nid}")
    def embed_card(nid: str) -> HTMLResponse:
        return HTMLResponse("<p>card</p>", headers={"Content-Security-Policy": "frame-ancestors *"})

    @app.get("/own")
    def own() -> HTMLResponse:
        return HTMLResponse("x", headers={"X-Content-Type-Options": "custom"})

    @app.get("/{path:path}")
    def page(path: str) -> HTMLResponse:
        return HTMLResponse("<p>page</p>")

    return TestClient(app)


def test_site_pages_get_nosniff_enforced_framing_and_report_only_policy():
    resp = _client().get("/notices")
    assert resp.headers["x-content-type-options"] == "nosniff"
    assert resp.headers["content-security-policy"] == "frame-ancestors 'self'"
    assert resp.headers["content-security-policy-report-only"] == SITE_CSP


def test_docs_pages_get_the_docs_policy():
    for path in ("/docs", "/redoc", "/docs/oauth2-redirect"):
        resp = _client().get(path)
        assert resp.headers["content-security-policy-report-only"] == DOCS_CSP, path


def test_embed_keeps_its_own_framing_and_gets_no_report_only_policy():
    resp = _client().get("/embed/notices/abc")
    assert resp.headers.get_list("content-security-policy") == ["frame-ancestors *"]
    assert "content-security-policy-report-only" not in resp.headers
    assert resp.headers["x-content-type-options"] == "nosniff"


def test_route_headers_win():
    assert _client().get("/own").headers.get_list("x-content-type-options") == ["custom"]


def test_report_only_policies_keep_the_hardening_directives():
    for policy in (SITE_CSP, DOCS_CSP):
        assert "frame-ancestors 'self'" in policy
        assert "object-src 'none'" in policy


def test_app_installs_the_middleware():
    from warn_v2.api import app

    assert any(m.cls is SecurityHeadersMiddleware for m in app.user_middleware)
