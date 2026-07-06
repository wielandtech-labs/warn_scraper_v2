"""Small self-contained HTML pages served from emailed links.

Confirmation/verification links land here rather than in the SPA so they work
even if the frontend bundle is unavailable (and in plain-text mail clients).
"""
from __future__ import annotations

from html import escape

from fastapi.responses import HTMLResponse

from warn_v2.api.seo import site_base_url

_BODY_STYLE = "font-family:system-ui,sans-serif;max-width:32rem;margin:4rem auto;padding:0 1rem"


def page(title: str, body: str, extra_html: str = "") -> HTMLResponse:
    """A minimal branded page: escaped title/body + optional trusted HTML block."""
    base = site_base_url()
    return HTMLResponse(
        f"<!doctype html><html><head><meta charset='utf-8'>"
        f"<meta name='viewport' content='width=device-width, initial-scale=1'>"
        f"<title>{escape(title)} — WARN Tracker</title></head>"
        f"<body style='{_BODY_STYLE}'>"
        f"<h1 style='font-size:1.25rem'>{escape(title)}</h1><p>{escape(body)}</p>"
        f"{extra_html}"
        f"<p><a href='{base}/'>← Back to WARN Tracker</a></p></body></html>"
    )
