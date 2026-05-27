"""Missouri WARN scraper.

Source: https://jobs.mo.gov/warn/YYYY - one page per year (2019-current).
Administered by the Missouri Department of Economic Development (DED).
The site is Incapsula-protected, so httpx returns a JS-challenge page;
Playwright (headless Chromium) is used to bypass it.

Schema (confirmed from live site, May 2026):
  Received | Title | Industry | Location(s) | County | Region |
  Type | Layoff date(s) | # affected | Notes
"""
from __future__ import annotations

import json
import re
from datetime import date

from bs4 import BeautifulSoup

from warn_v2.scrapers._helpers import as_date, as_int, as_str
from warn_v2.scrapers.base import NoticeRow, ParseFailed, ScrapeFailed
from warn_v2.scrapers.playwright_base import PlaywrightScraper
from warn_v2.scrapers.registry import register

_DATE_RE = re.compile(r"\d{1,2}/\d{1,2}/\d{4}")

SOURCE_BASE = "https://jobs.mo.gov/warn/"
_FIRST_YEAR = 2019


class MOScraper(PlaywrightScraper):
    state = "MO"
    source_url = SOURCE_BASE + str(date.today().year)
    expected_row_range = (10, 5_000)
    required_fields = frozenset({"employer", "notice_date"})

    def _navigate(self, page) -> None:  # type: ignore[override]
        """Navigate all year pages in a single browser session, return combined JSON."""
        pages: list[dict[str, str]] = []
        current_year = date.today().year
        for year in range(_FIRST_YEAR, current_year + 1):
            url = f"{SOURCE_BASE}{year}"
            try:
                # Use 'load' not 'networkidle' — MO site has background XHR that never idles
                page.goto(url, wait_until="load", timeout=60_000)
                page.wait_for_selector("table, .no-results, main", timeout=15_000)
                html = page.content()
                pages.append({"url": url, "html": html})
            except Exception:
                continue
        # Stash collected pages in a JS global so fetch() can retrieve them
        payload = json.dumps(pages)
        page.evaluate(f"window.__mo_pages__ = {json.dumps(payload)}")

    def fetch(self) -> bytes:
        """Override to extract multi-page JSON stashed by _navigate()."""
        try:
            from playwright.sync_api import sync_playwright

            from warn_v2.scrapers.playwright_base import _LAUNCH_ARGS

            with sync_playwright() as pw:
                browser = pw.chromium.launch(headless=True, args=_LAUNCH_ARGS)
                try:
                    context = browser.new_context()
                    page = context.new_page()
                    self._navigate(page)
                    payload = page.evaluate("window.__mo_pages__")
                finally:
                    browser.close()
            if not payload:
                raise ScrapeFailed("MO: _navigate produced no pages")
            return json.dumps({"pages": json.loads(payload)}).encode()
        except ScrapeFailed:
            raise
        except Exception as exc:
            raise ScrapeFailed(f"MO: Playwright fetch failed: {exc}") from exc

    def parse(self, raw: bytes) -> list[NoticeRow]:
        try:
            data = json.loads(raw)
        except Exception as exc:
            raise ParseFailed(f"MO: raw bytes are not valid JSON: {exc}") from exc

        pages = data.get("pages", [])
        if not pages:
            raise ParseFailed("MO: JSON payload contains no pages")

        rows: list[NoticeRow] = []
        for page in pages:
            html = page.get("html", "")
            url = page.get("url", SOURCE_BASE)
            rows.extend(_parse_page(html, url))

        if not rows:
            raise ParseFailed("MO: no data rows parsed from any year page")
        return rows


def _cell_str(cells: list, col: dict, c_key: str | None) -> str | None:
    """Return as_str of a table cell, or None if column absent or out of range."""
    if c_key is None:
        return None
    idx = col.get(c_key)
    if idx is None or idx >= len(cells):
        return None
    return as_str(_text(cells[idx]))


def _cell_int(cells: list, col: dict, c_key: str | None) -> int | None:
    """Return as_int of a table cell, or None if column absent or out of range."""
    if c_key is None:
        return None
    idx = col.get(c_key)
    if idx is None or idx >= len(cells):
        return None
    return as_int(_text(cells[idx]))


def _parse_page(html: str, url: str) -> list[NoticeRow]:
    soup = BeautifulSoup(html, "html.parser")
    table = soup.find("table")
    if table is None:
        return []

    all_trs = table.find_all("tr")
    if not all_trs:
        return []

    header_cells = [_text(td).lower() for td in all_trs[0].find_all(["td", "th"])]
    col = {name: i for i, name in enumerate(header_cells)}

    # Require at minimum company (Title) + received date columns.
    company_col = next((c for c in col if "title" in c), None)
    date_col = next((c for c in col if "received" in c), None)
    if company_col is None or date_col is None:
        return []

    count_col = next((c for c in col if "affected" in c), None)
    city_col = next((c for c in col if "location" in c), None)
    county_col = next((c for c in col if "county" in c), None)
    type_col = next((c for c in col if c.strip() == "type"), None)
    layoff_date_col = next((c for c in col if "layoff" in c and "date" in c), None)

    rows: list[NoticeRow] = []
    for tr in all_trs[1:]:
        cells = tr.find_all(["td", "th"])
        min_needed = max(col[company_col], col[date_col]) + 1
        if len(cells) < min_needed:
            continue
        employer = as_str(_text(cells[col[company_col]]))
        if not employer:
            continue
        notice_date = as_date(_text(cells[col[date_col]]))
        if notice_date is None:
            continue

        effective_date = None
        if layoff_date_col is not None and col[layoff_date_col] < len(cells):
            raw_ld = _text(cells[col[layoff_date_col]])
            # Handle ranges like "03/21/2025-09/30/2025" - extract first date with regex
            m = _DATE_RE.search(raw_ld)
            if m:
                effective_date = as_date(m.group(0))

        rows.append(
            NoticeRow(
                state="MO",
                employer=employer,
                notice_date=notice_date,
                effective_date=effective_date,
                layoff_count=_cell_int(cells, col, count_col),
                closure_type=_cell_str(cells, col, type_col),
                city=_cell_str(cells, col, city_col),
                county=_cell_str(cells, col, county_col),
                source_url=url,
            )
        )
    return rows


def _text(cell) -> str:
    return " ".join(cell.get_text(" ", strip=True).split())


register(MOScraper())
