"""Virginia WARN scraper.

Source: https://virginiaworks.gov/im-an-employer/retain-and-grow/warn-notices/
  (domain migrated from vec.virginia.gov as of 2026)

Schema (live as of May 2026):
  Company | Notice Date | Impact Date | Employees Affected | Location |
  Contact Person | Notice Type | Collective Bargaining Unit

The Company cell contains an <a> tag with the clean company name linking to the
filed WARN PDF, followed by the street address as raw text. We extract the link
text as employer and the href as raw_notice_url.

Location is "City, VA" — city is extracted by splitting on comma.
"""
from __future__ import annotations

import httpx
from bs4 import BeautifulSoup

from warn_v2.scrapers._helpers import as_date, as_int, as_str
from warn_v2.scrapers.base import NoticeRow, ParseFailed, ScrapeFailed
from warn_v2.scrapers.registry import register

SOURCE_URL = "https://virginiaworks.gov/im-an-employer/retain-and-grow/warn-notices/"

_UA = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) warn-v2/0.1"
    )
}


class VAScraper:
    state = "VA"
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
        table = soup.find("table")
        if table is None:
            raise ParseFailed("no <table> found on VA WARN page")

        all_trs = table.find_all("tr")
        if not all_trs:
            raise ParseFailed("VA table has no rows")

        header_cells = [_text(td).lower() for td in all_trs[0].find_all(["td", "th"])]
        if not header_cells or "company" not in header_cells:
            raise ParseFailed(f"unexpected VA header: {header_cells[:6]}")
        col = {name: i for i, name in enumerate(header_cells)}

        rows: list[NoticeRow] = []
        for tr in all_trs[1:]:
            cells = tr.find_all(["td", "th"])
            if len(cells) < len(header_cells):
                continue

            # Company cell: <a> text = clean employer name; href = notice PDF.
            company_cell = cells[col["company"]]
            anchor = company_cell.find("a")
            if anchor:
                employer = as_str(anchor.get_text(" ", strip=True))
                notice_url: str | None = anchor.get("href") or None
            else:
                employer = as_str(_text(company_cell))
                notice_url = None

            if not employer:
                continue
            notice_date = as_date(_text(cells[col["notice date"]]))
            if notice_date is None:
                continue

            location = _text(cells[col["location"]])
            city = as_str(location.split(",")[0].strip()) if location else None

            rows.append(
                NoticeRow(
                    state="VA",
                    employer=employer,
                    notice_date=notice_date,
                    effective_date=as_date(_text(cells[col["impact date"]])),
                    layoff_count=as_int(_text(cells[col["employees affected"]])),
                    closure_type=as_str(_text(cells[col["notice type"]])),
                    city=city,
                    raw_notice_url=notice_url,
                    source_url=SOURCE_URL,
                )
            )
        return rows


def _text(cell) -> str:
    return " ".join(cell.get_text(" ", strip=True).split())


register(VAScraper())
