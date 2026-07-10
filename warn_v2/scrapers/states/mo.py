"""Missouri WARN scraper.

Source: https://jobs.mo.gov/warn/YYYY - one page per year (2019-current).
Administered by the Missouri Department of Economic Development (DED).
The site is Incapsula-protected, so httpx returns a JS-challenge page;
Playwright (headless Chromium) is used to bypass it.

Schema (confirmed from live site, May 2026):
  Received | Title | Industry | Location(s) | County | Region |
  Type | Layoff date(s) | # affected | Notes

Historical backfill (Jul 2012 - Dec 2018): jobs.mo.gov purged its pre-2019
program-year pages (MO publishes by Program Year, July-June), but the Wayback
Machine holds a consolidated Jul-2012→Jun-2015 log PDF, the PY2015 log PDF,
and the PY2016-PY2018 HTML pages. Static pinned captures — no runtime CDX.
See ``_discover_mo_archive_urls`` / ``parse_mo_log_pdf`` /
``parse_mo_archive_html``.
"""
from __future__ import annotations

import io
import json
import re
from datetime import date

import pdfplumber
from bs4 import BeautifulSoup

from warn_v2.scrapers._helpers import as_date, as_int, as_str
from warn_v2.scrapers.base import NoticeRow, ParseFailed, ScrapeFailed
from warn_v2.scrapers.playwright_base import PlaywrightScraper
from warn_v2.scrapers.registry import register
from warn_v2.scrapers.wayback import replay_url

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


# ---------------------------------------------------------------------------
# Historical backfill (jobs.mo.gov via Wayback, Jul 2012 - Dec 2018) — see
# module docstring.
# ---------------------------------------------------------------------------

# Pinned Wayback captures (ts, original URL). The 2015-09-12 capture of
# warn-log-2016.pdf is deliberately absent: its 4 rows are a strict subset of
# the warn-log-py2015.pdf capture below (verified offline 2026-07-10).
# Mid-program-year captures leave gaps with no known Wayback coverage:
# Sep 2015-Jun 2016 (the PY2015 log stopped updating), May-Jun 2017 (PY2016
# page captured 2017-04) and Jan-Jun 2018 (PY2017 page captured 2017-12).
_ARCHIVE_CAPTURES: tuple[tuple[str, str], ...] = (
    # Consolidated log, Jul 2012 - Jun 2015 (PY2012-PY2014), 17-page PDF.
    (
        "20151018024542",
        "https://jobs.mo.gov/sites/jobs/files/warn_log_jul2012_to_present_2015-07-01.pdf",
    ),
    # PY2015 log PDF — rows Jul-Sep 2015 only (the file went stale; later
    # captures carry the same six rows).
    ("20161223014721", "https://jobs.mo.gov/sites/jobs/files/warn-log-py2015.pdf"),
    # PY2016-PY2018 pages. The PY2016 capture is the Spanish-path URL, but the
    # table content is the English original.
    ("20170409074237", "https://jobs.mo.gov/es/warn2016"),
    ("20171204110254", "https://jobs.mo.gov/content/missouri-warn-notices-py-2017"),
    ("20190211194351", "https://jobs.mo.gov/content/missouri-warn-notices-py-2018"),
)

# The regular scraper crawls 2019-present every run and that data is complete
# in prod; the PY2018 capture runs into early 2019, so archive parsers drop
# rows received on/after this date.
_BACKFILL_CUTOFF = date(2019, 1, 1)

# Received/layoff dates in the archives use 2- or 4-digit years, and amended
# notices stack several received dates in one cell — take the first.
_ARCHIVE_DATE_RE = re.compile(r"\d{1,2}/\d{1,2}/\d{2,4}")


def _discover_mo_archive_urls() -> list[str]:
    """Static pinned Wayback ``id_`` replay URLs — no runtime CDX."""
    return [replay_url(ts, url) for ts, url in _ARCHIVE_CAPTURES]


def _mo_archive_row(
    date_raw: str,
    employer_raw: str,
    location: str | None,
    county: str | None,
    closure_type: str | None,
    layoff_raw: str | None,
    count_raw: str | None,
    source_url: str,
) -> NoticeRow | None:
    m = _ARCHIVE_DATE_RE.search(date_raw or "")
    notice_date = as_date(m.group(0)) if m else None
    employer = as_str(employer_raw)
    if not employer or notice_date is None or notice_date >= _BACKFILL_CUTOFF:
        return None
    effective_date = None
    if layoff_raw:
        m = _ARCHIVE_DATE_RE.search(layoff_raw)
        if m:
            effective_date = as_date(m.group(0))
    return NoticeRow(
        state="MO",
        employer=employer,
        notice_date=notice_date,
        effective_date=effective_date,
        layoff_count=as_int(count_raw),
        closure_type=as_str(closure_type or ""),
        city=as_str(location or ""),
        county=as_str(county or ""),
        source_url=source_url,
    )


