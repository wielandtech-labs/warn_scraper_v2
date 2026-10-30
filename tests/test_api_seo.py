"""Tests for SEO metadata injection, sitemap, robots, and RSS feeds."""
from __future__ import annotations

import re
from datetime import date
from pathlib import Path
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
from warn_v2.db.models import Company, Notice
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


def test_meta_unknown_state_is_a_404():
    meta = page_meta_for_path("/states/zz")
    assert (meta.status, meta.noindex) == (404, True)
    assert meta.path == "/states/zz"


def test_meta_content_pages_have_bespoke_titles():
    for path in content_page_paths():
        meta = page_meta_for_path(path)
        assert meta.title != DEFAULT_TITLE
        assert meta.path == path


def test_meta_app_pages_have_bespoke_titles():
    for path in ("/notices", "/companies", "/map", "/stats"):
        meta = page_meta_for_path(path)
        assert meta.title != DEFAULT_TITLE
        assert meta.path == path


def test_meta_unknown_route_is_a_404():
    """Unknown paths used to get the homepage meta with a 200: an unlimited
    space of indexable soft-404s."""
    meta = page_meta_for_path("/no-such-page")
    assert (meta.status, meta.noindex) == (404, True)
    assert meta.title != DEFAULT_TITLE


def _router_paths() -> list[str]:
    src = (Path(__file__).parents[1] / "frontend" / "src" / "router.tsx").read_text(
        encoding="utf-8"
    )
    return re.findall(r'path: "(/[^"]*)"', src)


def test_every_static_client_route_is_served_with_200():
    """The server's route allowlist must track frontend/src/router.tsx, or a
    real page goes out as a 404. Parametrised routes are covered below."""
    static = [p for p in _router_paths() if "$" not in p]
    assert len(static) > 15  # the regex still matches the router's syntax
    for path in static:
        assert page_meta_for_path(path).status == 200, path


def test_every_parametrised_client_route_is_handled():
    dynamic = {p for p in _router_paths() if "$" in p}
    handled = {
        "/notices/$noticeId", "/companies/$companyId", "/states/$state",
        "/reports/industry/$sector",
    }
    assert dynamic == handled, "new parametrised route: add it to page_meta_for_path"
    assert page_meta_for_path("/reports/industry/23").status == 200
    assert page_meta_for_path("/reports/industry/99").status == 404


def test_private_routes_are_noindexed_not_404():
    for path in ("/login", "/account", "/admin/companies"):
        meta = page_meta_for_path(path)
        assert (meta.status, meta.noindex) == (200, True), path


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
    assert f'property="og:image" content="{site_base_url()}/og-image.png"' in html
    assert 'name="twitter:card" content="summary_large_image"' in html
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
    resp = api_client.get("/sitemaps/pages.xml")
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


def test_feed_rss_guid_is_domain_independent(api_client, db, monkeypatch):
    """guid must not embed the host, or a domain change re-notifies every subscriber."""
    n = _notice(db, state="CA", employer="Acme Inc")
    db.commit()

    def guids() -> list[str]:
        root = fromstring(api_client.get("/feed.rss").content)
        items = root.findall(".//item")
        assert all(it.find("guid").get("isPermaLink") == "false" for it in items)
        return [it.findtext("guid") for it in items]

    before = guids()
    assert before == [f"warn-v2:notice:{n.notice_id}"]
    monkeypatch.setenv("SITE_BASE_URL", "https://moved.example")
    # The link follows the new origin; the guid does not.
    root = fromstring(api_client.get("/feed.rss").content)
    assert root.findtext(".//item/link").startswith("https://moved.example/")
    assert guids() == before


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


# --- JSON-LD, Dynamic Detail Meta, and Fallback Tests ------------------------

def test_render_index_injects_json_ld():
    payload = {"@context": "https://schema.org", "@type": "Dataset", "name": "Test"}
    meta = PageMeta("T", "D", "/api-docs", json_ld=payload)
    html = render_index(_BASE_HTML, meta)
    assert '<script type="application/ld+json">' in html
    assert '"@type": "Dataset"' in html
    assert '"name": "Test"' in html


