"""Routes: /embed/* — widgets other sites can put on their pages.

- /embed/notices/{id}: a self-contained notice card, meant for an <iframe>.
- /embed/badge/state/{code}.svg: a shields-style badge with a state's
  workers-affected total for the last 30 days, meant for an <img>.

At the site root (not /api) and outside the rate limiter, like the share cards:
a newsroom article can carry them in front of every reader. The card is plain
HTML with inline CSS and no script, so the only header it needs to be framed is
``frame-ancestors *`` (no X-Frame-Options is set anywhere in the app). It is
``noindex`` so it never competes with the notice's own detail page in search.
"""
from __future__ import annotations

import threading
import time
from datetime import date, timedelta
from html import escape

from fastapi import APIRouter, Depends, HTTPException, Response
from fastapi.responses import HTMLResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from warn_v2.api.deps import get_db
from warn_v2.api.filters import apply_stats_closure_filter as _apply_closure_filter
from warn_v2.api.routes.stats import _not_superseded, _today
from warn_v2.api.seo import site_base_url
from warn_v2.db.models import Company, Notice
from warn_v2.states import is_valid_state, state_name

router = APIRouter(include_in_schema=False)

CARD_TTL_S = 3600
_CARD_HEADERS = {
    "Content-Security-Policy": "frame-ancestors *",
    "X-Robots-Tag": "noindex",
    "Cache-Control": f"public, max-age={CARD_TTL_S}",
}

# No `color-scheme` declaration and a transparent page: a framed document whose
# color scheme differs from its host's gets an opaque backdrop, so only the card
# itself carries a background (switched by prefers-color-scheme).
_CSS = """
:root{--bg:#fff;--fg:#0f172a;--muted:#64748b;--line:#e2e8f0;
--accent:#0284c7;--tag:#f1f5f9}
@media (prefers-color-scheme:dark){:root{--bg:#0f172a;--fg:#f1f5f9;--muted:#94a3b8;
--line:#334155;--accent:#38bdf8;--tag:#1e293b}}
*{box-sizing:border-box}
html,body{margin:0;background:transparent;color:var(--fg);
font:14px/1.4 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif}
.card{max-width:480px;background:var(--bg);border:1px solid var(--line);border-radius:12px;
padding:16px}
.head{display:flex;gap:12px;align-items:center}
.logo{width:40px;height:40px;border-radius:8px;object-fit:contain;background:#fff;
border:1px solid var(--line);flex:none}
h1{font-size:16px;margin:0;line-height:1.3;overflow-wrap:anywhere}
.where{color:var(--muted);font-size:13px}
.tags{margin-top:4px;display:flex;gap:6px;flex-wrap:wrap}
.tag{background:var(--tag);border-radius:999px;padding:1px 8px;font-size:11px;
font-weight:600;text-transform:uppercase;letter-spacing:.03em}
.big{font-size:28px;font-weight:700;margin:12px 0 0}
.big small{font-size:13px;font-weight:400;color:var(--muted)}
dl{display:grid;grid-template-columns:auto 1fr;gap:2px 12px;margin:10px 0 0;font-size:13px}
dt{color:var(--muted)}dd{margin:0}
.foot{margin-top:12px;padding-top:10px;border-top:1px solid var(--line);font-size:12px;
color:var(--muted)}
a{color:var(--accent);text-decoration:none}a:hover{text-decoration:underline}
"""


def _page(title: str, body: str, status_code: int = 200) -> HTMLResponse:
    return HTMLResponse(
        "<!doctype html><html lang='en'><head><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width, initial-scale=1'>"
        "<meta name='robots' content='noindex'>"
        f"<title>{escape(title)} — WARN Index</title><style>{_CSS}</style></head>"
        f"<body><div class='card'>{body}</div></body></html>",
        status_code=status_code,
        headers=_CARD_HEADERS,
    )


def _fmt_date(d: date | None) -> str:
    return f"{d:%b} {d.day}, {d.year}" if d else "Not published"


def _company(db: Session, notice: Notice) -> Company | None:
    """The notice's company, followed to its canonical row when consolidated."""
    company = notice.company
    if company is not None and company.canonical_company_id:
        company = db.get(Company, company.canonical_company_id) or company
    return company


