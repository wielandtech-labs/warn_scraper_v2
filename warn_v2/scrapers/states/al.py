"""Alabama WARN scraper.

Source: https://workforce.alabama.gov/warn-list/ (HTML table, cumulative since 1998).

Schema (live as of May 2026):
  Closing or Layoff | Initial Report Date | Planned Starting Date |
  Company | City | Planned # of Affected Employees

The page is cumulative — it returns all years regardless of the ?warn-year
query parameter. The table has a single header row followed by data rows.
"""
from __future__ import annotations

import httpx
from bs4 import BeautifulSoup

from warn_v2.scrapers._helpers import as_date, as_int, as_str
from warn_v2.scrapers.base import NoticeRow, ParseFailed, ScrapeFailed
from warn_v2.scrapers.registry import register

SOURCE_URL = "https://workforce.alabama.gov/warn-list/"

_UA = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) warn-v2/0.1"
    )
}


class ALScraper:
    state = "AL"
    source_url = SOURCE_URL
    # Cumulative from 1998 — typically 1000+ rows.
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
        table = soup.find("table")
        if table is None:
            raise ParseFailed("no <table> found on AL WARN page")

        all_trs = table.find_all("tr")
        if not all_trs:
            raise ParseFailed("AL table has no rows")

        header_cells = [_text(td).lower() for td in all_trs[0].find_all(["td", "th"])]
        if not header_cells or "company" not in header_cells:
            raise ParseFailed(f"unexpected AL header: {header_cells[:6]}")
        col = {name: i for i, name in enumerate(header_cells)}

        rows: list[NoticeRow] = []
        for tr in all_trs[1:]:
            cells = tr.find_all(["td", "th"])
            if len(cells) < len(header_cells):
                continue
            employer = as_str(_text(cells[col["company"]]))
            if not employer:
                continue
            notice_date = as_date(_text(cells[col["initial report date"]]))
            if notice_date is None:
                continue

            rows.append(
                NoticeRow(
                    state="AL",
                    employer=employer,
                    notice_date=notice_date,
                    effective_date=as_date(_text(cells[col["planned starting date"]])),
                    layoff_count=as_int(_text(cells[col["planned # of affected employees"]])),
                    closure_type=as_str(_text(cells[col["closing or layoff"]])),
                    city=as_str(_text(cells[col["city"]])),
                    source_url=SOURCE_URL,
                )
            )
        return rows


def _text(cell) -> str:
    return " ".join(cell.get_text(" ", strip=True).split())


register(ALScraper())
