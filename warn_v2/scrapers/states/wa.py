"""Washington WARN scraper.

Source: https://fortress.wa.gov/esd/file/warn/Public/SearchWARN.aspx (HTML table).

Schema (live as of May 2026):
  Company | Location | Layoff Start Date | # of Workers | Closure Layoff |
  Type of Layoff | Received Date | Notice

The table is surrounded by pagination rows (page number links) that must be
skipped. The header row is identified by looking for a cell whose text is
"Company".
"""
from __future__ import annotations

import httpx
from bs4 import BeautifulSoup

from warn_v2.scrapers._helpers import as_date, as_int, as_str
from warn_v2.scrapers.base import NoticeRow, ParseFailed, ScrapeFailed
from warn_v2.scrapers.registry import register

SOURCE_URL = "https://fortress.wa.gov/esd/file/warn/Public/SearchWARN.aspx"

_UA = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) warn-v2/0.1"
    )
}


class WAScraper:
    state = "WA"
    source_url = SOURCE_URL
    expected_row_range = (5, 5_000)
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
        tables = soup.find_all("table")
        if not tables:
            raise ParseFailed("no <table> found on WA WARN page")

        # First table contains the WARN data with pagination rows surrounding it.
        table = tables[0]
        all_trs = table.find_all("tr")
        if not all_trs:
            raise ParseFailed("WA table has no rows")

        # Find header row: the one containing a cell with text "Company".
        header_idx = None
        for i, tr in enumerate(all_trs):
            texts = [_text(td).lower() for td in tr.find_all(["td", "th"])]
            if "company" in texts:
                header_idx = i
                break
        if header_idx is None:
            raise ParseFailed("WA table: could not locate header row with 'Company'")

        header_cells = [_text(td).lower() for td in all_trs[header_idx].find_all(["td", "th"])]
        col = {name: i for i, name in enumerate(header_cells)}

        rows: list[NoticeRow] = []
        for tr in all_trs[header_idx + 1:]:
            cells = tr.find_all(["td", "th"])
            if len(cells) < len(header_cells):
                continue
            employer = as_str(_text(cells[col["company"]]))
            if not employer:
                continue
            # Skip pagination rows (employer cell is all digits / "...")
            bare = employer.replace(".", "").replace(" ", "")
            if bare.isdigit() or not employer[0].isalpha():
                continue

            notice_date = as_date(_text(cells[col["received date"]]))
            if notice_date is None:
                continue

            rows.append(
                NoticeRow(
                    state="WA",
                    employer=employer,
                    notice_date=notice_date,
                    effective_date=as_date(_text(cells[col["layoff start date"]])),
                    layoff_count=as_int(_text(cells[col["# of workers"]])),
                    closure_type=as_str(_text(cells[col["type of layoff"]])),
                    city=as_str(_text(cells[col["location"]])),
                    source_url=SOURCE_URL,
                    extra={"closure_layoff": as_str(_text(cells[col["closure layoff"]])) or ""},
                )
            )
        return rows


def _text(cell) -> str:
    return " ".join(cell.get_text(" ", strip=True).split())


register(WAScraper())
