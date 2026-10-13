"""Tests for the company-logo proxy (warn_v2.api.logo_fetch + /api/logos/{id})."""
from __future__ import annotations

import socket

import httpx
import pytest
from fastapi.testclient import TestClient

from warn_v2.api import logo_fetch as logos
from warn_v2.db.models import Company

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64
ICO = b"\x00\x00\x01\x00" + b"\x00" * 64
SVG = b'<svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script></svg>'


@pytest.fixture(autouse=True)
def _fresh_cache():
    logos.cache.clear()
    yield
    logos.cache.clear()


@pytest.fixture
def public_dns(monkeypatch):
    """Every host resolves to a public address unless a test overrides it."""
    addrs: dict[str, str] = {}

    def fake_getaddrinfo(host, port, *args, **kwargs):
        ip = addrs.get(host, "93.184.216.34")
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, port))]

    monkeypatch.setattr(logos.socket, "getaddrinfo", fake_getaddrinfo)
    return addrs


@pytest.fixture
def routes(monkeypatch):
    """Serve canned responses keyed by URL; record every URL requested."""
    table: dict[str, httpx.Response] = {}
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(str(request.url))
        return table.get(str(request.url), httpx.Response(404))

    real_client = httpx.Client

    def client_factory(**kwargs):
        return real_client(transport=httpx.MockTransport(handler), **kwargs)

    monkeypatch.setattr(logos.httpx, "Client", client_factory)
    return table, seen


def test_domain_normalisation():
    assert logos.domain_of("www.Acme.com") == "www.acme.com"
    assert logos.domain_of("http://acme.com/about") == "acme.com"
    assert logos.domain_of("") is None
    assert logos.domain_of(None) is None
    assert logos.domain_of("localhost") is None


def test_apple_touch_icon_preferred(public_dns, routes):
    table, seen = routes
    table["https://acme.com/apple-touch-icon.png"] = httpx.Response(200, content=PNG)
    assert logos.fetch_logo("acme.com") == (PNG, "image/png")
    assert seen == ["https://acme.com/apple-touch-icon.png"]


def test_declared_icon_then_favicon_fallback(public_dns, routes):
    table, seen = routes
    table["https://acme.com/"] = httpx.Response(
        200,
        text='<html><link rel="icon" href="/static/logo.svg">'
        '<link rel="shortcut icon" href="/static/fav.png"></html>',
    )
    table["https://acme.com/static/fav.png"] = httpx.Response(200, content=PNG)
    assert logos.fetch_logo("acme.com") == (PNG, "image/png")
    # The SVG link is skipped without being requested.
    assert "https://acme.com/static/logo.svg" not in seen

    table.pop("https://acme.com/static/fav.png")
    table["https://acme.com/favicon.ico"] = httpx.Response(200, content=ICO)
    assert logos.fetch_logo("acme.com") == (ICO, "image/x-icon")


def test_svg_and_html_bodies_rejected(public_dns, routes):
    table, _ = routes
    # Content-Type is ignored; only magic bytes count.
    table["https://acme.com/apple-touch-icon.png"] = httpx.Response(
        200, content=SVG, headers={"content-type": "image/png"}
    )
    table["https://acme.com/favicon.ico"] = httpx.Response(200, text="<html>not found</html>")
    assert logos.fetch_logo("acme.com") is None


def test_private_address_never_fetched(public_dns, routes):
    _, seen = routes
    public_dns["intranet.acme.com"] = "10.0.0.5"
    assert logos.fetch_logo("intranet.acme.com") is None
    assert seen == []


def test_redirect_to_private_host_refused(public_dns, routes):
    table, seen = routes
    public_dns["metadata.internal.example"] = "169.254.169.254"
    table["https://acme.com/apple-touch-icon.png"] = httpx.Response(
        302, headers={"location": "https://metadata.internal.example/latest"}
    )
    assert logos.fetch_logo("acme.com") is None
    assert "https://metadata.internal.example/latest" not in seen


def test_redirect_to_http_refused(public_dns, routes):
    table, _ = routes
    table["https://acme.com/apple-touch-icon.png"] = httpx.Response(
        301, headers={"location": "http://acme.com/apple-touch-icon.png"}
    )
    assert logos.fetch_logo("acme.com") is None


def test_size_cap(public_dns, routes):
    table, _ = routes
    big = PNG + b"\x00" * (logos.MAX_BYTES + 1)
    table["https://acme.com/apple-touch-icon.png"] = httpx.Response(200, content=big)
    assert logos.fetch_logo("acme.com") is None


def test_hits_and_misses_are_cached(public_dns, routes):
    table, seen = routes
    table["https://acme.com/apple-touch-icon.png"] = httpx.Response(200, content=PNG)
    assert logos.logo_for("acme.com") == (PNG, "image/png")
    assert logos.logo_for("https://acme.com/") == (PNG, "image/png")
    assert len(seen) == 1

    seen.clear()
    assert logos.logo_for("nologo.example") is None
    calls = len(seen)
    assert logos.logo_for("nologo.example") is None
    assert len(seen) == calls  # negative result cached too


@pytest.fixture
def api_client(db):
    from warn_v2.api import app
    from warn_v2.api.deps import get_db

    def _override():
        yield db

    app.dependency_overrides[get_db] = _override
    client = TestClient(app, raise_server_exceptions=True)
    yield client
    app.dependency_overrides.clear()


def test_route_serves_logo_with_cache_headers(api_client, db, public_dns, routes):
    table, _ = routes
    table["https://acme.com/apple-touch-icon.png"] = httpx.Response(200, content=PNG)
    db.add(Company(id=1, name="Acme", website="acme.com"))
    db.commit()

    r = api_client.get("/api/logos/1")
    assert r.status_code == 200
    assert r.headers["content-type"] == "image/png"
    assert r.headers["x-content-type-options"] == "nosniff"
    assert "max-age=604800" in r.headers["cache-control"]
    assert r.content == PNG


def test_route_404s_without_website_or_company(api_client, db, routes):
    _, seen = routes
    db.add(Company(id=2, name="No Site Inc", website=None))
    db.commit()
    for path in ("/api/logos/2", "/api/logos/999"):
        r = api_client.get(path)
        assert r.status_code == 404
        assert "max-age=86400" in r.headers["cache-control"]
    assert seen == []
