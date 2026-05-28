"""South Carolina WARN scraper.

Source: https://dew.sc.gov/employers/employer-resources
Data:   Cumulative YTD PDF; URL discovered from the landing page.

Schema (as of May 2026):
  Company | County | Notice Date | Layoff/Closure Date | Impacted |
  Layoff/Closure | Address

The last row on page 0 is a "Total WARN: N  NNNN" summary row; we skip it.
Page 1 is a county-level summary table with a different schema; we skip it.

One edge case: when a company's county value is "Statewide - Multiple Counties",
pdfplumber's column detection merges part of that text with the adjacent Notice
Date column.  We handle this by stripping alpha characters from the garbled
Notice Date cell and re-parsing the remaining digits.
"""
from __future__ import annotations

import io
import re

import httpx
import pdfplumber
from bs4 import BeautifulSoup

from warn_v2.scrapers._helpers import as_date, as_int, as_str
from warn_v2.scrapers.base import NoticeRow, ParseFailed, ScrapeFailed
from warn_v2.scrapers.registry import register

_LANDING_URL = "https://dew.sc.gov/employers/employer-resources"
_FALLBACK_URL = (
    "https://dew.sc.gov/sites/dew/files/Documents/"
    "2026%20South%20Carolina%20WARN_Report%2005132026.pdf"
)

_UA = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) warn-v2/0.1"
    )
}

_ZIP_RE = re.compile(r"\b(\d{5})(?:-\d{4})?\s*$")
_ALPHA_RE = re.compile(r"[A-Za-z]")


def _discover_pdf_url() -> str:
    try:
        r = httpx.get(_LANDING_URL, headers=_UA, timeout=30, follow_redirects=True)
        r.raise_for_status()
        soup = BeautifulSoup(r.content, "html.parser")
        for a in soup.find_all("a", href=True):
            href: str = a["href"]
            if "WARN_Report" in href:
                if href.startswith("/"):
                    href = "https://dew.sc.gov" + href
                return href
    except httpx.HTTPError:
        pass
    return _FALLBACK_URL


def _normalize_header(cell: object) -> str:
    if cell is None:
        return ""
    return " ".join(str(cell).lower().split())


def _extract_date_from_cell(cell_text: str) -> object:
    """Parse a date cell that may contain garbled interleaved text.

    When pdfplumber merges adjacent columns, date digits are interspersed with
    letters.  We strip alpha chars and try again.
    """
    if not cell_text:
        return None
    # Take the first date in a range like "5/1/2026 - 12/31/2026"
    first = cell_text.split(" - ")[0].strip()
    d = as_date(first)
    if d is not None:
        return d
    # Fallback: strip letters (handles merged county+date column)
    clean = _ALPHA_RE.sub("", first).strip()
    return as_date(clean) if clean else None


def _city_zip_from_address(address: str) -> tuple[str | None, str | None]:
    """Extract city and ZIP from a US address string."""
    m = _ZIP_RE.search(address)
    zip_code = m.group(1) if m else None
    # City is the last comma-delimited segment before state abbreviation
    parts = [p.strip() for p in address.split(",")]
    if len(parts) >= 2:
        # parts[-1] is "SC XXXXX", parts[-2] is city
        city = parts[-2].strip() or None
    else:
        city = None
    return city, zip_code


class SCScraper:
    state = "SC"
    source_url = _LANDING_URL
    expected_row_range = (5, 5_000)
    required_fields = frozenset({"employer", "notice_date"})

    def fetch(self) -> bytes:
        pdf_url = _discover_pdf_url()
        try:
            r = httpx.get(pdf_url, headers=_UA, timeout=60, follow_redirects=True)
            r.raise_for_status()
            return r.content
        except httpx.HTTPError as e:
            raise ScrapeFailed(f"GET {pdf_url}: {e}") from e

    def parse(self, raw: bytes) -> list[NoticeRow]:
        try:
            pdf = pdfplumber.open(io.BytesIO(raw))
        except Exception as e:
            raise ParseFailed(f"SC PDF: could not open: {e}") from e

        with pdf:
            all_rows: list[list] = []
            header: list[str] | None = None
            for page in pdf.pages:
                t = page.extract_table()
                if not t:
                    continue
                page_header = [_normalize_header(c) for c in t[0]]
                # Only process the main notice table (has "company" and "impacted")
                if "company" not in page_header or "impacted" not in page_header:
                    continue
                if header is None:
                    header = page_header
                all_rows.extend(t[1:])

        if header is None:
            raise ParseFailed("SC PDF: no notice table found")

        col = {name: i for i, name in enumerate(header)}
        rows: list[NoticeRow] = []
        for raw_row in all_rows:
            employer = as_str(raw_row[col["company"]])
            if not employer or employer.lower().startswith("total"):
                continue

            notice_date = _extract_date_from_cell(
                as_str(raw_row[col["notice date"]]) or ""
            )
            if notice_date is None:
                continue

            effective_raw = as_str(raw_row[col.get("layoff/closure date", -1)]) or ""
            effective_date = (
                as_date(effective_raw.split(" - ")[0].strip()) if effective_raw else None
            )

            count_raw = as_str(raw_row[col.get("impacted", -1)]) or ""
            count_m = re.search(r"\d+", count_raw)
            layoff_count = as_int(count_m.group()) if count_m else None

            closure_type = as_str(raw_row[col.get("layoff/closure", -1)])
            county = as_str(raw_row[col.get("county", -1)])
            address = as_str(raw_row[col.get("address", -1)]) or ""
            city, zip_code = _city_zip_from_address(address)

            rows.append(
                NoticeRow(
                    state="SC",
                    employer=employer,
                    notice_date=notice_date,
                    effective_date=effective_date,
                    layoff_count=layoff_count,
                    closure_type=closure_type,
                    city=city,
                    county=county,
                    zip=zip_code,
                    address=as_str(address),
                    source_url=_LANDING_URL,
                )
            )
        return rows


register(SCScraper())