@router.get("/embed/notices/{notice_id}")
def notice_card(notice_id: str, db: Session = Depends(get_db)) -> HTMLResponse:
    base = site_base_url()
    notice = db.get(Notice, notice_id)
    if notice is None:
        return _page(
            "Notice not found",
            "<h1>Notice not found</h1>"
            "<p class='where'>This WARN notice is not in WARN Index.</p>"
            f"<div class='foot'>Source: <a href='{escape(base, quote=True)}/' "
            "target='_blank' rel='noopener'>WARN Index</a></div>",
            status_code=404,
        )

    company = _company(db, notice)
    employer = company.name if company is not None else notice.employer
    logo = ""
    if company is not None and company.logo_url:
        # Through the site's own logo proxy, so third-party pages never hotlink
        # whatever host the logo was found on.
        src = escape(f"{base}/api/logos/{company.id}", quote=True)
        logo = f"<img class='logo' src='{src}' alt='' loading='lazy'>"

    st = state_name(notice.state) or notice.state
    city = notice.location.city if notice.location is not None else None
    where = f"{city}, {st}" if city else st
    tags = []
    if notice.closure_category:
        tags.append(f"<span class='tag'>{escape(notice.closure_category)}</span>")
    if notice.is_superseded:
        tags.append("<span class='tag'>Superseded</span>")
    tags_html = f"<div class='tags'>{''.join(tags)}</div>" if tags else ""
    count = (
        f"{notice.layoff_count:,} <small>workers affected</small>"
        if notice.layoff_count is not None
        else "— <small>workers affected not published</small>"
    )
    url = escape(f"{base}/notices/{notice.notice_id}", quote=True)
    body = (
        f"<div class='head'>{logo}<div><h1>{escape(employer)}</h1>"
        f"<div class='where'>{escape(where)}</div>{tags_html}</div></div>"
        f"<p class='big'>{count}</p>"
        "<dl>"
        f"<dt>Notice date</dt><dd>{_fmt_date(notice.notice_date)}</dd>"
        f"<dt>Effective date</dt><dd>{_fmt_date(notice.effective_date)}</dd>"
        "</dl>"
        f"<div class='foot'>Source: WARN Index · <a href='{url}' target='_blank' "
        "rel='noopener'>View complete filing ↗</a></div>"
    )
    return _page(f"{employer} WARN notice", body)


# ----- state badge -----

BADGE_TTL_S = 24 * 3600
BADGE_WINDOW_DAYS = 30
_badge_cache: dict[str, tuple[float, bytes]] = {}
_badge_lock = threading.Lock()


def _text_width(s: str) -> int:
    # Rough Verdana 11px advance; shields.io sizes its boxes the same way.
    return int(len(s) * 6.5) + 10


def render_badge(label: str, value: str) -> bytes:
    lw, vw = _text_width(label), _text_width(value)
    w = lw + vw
    label_e, value_e = escape(label), escape(value)
    svg = (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="20" role="img" '
        f'aria-label="{label_e}: {value_e}"><title>{label_e}: {value_e}</title>'
        '<linearGradient id="s" x2="0" y2="100%"><stop offset="0" stop-color="#bbb" '
        'stop-opacity=".1"/><stop offset="1" stop-opacity=".1"/></linearGradient>'
        f'<clipPath id="r"><rect width="{w}" height="20" rx="3" fill="#fff"/></clipPath>'
        f'<g clip-path="url(#r)"><rect width="{lw}" height="20" fill="#555"/>'
        f'<rect x="{lw}" width="{vw}" height="20" fill="#0284c7"/>'
        f'<rect width="{w}" height="20" fill="url(#s)"/></g>'
        '<g fill="#fff" text-anchor="middle" '
        'font-family="Verdana,Geneva,DejaVu Sans,sans-serif" font-size="11">'
        f'<text x="{lw / 2}" y="15" fill="#010101" fill-opacity=".3">{label_e}</text>'
        f'<text x="{lw / 2}" y="14">{label_e}</text>'
        f'<text x="{lw + vw / 2}" y="15" fill="#010101" fill-opacity=".3">{value_e}</text>'
        f'<text x="{lw + vw / 2}" y="14">{value_e}</text></g></svg>'
    )
    return svg.encode()


def _state_badge(db: Session, code: str) -> bytes:
    # Same population as the site's state totals: not superseded, Non-WARN out.
    since = _today() - timedelta(days=BADGE_WINDOW_DAYS)
    stmt = select(func.coalesce(func.sum(Notice.layoff_count), 0)).where(
        Notice.state == code, Notice.notice_date >= since
    )
    workers = db.execute(_apply_closure_filter(_not_superseded(stmt), None)).scalar_one()
    return render_badge(
        f"{state_name(code) or code} layoffs ({BADGE_WINDOW_DAYS}d)", f"{int(workers):,} workers"
    )


@router.get("/embed/badge/state/{code}.svg")
def state_badge(code: str, db: Session = Depends(get_db)) -> Response:
    code = code.upper()
    if not is_valid_state(code):
        raise HTTPException(status_code=404, detail="Unknown state")
    now = time.monotonic()
    with _badge_lock:
        hit = _badge_cache.get(code)
    if hit is None or hit[0] < now:
        hit = (now + BADGE_TTL_S, _state_badge(db, code))
        with _badge_lock:
            _badge_cache[code] = hit
    return Response(
        content=hit[1],
        media_type="image/svg+xml",
        headers={"Cache-Control": f"public, max-age={BADGE_TTL_S}"},
    )
