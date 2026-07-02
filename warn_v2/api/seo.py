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

DEFAULT_TITLE = "WARN Tracker — US layoff & closure notices"
DEFAULT_DESCRIPTION = (
    "Search, map, and track WARN Act layoff and plant-closure notices across "
    "all 50 US states and DC, updated daily."
)


def site_base_url() -> str:
    """Canonical origin for absolute URLs (canonical/OG/sitemap), no trailing slash."""
    return os.getenv("SITE_BASE_URL", "https://warn.wielandtech.com").rstrip("/")


@dataclass(frozen=True)
class PageMeta:
    title: str
    description: str
    path: str  # canonical path, leading slash, no host

    @property
    def canonical(self) -> str:
        return site_base_url() + self.path


# Static content pages (Phase 3) get their meta from this table. Keyed by path.
_CONTENT_PAGES: dict[str, tuple[str, str]] = {
    "/about": (
        "About — WARN Tracker",
        "Who we are and how WARN Tracker collects, cleans, and publishes US "
        "layoff-notice data.",
    ),
    "/warn-act": (
        "What is the WARN Act? — WARN Tracker",
        "A plain-English guide to the federal Worker Adjustment and Retraining "
        "Notification (WARN) Act: who must file, when, and what the notices mean.",
    ),
    "/methodology": (
        "Methodology & data sources — WARN Tracker",
        "How WARN Tracker scrapes 50+ state labor agencies, de-duplicates and "
        "enriches employers, and geocodes layoff notices.",
    ),
    "/faq": (
        "FAQ — WARN Tracker",
        "Frequently asked questions about WARN notices, our data, coverage, and "
        "how to use the layoff database.",
    ),
    "/cited-by": (
        "Cited by — WARN Tracker",
        "Newsrooms, researchers, and analysts that rely on WARN Tracker's "
        "layoff-notice data.",
    ),
    "/api-docs": (
        "Data & API — WARN Tracker",
        "Use the WARN Tracker layoff dataset via a public JSON API or bulk "
        "CSV/JSON downloads.",
    ),
}


# Top-level app views (client-rendered lists/maps). Bespoke titles for
# per-page indexing and link unfurls; the sitemap already advertises these
# paths (see routes/seo.py `_APP_PAGES`).
_APP_PAGES_META: dict[str, tuple[str, str]] = {
    "/notices": (
        "Layoff notices — WARN Tracker",
        "Search and filter every WARN Act layoff and closure notice on record "
        "by state, employer, industry, and date. Export as CSV or JSON.",
    ),
    "/companies": (
        "Companies & corporate families — WARN Tracker",
        "The employers behind US WARN notices, de-duplicated and enriched — "
        "with corporate family groupings and total workers affected.",
    ),
    "/map": (
        "Layoff map — WARN Tracker",
        "Interactive map of US WARN Act layoff and closure notices, "
        "filterable by state, industry, and date.",
    ),
    "/stats": (
        "Layoff statistics & trends — WARN Tracker",
        "Charts of US WARN notices over time and by state, industry, and "
        "employer.",
    ),
}


def content_page_paths() -> list[str]:
    """Paths of the static content pages — for sitemap + footer generation."""
    return sorted(_CONTENT_PAGES)


def page_meta_for_path(path: str) -> PageMeta:
    """Resolve a request path to its SEO metadata.

    Falls back to site defaults for any path without bespoke metadata (e.g.
    ``/notices``, ``/map``) — those still get a correct canonical URL.
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
            "Scraper status — WARN Tracker",
            "Live status of WARN Tracker's state scrapers: which jurisdictions "
            "are operational and when each last successfully updated.",
            "/status",
        )

    if path == "/states":
        return PageMeta(
            "Layoffs by state — WARN Tracker",
            "Browse WARN Act layoff and closure notices by US state. Totals, "
            "trends, and the latest filings for each jurisdiction.",
            "/states",
        )

    m = re.fullmatch(r"/states/([A-Za-z]{2})", path)
    if m:
        code = m.group(1).upper()
        name = state_name(code)
        if name:
            return PageMeta(
                f"{name} layoffs & WARN notices — WARN Tracker",
                f"WARN Act layoff and plant-closure notices in {name}: latest "
                f"filings, affected-worker totals, top employers, and trends.",
                f"/states/{code}",
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
    image = base + "/og-image.png"  # 1200x630 card in frontend/public/
    return (
        f'\n    <link rel="canonical" href="{url}" />'
        f'\n    <meta property="og:site_name" content="WARN Tracker" />'
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
        f'title="WARN Tracker — latest notices" href="{feed}" />'
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
