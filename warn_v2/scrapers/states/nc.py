"""North Carolina WARN scraper.

Source: https://www.commerce.nc.gov/.../report-workforce-warn-summary-list-{year}

Schema (live as of May 2026):
  County | Warn Number | Date of Notice | Date Received by NC | Effective Date |
  WARN Notice: WARN Notice Name | WARN notice type | Type of layoff or closure |
  Number affected at this location | Address 1 | City

The page URL embeds the year. Falls back to prior year when current year 404s.
"""
from __future__ import annotations

from datetime import date

import httpx
from bs4 import BeautifulSoup

from warn_v2.scrapers._helpers import as_date, as_int, as_str
from warn_v2.scrapers.base import NoticeRow, ParseFailed, ScrapeFailed
from warn_v2.scrapers.registry import register

_URL = (
    "https://www.commerce.nc.gov/data-tools-reports/labor-market-data-tools"
    "/workforce-warn-reports/report-workforce-warn-summary-list-{year}"
)

_UA = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) warn-v2/0.1"
    )
}


def _source_url(year: int) -> str:
    return _URL.format(year=year)


class NCScraper:
    state = "NC"
    source_url = _URL.format(year=date.today().year)
    expected_row_range = (5, 2_000)
    required_fields = frozenset({"employer", "notice_date"})

    def fetch(self) -> bytes:
        year = date.today().year
        for yr in (year, year - 1):
            url = _source_url(yr)
            try:
                r = httpx.get(url, headers=_UA, timeout=60, follow_redirects=True)
                if r.status_code == 200 and b"<table" in r.content:
                    self.source_url = url
                    return r.content
            except httpx.HTTPError:
                pass
        raise ScrapeFailed(f"Could not fetch NC WARN page for {year} or {year - 1}")

    def parse(self, raw: bytes) -> list[NoticeRow]:
        soup = BeautifulSoup(raw, "html.parser")
        table = soup.find("table")
        if table is None:
            raise ParseFailed("no <table> found on NC WARN page")

        all_trs = table.find_all("tr")
        if not all_trs:
            raise ParseFailed("NC table has no rows")

        header_cells = [_text(td).lower() for td in all_trs[0].find_all(["td", "th"])]
        if not header_cells or not any("warn" in h for h in header_cells):
            raise ParseFailed(f"unexpected NC header: {header_cells[:6]}")
        col = {name: i for i, name in enumerate(header_cells)}

        # Employer column name contains a colon; find it by partial match.
        employer_col = next(
            (k for k in col if "warn notice name" in k or "warn notice:" in k),
            None,
        )
        if employer_col is None:
            raise ParseFailed(f"NC: could not find employer column; headers: {header_cells}")

        # "Address 1" is the street address of the layoff site; optional.
        address_col = next((k for k in col if "address" in k), None)

        rows: list[NoticeRow] = []
        for tr in all_trs[1:]:
            cells = tr.find_all(["td", "th"])
            if len(cells) < len(header_cells):
                continue
            employer = as_str(_text(cells[col[employer_col]]))
            if not employer:
                continue
            notice_date = as_date(_text(cells[col["date of notice"]]))
            if notice_date is None:
                continue

            address = (
                as_str(_text(cells[col[address_col]]))
                if address_col is not None
                else None
            )

            rows.append(
                NoticeRow(
                    state="NC",
                    employer=employer,
                    notice_date=notice_date,
                    effective_date=as_date(_text(cells[col["effective date"]])),
                    layoff_count=as_int(
                        _text(cells[col["number affected at this location"]])
                    ),
                    closure_type=as_str(
                        _text(cells[col["type of layoff or closure"]])
                    ),
                    city=as_str(_text(cells[col["city"]])),
                    county=as_str(_text(cells[col["county"]])),
                    address=address,
                    source_url=self.source_url,
                    extra={
                        "warn_number": as_str(_text(cells[col["warn number"]])) or "",
                        "warn_notice_type": as_str(
                            _text(cells[col["warn notice type"]])
                        ) or "",
                    },
                )
            )
        return rows


def _text(cell) -> str:
    return " ".join(cell.get_text(" ", strip=True).split())


register(NCScraper())
