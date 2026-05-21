"""Utah WARN scraper.

Source: https://jobs.utah.gov/employer/business/warnnotices.html

Schema (live as of May 2026):
  Date of Notice | Company Name | Location | Affected Workers

Static HTML table; no PDF links per row.
"""
from __future__ import annotations

import httpx
from bs4 import BeautifulSoup

from warn_v2.scrapers._helpers import as_date, as_int, as_str
from warn_v2.scrapers.base import NoticeRow, ParseFailed, ScrapeFailed
from warn_v2.scrapers.registry import register

SOURCE_URL = "https://jobs.utah.gov/employer/business/warnnotices.html"

_UA = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) warn-v2/0.1"
    )
}


class UTScraper:
    state = "UT"
    source_url = SOURCE_URL
    expected_row_range = (5, 5_000)
    required_fields = frozenset({"employer", "notice_date"})

    def fetch(self) -> bytes:
        try:
            r = httpx.get(SOURCE_URL, headers=_UA, timeout=30, follow_redirects=True)
            r.raise_for_status()
            return r.content
        except httpx.HTTPError as e:
            raise ScrapeFailed(f"GET {SOURCE_URL}: {e}") from e

    def parse(self, raw: bytes) -> list[NoticeRow]:
        soup = BeautifulSoup(raw, "html.parser")
        table = soup.find("table")
        if table is None:
            raise ParseFailed("no <table> found on UT WARN page")

        all_trs = table.find_all("tr")
        if not all_trs:
            raise ParseFailed("UT table has no rows")

        header_cells = [_text(td).lower() for td in all_trs[0].find_all(["td", "th"])]
        if not header_cells or "company name" not in header_cells:
            raise ParseFailed(f"unexpected UT header: {header_cells[:5]}")
        col = {name: i for i, name in enumerate(header_cells)}

        rows: list[NoticeRow] = []
        for tr in all_trs[1:]:
            cells = tr.find_all(["td", "th"])
            if len(cells) < 3:
                continue
            employer = as_str(_text(cells[col["company name"]]))
            if not employer:
                continue
            notice_date = as_date(_text(cells[col["date of notice"]]))
            if notice_date is None:
                continue

            rows.append(
                NoticeRow(
                    state="UT",
                    employer=employer,
                    notice_date=notice_date,
                    layoff_count=as_int(_text(cells[col["affected workers"]])),
                    city=as_str(_text(cells[col["location"]])),
                    source_url=SOURCE_URL,
                )
            )
        return rows


def _text(cell) -> str:
    return " ".join(cell.get_text(" ", strip=True).split())


register(UTScraper())
