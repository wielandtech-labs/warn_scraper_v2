"""Tests for SEO metadata injection, sitemap, robots, and RSS feeds."""
from __future__ import annotations

from datetime import date
from xml.etree.ElementTree import fromstring

import pytest
from fastapi.testclient import TestClient

from warn_v2.api.seo import (
    DEFAULT_TITLE,
    PageMeta,
    content_page_paths,
    page_meta_for_path,
    render_index,
    site_base_url,
)
from warn_v2.db.models import Notice
from warn_v2.states import STATE_NAMES

_BASE_HTML = (
    "<!doctype html><html><head>"
    '<meta name="description" content="default desc" />'
    "<title>Default Title</title>"
    "</head><body><div id=root></div></body></html>"
)


@pytest.fixture()
def api_client(db):
    from warn_v2.api import app
    from warn_v2.api.deps import get_db

    def _override():
        yield db

    app.dependency_overrides[get_db] = _override
    client = TestClient(app, raise_server_exceptions=True)
    yield client
    app.dependency_overrides.clear()


def _notice(db, state="CA", employer="Acme Inc", notice_date=date(2026, 1, 15),
            layoff_count=100, closure_category=None):
    n = Notice(
        notice_id=f"seo_{state}_{notice_date}_{employer[:8]}",
        state=state,
        employer=employer,
        notice_date=notice_date,
        layoff_count=layoff_count,
        closure_category=closure_category,
    )
    db.add(n)
    db.flush()
    return n


# --- page_meta_for_path -----------------------------------------------------

def test_meta_home():
    meta = page_meta_for_path("/")
    assert meta.title == DEFAULT_TITLE
    assert meta.path == "/"


def test_meta_state_page():
    meta = page_meta_for_path("/states/ca")
    assert "California" in meta.title
    assert meta.path == "/states/CA"  # canonical uppercases the code


def test_meta_state_trailing_slash_and_query_normalised():
    meta = page_meta_for_path("/states/tx/?foo=bar")
    assert "Texas" in meta.title
    assert meta.path == "/states/TX"


def test_meta_unknown_state_falls_back_to_default():
    meta = page_meta_for_path("/states/zz")
    assert meta.title == DEFAULT_TITLE
    # canonical preserves the requested (normalised) path
    assert meta.path == "/states/zz"


def test_meta_content_pages_have_bespoke_titles():
    for path in content_page_paths():
        meta = page_meta_for_path(path)
        assert meta.title != DEFAULT_TITLE
        assert meta.path == path


def test_meta_unknown_route_keeps_canonical_path():
    meta = page_meta_for_path("/notices")
    assert meta.title == DEFAULT_TITLE
    assert meta.path == "/notices"


# --- render_index -----------------------------------------------------------

def test_render_index_overrides_title_and_description():
    meta = PageMeta("My Title", "My description", "/states/CA")
    html = render_index(_BASE_HTML, meta)
    assert "<title>My Title</title>" in html
    assert "Default Title" not in html
    assert 'content="My description"' in html
    assert "default desc" not in html


def test_render_index_injects_canonical_and_og():
    meta = PageMeta("T", "D", "/states/CA")
    html = render_index(_BASE_HTML, meta)
    assert f'rel="canonical" href="{site_base_url()}/states/CA"' in html
    assert 'property="og:title" content="T"' in html
    assert 'type="application/rss+xml"' in html
    # injected before the single closing head tag
    assert html.count("</head>") == 1


def test_render_index_escapes_quotes_in_meta():
    meta = PageMeta('A "quoted" title', 'desc & ampersand', "/x")
    html = render_index(_BASE_HTML, meta)
    assert '"quoted"' not in html.split("<title>")[1].split("</title>")[0] or "&quot;" in html
    assert "&amp;" in html


def test_site_base_url_from_env(monkeypatch):
    monkeypatch.setenv("SITE_BASE_URL", "https://example.test/")
    assert site_base_url() == "https://example.test"  # trailing slash stripped


# --- /robots.txt and /sitemap.xml -------------------------------------------

def test_robots_txt(api_client):
    resp = api_client.get("/robots.txt")
    assert resp.status_code == 200
    assert "Sitemap:" in resp.text
    assert "/sitemap.xml" in resp.text


def test_sitemap_lists_all_states_and_content(api_client):
    resp = api_client.get("/sitemap.xml")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("application/xml")
    root = fromstring(resp.content)
    ns = {"sm": "http://www.sitemaps.org/schemas/sitemap/0.9"}
    locs = {el.text for el in root.findall(".//sm:loc", ns)}
    base = site_base_url()
    # every state, the states index, and content pages are present
    for code in STATE_NAMES:
        assert f"{base}/states/{code}" in locs
    assert f"{base}/states" in locs
    for path in content_page_paths():
        assert f"{base}{path}" in locs


# --- RSS feeds --------------------------------------------------------------

def test_feed_rss_returns_recent_notices(api_client, db):
    _notice(db, state="CA", employer="Acme Inc", notice_date=date(2026, 1, 1))
    _notice(db, state="TX", employer="Texas Co", notice_date=date(2026, 2, 1))
    db.commit()

    resp = api_client.get("/feed.rss")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("application/rss+xml")
    root = fromstring(resp.content)
    items = root.findall(".//item")
    assert len(items) == 2
    titles = {it.findtext("title") for it in items}
    assert "Texas Co (TX)" in titles


def test_feed_rss_excludes_superseded(api_client, db):
    _notice(db, state="CA", employer="Active Co")
    sup = _notice(db, state="CA", employer="Old Co", notice_date=date(2026, 1, 1))
    sup.is_superseded = True
    db.commit()

    root = fromstring(api_client.get("/feed.rss").content)
    titles = {it.findtext("title") for it in root.findall(".//item")}
    assert any("Active Co" in t for t in titles)
    assert not any("Old Co" in t for t in titles)


def test_state_feed_rss_filters_by_state(api_client, db):
    _notice(db, state="CA", employer="Cali Co")
    _notice(db, state="TX", employer="Texas Co", notice_date=date(2026, 2, 1))
    db.commit()

    root = fromstring(api_client.get("/states/CA/feed.rss").content)
    titles = [it.findtext("title") for it in root.findall(".//item")]
    assert titles == ["Cali Co (CA)"]


def test_state_feed_rss_unknown_state_404(api_client, db):
    db.commit()
    assert api_client.get("/states/ZZ/feed.rss").status_code == 404
