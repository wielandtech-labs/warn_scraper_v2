"""Routes: sitemap.xml, robots.txt, and RSS feeds.

These live outside ``/api`` because crawlers and feed readers expect them at the
site root. They're registered on the app directly (see ``warn_v2.api``) so they
take precedence over the SPA static mount.
"""
from __future__ import annotations

from datetime import UTC, datetime
from xml.etree.ElementTree import Element, SubElement, tostring

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import PlainTextResponse, Response
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from warn_v2.api.deps import get_db
from warn_v2.api.filters import apply_notice_filters
from warn_v2.api.seo import content_page_paths, site_base_url
from warn_v2.companies.naics import SECTOR_NAME
from warn_v2.db.models import Company, Notice
from warn_v2.states import STATE_NAMES, is_valid_state, state_name

router = APIRouter(tags=["seo"], include_in_schema=False)

# Top-level SPA pages worth advertising to crawlers besides the state/content set.
_APP_PAGES = [
    "/",
    "/notices",
    "/companies",
    "/map",
    "/stats",
    "/states",
    "/reports",
    "/outlook",
    "/status",
]

_RSS_LIMIT = 50
_SITEMAP_NS = "http://www.sitemaps.org/schemas/sitemap/0.9"
_SITEMAP_CHUNK = 20_000  # URLs per child sitemap (the protocol allows 50,000)
_HTTP_DATE = "%a, %d %b %Y %H:%M:%S GMT"


@router.get("/robots.txt", response_class=PlainTextResponse)
def robots_txt() -> str:
    return f"User-agent: *\nAllow: /\nSitemap: {site_base_url()}/sitemap.xml\n"


def _xml(root: Element) -> Response:
    xml = b'<?xml version="1.0" encoding="UTF-8"?>\n' + tostring(root, encoding="utf-8")
    return Response(content=xml, media_type="application/xml")


def _company_rows():
    """Canonical companies with at least one visible notice, and the date of
    their latest one (a new filing is what changes the page). Merged
    duplicates roll up into their canonical, which is the URL listed."""
    canon = func.coalesce(Company.canonical_company_id, Company.id)
    return (
        select(canon.label("cid"), func.max(Notice.notice_date).label("last"))
        .join(Notice, Notice.company_id == Company.id)
        .where(Notice.is_superseded.is_(False))
        .group_by(canon)
    )


def _notice_ids():
    return select(Notice.notice_id).where(Notice.is_superseded.is_(False))


