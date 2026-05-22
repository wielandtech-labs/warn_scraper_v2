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

import httpx
import pdfplumber

from warn_v2.scrapers._helpers import as_date, as_int, as_str
from warn_v2.scrapers.base import NoticeRow, ParseFailed, ScrapeFailed
from warn_v2.scrapers.registry import register

_PAGE_URL = "https://www.dws.state.nm.us/Rapid-Response"
_PDF_TMPL = "https://www.dws.state.nm.us/Portals/0/DM/Business/{year}_WARN.pdf"

_UA = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) warn-v2/0.1"
    )
}


def _pdf_url(year: int) -> str:
    return _PDF_TMPL.format(year=year)


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
