"""South Dakota WARN scraper.

Source: https://dlr.sd.gov/workforce_services/businesses/warn_notices.aspx

Schema (live as of May 2026):
  Company | Location | Date Received | Employees Affected

Static HTML table; company cell has an anchor linking to a per-notice PDF
at /workforce_services/businesses/warn_notices/<slug>.pdf on dlr.sd.gov.

Location can be a comma-separated list of cities; city is set to the first.
Employees Affected can have a non-numeric suffix like "(nationwide)" — we
extract only the leading integer.
"""
from __future__ import annotations

import re

import httpx
from bs4 import BeautifulSoup

from warn_v2.scrapers._helpers import as_date, as_str
from warn_v2.scrapers.base import NoticeRow, ParseFailed, ScrapeFailed
from warn_v2.scrapers.registry import register

SOURCE_URL = "https://dlr.sd.gov/workforce_services/businesses/warn_notices.aspx"
_BASE_URL = "https://dlr.sd.gov"

_UA = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) warn-v2/0.1"
    )
}

_LEADING_INT = re.compile(r"^\d+")


class SDScraper:
    state = "SD"
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
            raise ParseFailed("no <table> found on SD WARN page")

        all_trs = table.find_all("tr")
        if not all_trs:
            raise ParseFailed("SD table has no rows")

        header_cells = [_text(td).lower() for td in all_trs[0].find_all(["td", "th"])]
        if not header_cells or "company" not in header_cells:
            raise ParseFailed(f"unexpected SD header: {header_cells[:5]}")
        col = {name: i for i, name in enumerate(header_cells)}

        rows: list[NoticeRow] = []
        for tr in all_trs[1:]:
            cells = tr.find_all(["td", "th"])
            if len(cells) < 3:
                continue

            company_cell = cells[col["company"]]
            anchor = company_cell.find("a")
            employer = as_str(_text(anchor) if anchor else _text(company_cell))
            if not employer:
                continue
            notice_date = as_date(_text(cells[col["date received"]]))
            if notice_date is None:
                continue

            notice_url: str | None = None
            if anchor and anchor.get("href"):
                href = anchor["href"]
                notice_url = href if href.startswith("http") else _BASE_URL + href

            location_raw = _text(cells[col["location"]])
            city = as_str(location_raw.split(",")[0].strip()) if location_raw else None

            count_raw = _text(cells[col["employees affected"]])
            m = _LEADING_INT.match(count_raw)
            layoff_count = int(m.group()) if m else None

            rows.append(
                NoticeRow(
                    state="SD",
                    employer=employer,
                    notice_date=notice_date,
                    layoff_count=layoff_count,
                    city=city,
                    raw_notice_url=notice_url,
                    source_url=SOURCE_URL,
                )
            )
        return rows


def _text(cell) -> str:
    return " ".join(cell.get_text(" ", strip=True).split())


register(SDScraper())
