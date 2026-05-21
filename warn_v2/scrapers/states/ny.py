"""New York WARN scraper.

Source: https://dol.ny.gov/warn-notices  (HTML index)

V1 also fetched each linked PDF inline to extract `Number Affected:` and
`Classification:`. V2 defers per-PDF parsing to the enrichment worker (Phase 4)
to keep `parse()` pure on the saved HTML snapshot — otherwise the self-heal
agent can't replay a failing scrape against a regenerated parser.

The scraper still surfaces the PDF URL in `raw_notice_url`, so enrichment can
fetch it on demand.
"""
from __future__ import annotations

from datetime import datetime

import httpx
from bs4 import BeautifulSoup

from warn_v2.scrapers._helpers import as_date, as_str
from warn_v2.scrapers.base import NoticeRow, ParseFailed, ScrapeFailed
from warn_v2.scrapers.registry import register

SOURCE_URL = "https://dol.ny.gov/warn-notices"
BASE_URL = "https://dol.ny.gov"

_UA = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) warn-v2/0.1"
    ),
    "X-Requested-With": "XMLHttpRequest",
}


class NYScraper:
    state = "NY"
    source_url = SOURCE_URL
    # 2026 YTD ~110, full year ~280 per V1 sheet — generous bounds for spikes.
    expected_row_range = (10, 5_000)
    required_fields = frozenset({"employer", "notice_date"})

    def fetch(self) -> bytes:
        try:
            r = httpx.get(SOURCE_URL, headers=_UA, timeout=60, follow_redirects=True)
            r.raise_for_status()
            return r.content
        except httpx.HTTPError as e:
            raise ScrapeFailed(f"GET {SOURCE_URL}: {e}") from e

    def parse(self, raw: bytes) -> list[NoticeRow]:
        soup = BeautifulSoup(raw, "html.parser")
        table = soup.find("table")
        if table is None:
            raise ParseFailed("no <table> found in NY DOL page")

        headers = [as_str(th.get_text()) or "" for th in table.find_all("th")]
        idx = _header_index(headers)

        body = table.find("tbody") or table
        rows: list[NoticeRow] = []
        for tr in body.find_all("tr"):
            cells = tr.find_all("td")
            if not cells:
                continue
            employer = as_str(cells[idx["company"]].get_text())
            if not employer:
                continue

            # NY's tables use whichever of "Notice Date" or "Date Posted" is
            # present; either works for identifying when the notice landed.
            notice_date = None
            for key in ("notice_date", "date_posted"):
                if key in idx:
                    notice_date = as_date(cells[idx[key]].get_text(strip=True))
                    if notice_date:
                        break
            if notice_date is None:
                # Skip rows without any usable date (header echoes, footers).
                continue

            link = cells[idx["company"]].find("a")
            href = link.get("href") if link else None
            raw_notice_url = _abs_url(href) if href else None

            rows.append(
                NoticeRow(
                    state="NY",
                    employer=employer,
                    notice_date=notice_date,
                    layoff_count=None,  # populated by enrichment (Phase 4)
                    source_url=SOURCE_URL,
                    raw_notice_url=raw_notice_url,
                )
            )
        return rows


def _header_index(headers: list[str]) -> dict[str, int]:
    """Map normalized header names → column index."""
    idx: dict[str, int] = {}
    for i, h in enumerate(headers):
        key = h.lower().strip().replace(" ", "_").replace("\xa0", "_")
        if key in {"company_name", "company"}:
            idx.setdefault("company", i)
        elif key in {"notice_date"}:
            idx["notice_date"] = i
        elif key in {"date_posted"}:
            idx["date_posted"] = i
    if "company" not in idx:
        raise ParseFailed(f"could not find company column in headers={headers}")
    return idx


def _abs_url(href: str) -> str:
    if href.startswith("http://") or href.startswith("https://"):
        return href
    if href.startswith("/"):
        return BASE_URL + href
    return f"{BASE_URL}/{href.lstrip('/')}"


# Silence "imported but unused" lint when datetime is referenced only in docstring.
_ = datetime

register(NYScraper())
