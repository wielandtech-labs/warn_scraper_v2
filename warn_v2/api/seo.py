"""Per-route SEO metadata for the (otherwise client-rendered) SPA.

The frontend is a pure client-side Vite/React app served as a static
``index.html`` by FastAPI. Crawlers that execute JS (Googlebot) render the body
fine, but social/link unfurlers and per-page indexing rely on a correct
``<title>``, description, canonical URL, OpenGraph tags, and JSON-LD in the
HTML *as served*. Rather than adopt SSR, we substitute those head tags into the
served ``index.html`` based on the request path (see ``SPAStaticFiles`` in
``warn_v2.api``).

This module is pure (no FastAPI imports) so it's trivially unit-testable.
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass
from html import escape

from warn_v2.states import state_name

DEFAULT_TITLE = "WARN Index — US WARN Layoff Tracker & Layoff Database"
DEFAULT_DESCRIPTION = (
    "The national WARN layoff tracker and database. Track, search, and map "
    "Worker Adjustment and Retraining Notification (WARN) layoffs and plant "
    "closures across all 50 US states, updated daily."
)


def site_base_url() -> str:
    """Canonical origin for absolute URLs (canonical/OG/sitemap), no trailing slash."""
    return os.getenv("SITE_BASE_URL", "https://warnindex.com").rstrip("/")


# The site-wide share card in frontend/public/ (regenerate with
# `python -m warn_v2.scripts.render_brand_images`).
DEFAULT_IMAGE = "/og-image.png"


@dataclass(frozen=True)
class PageMeta:
    title: str
    description: str
    path: str  # canonical path, leading slash, no host
    image: str = DEFAULT_IMAGE  # 1200x630 og:image path, no host

    @property
    def canonical(self) -> str:
        return site_base_url() + self.path


# Static content pages (Phase 3) get their meta from this table. Keyed by path.
_CONTENT_PAGES: dict[str, tuple[str, str]] = {
    "/about": (
        "About WARN Index — US Layoff Tracker & Database",
        "About WARN Index: a nationwide, daily-updated US layoff tracker and "
        "standardized WARN database aggregating notices across all 50 state "
        "labor agencies.",
    ),
    "/warn-act": (
        "What is the WARN Act? Guide to Worker Adjustment and Retraining Notification — WARN Index",
        "A plain-English guide to the federal Worker Adjustment and Retraining "
        "Notification (WARN) Act: covered employers, 60-day notice requirements, "
        "and state mini-WARN laws.",
    ),
    "/methodology": (
        "Methodology & Data Sources — WARN Layoff Database — WARN Index",
        "How the WARN Index layoff database scrapes 50+ state labor agencies, "
        "standardizes employer records, and geocodes WARN layoffs.",
    ),
    "/faq": (
        "FAQ — WARN Layoff Database & Tracker — WARN Index",
        "Frequently asked questions about Worker Adjustment and Retraining "
        "Notification (WARN) filings, state coverage, and using the WARN Index "
        "layoff database.",
    ),
    "/cited-by": (
        "Cited By — WARN Index Layoff Data in the News",
        "Newsrooms, researchers, and analysts that rely on WARN Index's "
        "layoff database and WARN notices in their reporting.",
    ),
    "/api-docs": (
        "WARN Dataset & API — Layoff Database Access — WARN Index",
        "Access the complete WARN dataset and layoff database via public REST "
        "API or bulk CSV and JSON downloads. Historical Worker Adjustment and "
        "Retraining Notification records.",
    ),
}


# Top-level app views (client-rendered lists/maps). Bespoke titles for
# per-page indexing and link unfurls; the sitemap already advertises these
# paths (see routes/seo.py `_APP_PAGES`).
_APP_PAGES_META: dict[str, tuple[str, str]] = {
    "/notices": (
        "WARN Layoffs & Filings — Search Layoff Database — WARN Index",
        "Search and filter the complete WARN layoff database by state, "
        "employer, industry, and date. Download CSV/JSON records from our "
        "nationwide WARN tracker.",
    ),
    "/companies": (
        "Companies & Corporate Families — WARN Layoff Database — WARN Index",
        "Track the employers behind US WARN layoffs, de-duplicated and enriched "
        "into corporate families with total workers affected across all subsidiaries.",
    ),
    "/map": (
        "WARN Layoff Map — Interactive US WARN Tracker — WARN Index",
        "Interactive map of US WARN layoffs and plant-closure notices across "
        "all 50 states, filterable by state, industry, and date.",
    ),
    "/stats": (
        "WARN Layoff Statistics & Trends — WARN Index Tracker",
        "Historical trends and charts of US WARN layoffs by state, industry "
        "sector, and employer from our nationwide layoff database.",
    ),
    "/reports": (
        "Economic Sentiment & Industry Reports — WARN Index",
        "Weekly layoff-trend scorecards for every NAICS industry sector plus "
        "a national economic outlook, computed from the WARN dataset.",
    ),
    "/outlook": (
        "Layoff Outlook & Macro Trends — WARN Index",
        "Statistically tested findings on where US layoffs are heading: state "
        "and industry trends and the link to unemployment, derived from the WARN database.",
    ),
}


def content_page_paths() -> list[str]:
    """Paths of the static content pages — for sitemap + footer generation."""
    return sorted(_CONTENT_PAGES)


def page_meta_for_path(path: str) -> PageMeta:
    """Resolve a request path to its SEO metadata.

    Falls back to site defaults for any path without bespoke metadata (e.g.
    ``/login``, detail pages) — those still get a correct canonical URL.
    """
    # Normalise: strip query/fragment and a trailing slash (except root).
    path = path.split("?", 1)[0].split("#", 1)[0]
    if len(path) > 1:
        path = path.rstrip("/")
    if not path:
        path = "/"

    if path == "/":
        return PageMeta(DEFAULT_TITLE, DEFAULT_DESCRIPTION, "/")

    if path == "/status":
        return PageMeta(
            "Scraper status — WARN Index",
            "Live status of WARN Index's state scrapers: which jurisdictions "
            "are operational and when each last successfully updated.",
            "/status",
        )

    if path == "/states":
        return PageMeta(
            "WARN Layoffs by State — State WARN Tracker — WARN Index",
            "Browse Worker Adjustment and Retraining Notification (WARN) layoffs "
            "and closure notices by US state. Totals, trends, and the latest "
            "filings for each jurisdiction.",
            "/states",
        )

    m = re.fullmatch(r"/states/([A-Za-z]{2})", path)
    if m:
        code = m.group(1).upper()
        name = state_name(code)
        if name:
            return PageMeta(
                f"{name} WARN Layoffs & Notices — WARN Index Tracker",
                f"Worker Adjustment and Retraining Notification (WARN) layoffs "
                f"and plant-closure notices in {name}: latest filings, affected-worker "
                f"totals, top employers, and trends.",
                f"/states/{code}",
                image=f"/og/states/{code}.png",
            )

    content = _CONTENT_PAGES.get(path) or _APP_PAGES_META.get(path)
    if content:
        return PageMeta(content[0], content[1], path)

    # Unknown SPA route: site defaults, but canonicalise to the requested path.
    return PageMeta(DEFAULT_TITLE, DEFAULT_DESCRIPTION, path)


def _head_tags(meta: PageMeta) -> str:
    """The block of canonical/OG/Twitter/JSON-LD tags injected before </head>."""
    t = escape(meta.title, quote=True)
    d = escape(meta.description, quote=True)
    url = escape(meta.canonical, quote=True)
    base = escape(site_base_url(), quote=True)
    feed = base + "/feed.rss"
    image = base + escape(meta.image, quote=True)
    return (
        f'\n    <link rel="canonical" href="{url}" />'
        f'\n    <meta property="og:site_name" content="WARN Index" />'
        f'\n    <meta property="og:type" content="website" />'
        f'\n    <meta property="og:title" content="{t}" />'
        f'\n    <meta property="og:description" content="{d}" />'
        f'\n    <meta property="og:url" content="{url}" />'
        f'\n    <meta property="og:image" content="{image}" />'
        f'\n    <meta property="og:image:width" content="1200" />'
        f'\n    <meta property="og:image:height" content="630" />'
        f'\n    <meta name="twitter:card" content="summary_large_image" />'
        f'\n    <meta name="twitter:title" content="{t}" />'
        f'\n    <meta name="twitter:description" content="{d}" />'
        f'\n    <meta name="twitter:image" content="{image}" />'
        f'\n    <link rel="alternate" type="application/rss+xml" '
        f'title="WARN Index — latest notices" href="{feed}" />'
    )


def render_index(base_html: str, meta: PageMeta) -> str:
    """Return ``base_html`` with its title/description overridden for ``meta``
    and the canonical/OG/Twitter tags injected before ``</head>``.

    Operates by targeted substitution on the built ``index.html`` so the source
    file keeps real, dev-friendly defaults (no template placeholders).
    """
    title = escape(meta.title)
    desc = escape(meta.description, quote=True)

    html = re.sub(
        r"<title>.*?</title>",
        lambda _m: f"<title>{title}</title>",
        base_html,
        count=1,
        flags=re.DOTALL,
    )
    html = re.sub(
        r'(<meta\s+name="description"\s+content=")[^"]*(")',
        lambda m: m.group(1) + desc + m.group(2),
        html,
        count=1,
    )
    if "</head>" in html:
        html = html.replace("</head>", _head_tags(meta) + "\n  </head>", 1)
    return html
