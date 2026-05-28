"""Illinois WARN scraper.

Source: https://www.illinoisworknet.com/LayoffRecovery/Pages/ArchivedWARNReports.aspx
Data:   Monthly Excel (.xlsx/.xls) files, one per calendar month.
        The archive page lists all available files; fetch() downloads the most
        recent one.

Excel columns (A-T, row 1 = header):
  COMPANY NAME | DBA | COMPANY ADDRESS | CITY, STATE, ZIP | UNION |
  BUMPING RIGHTS | LOCAL WORKFORCE AREA | REGION NUMBER | TYPE OF COMPANY |
  TYPE OF EVENT | WARN RECEIVED DATE | FIRST LAYOFF DATE |
  ENDING LAYOFF DATE | LAYOFF SCHEDULE | WORKERS AFFECTED | TYPE OF LAYOFF |
  EVENT CAUSES | CEJA RELATED | COUNTY | COMPANY NAICS

Dates in the Excel file are stored as Excel/Python datetime objects.
"""
from __future__ import annotations

import io
import re
from datetime import date, datetime

import httpx
import openpyxl
from bs4 import BeautifulSoup

from warn_v2.scrapers._helpers import as_int, as_str, zip_from
from warn_v2.scrapers.base import NoticeRow, ParseFailed, ScrapeFailed
from warn_v2.scrapers.registry import register

_ARCHIVE_URL = (
    "https://www.illinoisworknet.com/LayoffRecovery/Pages/ArchivedWARNReports.aspx"
)
_SOURCE_URL = _ARCHIVE_URL
_BASE_URL = "https://www.illinoisworknet.com"

_UA = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
    ),
    "Referer": _ARCHIVE_URL,
}

# Matches href containing MonthlyWARN or Monthly WARN (both .xlsx and .xls)
_XL_HREF_RE = re.compile(r"[Mm]onthly.?[Ww][Aa][Rr][Nn].*\.xlsx?", re.I)


def _discover_latest_url() -> str:
    """Scrape the archive page and return the URL of the most recent Excel file."""
    try:
        r = httpx.get(_ARCHIVE_URL, headers=_UA, timeout=30, follow_redirects=True)
        r.raise_for_status()
    except httpx.HTTPError as e:
        raise ScrapeFailed(f"IL: archive page fetch error: {e}") from e

    soup = BeautifulSoup(r.content, "lxml")
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if _XL_HREF_RE.search(href):
            # href may be a relative _layouts/download.aspx?SourceUrl=... wrapper
            # or a direct /DownloadPrint/... path
            if href.startswith("/_layouts"):
                m = re.search(r"SourceUrl=([^&]+)", href)
                if m:
                    return m.group(1)
            if href.startswith("http"):
                return href
            return _BASE_URL + href
    raise ScrapeFailed("IL: could not find monthly WARN Excel link on archive page")


def _as_date(val: object) -> date | None:
    """Convert an openpyxl cell value (datetime or None) to a date."""
    if val is None:
        return None
    if isinstance(val, datetime):
        return val.date()
    if isinstance(val, date):
        return val
    # fallback: try string
    from warn_v2.scrapers._helpers import as_date

    return as_date(str(val))


def _parse_city(city_state_zip: str | None) -> str | None:
    """Extract city from 'City, IL 60544' formatted strings."""
    if not city_state_zip:
        return None
    return city_state_zip.split(",")[0].strip() or None


class ILScraper:
    state = "IL"
    source_url = _SOURCE_URL
    expected_row_range = (1, 10_000)
    required_fields = frozenset({"employer", "notice_date"})

    def fetch(self) -> bytes:
        xl_url = _discover_latest_url()
        try:
            r = httpx.get(xl_url, headers=_UA, timeout=60, follow_redirects=True)
            r.raise_for_status()
            return r.content
        except httpx.HTTPError as e:
            raise ScrapeFailed(f"IL: GET {xl_url}: {e}") from e

    def parse(self, raw: bytes) -> list[NoticeRow]:
        try:
            wb = openpyxl.load_workbook(io.BytesIO(raw), data_only=True, read_only=True)
        except Exception as e:
            raise ParseFailed(f"IL Excel: could not open: {e}") from e

        ws = wb.active
        rows: list[NoticeRow] = []
        header: dict[str, int] = {}

        for row_idx, row in enumerate(ws.iter_rows(values_only=True)):
            # Build header map from first row
            if row_idx == 0:
                for col_idx, val in enumerate(row):
                    if val is not None:
                        key = " ".join(str(val).split()).upper().rstrip(":")
                        header[key] = col_idx
                continue

            current_row = row  # bind loop variable for closure

            def _col(name: str, _r: tuple = current_row) -> object:
                idx = header.get(name, -1)
                return _r[idx] if 0 <= idx < len(_r) else None

            employer_raw = _col("COMPANY NAME")
            if employer_raw is None:
                continue
            employer = " ".join(str(employer_raw).split())
            if not employer:
                continue

            notice_date = _as_date(_col("WARN RECEIVED DATE"))
            if notice_date is None:
                continue

            effective_date = _as_date(_col("FIRST LAYOFF DATE"))
            workers_raw = _col("WORKERS AFFECTED")
            layoff_count = as_int(workers_raw) if workers_raw is not None else None

            city_state_zip = as_str(_col("CITY, STATE, ZIP")) or None
            city = _parse_city(city_state_zip)
            zip_code = zip_from(city_state_zip)
            county = as_str(_col("COUNTY")) or None
            company_address = as_str(_col("COMPANY ADDRESS")) or None
            # Combine street + "City, State ZIP" into one mailing-address string.
            address_parts = [p for p in (company_address, city_state_zip) if p]
            address = ", ".join(address_parts) if address_parts else None
            closure_type = as_str(_col("TYPE OF EVENT")) or None
            layoff_type = as_str(_col("TYPE OF LAYOFF")) or None
            event_causes = as_str(_col("EVENT CAUSES")) or None
            naics_raw = _col("COMPANY NAICS")
            if isinstance(naics_raw, (int, float)):
                naics = str(int(naics_raw))
            else:
                naics = as_str(naics_raw) or None

            rows.append(
                NoticeRow(
                    state="IL",
                    employer=employer,
                    notice_date=notice_date,
                    effective_date=effective_date,
                    layoff_count=layoff_count,
                    city=city,
                    county=county,
                    zip=zip_code,
                    address=address,
                    closure_type=closure_type,
                    source_url=_SOURCE_URL,
                    extra={
                        "layoff_type": layoff_type,
                        "event_causes": event_causes,
                        "naics": naics,
                        "workforce_area": as_str(_col("LOCAL WORKFORCE AREA")) or None,
                    },
                )
            )

        wb.close()

        if not rows:
            raise ParseFailed("IL Excel: no data rows found")
        return rows


register(ILScraper())
