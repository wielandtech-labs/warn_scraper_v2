"""District of Columbia WARN scraper.

Source: https://does.dc.gov/page/industry-closings-and-layoffs-warn-notifications-{year}

Schema (live as of May 2026):
  Notice Date | Organization Name | Number toEmployees Affected | Effective Layoff Date | Code Type

"Code Type" maps 1 → Layoff, 2 → Permanent Closures.
Dates are spelled out: "February 2, 2026".
DC does not publish city or ZIP in the WARN table (all notices are in DC).
"""
from __future__ import annotations

from datetime import date

import httpx
from bs4 import BeautifulSoup

from warn_v2.scrapers._helpers import as_date, as_int, as_str
from warn_v2.scrapers.base import NoticeRow, ParseFailed, ScrapeFailed
from warn_v2.scrapers.registry import register

_URL = "https://does.dc.gov/page/industry-closings-and-layoffs-warn-notifications-{year}"

_UA = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) warn-v2/0.1"
    )
}

_CODE_TYPE = {"1": "Layoff", "2": "Permanent Closures"}


def _source_url(year: int) -> str:
    return _URL.format(year=year)


def _fetch_dc_year(year: int) -> bytes | None:
    """Fetch the DC WARN HTML table for a specific year.

    Returns the page bytes if the table is present, or None if the page exists
    but has no WARN data (empty year or future year).
    """
    url = _source_url(year)
    try:
        r = httpx.get(url, headers=_UA, timeout=60, follow_redirects=True)
        r.raise_for_status()
    except httpx.HTTPError:
        return None
    return r.content if b"Organization Name" in r.content else None


class DCScraper:
    state = "DC"
    source_url = _URL.format(year=date.today().year)
    expected_row_range = (1, 500)
    required_fields = frozenset({"employer", "notice_date"})

    def fetch(self) -> bytes:
        year = date.today().year
        for yr in (year, year - 1):
            url = _source_url(yr)
            try:
                r = httpx.get(url, headers=_UA, timeout=60, follow_redirects=True)
                r.raise_for_status()
                if b"Organization Name" in r.content or b"organization name" in r.content.lower():
                    self.source_url = url
                    return r.content
            except httpx.HTTPError:
                pass
        raise ScrapeFailed(f"Could not fetch DC WARN page for {year} or {year - 1}")

    def parse(self, raw: bytes) -> list[NoticeRow]:
        soup = BeautifulSoup(raw, "html.parser")
        table = soup.find("table")
        if table is None:
            raise ParseFailed("no <table> found on DC WARN page")

        all_trs = table.find_all("tr")
        if not all_trs:
            raise ParseFailed("DC table has no rows")

        header_cells = [_text(td).lower() for td in all_trs[0].find_all(["td", "th"])]
        if not header_cells or "organization name" not in header_cells:
            raise ParseFailed(f"unexpected DC header: {header_cells[:6]}")
        col = {name: i for i, name in enumerate(header_cells)}

        rows: list[NoticeRow] = []
        for tr in all_trs[1:]:
            cells = tr.find_all(["td", "th"])
            if len(cells) < len(header_cells):
                continue
            employer = as_str(_text(cells[col["organization name"]]))
            if not employer:
                continue
            notice_date = as_date(_text(cells[col["notice date"]]))
            if notice_date is None:
                continue

            code = _text(cells[col["code type"]]).strip()
            closure_type = _CODE_TYPE.get(code, as_str(code))

            rows.append(
                NoticeRow(
                    state="DC",
                    employer=employer,
                    notice_date=notice_date,
                    effective_date=as_date(_text(cells[col["effective layoff date"]])),
                    layoff_count=as_int(_text(cells[col["number toemployees affected"]])),
                    closure_type=closure_type,
                    source_url=self.source_url,
                )
            )
        return rows


def _text(cell) -> str:
    return " ".join(cell.get_text(" ", strip=True).split())


register(DCScraper())
