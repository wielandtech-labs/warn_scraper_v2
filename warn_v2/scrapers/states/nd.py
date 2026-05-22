"""North Dakota WARN scraper.

Source: https://www.jobsnd.com/employers/warn-notices
Data:   Single cumulative PDF (2015 to present) at a stable URL.

Schema (as of 2026):
  Company Name | Location | WARN Dated | Date of Layoff/Closure |
  Number Laid Off/Affected | Notes

Older entries (pre-2023) have separate WARN Dated and Date of Layoff/Closure
columns.  Newer entries consolidate both dates into the WARN Dated cell (e.g.
"1/15/2026 1/28/2026") while the Layoff/Closure column is blank.

The PDF has two pages.  Page 1 has a proper header row; page 2 starts
directly with data (no header repeat).
"""
from __future__ import annotations

import io
import re

import httpx
import pdfplumber

from warn_v2.scrapers._helpers import as_date, as_str
from warn_v2.scrapers.base import NoticeRow, ParseFailed, ScrapeFailed
from warn_v2.scrapers.registry import register

_PDF_URL = (
    "https://jobsnd.com/sites/www/files/documents/jsnd-documents/"
    "WARN%20Notices%202015%20to%20present.pdf"
)
_SOURCE_URL = "https://www.jobsnd.com/employers/warn-notices"

_UA = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) warn-v2/0.1"
    )
}

_DATE_RE = re.compile(r"\d{1,2}/\d{1,2}/\d{4}")
_COUNT_RE = re.compile(r"[\d,]+")


def _extract_dates(warn_dated_cell: str) -> tuple[object, object]:
    """Return (notice_date, effective_date) from a potentially merged date cell.

    Newer entries contain two dates in one cell: "1/15/2026 1/28/2026".
    Older entries have a single date here and a separate effective-date column.
    """
    dates = _DATE_RE.findall(warn_dated_cell or "")
    notice = as_date(dates[0]) if dates else None
    effective = as_date(dates[1]) if len(dates) >= 2 else None
    return notice, effective


def _extract_count(raw: str) -> int | None:
    """Extract leading integer from messy count strings like '25+' or '670'."""
    m = _COUNT_RE.search(raw or "")
    if not m:
        return None
    try:
        return int(m.group().replace(",", ""))
    except ValueError:
        return None


def _extract_city(location: str) -> str | None:
    """Extract city from location strings like 'Fargo, ND' or 'Nationwide'."""
    if not location:
        return None
    # "City, ST" → city
    if "," in location:
        return location.split(",")[0].strip() or None
    return location.strip() or None


class NDScraper:
    state = "ND"
    source_url = _SOURCE_URL
    expected_row_range = (10, 10_000)
    required_fields = frozenset({"employer", "notice_date"})

    def fetch(self) -> bytes:
        try:
            r = httpx.get(_PDF_URL, headers=_UA, timeout=60, follow_redirects=True)
            r.raise_for_status()
            return r.content
        except httpx.HTTPError as e:
            raise ScrapeFailed(f"GET {_PDF_URL}: {e}") from e

    def parse(self, raw: bytes) -> list[NoticeRow]:
        try:
            pdf = pdfplumber.open(io.BytesIO(raw))
        except Exception as e:
            raise ParseFailed(f"ND PDF: could not open: {e}") from e

        all_data_rows: list[list] = []
        header: list[str] | None = None

        with pdf:
            for page in pdf.pages:
                t = page.extract_table()
                if not t:
                    continue
                # Detect header row: first row contains "Company" in col 0
                row0_text = str(t[0][0] or "").lower()
                if "company" in row0_text:
                    if header is None:
                        header = [" ".join(str(c or "").lower().split()) for c in t[0]]
                    all_data_rows.extend(t[1:])
                else:
                    # Page 2: no header repeat — all rows are data
                    all_data_rows.extend(t)

        if header is None:
            raise ParseFailed("ND PDF: no notice table found")

        col = {name: i for i, name in enumerate(header)}
        eff_col = col.get("date of layoff/closure", -1)
        count_col = col.get("number laid off/affected", -1)
        notes_col = col.get("notes", -1)

        rows: list[NoticeRow] = []
        for raw_row in all_data_rows:
            employer = as_str(raw_row[col.get("company name", 0)])
            if not employer:
                continue

            warn_dated = as_str(raw_row[col.get("warn dated", 2)]) or ""
            notice_date, merged_effective = _extract_dates(warn_dated)
            if notice_date is None:
                continue

            # Prefer the merged effective date; fall back to the dedicated column
            if merged_effective is not None:
                effective_date = merged_effective
            else:
                eff_raw = as_str(raw_row[eff_col]) if eff_col >= 0 else ""
                m = _DATE_RE.search(eff_raw or "")
                effective_date = as_date(m.group()) if m else None

            location = as_str(raw_row[col.get("location", 1)]) or ""
            city = _extract_city(location)

            count_raw = as_str(raw_row[count_col]) if count_col >= 0 else ""
            layoff_count = _extract_count(count_raw)

            notes = as_str(raw_row[notes_col]) if notes_col >= 0 else ""

            rows.append(
                NoticeRow(
                    state="ND",
                    employer=employer,
                    notice_date=notice_date,
                    effective_date=effective_date,
                    layoff_count=layoff_count,
                    city=city,
                    source_url=_SOURCE_URL,
                    extra={"location": location, "notes": notes or ""},
                )
            )
        return rows


register(NDScraper())
