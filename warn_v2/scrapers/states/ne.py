"""Nebraska WARN scraper.

Source: https://dol.nebraska.gov/ReemploymentServices/LayoffServices/LayoffsAndDownsizingWARN

Schema (live as of May 2026):
  Date | Company | Jobs Affected | Location

Static HTML table; company cell has an anchor linking to the individual
notice document at /webdocs/getfile/<uuid>.
"""
from __future__ import annotations

import re
from pathlib import Path

import httpx
from bs4 import BeautifulSoup

from warn_v2.scrapers._helpers import as_date, as_int, as_str, norm
from warn_v2.scrapers.base import NoticeRow, ParseFailed, ScrapeFailed
from warn_v2.scrapers.bundled import load_archive
from warn_v2.scrapers.registry import register

SOURCE_URL = (
    "https://dol.nebraska.gov/ReemploymentServices/LayoffServices/LayoffsAndDownsizingWARN"
)
_BASE_URL = "https://dol.nebraska.gov"

_UA = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) warn-v2/0.1"
    )
}


class NEScraper:
    state = "NE"
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
        return _parse_ne_table(raw, SOURCE_URL)


def _parse_ne_table(raw: bytes, source_url: str) -> list[NoticeRow]:
    soup = BeautifulSoup(raw, "html.parser")
    table = soup.find("table")
    if table is None:
        raise ParseFailed("no <table> found on NE WARN page")

    all_trs = table.find_all("tr")
    if not all_trs:
        raise ParseFailed("NE table has no rows")

    # The live page's first row is the column header; the legacy per-year
    # report fragments prepend banner rows ("WARN Report" / "{Y} Events as
    # of ...") — scan for the row that names Company.
    header_idx: int | None = None
    header_cells: list[str] = []
    for i, tr in enumerate(all_trs):
        cells = [_text(td).lower() for td in tr.find_all(["td", "th"])]
        if "company" in cells:
            header_idx, header_cells = i, cells
            break
    if header_idx is None:
        raise ParseFailed("no NE header row naming 'company' found")
    col = {name: i for i, name in enumerate(header_cells)}

    rows: list[NoticeRow] = []
    for tr in all_trs[header_idx + 1 :]:
        cells = tr.find_all(["td", "th"])
        if len(cells) < 3:
            continue

        company_cell = cells[col["company"]]
        anchor = company_cell.find("a")
        employer = as_str(_text(anchor) if anchor else _text(company_cell))
        if not employer:
            continue
        notice_date = as_date(_text(cells[col["date"]]))
        if notice_date is None:
            continue

        notice_url: str | None = None
        if anchor and anchor.get("href"):
            href = anchor["href"]
            notice_url = href if href.startswith("http") else _BASE_URL + href

        # Live schema has only Location (which holds the city); the legacy
        # per-year fragments add a City column, with Location carrying the
        # worksite detail ("Omaha Distribution Center"). Keep the clean city
        # and stash a distinct Location in address so same-employer/date/city
        # worksite pairs merge with summed counts (_merge_worksite_rows).
        location = as_str(_text(cells[col["location"]]))
        address: str | None = None
        if "city" in col:
            city = as_str(_text(cells[col["city"]]))
            if location and norm(location) != norm(city or ""):
                address = location
        else:
            city = location

        raw_count = _text(cells[col["jobs affected"]]).replace(",", "")
        rows.append(
            NoticeRow(
                state="NE",
                employer=employer,
                notice_date=notice_date,
                layoff_count=as_int(raw_count),
                city=city,
                address=address,
                raw_notice_url=notice_url,
                source_url=source_url,
            )
        )
    return rows


def _text(cell) -> str:
    return " ".join(cell.get_text(" ", strip=True).replace("\xa0", " ").split())


register(NEScraper())


# ---------------------------------------------------------------------------
# Historical backfill: the frozen legacy per-year endpoint (Mode 3b)
# ---------------------------------------------------------------------------
# dol.nebraska.gov/LayoffServices/WARNReportData/?year={Y} still serves the
# 2010-2020 per-year report fragments (same table plus a City column, banner
# rows before the header). Snapshotted 2026-07-10 and bundled as
# warn_v2/scrapers/data/ne_archive.tar.gz. 2021-2022 exist only in Wayback
# captures of the rolling live page — not bundled here.

_ARCHIVE_TGZ = Path(__file__).resolve().parent.parent / "data" / "ne_archive.tar.gz"
_ARCHIVE_URL = "https://dol.nebraska.gov/LayoffServices/WARNReportData/?year={year}"
_YEAR_RE = re.compile(r"\d{4}")


def ne_archive_files() -> list[tuple[str, bytes]]:
    """(member_name, bytes) for each bundled warnreportdata_<year>.html."""
    return load_archive(_ARCHIVE_TGZ)


def parse_ne_archive(raw: bytes, member_name: str) -> list[NoticeRow]:
    """Parse one bundled legacy fragment, stamping its per-year source URL."""
    m = _YEAR_RE.search(member_name)
    source_url = _ARCHIVE_URL.format(year=m.group()) if m else SOURCE_URL
    return _parse_ne_table(raw, source_url)
