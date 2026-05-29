"""JobLink shared platform scraper.

Several state workforce agencies use a common Rails-based product (variously
branded "JobLink", "JobConnection", "JobMatch", etc.). They all expose WARN
notices through a `/search/warn_lookups` endpoint with the same query-param
shape and a six-column results table:

    Employer | City | ZIP | LWIB Area | Notice Date | WARN Type

Each row links to a per-notice detail page (`/search/warn_lookups/<id>`) that
holds the full address and "Number of Employees Affected".

``fetch()`` collects both the search results page and every linked detail page,
returning a JSON bundle so that ``parse()`` is a pure function on bytes:

    {"search_html": "...", "details": {"https://host/search/warn_lookups/42": "..."}}

``parse()`` also accepts raw HTML bytes (backward-compatible with existing
snapshots that pre-date the bundle format).

Concrete subclasses just need to declare a ``host`` (e.g. ``azjobconnection.gov``)
and call ``register(MyJobLinkScraper())`` — everything else is inherited.

V1 reference: app/states/helpers/job_link_state.py
"""
from __future__ import annotations

import json
import logging
import time
from datetime import datetime
from typing import ClassVar

import httpx
from bs4 import BeautifulSoup

from warn_v2.scrapers._helpers import as_date, as_int, as_str
from warn_v2.scrapers.base import NoticeRow, ParseFailed, ScrapeFailed

log = logging.getLogger(__name__)


def _build_url(host: str, year: int | None = None) -> str:
    year = year or datetime.now().year
    return (
        f"https://{host}/search/warn_lookups"
        f"?utf8=%E2%9C%93"
        f"&q%5Bnotice_eq%5D=true"
        f"&q%5Bnotice_on_gteq%5D={year}-01-01"
        f"&q%5Bnotice_on_lteq%5D={year}-12-31"
        f"&q%5Bs%5D=notice_on+desc"
        f"&commit=Search"
    )


_UA = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) warn-v2/0.1"
    )
}


class JobLinkScraper:
    """Base class for JobLink-platform state WARN scrapers."""

    # Subclasses set these:
    state: ClassVar[str] = ""
    host: ClassVar[str] = ""  # e.g. "azjobconnection.gov"
    expected_row_range: ClassVar[tuple[int, int]] = (1, 2_000)

    required_fields: ClassVar[frozenset[str]] = frozenset({"employer", "notice_date"})

    def __init__(self) -> None:
        if not self.state or not self.host:
            raise TypeError(f"{type(self).__name__} must set `state` and `host`")
        self.source_url = _build_url(self.host)

    def fetch(self) -> bytes:
        """Fetch search results page + all linked detail pages.

        Returns a JSON bundle: ``{"search_html": "...", "details": {...}}``.
        Detail keys are the full detail-page URL; values are the page HTML.
        Missing or errored detail pages are silently omitted — the notice
        will still be stored, just without address / employee count.
        """
        try:
            r = httpx.get(
                self.source_url,
                timeout=60,
                follow_redirects=True,
                headers=_UA,
            )
            r.raise_for_status()
        except httpx.HTTPError as e:
            raise ScrapeFailed(f"GET {self.source_url}: {e}") from e

        # Discover detail URLs from the search results table.
        soup = BeautifulSoup(r.content, "html.parser")
        detail_urls: list[str] = []
        table = soup.find("table")
        if table:
            for a in table.find_all("a", href=True):
                href: str = a["href"]
                if "/warn_lookups/" in href:
                    full = (
                        f"https://{self.host}{href}"
                        if href.startswith("/")
                        else href
                    )
                    if full not in detail_urls:
                        detail_urls.append(full)

        # Fetch each detail page; best-effort (failures silently omitted).
        # A short inter-request delay avoids 429 rate-limiting from the
        # JobLink platform, which throttles rapid sequential requests.
        details: dict[str, str] = {}
        for url in detail_urls:
            try:
                dr = httpx.get(url, headers=_UA, timeout=30, follow_redirects=True)
                dr.raise_for_status()
                details[url] = dr.text
            except httpx.HTTPError as exc:
                log.warning("%s: detail fetch failed: %s", url, exc)
            time.sleep(1.5)

        return json.dumps({"search_html": r.text, "details": details}).encode()

    def parse(self, raw: bytes) -> list[NoticeRow]:
        """Parse notice rows from a bundle or a raw search-results HTML page."""
        # Detect format: JSON bundle (new fetch()) vs raw HTML (old snapshots).
        details: dict[str, str] = {}
        search_bytes: bytes
        if raw.lstrip()[:1] == b"{":
            try:
                bundle = json.loads(raw)
                search_bytes = bundle["search_html"].encode()
                details = bundle.get("details", {})
            except (json.JSONDecodeError, KeyError):
                search_bytes = raw
        else:
            search_bytes = raw

        soup = BeautifulSoup(search_bytes, "html.parser")
        table = soup.find("table")
        if table is None:
            raise ParseFailed("no results table found")

        tbody = table.find("tbody") or table
        trs = tbody.find_all("tr")
        rows: list[NoticeRow] = []
        for tr in trs:
            cells = [td.get_text(strip=True) for td in tr.find_all("td")]
            if len(cells) < 6:
                continue
            employer = as_str(cells[0])
            if not employer:
                continue
            notice_date = as_date(cells[4])
            if notice_date is None:
                continue
            link_el = tr.find("a")
            detail_path = link_el.get("href") if link_el else None
            raw_notice_url = (
                f"https://{self.host}{detail_path}" if detail_path else None
            )

            # Enrich with detail page if it was fetched.
            address: str | None = None
            layoff_count: int | None = None
            if raw_notice_url and raw_notice_url in details:
                address, layoff_count = _parse_detail(details[raw_notice_url])

            rows.append(
                NoticeRow(
                    state=self.state,
                    employer=employer,
                    notice_date=notice_date,
                    layoff_count=layoff_count,
                    closure_type=as_str(cells[5]),
                    city=as_str(cells[1]),
                    zip=_norm_zip(cells[2]),
                    address=address,
                    source_url=self.source_url,
                    raw_notice_url=raw_notice_url,
                    extra={"lwib_area": cells[3]} if cells[3] else {},
                )
            )
        return rows


def _parse_detail(html: str | bytes) -> tuple[str | None, int | None]:
    """Extract address and employee count from a JobLink detail page.

    Returns ``(address, layoff_count)``.  Either may be None if the field
    is absent or unparseable.
    """
    soup = BeautifulSoup(html, "html.parser")
    dl = soup.find("div", class_="definition-list")
    if dl is None:
        return None, None
    labels: dict[str, str] = {}
    for h3, p in zip(dl.find_all("h3"), dl.find_all("p"), strict=False):
        key = h3.get_text(strip=True).lower()
        labels[key] = p.get_text(separator=" ", strip=True)
    address = labels.get("address") or None
    count = as_int(labels.get("number of employees affected"))
    return address, count


def _norm_zip(value: str) -> str | None:
    s = as_str(value)
    if not s:
        return None
    digits = "".join(c for c in s if c.isdigit())
    return digits[:5] if len(digits) >= 5 else None


# Re-export the as_int helper so subclasses can keep their imports terse.
__all__ = ["JobLinkScraper", "as_int"]
