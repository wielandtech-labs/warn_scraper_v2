"""Mississippi WARN scraper.

Source: https://mdes.ms.gov/information-center/warn-information/
Data:   Quarterly PDF reports; one PDF per quarter.

Schema (as of early 2026):
  Date of Notice | Company Name | City | County | Workforce Area |
  Event Number | NAICS CODE & Description | (merged cols) |
  Type of Action | Number Affected | Date of Action | Reason/Comments

fetch() discovers all quarterly PDF URLs from the landing page and downloads
the most recent one.  Each quarterly PDF covers roughly three months of
notices (15-30 rows).

Multi-line cells (Company Name, Workforce Area, etc.) are joined with a space.
Continuation rows where col 0 is None are skipped.
The Date of Action field occasionally uses "." instead of "/" as the separator
(e.g. "4/3.2026"); we normalise that before parsing.
"""
from __future__ import annotations

import io
import re

import httpx
import pdfplumber
from bs4 import BeautifulSoup

from warn_v2.scrapers._helpers import as_date, as_str
from warn_v2.scrapers.base import NoticeRow, ParseFailed, ScrapeFailed
from warn_v2.scrapers.registry import register

_LANDING_URL = "https://mdes.ms.gov/information-center/warn-information/"
_BASE_URL = "https://mdes.ms.gov"
_FALLBACK_URL = (
    "https://mdes.ms.gov/media/502986/warn-py2025-qtr-3-jan-mar-2026.pdf"
)

_UA = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) warn-v2/0.1"
    )
}

_PDF_HREF = re.compile(r"/media/\d+/warn[^\"']*\.pdf", re.I)
_LEADING_INT = re.compile(r"\d+")


def _discover_pdf_urls() -> list[str]:
    """Return all quarterly WARN PDF URLs from the landing page (most-recent first)."""
    try:
        r = httpx.get(_LANDING_URL, headers=_UA, timeout=30, follow_redirects=True)
        r.raise_for_status()
        soup = BeautifulSoup(r.content, "html.parser")
        urls: list[str] = []
        for a in soup.find_all("a", href=True):
            href: str = a["href"]
            if _PDF_HREF.match(href):
                url = href if href.startswith("http") else _BASE_URL + href
                if url not in urls:
                    urls.append(url)
        return urls or [_FALLBACK_URL]
    except httpx.HTTPError:
        return [_FALLBACK_URL]


def _normalize_cell(value: object) -> str:
    """Join multi-line cell values with a space; return empty string for None."""
    if value is None:
        return ""
    return " ".join(str(value).split())


def _normalize_date(raw: str) -> object:
    """Parse a date string, tolerating '.' used as separator instead of '/'."""
    cleaned = raw.strip()
    # Replace lone dots used as date separators: "4/3.2026" -> "4/3/2026"
    cleaned = re.sub(r"(\d)\.", r"\1/", cleaned)
    return as_date(cleaned)


def _parse_pdf(raw: bytes) -> list[NoticeRow]:
    try:
        pdf = pdfplumber.open(io.BytesIO(raw))
    except Exception as e:
        raise ParseFailed(f"MS PDF: could not open: {e}") from e

    with pdf:
        header: list[str] | None = None
        col: dict[str, int] = {}
        data_rows: list[list] = []

        for page in pdf.pages:
            t = page.extract_table()
            if not t:
                continue
            page_hdr = [" ".join(str(c).lower().split()) if c else "" for c in t[0]]
            if "company name" not in page_hdr or "type of action" not in page_hdr:
                continue
            if header is None:
                header = page_hdr
                col = {name: i for i, name in enumerate(header)}
            # Skip header row, add only non-continuation rows
            for row in t[1:]:
                if row[0] is None:
                    continue
                data_rows.append(row)

    if header is None:
        raise ParseFailed("MS PDF: no notice table found")

    rows: list[NoticeRow] = []
    for raw_row in data_rows:
        employer = _normalize_cell(raw_row[col.get("company name", 1)])
        if not employer or employer.lower().startswith("date of"):
            continue

        notice_date = _normalize_date(_normalize_cell(raw_row[col.get("date of notice", 0)]))
        if notice_date is None:
            continue

        eff_raw = _normalize_cell(raw_row[col.get("date of action", 11)])
        effective_date = _normalize_date(eff_raw) if eff_raw else None

        count_raw = _normalize_cell(raw_row[col.get("number affected", 10)])
        m = _LEADING_INT.search(count_raw)
        layoff_count = int(m.group()) if m else None

        closure_type = as_str(_normalize_cell(raw_row[col.get("type of action", 9)]))
        city = as_str(_normalize_cell(raw_row[col.get("city", 2)]))
        county = as_str(_normalize_cell(raw_row[col.get("county", 3)]))
        wda = _normalize_cell(raw_row[col.get("workforce area", 4)])

        rows.append(
            NoticeRow(
                state="MS",
                employer=employer,
                notice_date=notice_date,
                effective_date=effective_date,
                layoff_count=layoff_count,
                closure_type=closure_type,
                city=city,
                county=county,
                source_url=_LANDING_URL,
                extra={"wda": wda} if wda else {},
            )
        )
    return rows


class MSScraper:
    state = "MS"
    source_url = _LANDING_URL
    expected_row_range = (1, 5_000)
    required_fields = frozenset({"employer", "notice_date"})

    def fetch(self) -> bytes:
        urls = _discover_pdf_urls()
        pdf_url = urls[0] if urls else _FALLBACK_URL
        try:
            r = httpx.get(pdf_url, headers=_UA, timeout=60, follow_redirects=True)
            r.raise_for_status()
            return r.content
        except httpx.HTTPError as e:
            raise ScrapeFailed(f"GET {pdf_url}: {e}") from e

    def parse(self, raw: bytes) -> list[NoticeRow]:
        return _parse_pdf(raw)


register(MSScraper())