def test_render_index_injects_semantic_fallback():
    meta = PageMeta("Test Page Title", "Test description text", "/notices")
    html = render_index(_BASE_HTML, meta)
    assert '<div id="root">' in html
    assert (
        '<h1 style="font-size:1.75rem;font-weight:700;margin-bottom:0.75rem">'
        "Test Page Title</h1>"
    ) in html
    assert "Test description text" in html
    assert '<a href="/notices"' in html


def test_meta_json_ld_schemas():
    # Home has WebSite and Dataset schemas
    home = page_meta_for_path("/")
    assert home.json_ld is not None
    assert isinstance(home.json_ld, list)
    types = {item["@type"] for item in home.json_ld}
    assert "WebSite" in types
    assert "Dataset" in types

    # API docs has Dataset schema
    api_docs = page_meta_for_path("/api-docs")
    assert api_docs.json_ld is not None
    assert any(
        (item["@type"] == "Dataset" if isinstance(item, dict) else False)
        for item in (api_docs.json_ld if isinstance(api_docs.json_ld, list) else [api_docs.json_ld])
    )

    # FAQ and WARN Act have FAQPage schema
    faq = page_meta_for_path("/faq")
    assert faq.json_ld is not None
    warn_act = page_meta_for_path("/warn-act")
    assert warn_act.json_ld is not None

    # Mini-WARN laws has TechArticle, FAQPage, and BreadcrumbList
    mini_warn = page_meta_for_path("/mini-warn-laws")
    assert mini_warn.json_ld is not None
    assert isinstance(mini_warn.json_ld, list)
    mini_types = {item["@type"] for item in mini_warn.json_ld}
    assert "TechArticle" in mini_types
    assert "FAQPage" in mini_types
    assert "BreadcrumbList" in mini_types
    assert "California" in mini_warn.title or "Mini-WARN" in mini_warn.title

    # Cited by has Dataset schema and BreadcrumbList
    cited_by = page_meta_for_path("/cited-by")
    assert cited_by.json_ld is not None
    assert isinstance(cited_by.json_ld, list)
    cited_types = {item["@type"] for item in cited_by.json_ld}
    assert "Dataset" in cited_types
    assert "BreadcrumbList" in cited_types
    assert "Press Kit" in cited_by.title

    # State page has BreadcrumbList schema
    ca = page_meta_for_path("/states/CA")
    assert ca.json_ld is not None
    assert ca.json_ld["@type"] == "BreadcrumbList"


def test_meta_company_detail_page_with_and_without_db(db):
    comp = Company(id=999, name="Initech Corporation")
    db.add(comp)
    db.commit()

    # With DB
    with_db = page_meta_for_path("/companies/999", db=db)
    assert "Initech Corporation" in with_db.title
    assert "Initech Corporation" in with_db.description
    assert with_db.json_ld["@type"] == "BreadcrumbList"

    # Without DB falls back gracefully
    without_db = page_meta_for_path("/companies/999")
    assert "Company #999" in without_db.title


def test_meta_notice_detail_page_with_and_without_db(db):
    _notice(db, state="OH", employer="Cleveland Dynamics", layoff_count=150)
    db.commit()
    nid = "seo_OH_2026-01-15_Clevelan"

    # With DB: employer, place, size and month make each page's title unique
    with_db = page_meta_for_path(f"/notices/{nid}", db=db)
    assert with_db.title.startswith("Cleveland Dynamics Layoffs: 150 Workers in Ohio (Jan 2026)")
    assert "on January 15, 2026: 150 workers affected" in with_db.description
    assert (with_db.status, with_db.noindex) == (200, False)

    # Without DB falls back gracefully
    without_db = page_meta_for_path(f"/notices/{nid}")
    assert "WARN Layoff Notice Filing" in without_db.title


def test_meta_unknown_notice_and_company_are_404s(db):
    assert page_meta_for_path("/notices/nope", db=db).status == 404
    assert page_meta_for_path("/companies/424242", db=db).status == 404
    # No DB to ask: a generic 200, never a false 404
    assert page_meta_for_path("/companies/424242").status == 200


