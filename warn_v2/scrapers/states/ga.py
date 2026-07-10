"""Georgia WARN scraper.

Source: https://www.tcsg.edu/warn-public-view/
Administered by the Technical College System of Georgia (TCSG) since Jan 2023.
Prior data (through June 2013) archived at the legacy GA DOL site.

Schema (TCSG public table, live as of May 2026):
  GA WARN ID | Company Name | Submitted Date |
  Total Number of Affected Employees | Entry ID

Backfill (Mode 3b): the 31 GA2022* GravityView entry detail pages TCSG still
served live on 2026-07-10 (ids GA202200071-103; 083 and 097 pruned at the
source) are bundled in ``data/ga_archive.tar.gz`` together with the listing
DataTables JSON — see ``ga_archive_files`` / ``parse_ga_entry_page``.
"""
from __future__ import annotations

import json
import re
from datetime import date
from functools import lru_cache
from html import unescape
from typing import NamedTuple

from bs4 import BeautifulSoup

from warn_v2.scrapers._helpers import as_date, as_int, as_str
from warn_v2.scrapers.base import NoticeRow, ParseFailed
from warn_v2.scrapers.bundled import DATA_DIR, load_archive
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
        # The AJAX payload returns quickly, but DataTables is slow to paint the
        # rows into the DOM: the site's Content-Security-Policy blocks the
        # responsive extension on cdn.datatables.net, so DataTables stalls on
        # the failed CDN loads (~20s observed) before rendering.  Wait well past
        # that for the first row to appear.
        page.wait_for_selector("table tbody tr", timeout=45_000)

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


# ---------------------------------------------------------------------------
# GA 2022 bundled backfill (Mode 3b)
# ---------------------------------------------------------------------------

_GA_ARCHIVE = DATA_DIR / "ga_archive.tar.gz"
_LISTING_MEMBER = "gravityview_listing.json"


def ga_archive_files() -> list[tuple[str, bytes]]:
    """Entry-page members of the bundled GA2022 snapshot.

    The listing JSON member rides along in the same tar.gz but is consumed by
    ``_listing_index`` (for submitted dates), not parsed as a page.
    """
    return [
        (name, raw)
        for name, raw in load_archive(_GA_ARCHIVE)
        if name.endswith(".html")
    ]


class _ListingEntry(NamedTuple):
    notice_date: date | None  # the listing's "Submitted Date" (date_created)
    layoff_count: int | None
    entry_url: str | None


@lru_cache(maxsize=1)
def _listing_index() -> dict[str, _ListingEntry]:
    """GA WARN ID → listing fields, from the bundled DataTables payload.

    Cells hold the raw HTML the live table renders (the GA WARN ID cell is an
    ``<a href=".../entry/N/">`` anchor; text may carry entities), so unescape
    before indexing.
    """
    raw = next(b for n, b in load_archive(_GA_ARCHIVE) if n == _LISTING_MEMBER)
    index: dict[str, _ListingEntry] = {}
    for row in json.loads(raw)["data"]:
        # Rows are plain 5-cell lists, or dicts keyed "0".."4" (+ gv_marker).
        cells = [row[str(i)] for i in range(5)] if isinstance(row, dict) else row[:5]
        anchor, _company, date_created, count, _entry_id = cells
        ga_warn_id = unescape(re.sub(r"<[^>]+>", "", anchor)).strip()
        href = re.search(r'href="([^"]+)"', anchor)
        index[ga_warn_id] = _ListingEntry(
            notice_date=as_date(unescape(date_created)),
            layoff_count=as_int(unescape(str(count))),
            entry_url=href.group(1) if href else None,
        )
    return index


def parse_ga_entry_page(raw: bytes) -> list[NoticeRow]:
    """Parse one bundled TCSG entry detail page into a single NoticeRow.

    The entry page carries the enrichment fields (county, street address,
    closure type, first separation date) but NOT the submitted date shown in
    the public listing — its only date is "First Date of Separation". The
    live scraper stored these notices from the listing with
    ``notice_date = Submitted Date`` and ``city = zip = None``, and all of
    those fields feed ``notice_id`` — so take notice_date from the bundled
    listing (keyed by GA WARN ID) and leave city/zip unset. The upsert then
    COALESCE-fills the richer fields onto the existing rows instead of
    minting duplicates.
    """
    soup = BeautifulSoup(raw, "html.parser")

    # Label → value pairs from the GravityView detail table; first occurrence
    # wins (Zip Code appears twice). Mirrors enrich_ga._parse_detail_fields.
    fields: dict[str, str] = {}
    for tr in soup.find_all("tr"):
        label_el = tr.find("span", class_="gv-field-label")
        td = tr.find("td")
        if not (label_el and td):
            continue
        label = label_el.get_text(strip=True)
        value = _text(td)
        if label and value and label not in fields:
            fields[label] = value

    ga_warn_id = as_str(fields.get("GA WARN ID"))
    employer = as_str(fields.get("Company Name"))
    if not ga_warn_id or not employer:
        raise ParseFailed("GA entry page: GA WARN ID or Company Name missing")

    listing = _listing_index().get(ga_warn_id)
    if listing is None or listing.notice_date is None:
        raise ParseFailed(
            f"GA entry page {ga_warn_id}: no submitted date in the bundled listing"
        )

    # Strip the "Map It" widget text appended to the address (as enrich_ga does).
    addr_raw = fields.get("Company Address")
    address = addr_raw.removesuffix("Map It").strip() or None if addr_raw else None

    return [
        NoticeRow(
            state="GA",
            employer=employer,
            notice_date=listing.notice_date,
            effective_date=as_date(fields.get("First Date of Separation")),
            # The page's total matches the listing's count on every bundled
            # entry (verified 2026-07-10); the listing is the fallback.
            layoff_count=as_int(fields.get("Total Number of Affected Employees"))
            or listing.layoff_count,
            closure_type=as_str(fields.get("Type of Layoff or Closure")),
            county=as_str(fields.get("County")),
            address=address,
            source_url=SOURCE_URL,
            raw_notice_url=listing.entry_url,
            extra={"ga_warn_id": ga_warn_id},
        )
    ]


register(GAScraper())
