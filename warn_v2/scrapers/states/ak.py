"""Alaska WARN scraper.

Source: https://jobs.alaska.gov/rr/WARN_notices.htm

Schema (live as of May 2026):
  Company | Location | Notice Date | Layoff Date | Employees Affected | Notes

Static HTML table; company cell has an anchor linking to a per-notice PDF
at /RR/notices/<filename>.pdf on labor.alaska.gov.

Notes contains the closure type ("Closure", "Layoff", "Loss of Contract", etc.).
Employees Affected can be "TBA" or "N Alaska Workers" — we extract the first
integer if present.
Layoff Date can be a free-text description ("Begins 7/7/25 and will be...") —
as_date handles gracefully and returns None for unparseable strings.
"""
from __future__ import annotations

import re

import httpx
from bs4 import BeautifulSoup

from warn_v2.scrapers._helpers import as_date, as_str
from warn_v2.scrapers.base import NoticeRow, ParseFailed, ScrapeFailed
from warn_v2.scrapers.registry import register

SOURCE_URL = "https://jobs.alaska.gov/rr/WARN_notices.htm"
_BASE_URL = "https://labor.alaska.gov"

_UA = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) warn-v2/0.1"
    )
}

_LEADING_INT = re.compile(r"\d+")


class AKScraper:
    state = "AK"
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
            raise ParseFailed("no <table> found on AK WARN page")

        all_trs = table.find_all("tr")
        if not all_trs:
            raise ParseFailed("AK table has no rows")

        header_cells = [_text(td).lower() for td in all_trs[0].find_all(["td", "th"])]
        if not header_cells or "company" not in header_cells:
            raise ParseFailed(f"unexpected AK header: {header_cells[:6]}")
        col = {name: i for i, name in enumerate(header_cells)}

        rows: list[NoticeRow] = []
        for tr in all_trs[1:]:
            cells = tr.find_all(["td", "th"])
            if not cells:
                continue

            company_cell = cells[col["company"]]
            anchor = company_cell.find("a")
            employer = as_str(_text(anchor) if anchor else _text(company_cell))
            if not employer:
                continue
            notice_date = as_date(_text(cells[col["notice date"]]))
            if notice_date is None:
                continue

            notice_url: str | None = None
            if anchor and anchor.get("href"):
                href = anchor["href"]
                notice_url = href if href.startswith("http") else _BASE_URL + href

            count_raw = _text(cells[col["employees affected"]])
            m = _LEADING_INT.search(count_raw)
            layoff_count = int(m.group()) if m else None

            notes_idx = col.get("notes")
            closure_type = (
                as_str(_text(cells[notes_idx])) if notes_idx is not None else None
            )

            rows.append(
                NoticeRow(
                    state="AK",
                    employer=employer,
                    notice_date=notice_date,
                    effective_date=as_date(_text(cells[col["layoff date"]])),
                    layoff_count=layoff_count,
                    closure_type=closure_type,
                    city=as_str(_text(cells[col["location"]])),
                    raw_notice_url=notice_url,
                    source_url=SOURCE_URL,
                )
            )
        return rows


def _text(cell) -> str:
    return " ".join(cell.get_text(" ", strip=True).split())


register(AKScraper())
