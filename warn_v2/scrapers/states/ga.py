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
    expected_row_range = (100, 500)
    required_fields = frozenset({"employer", "notice_date"})
    # raw_notice_url points to a GravityView HTML entry page, not a direct PDF.
    # enrich_ga handles scraping the page, extracting fields, and downloading
    # the embedded gk-download PDF.  download_pdfs must skip GA.
    raw_notice_url_is_pdf = False

    def _navigate(self, page) -> None:  # type: ignore[override]
        # "load" fires when the HTML is parsed; wait_for_selector then blocks
        # until the data table appears.  "networkidle" times out on this page
        # because background XHRs never fully settle.
        page.goto(SOURCE_URL, wait_until="load", timeout=60_000)
        page.wait_for_selector("table", timeout=30_000)

        # The DataTables defaults to 25 rows/page.  Select "All" (-1) so a
        # single server-side AJAX call returns every entry.  We intercept the
        # response to know exactly when the reload is done before calling
        # page.content(), avoiding a race with partial rendering.
        with page.expect_response(
            lambda r: "admin-ajax.php" in r.url, timeout=30_000
        ):
            page.select_option(
                "select[name='DataTables_Table_0_length']", "-1"
            )
        # Table rows are rendered synchronously from the AJAX payload, so a
        # brief selector wait is enough for the DOM to settle.
        page.wait_for_selector("table tbody tr", timeout=10_000)

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
        # GA WARN ID column — the cell contains <a href="…/entry/NNN/">GA…ID</a>
        id_col = next((c for c in col if "warn" in c and "id" in c), None)

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
            # Extract entry detail URL from the GA WARN ID link.
            raw_notice_url: str | None = None
            if id_col is not None and col[id_col] < len(cells):
                a_tag = cells[col[id_col]].find("a")
                if a_tag and a_tag.get("href"):
                    raw_notice_url = a_tag["href"]
            rows.append(
                NoticeRow(
                    state="GA",
                    employer=employer,
                    notice_date=notice_date,
                    layoff_count=layoff_count,
                    source_url=SOURCE_URL,
                    raw_notice_url=raw_notice_url,
                )
            )
        if not rows:
            raise ParseFailed("GA WARN page: no data rows parsed from table")
        return rows


def _text(cell) -> str:
    return " ".join(cell.get_text(" ", strip=True).split())


register(GAScraper())
