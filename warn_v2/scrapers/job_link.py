"""JobLink shared platform scraper.

Several state workforce agencies use a common Rails-based product (variously
branded "JobLink", "JobConnection", "JobMatch", etc.). They all expose WARN
notices through a `/search/warn_lookups` endpoint with the same query-param
shape and a six-column results table:

    Employer | City | ZIP | LWIB Area | Notice Date | WARN Type

Each row links to a per-notice detail page (`/search/warn_lookups/<id>`) that
holds the "Number of Affected Employees" field. Pulling that count requires
N+1 fetches and is reserved for the enrichment worker (Phase 4) — Phase 1 ships
notice metadata with `layoff_count=None` for JobLink states.

Concrete subclasses just need to declare a `host` (e.g. `azjobconnection.gov`)
and call `register(MyJobLinkScraper())` — everything else is inherited.

V1 reference: app/states/helpers/job_link_state.py
"""
from __future__ import annotations

from datetime import datetime
from typing import ClassVar

import httpx
import pandas as pd
from bs4 import BeautifulSoup

from warn_v2.scrapers._helpers import as_date, as_int, as_str
from warn_v2.scrapers.base import NoticeRow, ParseFailed, ScrapeFailed


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
        try:
            r = httpx.get(
                self.source_url,
                timeout=60,
                follow_redirects=True,
                # JobLink occasionally serves "noisy" HTML to default UAs.
                headers={
                    "User-Agent": (
                        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                        "(KHTML, like Gecko) warn-v2/0.1"
                    )
                },
            )
            r.raise_for_status()
            return r.content
        except httpx.HTTPError as e:
            raise ScrapeFailed(f"GET {self.source_url}: {e}") from e

    def parse(self, raw: bytes) -> list[NoticeRow]:
        soup = BeautifulSoup(raw, "html.parser")
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
                # Skip non-data rows (e.g. "No notices found" placeholder).
                continue
            link_el = tr.find("a")
            detail_path = link_el.get("href") if link_el else None
            raw_notice_url = (
                f"https://{self.host}{detail_path}" if detail_path else None
            )
            rows.append(
                NoticeRow(
                    state=self.state,
                    employer=employer,
                    notice_date=notice_date,
                    layoff_count=None,  # populated by enrichment (Phase 4)
                    closure_type=as_str(cells[5]),
                    city=as_str(cells[1]),
                    zip=_norm_zip(cells[2]),
                    source_url=self.source_url,
                    raw_notice_url=raw_notice_url,
                    extra={"lwib_area": cells[3]} if cells[3] else {},
                )
            )
        return rows


def _norm_zip(value: str) -> str | None:
    s = as_str(value)
    if not s:
        return None
    digits = "".join(c for c in s if c.isdigit())
    return digits[:5] if len(digits) >= 5 else None


# Re-export the as_int helper so subclasses can keep their imports terse.
__all__ = ["JobLinkScraper", "as_int"]