def _chunks(db: Session, stmt) -> int:
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    return -(-total // _SITEMAP_CHUNK)


@router.get("/sitemap.xml")
def sitemap_xml(db: Session = Depends(get_db)) -> Response:
    """Sitemap index. Children are chunked under the protocol's 50,000-URL
    limit, so every company and notice page is listed, not just the newest."""
    base = site_base_url()
    index = Element("sitemapindex", xmlns=_SITEMAP_NS)
    names = ["pages"]
    names += [f"companies-{i}" for i in range(_chunks(db, _company_rows()))]
    names += [f"notices-{i}" for i in range(_chunks(db, _notice_ids()))]
    for name in names:
        SubElement(SubElement(index, "sitemap"), "loc").text = f"{base}/sitemaps/{name}.xml"
    return _xml(index)


@router.get("/sitemaps/pages.xml")
def sitemap_pages() -> Response:
    base = site_base_url()
    urlset = Element("urlset", xmlns=_SITEMAP_NS)

    def add(path: str, changefreq: str, priority: str) -> None:
        url = SubElement(urlset, "url")
        SubElement(url, "loc").text = base + path
        SubElement(url, "changefreq").text = changefreq
        SubElement(url, "priority").text = priority

    for path in _APP_PAGES:
        add(path, "daily", "1.0" if path == "/" else "0.9")
    for path in content_page_paths():
        add(path, "monthly", "0.7")
    for code in sorted(STATE_NAMES):
        add(f"/states/{code}", "daily", "0.8")
    for sector in sorted(SECTOR_NAME):
        add(f"/reports/industry/{sector}", "weekly", "0.6")
    return _xml(urlset)


@router.get("/sitemaps/companies-{chunk:int}.xml")
def sitemap_companies(chunk: int, db: Session = Depends(get_db)) -> Response:
    rows = _company_rows().subquery()
    page = db.execute(
        select(rows.c.cid, rows.c.last)
        .order_by(rows.c.cid)
        .offset(chunk * _SITEMAP_CHUNK)
        .limit(_SITEMAP_CHUNK)
    ).all()
    if not page:
        raise HTTPException(status_code=404, detail="No such sitemap")
    base = site_base_url()
    urlset = Element("urlset", xmlns=_SITEMAP_NS)
    for cid, last in page:
        url = SubElement(urlset, "url")
        SubElement(url, "loc").text = f"{base}/companies/{cid}"
        if last is not None:
            SubElement(url, "lastmod").text = last.isoformat()
    return _xml(urlset)


@router.get("/sitemaps/notices-{chunk:int}.xml")
def sitemap_notices(chunk: int, db: Session = Depends(get_db)) -> Response:
    ids = db.scalars(
        _notice_ids()
        .order_by(Notice.notice_id)
        .offset(chunk * _SITEMAP_CHUNK)
        .limit(_SITEMAP_CHUNK)
    ).all()
    if not ids:
        raise HTTPException(status_code=404, detail="No such sitemap")
    base = site_base_url()
    urlset = Element("urlset", xmlns=_SITEMAP_NS)
    for nid in ids:
        SubElement(SubElement(urlset, "url"), "loc").text = f"{base}/notices/{nid}"
    return _xml(urlset)


def _rss(title: str, description: str, path: str, notices: list[Notice]) -> Response:
    base = site_base_url()
    rss = Element("rss", version="2.0")
    channel = SubElement(rss, "channel")
    SubElement(channel, "title").text = title
    SubElement(channel, "link").text = base + path
    SubElement(channel, "description").text = description
    for n in notices:
        item = SubElement(channel, "item")
        loc = n.state or ""
        SubElement(item, "title").text = f"{n.employer} ({loc})" if loc else (n.employer or "")
        link = f"{base}/notices/{n.notice_id}"
        SubElement(item, "link").text = link
        # Deliberately NOT the URL. Feed readers de-duplicate on guid, so a
        # URL guid makes every item look brand new to every subscriber the moment
        # the canonical host changes — a burst of duplicate notifications for
        # layoffs they have already seen. The notice id is stable across any
        # future domain or path change; <link> above still carries the URL.
        guid = SubElement(item, "guid", isPermaLink="false")
        guid.text = f"warn-v2:notice:{n.notice_id}"
        parts = []
        if n.layoff_count:
            parts.append(f"{n.layoff_count:,} workers affected")
        if n.closure_category:
            parts.append(n.closure_category)
        if n.effective_date:
            parts.append(f"effective {n.effective_date.isoformat()}")
        SubElement(item, "description").text = "; ".join(parts) or "WARN notice"
        if n.notice_date:
            dt = datetime(n.notice_date.year, n.notice_date.month, n.notice_date.day,
                          tzinfo=UTC)
            SubElement(item, "pubDate").text = dt.strftime(_HTTP_DATE)
    xml = b'<?xml version="1.0" encoding="UTF-8"?>\n' + tostring(rss, encoding="utf-8")
    return Response(content=xml, media_type="application/rss+xml")


def _latest_notices(db: Session, state: str | None = None) -> list[Notice]:
    stmt = (
        select(Notice)
        .where(Notice.is_superseded.is_(False))
        .order_by(Notice.notice_date.desc().nullslast(), Notice.scraped_at.desc())
    )
    stmt = apply_notice_filters(stmt, state=state)
    return list(db.scalars(stmt.limit(_RSS_LIMIT)))


@router.get("/feed.rss")
def feed_rss(db: Session = Depends(get_db)) -> Response:
    return _rss(
        "WARN Index — latest layoff notices",
        "The most recent WARN Act layoff and closure notices across all states.",
        "/feed.rss",
        _latest_notices(db),
    )


@router.get("/states/{code}/feed.rss")
def state_feed_rss(code: str, db: Session = Depends(get_db)) -> Response:
    if not is_valid_state(code):
        raise HTTPException(status_code=404, detail="Unknown state")
    name = state_name(code)
    return _rss(
        f"WARN Index — latest {name} layoff notices",
        f"The most recent WARN Act layoff and closure notices in {name}.",
        f"/states/{code.upper()}/feed.rss",
        _latest_notices(db, state=code),
    )
