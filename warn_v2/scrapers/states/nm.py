"""New Mexico WARN scraper.

Source: https://www.dws.state.nm.us/Rapid-Response
Data:   https://www.dws.state.nm.us/Portals/0/DM/Business/{year}_WARN.pdf

Schema (PDF, single page, live as of May 2026):
  NOTICE DATE | JOB SITE NAME | COUNTY NAME | WDA NAME |
  TOTAL LAYOFF NUMBER | LAYOFF DATE | RECEIVED DATE | CITY NAME

Annual PDF updated throughout the year. Falls back to the prior year if the
current-year PDF has no data rows.
"""
from __future__ import annotations

import io
from datetime import date
from urllib.parse import urljoin

import httpx
import pdfplumber
from bs4 import BeautifulSoup

from warn_v2.scrapers._helpers import as_date, as_int, as_str
from warn_v2.scrapers.base import NoticeRow, ParseFailed, ScrapeFailed
from warn_v2.scrapers.registry import register

_PAGE_URL = "https://www.dws.state.nm.us/Rapid-Response"
_PDF_TMPL = "https://www.dws.state.nm.us/Portals/0/DM/Business/{year}_WARN.pdf"

# A realistic browser User-Agent is required: the dws.state.nm.us WAF rejects
# requests whose UA looks automated (the old "warn-v2/0.1" token returned a
# 200 "The requested URL was rejected" stub instead of the PDF — 2026-06).
_UA = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/pdf,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}


def _pdf_url(year: int) -> str:
    return _PDF_TMPL.format(year=year)


def _discover_archive_pdf_urls() -> list[str]:
    """Discover per-year WARN PDF links from the Rapid-Response page (backfill).

    The hub links yearly PDFs back to 2016, but filenames vary by year
    (2018_WARN10042018.pdf, 2017_WARN_October_.pdf — verified 2026-06-12), so
    we scrape the anchors rather than templating the URL. Records before 2016
    are request-only (see docs/foia/nm.md).
    """
    try:
        r = httpx.get(_PAGE_URL, headers=_UA, timeout=60, follow_redirects=True)
        r.raise_for_status()
    except httpx.HTTPError as e:
        raise ScrapeFailed(f"GET {_PAGE_URL}: {e}") from e

    soup = BeautifulSoup(r.content, "html.parser")
    urls: list[str] = []
    for a in soup.find_all("a", href=True):
        href: str = a["href"]
        if "warn" not in href.lower() or not href.lower().endswith(".pdf"):
            continue
        full = href if href.startswith("http") else urljoin(str(r.url), href)
        if full not in urls:
            urls.append(full)
    return urls


class NMScraper:
    state = "NM"
    source_url = _pdf_url(date.today().year)
    expected_row_range = (1, 5_000)
    required_fields = frozenset({"employer", "notice_date"})

    def fetch(self) -> bytes:
        year = date.today().year
        for y in (year, year - 1):
            url = _pdf_url(y)
            try:
                r = httpx.get(url, headers=_UA, timeout=60, follow_redirects=True)
                r.raise_for_status()
                # Confirm it's a PDF with some data
                rows = self.parse(r.content)
                if rows:
                    return r.content
            except (httpx.HTTPError, ParseFailed):
                continue
        raise ScrapeFailed("NM: could not retrieve a PDF with WARN data")

    def parse(self, raw: bytes) -> list[NoticeRow]:
        try:
            pdf = pdfplumber.open(io.BytesIO(raw))
        except Exception as e:
            raise ParseFailed(f"NM PDF: could not open: {e}") from e

        with pdf:
            all_table_rows: list[list] = []
            header: list[str] | None = None
            for page in pdf.pages:
                t = page.extract_table()
                if not t:
                    continue
                if header is None:
                    raw_hdr = [str(c).strip().lower() if c else "" for c in t[0]]
                    raw_hdr = [" ".join(h.split()) for h in raw_hdr]
                    header = raw_hdr
                    all_table_rows.extend(t[1:])
                else:
                    all_table_rows.extend(t[1:])

        if header is None:
            raise ParseFailed("NM PDF: no table found")
        if "job site name" not in header:
            raise ParseFailed(f"NM PDF: unexpected header: {header[:5]}")

        col = {name: i for i, name in enumerate(header)}
        rows: list[NoticeRow] = []
        for raw_row in all_table_rows:
            employer = as_str(raw_row[col["job site name"]])
            if not employer:
                continue
            notice_date = as_date(raw_row[col["notice date"]])
            if notice_date is None:
                continue
            rows.append(
                NoticeRow(
                    state="NM",
                    employer=employer,
                    notice_date=notice_date,
                    effective_date=as_date(raw_row[col.get("layoff date", -1)])
                    if "layoff date" in col else None,
                    layoff_count=as_int(raw_row[col["total layoff number"]]),
                    county=as_str(raw_row[col["county name"]]),
                    city=as_str(raw_row[col["city name"]]),
                    source_url=_pdf_url(date.today().year),
                    extra={
                        "wda": as_str(raw_row[col.get("wda name", -1)]) or ""
                        if "wda name" in col else ""
                    },
                )
            )
        return rows


register(NMScraper())
