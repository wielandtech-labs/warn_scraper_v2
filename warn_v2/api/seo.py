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

import json
import os
import re
from dataclasses import dataclass
from datetime import date
from html import escape
from typing import TYPE_CHECKING, Any

from warn_v2.states import state_name

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

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
    json_ld: dict[str, Any] | list[dict[str, Any]] | None = None
    fallback_html: str | None = None
    status: int = 200  # HTTP status the SPA shell is served with
    noindex: bool = False

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
    "/mini-warn-laws": (
        "State Mini-WARN Act Guide — California, New York, New Jersey — WARN Index",
        "A comprehensive guide to state mini-WARN layoff laws: California Cal-WARN, "
        "New York 90-day rules, New Jersey mandatory severance pay, Illinois, and "
        "state-by-state statutory thresholds.",
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
        "Press Kit & Citation Guide — Layoff Data for Journalists — WARN Index",
        "Citation formats (BibTeX, APA, MLA), newsroom fast facts, and bulk dataset "
        "access for journalists and economic researchers citing WARN Index.",
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


# Every other page the client router (frontend/src/router.tsx) serves. Paths
# outside these and the parametrised routes get the SPA with a 404 status, so
# crawlers don't index an unlimited space of soft-404s.
_OTHER_SPA_ROUTES = frozenset({
    "/", "/states", "/status", "/radar", "/timelapse", "/terms",
})
# Account/admin views: real pages, but nothing a search engine should index.
_PRIVATE_ROUTES = frozenset({"/login", "/signup", "/alerts", "/account"})


def _not_found(path: str) -> PageMeta:
    return PageMeta(
        "Page not found — WARN Index",
        "This page doesn't exist. Search WARN layoff notices by state, employer, "
        "or date on WARN Index.",
        path,
        status=404,
        noindex=True,
    )


def content_page_paths() -> list[str]:
    """Paths of the static content pages — for sitemap + footer generation."""
    return sorted(_CONTENT_PAGES)


def _dataset_json_ld() -> dict[str, Any]:
    base = site_base_url()
    return {
        "@context": "https://schema.org",
        "@type": "Dataset",
        "name": "WARN Index — US WARN Act Layoff Dataset",
        "description": DEFAULT_DESCRIPTION,
        "url": f"{base}/api-docs",
        "keywords": [
            "WARN layoffs",
            "WARN layoff tracker",
            "WARN Database",
            "WARN Dataset",
            "WARN tracker",
            "Layoff database",
            "Worker Adjustment and Retraining Notification",
        ],
        "creator": {
            "@type": "Organization",
            "name": "WARN Index",
            "url": base,
        },
        "distribution": [
            {
                "@type": "DataDownload",
                "encodingFormat": "text/csv",
                "contentUrl": f"{base}/api/notices/export?format=csv",
            },
            {
                "@type": "DataDownload",
                "encodingFormat": "application/json",
                "contentUrl": f"{base}/api/notices/export?format=json",
            },
        ],
        "isAccessibleForFree": True,
        "license": "https://creativecommons.org/licenses/by/4.0/",
        "spatialCoverage": {
            "@type": "Place",
            "name": "United States",
        },
    }


def _website_json_ld() -> dict[str, Any]:
    base = site_base_url()
    return {
        "@context": "https://schema.org",
        "@type": "WebSite",
        "name": "WARN Index",
        "url": base,
        "description": DEFAULT_DESCRIPTION,
        "potentialAction": {
            "@type": "SearchAction",
            "target": f"{base}/notices?employer={{search_term_string}}",
            "query-input": "required name=search_term_string",
        },
    }


def _faq_json_ld(is_warn_act: bool = False) -> dict[str, Any]:
    if is_warn_act:
        questions = [
            (
                "What is the Worker Adjustment and Retraining Notification (WARN) Act?",
                "The Worker Adjustment and Retraining Notification (WARN) Act is a US federal law "
                "that requires employers with 100 or more full-time employees to give at least "
                "60 calendar days advance written notice before a plant closing or mass layoff.",
            ),
            (
                "Who has to give notice?",
                "The federal WARN Act generally applies to employers with 100 or more "
                "full-time employees. Notice is triggered by a plant closing (50+ employees) "
                "or mass layoff (500+ employees, or 50-499 if they make up at least one third "
                "of active workforce).",
            ),
            (
                "What are state mini-WARN laws?",
                "Many states have their own WARN-style laws with lower thresholds, longer notice "
                "periods, or broader coverage (e.g. California, New York, New Jersey, Illinois).",
            ),
        ]
    else:
        questions = [
            (
                "What is a WARN notice?",
                "A legally required advance notice that an employer files with state labor "
                "agencies before a covered plant closing or mass layoff.",
            ),
            (
                "How does the WARN layoff tracker work?",
                "We scrape state labor agency listings daily, normalizing and deduplicating "
                "filings into a unified nationwide layoff database.",
            ),
            (
                "Which states are covered?",
                "All 50 US states and the District of Columbia.",
            ),
            (
                "Can I download the WARN dataset or use an API?",
                "Yes. The complete dataset is available via public REST API and bulk "
                "CSV/JSON downloads.",
            ),
        ]

    return {
        "@context": "https://schema.org",
        "@type": "FAQPage",
        "mainEntity": [
            {
                "@type": "Question",
                "name": q,
                "acceptedAnswer": {"@type": "Answer", "text": a},
            }
            for q, a in questions
        ],
    }


def _mini_warn_faq_json_ld() -> dict[str, Any]:
    questions = [
        (
            "Does a state mini-WARN law replace the federal WARN Act?",
            "No. State mini-WARN laws operate concurrently with federal law. When an employer "
            "is subject to both federal and state statutes, the employer must comply with "
            "whichever law provides greater protection to workers.",
        ),
        (
            "Which states require 90 days advance notice instead of 60 days?",
            "New York, New Jersey, Maine, and Nebraska require 90 calendar days of advance notice "
            "before a covered plant closure or mass layoff takes effect, compared to the "
            "60-day federal baseline.",
        ),
        (
            "Which states require mandatory severance pay for laid-off workers?",
            "New Jersey mandates one week of severance pay per full year of employment, "
            "plus a 4-week penalty for notice failures. Maine mandates one week of severance "
            "pay per year of service for workers affected by covered facility closures "
            "or relocations.",
        ),
        (
            "How does California Cal-WARN differ from the federal WARN Act?",
            "California Cal-WARN applies to employers with 75+ employees (including part-time) "
            "and triggers upon a layoff of 50+ workers within 30 days without needing to "
            "satisfy the federal 33% workforce threshold.",
        ),
    ]
    return {
        "@context": "https://schema.org",
        "@type": "FAQPage",
        "mainEntity": [
            {
                "@type": "Question",
                "name": q,
                "acceptedAnswer": {"@type": "Answer", "text": a},
            }
            for q, a in questions
        ],
    }


def _mini_warn_article_json_ld() -> dict[str, Any]:
    base = site_base_url()
    return {
        "@context": "https://schema.org",
        "@type": "TechArticle",
        "headline": "State Mini-WARN Act Laws: Complete 50-State Guide & Comparison",
        "description": (
            "A comprehensive guide comparing federal WARN Act requirements against state "
            "mini-WARN statutes in California, New York, New Jersey, Illinois, and more."
        ),
        "url": f"{base}/mini-warn-laws",
        "author": {
            "@type": "Organization",
            "name": "WARN Index",
            "url": base,
        },
        "publisher": {
            "@type": "Organization",
            "name": "WARN Index",
            "url": base,
        },
    }


def _breadcrumb_json_ld(crumbs: list[tuple[str, str]]) -> dict[str, Any]:
    base = site_base_url()
    return {
        "@context": "https://schema.org",
        "@type": "BreadcrumbList",
        "itemListElement": [
            {
                "@type": "ListItem",
                "position": i + 1,
                "name": name,
                "item": base + path if path.startswith("/") else path,
            }
            for i, (name, path) in enumerate(crumbs)
        ],
    }


def page_meta_for_path(path: str, db: Session | None = None) -> PageMeta:
    """Resolve a request path to its SEO metadata and JSON-LD structured data.

    Falls back to site defaults for any path without bespoke metadata (e.g.
    ``/login``) — those still get a correct canonical URL. If a DB session is
    passed, dynamic titles/descriptions are resolved for company and notice
    detail pages.
    """
    # Normalise: strip query/fragment and a trailing slash (except root).
    path = path.split("?", 1)[0].split("#", 1)[0]
    if len(path) > 1:
        path = path.rstrip("/")
    if not path:
        path = "/"

    if path == "/":
        return PageMeta(
            DEFAULT_TITLE,
            DEFAULT_DESCRIPTION,
            "/",
            json_ld=[_website_json_ld(), _dataset_json_ld()],
        )

    if path == "/status":
        return PageMeta(
            "Scraper status — WARN Index",
            "Live status of WARN Index's state scrapers: which jurisdictions "
            "are operational and when each last successfully updated.",
            "/status",
            json_ld=_breadcrumb_json_ld([("Home", "/"), ("Status", "/status")]),
        )

    if path == "/states":
        return PageMeta(
            "WARN Layoffs by State — State WARN Tracker — WARN Index",
            "Browse Worker Adjustment and Retraining Notification (WARN) layoffs "
            "and closure notices by US state. Totals, trends, and the latest "
            "filings for each jurisdiction.",
            "/states",
            json_ld=_breadcrumb_json_ld([("Home", "/"), ("States", "/states")]),
        )

    if path == "/api-docs":
        content = _CONTENT_PAGES["/api-docs"]
        return PageMeta(
            content[0],
            content[1],
            "/api-docs",
            json_ld=[
                _dataset_json_ld(),
                _breadcrumb_json_ld([("Home", "/"), ("Data & API", "/api-docs")]),
            ],
        )

    if path == "/faq":
        content = _CONTENT_PAGES["/faq"]
        return PageMeta(
            content[0],
            content[1],
            "/faq",
            json_ld=[
                _faq_json_ld(is_warn_act=False),
                _breadcrumb_json_ld([("Home", "/"), ("FAQ", "/faq")]),
            ],
        )

    if path == "/warn-act":
        content = _CONTENT_PAGES["/warn-act"]
        return PageMeta(
            content[0],
            content[1],
            "/warn-act",
            json_ld=[
                _faq_json_ld(is_warn_act=True),
                _breadcrumb_json_ld([("Home", "/"), ("What is the WARN Act?", "/warn-act")]),
            ],
        )

    if path == "/mini-warn-laws":
        content = _CONTENT_PAGES["/mini-warn-laws"]
        return PageMeta(
            content[0],
            content[1],
            "/mini-warn-laws",
            json_ld=[
                _mini_warn_article_json_ld(),
                _mini_warn_faq_json_ld(),
                _breadcrumb_json_ld([
                    ("Home", "/"),
                    ("What is the WARN Act?", "/warn-act"),
                    ("State Mini-WARN Laws", "/mini-warn-laws"),
                ]),
            ],
        )

    if path == "/cited-by":
        content = _CONTENT_PAGES["/cited-by"]
        return PageMeta(
            content[0],
            content[1],
            "/cited-by",
            json_ld=[
                _dataset_json_ld(),
                _breadcrumb_json_ld([("Home", "/"), ("Press Kit & Citation Guide", "/cited-by")]),
            ],
        )

    m = re.fullmatch(r"/states/([A-Za-z]{2})", path)
    if m:
        code = m.group(1).upper()
        name = state_name(code)
        if not name:
            return _not_found(path)
        return PageMeta(
            f"{name} WARN Layoffs & Notices — WARN Index Tracker",
            f"Worker Adjustment and Retraining Notification (WARN) layoffs "
            f"and plant-closure notices in {name}: latest filings, affected-worker "
            f"totals, top employers, and trends.",
            f"/states/{code}",
            image=f"/og/states/{code}.png",
            json_ld=_breadcrumb_json_ld([
                ("Home", "/"),
                ("States", "/states"),
                (name, f"/states/{code}"),
            ]),
        )

    m = re.fullmatch(r"/reports/industry/([^/]+)", path)
    if m:
        from warn_v2.companies.naics import SECTOR_NAME

        sector = m.group(1)
        if sector not in SECTOR_NAME:
            return _not_found(path)
        return PageMeta(
            f"{SECTOR_NAME[sector]} Layoffs — Weekly Industry Report — WARN Index",
            f"Weekly WARN layoff scorecard for {SECTOR_NAME[sector]} (NAICS {sector}): "
            f"notice and affected-worker trends, top states, and recent filings.",
            path,
            json_ld=_breadcrumb_json_ld([
                ("Home", "/"),
                ("Reports", "/reports"),
                (SECTOR_NAME[sector], path),
            ]),
        )

    m = re.fullmatch(r"/companies/(\d+)", path)
    if m:
        return _company_meta(int(m.group(1)), db)

    m = re.fullmatch(r"/notices/([^/]+)", path)
    if m:
        return _notice_meta(m.group(1), db)

    matched_content = _CONTENT_PAGES.get(path) or _APP_PAGES_META.get(path)
    if matched_content:
        crumbs = [("Home", "/")]
        title_clean = matched_content[0].split(" — ")[0]
        crumbs.append((title_clean, path))
        return PageMeta(
            matched_content[0],
            matched_content[1],
            path,
            json_ld=_breadcrumb_json_ld(crumbs),
        )

    if path in _PRIVATE_ROUTES or path == "/admin" or path.startswith("/admin/"):
        return PageMeta(DEFAULT_TITLE, DEFAULT_DESCRIPTION, path, noindex=True)
    if path in _OTHER_SPA_ROUTES:
        return PageMeta(DEFAULT_TITLE, DEFAULT_DESCRIPTION, path)
    return _not_found(path)


def _fmt_day(d: date) -> str:
    return f"{d:%B} {d.day}, {d.year}"


def _company_meta(cid: int, db: Session | None) -> PageMeta:
    """Company detail. A merged duplicate canonicalises to the company it was
    merged into, and its copy describes that company's whole history, which
    is what the page shows. Without a DB (or on a DB error) the page is
    served with a generic title rather than a false 404."""
    from sqlalchemy import distinct, func, or_, select

    from warn_v2.db.models import Company, Notice

    comp = canon = None
    stats = None
    if db is not None:
        try:
            comp = db.get(Company, cid)
            if comp is not None:
                canon_id = comp.canonical_company_id or comp.id
                canon = comp if canon_id == comp.id else db.get(Company, canon_id)
                members = select(Company.id).where(
                    or_(Company.id == canon_id, Company.canonical_company_id == canon_id)
                )
                stats = db.execute(
                    select(
                        func.count(),
                        func.sum(Notice.layoff_count),
                        func.count(distinct(Notice.state)),
                        func.min(Notice.notice_date),
                        func.max(Notice.notice_date),
                    ).where(Notice.company_id.in_(members), Notice.is_superseded.is_(False))
                ).one()
        except Exception:
            comp = canon = stats = None
        else:
            if comp is None:
                return _not_found(f"/companies/{cid}")

    if canon is None or stats is None:
        name = f"Company #{cid}"
        return PageMeta(
            f"{name} Layoffs & WARN Notices — WARN Index",
            f"Worker Adjustment and Retraining Notification (WARN) filings, plant "
            f"closures, and layoff history for {name}.",
            f"/companies/{cid}",
        )

    # The page's own name (as the client titles it too), with the history and
    # canonical URL of the company it was merged into.
    name = comp.name if comp is not None else canon.name
    path = f"/companies/{canon.id}"
    n, workers, n_states, first, last = stats
    if n:
        parts = [f"{name}: {n:,} WARN layoff notice{'s' if n != 1 else ''}"]
        if first:
            parts.append(f" since {first.year}")
        if workers:
            parts.append(f", affecting {workers:,} workers")
        parts.append(f" in {n_states} state{'s' if n_states != 1 else ''}.")
        if last:
            parts.append(f" Latest filing {_fmt_day(last)}.")
        desc = "".join(parts)
    else:
        desc = f"WARN layoff notice history for {name}."
    return PageMeta(
        f"{name} Layoffs & WARN Notices — WARN Index",
        desc,
        path,
        json_ld=_breadcrumb_json_ld([
            ("Home", "/"),
            ("Companies", "/companies"),
            (name, path),
        ]),
        # A company whose every notice was superseded has nothing to show.
        noindex=not n,
    )


def _notice_meta(nid: str, db: Session | None) -> PageMeta:
    """Notice detail: employer, place, date and size in the title and
    description, so each of ~100k pages reads as its own document. A
    superseded notice (a duplicate of a later filing) is noindexed."""
    from warn_v2.db.models import Notice

    path = f"/notices/{nid}"
    notc = None
    if db is not None:
        try:
            notc = db.get(Notice, nid)
            city = notc.location.city if notc is not None and notc.location else None
        except Exception:
            db = notc = None
        else:
            if notc is None:
                return _not_found(path)

    if notc is None:
        return PageMeta(
            "WARN Layoff Notice Filing — WARN Index",
            "Worker Adjustment and Retraining Notification (WARN) advance notice "
            "filing details from official state labor records.",
            path,
        )

    st = notc.state
    place = f"{city}, {st}" if city else (state_name(st) or st)
    when = f" ({notc.notice_date:%b %Y})" if notc.notice_date else ""
    if notc.layoff_count:
        title = f"{notc.employer} Layoffs: {notc.layoff_count:,} Workers in {place}{when}"
    else:
        title = f"{notc.employer} WARN Notice in {place}{when}"
    desc = f"{notc.employer} filed a WARN notice in {place}"
    if notc.notice_date:
        desc += f" on {_fmt_day(notc.notice_date)}"
    details = []
    if notc.layoff_count:
        details.append(f"{notc.layoff_count:,} workers affected")
    if notc.closure_type:
        details.append(notc.closure_type.strip().lower())
    if notc.effective_date:
        details.append(f"effective {_fmt_day(notc.effective_date)}")
    desc += (": " + ", ".join(details) + ".") if details else "."
    return PageMeta(
        f"{title} — WARN Index",
        desc,
        path,
        image=f"/og/notices/{nid}.png",
        json_ld=_breadcrumb_json_ld([
            ("Home", "/"),
            ("Notices", "/notices"),
            (f"{notc.employer} ({st})", path),
        ]),
        noindex=notc.is_superseded,
    )


def _head_tags(meta: PageMeta) -> str:
    """The block of canonical/OG/Twitter/JSON-LD tags injected before </head>."""
    t = escape(meta.title, quote=True)
    d = escape(meta.description, quote=True)
    url = escape(meta.canonical, quote=True)
    base = escape(site_base_url(), quote=True)
    feed = base + "/feed.rss"
    image = base + escape(meta.image, quote=True)
    tags = [
        # A noindexed page shouldn't also nominate itself as canonical.
        '    <meta name="robots" content="noindex" />'
        if meta.noindex
        else f'    <link rel="canonical" href="{url}" />',
        '    <meta property="og:site_name" content="WARN Index" />',
        '    <meta property="og:type" content="website" />',
        f'    <meta property="og:title" content="{t}" />',
        f'    <meta property="og:description" content="{d}" />',
        f'    <meta property="og:url" content="{url}" />',
        f'    <meta property="og:image" content="{image}" />',
        '    <meta property="og:image:width" content="1200" />',
        '    <meta property="og:image:height" content="630" />',
        '    <meta name="twitter:card" content="summary_large_image" />',
        f'    <meta name="twitter:title" content="{t}" />',
        f'    <meta name="twitter:description" content="{d}" />',
        f'    <meta name="twitter:image" content="{image}" />',
        (
            '    <link rel="alternate" type="application/rss+xml" '
            f'title="WARN Index — latest notices" href="{feed}" />'
        ),
    ]
    if meta.json_ld:
        ld_payload = meta.json_ld
        ld_str = json.dumps(ld_payload, indent=2, ensure_ascii=False).replace("</", "<\\/")
        tags.append(f'    <script type="application/ld+json">\n{ld_str}\n    </script>')
    return "\n" + "\n".join(tags)


def render_index(base_html: str, meta: PageMeta) -> str:
    """Return ``base_html`` with its title/description overridden for ``meta``
    and the canonical/OG/Twitter/JSON-LD tags injected before ``</head>``.
    Also injects a lightweight semantic fallback inside ``<div id="root">``
    so crawlers receive meaningful HTML content even without executing JS.
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

    # Provide crawler/no-JS semantic body fallback within root container
    h1_text = escape(meta.title)
    p_text = escape(meta.description)
    fallback = (
        '<div id="root">'
        '<main style="max-width:48rem;margin:2rem auto;'
        'padding:1rem;font-family:system-ui,sans-serif">'
        f'<h1 style="font-size:1.75rem;font-weight:700;margin-bottom:0.75rem">{h1_text}</h1>'
        '<p style="color:#475569;font-size:1.1rem;line-height:1.6;'
        f'margin-bottom:1.5rem">{p_text}</p>'
        '<nav style="display:flex;gap:1rem;font-size:0.875rem">'
        '<a href="/" style="color:#0284c7">Home</a>'
        '<a href="/notices" style="color:#0284c7">Notices</a>'
        '<a href="/companies" style="color:#0284c7">Companies</a>'
        '<a href="/states" style="color:#0284c7">States</a>'
        '<a href="/api-docs" style="color:#0284c7">Data &amp; API</a>'
        '</nav>'
        '</main>'
        '</div>'
    )
    html = re.sub(
        r'<div id=["\']?root["\']?>.*?</div>',
        lambda _m: fallback,
        html,
        count=1,
        flags=re.DOTALL,
    )
    return html
