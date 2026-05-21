"""Indiana WARN scraper.

Source: https://www.in.gov/dwd/warn-notices/current-warn-notices/

Schema (live as of May 2026):
  Company | City | Affected Workers | Notice Date | LO/CL Date |
  NAICS | Description of Work/Industry | Notice Type | (PDF link)

Notice Type is "LO" (Layoff) or "CL" (Closure). LO/CL Date is the
effective layoff or closure date. The last column is empty in the header
but contains a PDF link per row.

The table has id="table33066" (stable since V1, May 2021).
"""
from __future__ import annotations

import httpx
from bs4 import BeautifulSoup

from warn_v2.scrapers._helpers import as_date, as_int, as_str
from warn_v2.scrapers.base import NoticeRow, ParseFailed, ScrapeFailed
from warn_v2.scrapers.registry import register

SOURCE_URL = "https://www.in.gov/dwd/warn-notices/current-warn-notices/"

_UA = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) warn-v2/0.1"
    )
}

_BASE_URL = "https://www.in.gov"

_NOTICE_TYPE = {"lo": "Layoff", "cl": "Closure"}


class INScraper:
    state = "IN"
    source_url = SOURCE_URL
    # Cumulative table — ~1000+ rows.
    expected_row_range = (50, 20_000)
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
        table = soup.find("table", {"id": "table33066"})
        if table is None:
            # Fall back to first table if id changed.
            table = soup.find("table")
        if table is None:
            raise ParseFailed("no <table> found on IN WARN page")

        all_trs = table.find_all("tr")
        if not all_trs:
            raise ParseFailed("IN table has no rows")

        header_cells = [_text(td).lower() for td in all_trs[0].find_all(["td", "th"])]
        if not header_cells or "company" not in header_cells:
            raise ParseFailed(f"unexpected IN header: {header_cells[:6]}")
        col = {name: i for i, name in enumerate(header_cells)}

        rows: list[NoticeRow] = []
        for tr in all_trs[1:]:
            cells = tr.find_all(["td", "th"])
            if len(cells) < 4:
                continue
            employer = as_str(_text(cells[col["company"]]))
            if not employer:
                continue
            notice_date = as_date(_text(cells[col["notice date"]]))
            if notice_date is None:
                continue

            notice_type_raw = _text(cells[col["notice type"]]).lower()
            closure_type = _NOTICE_TYPE.get(notice_type_raw, as_str(notice_type_raw))

            # Last column may contain a PDF link.
            notice_url: str | None = None
            last_cell = cells[-1]
            anchor = last_cell.find("a")
            if anchor and anchor.get("href"):
                href = anchor["href"]
                notice_url = href if href.startswith("http") else _BASE_URL + href

            naics_idx = col.get("naics")
            industry_idx = col.get("description of work/industry")

            rows.append(
                NoticeRow(
                    state="IN",
                    employer=employer,
                    notice_date=notice_date,
                    effective_date=as_date(_text(cells[col["lo/cl date"]])),
                    layoff_count=as_int(_text(cells[col["affected workers"]])),
                    closure_type=closure_type,
                    city=as_str(_text(cells[col["city"]])),
                    raw_notice_url=notice_url,
                    source_url=SOURCE_URL,
                    extra={
                        "naics": (
                            as_str(_text(cells[naics_idx])) or ""
                            if naics_idx is not None else ""
                        ),
                        "industry": (
                            as_str(_text(cells[industry_idx])) or ""
                            if industry_idx is not None else ""
                        ),
                    },
                )
            )
        return rows


def _text(cell) -> str:
    return " ".join(cell.get_text(" ", strip=True).split())


register(INScraper())