def _clean_cell(cell) -> str:
    """Collapse a pdfplumber cell (may be None / hold wrap newlines) to one line."""
    return " ".join(str(cell).split()) if cell else ""


def parse_mo_log_pdf(raw: bytes, source_url: str) -> list[NoticeRow]:
    """Parse a WARN-log PDF (the consolidated Jul2012-2015 log or the PY2015 log).

    Both are lattice tables with the same 8 logical columns
    (Date Rec'd | Company Name | Location(s) | County | Region | Type |
    Layoff or Closing Date | # Affected), but the consolidated log's merged
    cells make pdfplumber report most pages as 24 physical columns with the
    values at every third index — read cell ``i * (ncols // 8)``. Data rows
    are keyed by a date in the first column (amended notices stack several;
    the first is the original filing); dateless rows are headers, PY totals,
    or the location-list overflow of a row split across a page break (its
    filing is already captured on the previous page).
    """
    rows: list[NoticeRow] = []
    try:
        pdf = pdfplumber.open(io.BytesIO(raw))
    except Exception as exc:
        raise ParseFailed(f"MO log PDF: not a readable PDF: {exc}") from exc
    with pdf:
        for page in pdf.pages:
            for tbl in page.extract_tables():
                for r in tbl:
                    if not r or len(r) % 8:
                        continue
                    stride = len(r) // 8
                    cells = [_clean_cell(r[i * stride]) for i in range(8)]
                    row = _mo_archive_row(
                        cells[0],  # Date Rec'd
                        cells[1],  # Company Name
                        cells[2],  # Location(s)
                        cells[3],  # County
                        cells[5],  # Type of Notice (4 is WIA/WIOA Region)
                        cells[6],  # Layoff or Closing Date
                        cells[7],  # # Affected
                        source_url,
                    )
                    if row is not None:
                        rows.append(row)
    if not rows:
        raise ParseFailed("MO log PDF: no notice rows parsed")
    return rows


def parse_mo_archive_html(raw: bytes, source_url: str) -> list[NoticeRow]:
    """Parse an archived PY-page capture (PY2016-PY2018).

    These are raw HTML documents, not the Playwright-stashed JSON envelope
    ``MOScraper.parse`` expects, and the headers differ from the live table
    (DATE RECEIVED / COMPANY NAME vs Received / Title). The TOTAL footer row
    has no received date and is dropped by ``_mo_archive_row``.
    """
    soup = BeautifulSoup(raw, "html.parser")
    rows: list[NoticeRow] = []
    for table in soup.find_all("table"):
        trs = table.find_all("tr")
        if not trs:
            continue
        hdr = [_text(c).lower() for c in trs[0].find_all(["td", "th"])]
        col = {name: i for i, name in enumerate(hdr)}
        date_i = next((col[c] for c in col if "date received" in c), None)
        comp_i = next((col[c] for c in col if "company name" in c), None)
        if date_i is None or comp_i is None:
            continue
        loc_i = next((col[c] for c in col if "location" in c), None)
        county_i = next((col[c] for c in col if "county" in c), None)
        type_i = next((col[c] for c in col if c.strip() == "type"), None)
        layoff_i = next((col[c] for c in col if "layoff date" in c), None)
        count_i = next((col[c] for c in col if "affected" in c), None)

        def _cell(tds: list[str], i: int | None) -> str | None:
            return tds[i] if i is not None and i < len(tds) else None

        for tr in trs[1:]:
            tds = [_text(c) for c in tr.find_all(["td", "th"])]
            if len(tds) <= max(date_i, comp_i):
                continue
            row = _mo_archive_row(
                tds[date_i],
                tds[comp_i],
                _cell(tds, loc_i),
                _cell(tds, county_i),
                _cell(tds, type_i),
                _cell(tds, layoff_i),
                _cell(tds, count_i),
                source_url,
            )
            if row is not None:
                rows.append(row)
    if not rows:
        raise ParseFailed("MO archive page: no notice rows parsed")
    return rows
