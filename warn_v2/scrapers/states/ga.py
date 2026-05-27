"""Georgia WARN scraper.

Source: https://www.tcsg.edu/warn-public-view/
Administered by the Technical College System of Georgia (TCSG) since Jan 2023.
Prior data (through June 2013) archived at the legacy GA DOL site.

Schema (TCSG public table, live as of May 2026):
  GA WARN ID | Company Name | Submitted Date |
  Total Number of Affected Employees | Entry ID
"""
from __future__ import annotations

from bs4 import BeautifulSoup

from warn_v2.scrapers._helpers import as_date, as_int, as_str
from warn_v2.scrapers.base import NoticeRow, ParseFailed
from warn_v2.scrapers.playwright_base import PlaywrightScraper
from warn_v2.scrapers.registry import register

SOURCE_URL = "https://www.tcsg.edu/warn-public-view/"


class GAScraper(PlaywrightScraper):
    state = "GA"
    source_url = SOURCE_URL
    expected_row_range = (5, 300)
    required_fields = frozenset({"employer", "notice_date"})

    def _navigate(self, page) -> None:  # type: ignore[override]
        page.goto(SOURCE_URL, wait_until="networkidle", timeout=60_000)
        page.wait_for_selector("table", timeout=20_000)

    def parse(self, raw: bytes) -> list[NoticeRow]:
        soup = BeautifulSoup(raw, "html.parser")
        table = soup.find("table")
        if table is None:
            raise ParseFailed("no <table> found on GA WARN page")

        all_trs = table.find_all("tr")
        if not all_trs:
            raise ParseFailed("GA WARN table has no rows")

        header_cells = [_text(td).lower() for td in all_trs[0].find_all(["td", "th"])]
        col = {name: i for i, name in enumerate(header_cells)}

        # Require at minimum company name + date columns.
        company_col = next((c for c in col if "company" in c), None)
        date_col = next((c for c in col if "date" in c), None)
        if company_col is None or date_col is None:
            raise ParseFailed(
                f"unexpected GA header — company or date column missing: {header_cells}"
            )

        count_col = next((c for c in col if "affected" in c or "employee" in c), None)

        rows: list[NoticeRow] = []
        for tr in all_trs[1:]:
            cells = tr.find_all(["td", "th"])
            if len(cells) <= max(col[company_col], col[date_col]):
                continue
            employer = as_str(_text(cells[col[company_col]]))
            if not employer:
                continue
            notice_date = as_date(_text(cells[col[date_col]]))
            if notice_date is None:
                continue
            layoff_count = (
                as_int(_text(cells[col[count_col]])) if count_col is not None else None
            )
            rows.append(
                NoticeRow(
                    state="GA",
                    employer=employer,
                    notice_date=notice_date,
                    layoff_count=layoff_count,
                    source_url=SOURCE_URL,
                )
            )
        if not rows:
            raise ParseFailed("GA WARN page: no data rows parsed from table")
        return rows


def _text(cell) -> str:
    return " ".join(cell.get_text(" ", strip=True).split())


register(GAScraper())