def test_meta_superseded_notice_is_noindexed(db):
    n = _notice(db, employer="Dupe Co")
    n.is_superseded = True
    db.commit()
    meta = page_meta_for_path(f"/notices/{n.notice_id}", db=db)
    assert (meta.status, meta.noindex) == (200, True)
    assert 'name="robots" content="noindex"' in render_index(_BASE_HTML, meta)
    assert 'rel="canonical"' not in render_index(_BASE_HTML, meta)


def test_meta_company_summarises_history_and_merged_dupe_canonicalises(db):
    db.add_all([Company(id=7, name="Globex"), Company(id=8, name="Globex Inc",
                                                     canonical_company_id=7)])
    a = _notice(db, state="CA", employer="Globex", notice_date=date(2019, 3, 1),
                layoff_count=100)
    b = _notice(db, state="TX", employer="Globex Inc", notice_date=date(2025, 6, 2),
                layoff_count=1200)
    a.company_id, b.company_id = 7, 8
    db.commit()

    canon = page_meta_for_path("/companies/7", db=db)
    assert canon.description == (
        "Globex: 2 WARN layoff notices since 2019, affecting 1,300 workers in "
        "2 states. Latest filing June 2, 2025."
    )
    dupe = page_meta_for_path("/companies/8", db=db)
    assert dupe.path == "/companies/7"  # canonical points at the merge target
    # titled by its own name, like the client does; history is the merged whole
    assert dupe.title.startswith("Globex Inc Layoffs")
    assert dupe.description.startswith("Globex Inc: 2 WARN layoff notices")


def test_spa_serves_404_status_for_unknown_paths(tmp_path, db):
    from warn_v2.api import create_app

    (tmp_path / "index.html").write_text(_BASE_HTML, encoding="utf-8")
    client = TestClient(create_app(static_dir=tmp_path))
    assert client.get("/states/CA").status_code == 200
    assert client.get("/notices").status_code == 200
    missing = client.get("/companies/31337")
    assert missing.status_code == 404
    assert missing.headers["content-type"].startswith("text/html")  # still the SPA
    assert client.get("/no-such-page").status_code == 404


def _locs(resp) -> list[str]:
    assert resp.status_code == 200
    ns = {"sm": "http://www.sitemaps.org/schemas/sitemap/0.9"}
    return [el.text for el in fromstring(resp.content).findall(".//sm:loc", ns)]


def test_sitemap_index_covers_every_company_and_notice(api_client, db, monkeypatch):
    from warn_v2.api.routes import seo as seo_routes

    monkeypatch.setattr(seo_routes, "_SITEMAP_CHUNK", 2)
    db.add_all([Company(id=c, name=f"Co {c}") for c in (1, 2, 3)])
    db.add(Company(id=4, name="Co 4 dupe", canonical_company_id=1))
    db.add(Company(id=5, name="No visible notices"))
    for cid, st, day in ((1, "CA", 1), (2, "NY", 2), (3, "TX", 3), (4, "OH", 4)):
        _notice(db, state=st, employer=f"Co {cid}", notice_date=date(2026, 1, day)).company_id = cid
    hidden = _notice(db, state="WA", employer="Co 5")
    hidden.company_id, hidden.is_superseded = 5, True
    db.commit()

    base = site_base_url()
    children = _locs(api_client.get("/sitemap.xml"))
    assert children == [f"{base}/sitemaps/{n}.xml" for n in
                        ("pages", "companies-0", "companies-1", "notices-0", "notices-1")]
    companies = (_locs(api_client.get("/sitemaps/companies-0.xml"))
                 + _locs(api_client.get("/sitemaps/companies-1.xml")))
    # canonical ids only (4 rolls up into 1); 5 has no visible notice
    assert companies == [f"{base}/companies/{c}" for c in (1, 2, 3)]
    first = api_client.get("/sitemaps/companies-0.xml").text
    assert "<lastmod>2026-01-04</lastmod>" in first  # company 1's latest, via its dupe
    notices = (_locs(api_client.get("/sitemaps/notices-0.xml"))
               + _locs(api_client.get("/sitemaps/notices-1.xml")))
    assert len(notices) == 4 and not any("WA" in n for n in notices)
    assert api_client.get("/sitemaps/notices-9.xml").status_code == 404
