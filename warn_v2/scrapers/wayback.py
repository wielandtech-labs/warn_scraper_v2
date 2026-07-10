"""Shared Wayback Machine helpers for historical backfills.

Wayback is aggressively rate limited: keep requests strictly sequential,
pace them, and back off in escalating steps on errors (a lost file costs a
whole extra multi-hour pass). CDX queries count against the same budget.
"""
from __future__ import annotations

import logging
import time

import httpx

from warn_v2.scrapers.base import ScrapeFailed

log = logging.getLogger(__name__)

CDX_API = "https://web.archive.org/cdx/search/cdx"

_UA = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
    )
}

# Pacing before every request; escalating waits between retries.
_DELAY = 3
_BACKOFFS = (15, 30, 60)


def replay_url(ts: str, url: str) -> str:
    """`id_` replay URL — raw archived bytes without Wayback's injected JS."""
    return f"https://web.archive.org/web/{ts}id_/{url}"


def fetch(url: str, *, timeout: float = 120.0) -> bytes | None:
    """Throttled GET of a Wayback URL. None on 404; ScrapeFailed when all
    retries are exhausted."""
    last: Exception | None = None
    for wait in (0, *_BACKOFFS):
        if wait:
            log.info("wayback: backing off %ds (%s)", wait, last)
            time.sleep(wait)
        time.sleep(_DELAY)
        try:
            r = httpx.get(url, headers=_UA, timeout=timeout, follow_redirects=True)
            if r.status_code == 404:
                return None
            r.raise_for_status()
            return r.content
        except httpx.HTTPError as e:
            last = e
    raise ScrapeFailed(f"GET {url}: {last}")


def cdx_query(params: dict) -> list[list[str]]:
    """Throttled CDX index query. Returns data rows (header row stripped).

    Caller supplies ``url``/``matchType``/``filter``/... — ``output=json``
    and a status-200 filter are applied by default. Note: ``matchType=domain``
    with a content filter can silently return 0 rows on large domains — use
    targeted path prefixes (lesson from the 2026-07-10 sweep).
    """
    query: dict = {"output": "json", "limit": "20000", "fl": "timestamp,original"}
    query.update(params)
    filters = query.get("filter")
    if filters is None:
        query["filter"] = ["statuscode:200"]

    last: Exception | None = None
    for wait in (0, *_BACKOFFS):
        if wait:
            log.info("wayback: CDX backing off %ds (%s)", wait, last)
            time.sleep(wait)
        time.sleep(_DELAY)
        try:
            r = httpx.get(CDX_API, params=query, headers=_UA, timeout=180)
            r.raise_for_status()
            rows = r.json()
            return rows[1:] if rows else []
        except (httpx.HTTPError, ValueError) as e:
            last = e
    raise ScrapeFailed(f"CDX query {query.get('url')}: {last}")
