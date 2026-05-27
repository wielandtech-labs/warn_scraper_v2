"""Ohio WARN scraper.

Source: https://jfs.ohio.gov/...current-public-notices-of-layoffs-and-closures_warn
Administered by the Ohio Department of Job and Family Services (JFS).

The page renders a static HTML shell; the table rows are populated by JavaScript
after load, so Playwright is required. A realistic Chrome User-Agent is also needed.

Schema (confirmed from live site, May 2026):
  Company | Date Received | City/County | Layoff/Closure |
  Potential Number Affected | Layoff Date(s) | Phone Number | Union
"""
from __future__ import annotations

import re

from bs4 import BeautifulSoup

from warn_v2.scrapers._helpers import as_date, as_int, as_str
from warn_v2.scrapers.base import NoticeRow, ParseFailed
from warn_v2.scrapers.playwright_base import PlaywrightScraper
from warn_v2.scrapers.registry import register

SOURCE_URL = (
    "https://jfs.ohio.gov/job-services-and-unemployment/job-services/"
    "job-programs-and-services/submit-a-warn-notice/"
    "current-public-notices-of-layoffs-and-closures-sa/"
    "current-public-notices-of-layoffs-and-closures_warn"
)

# Realistic Chrome UA required — site returns empty table to bot UAs
_CHROME_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)

_DATE_RE = re.compile(r"\d{1,2}/\d{1,2}/\d{4}")


class OHScraper(PlaywrightScraper):
    state = "OH"
    source_url = SOURCE_URL
    expected_row_range = (5, 300)
    required_fields = frozenset({"employer", "notice_date"})

    def _navigate(self, page) -> None:  # type: ignore[override]
        page.context.set_extra_http_headers({"Accept": "text/html,application/xhtml+xml"})
        page.set_extra_http_headers({"User-Agent": _CHROME_UA})
        page.goto(SOURCE_URL, wait_until="load", timeout=60_000)
        # Wait until table is populated with at least one data row
        page.wait_for_selector("table tr td", timeout=20_000)

    def fetch(self) -> bytes:
        """Override to pass a realistic User-Agent via browser context."""
        try:
            from playwright.sync_api import sync_playwright

            from warn_v2.scrapers.playwright_base import _LAUNCH_ARGS

            with sync_playwright() as pw:
                browser = pw.chromium.launch(headless=True, args=_LAUNCH_ARGS)
                try:
                    ctx = browser.new_context(
                        user_agent=_CHROME_UA,
                        extra_http_headers={"Accept": "text/html,application/xhtml+xml"},
                    )
                    page = ctx.new_page()
                    self._navigate(page)
                    html = page.content()
                finally:
                    browser.close()
            return html.encode()
        except Exception as exc:
            from warn_v2.scrapers.base import ScrapeFailed

            raise ScrapeFailed(f"OH: Playwright fetch failed: {exc}") from exc

    def parse(self, raw: bytes) -> list[NoticeRow]:
        soup = BeautifulSoup(raw, "html.parser")
        table = soup.find("table")
        if table is None:
            raise ParseFailed("no <table> found on OH WARN page")

        all_trs = table.find_all("tr")
        if not all_trs:
            raise ParseFailed("OH WARN table has no rows")

        header_cells = [_text(td).lower() for td in all_trs[0].find_all(["td", "th"])]
        col = {name: i for i, name in enumerate(header_cells)}

        company_col = next((c for c in col if "company" in c), None)
        date_col = next((c for c in col if "received" in c), None)
        if company_col is None or date_col is None:
            raise ParseFailed(
                f"unexpected OH header — company or date column missing: {header_cells}"
            )

        city_col = next((c for c in col if "city" in c or "county" in c), None)
        type_col = next((c for c in col if "layoff" in c and "closure" in c), None)
        count_col = next((c for c in col if "affected" in c or "number" in c), None)
        layoff_date_col = next(
            (c for c in col if "layoff" in c and "date" in c), None
        )

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

            # City/County is "Toledo/Lucas" — split on "/"
            city = county = None
            if city_col is not None and col[city_col] < len(cells):
                cc = _text(cells[col[city_col]])
                parts = cc.split("/", 1)
                city = as_str(parts[0])
                county = as_str(parts[1]) if len(parts) > 1 else None

            effective_date = None
            if layoff_date_col is not None and col[layoff_date_col] < len(cells):
                m = _DATE_RE.search(_text(cells[col[layoff_date_col]]))
                if m:
                    effective_date = as_date(m.group(0))

            rows.append(
                NoticeRow(
                    state="OH",
                    employer=employer,
                    notice_date=notice_date,
                    effective_date=effective_date,
                    layoff_count=(
                        as_int(_text(cells[col[count_col]]))
                        if count_col is not None and col[count_col] < len(cells)
                        else None
                    ),
                    closure_type=(
                        as_str(_text(cells[col[type_col]]))
                        if type_col is not None and col[type_col] < len(cells)
                        else None
                    ),
                    city=city,
                    county=county,
                    source_url=SOURCE_URL,
                )
            )

        if not rows:
            raise ParseFailed("OH WARN page: no data rows parsed from table")
        return rows


def _text(cell) -> str:
    return " ".join(cell.get_text(" ", strip=True).split())


register(OHScraper())
