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
from sqlalchemy import select
from sqlalchemy.orm import Session

from warn_v2.api.deps import get_db
from warn_v2.api.filters import apply_notice_filters
from warn_v2.api.seo import content_page_paths, site_base_url
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
    "/status",
]

_RSS_LIMIT = 50
_HTTP_DATE = "%a, %d %b %Y %H:%M:%S GMT"


@router.get("/robots.txt", response_class=PlainTextResponse)
def robots_txt() -> str:
    return f"User-agent: *\nAllow: /\nSitemap: {site_base_url()}/sitemap.xml\n"


@router.get("/sitemap.xml")
def sitemap_xml(db: Session = Depends(get_db)) -> Response:
    base = site_base_url()
    urlset = Element("urlset", xmlns="http://www.sitemaps.org/schemas/sitemap/0.9")

    # 1. Main app routes (daily, high priority)
    for path in _APP_PAGES:
        url = SubElement(urlset, "url")
        SubElement(url, "loc").text = base + path
        SubElement(url, "changefreq").text = "daily"
        SubElement(url, "priority").text = "1.0" if path == "/" else "0.9"

    # 2. Static content pages (monthly)
    for path in content_page_paths():
        url = SubElement(urlset, "url")
        SubElement(url, "loc").text = base + path
        SubElement(url, "changefreq").text = "monthly"
        SubElement(url, "priority").text = "0.7"

    # 3. 50 states + DC (daily)
    for code in sorted(STATE_NAMES):
        url = SubElement(urlset, "url")
        SubElement(url, "loc").text = f"{base}/states/{code}"
        SubElement(url, "changefreq").text = "daily"
        SubElement(url, "priority").text = "0.8"

    # 4. Canonical companies (weekly)
    try:
        canonical_companies = db.scalars(
            select(Company.id)
            .where(Company.canonical_company_id.is_(None))
            .order_by(Company.id.desc())
            .limit(10000)
        ).all()
        for cid in canonical_companies:
            url = SubElement(urlset, "url")
            SubElement(url, "loc").text = f"{base}/companies/{cid}"
            SubElement(url, "changefreq").text = "weekly"
            SubElement(url, "priority").text = "0.6"
    except Exception:
        pass

    # 5. Recent non-superseded notices (monthly)
    try:
        recent_notices = db.scalars(
            select(Notice.notice_id)
            .where(Notice.is_superseded.is_(False))
            .order_by(Notice.notice_date.desc().nullslast(), Notice.scraped_at.desc())
            .limit(5000)
        ).all()
        for nid in recent_notices:
            url = SubElement(urlset, "url")
            SubElement(url, "loc").text = f"{base}/notices/{nid}"
            SubElement(url, "changefreq").text = "monthly"
            SubElement(url, "priority").text = "0.5"
    except Exception:
        pass

    xml = b'<?xml version="1.0" encoding="UTF-8"?>\n' + tostring(urlset, encoding="utf-8")
    return Response(content=xml, media_type="application/xml")


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
