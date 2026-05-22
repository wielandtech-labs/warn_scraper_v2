"""Idaho WARN scraper.

Source: https://www.labor.idaho.gov/businesses/layoff-assistance/
Data:   PDF discovered dynamically from the landing page

Schema (cumulative multi-page PDF, live as of May 2026):
  Date of Letter | Updates | Company | Address | City | State | Zip |
  No. of Employees Affected | Effective or Commencing Date

The PDF is cumulative (all years since ~2009); the URL is date-stamped and
changes each time the state updates it. fetch() discovers the current URL by
parsing the landing page. Each PDF page repeats the header row; we skip it.
Multi-line cell values (multiple locations) use the first line. Affected count
can include non-numeric suffixes like "(2 in ID)"; we extract the leading int.
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

_LANDING_URL = "https://www.labor.idaho.gov/businesses/layoff-assistance/"
_FALLBACK_URL = (
    "https://www.labor.idaho.gov/wp-content/uploads/2026/04/Idaho-WARN-notices.pdf"
)

_UA = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) warn-v2/0.1"
    )
}

_LEADING_INT = re.compile(r"\d+")


def _discover_pdf_url() -> str:
    try:
        r = httpx.get(_LANDING_URL, headers=_UA, timeout=30, follow_redirects=True)
        r.raise_for_status()
        soup = BeautifulSoup(r.content, "html.parser")
        for a in soup.find_all("a", href=True):
            href = a["href"]
            if "Idaho-WARN" in href or "WARN_Notices_Idaho" in href:
                return href
    except httpx.HTTPError:
        pass
    return _FALLBACK_URL


class IDScraper:
    state = "ID"
    source_url = _LANDING_URL
    expected_row_range = (10, 10_000)
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
            raise ParseFailed(f"ID PDF: could not open: {e}") from e

        with pdf:
            all_data_rows: list[list] = []
            header: list[str] | None = None
            for page in pdf.pages:
                t = page.extract_table()
                if not t:
                    continue
                # Header repeats on every page — always skip row 0
                if header is None:
                    raw_hdr = [str(c).strip().lower() if c else "" for c in t[0]]
                    header = [" ".join(h.split()) for h in raw_hdr]
                all_data_rows.extend(t[1:])

        if header is None:
            raise ParseFailed("ID PDF: no table found")
        if "company" not in header:
            raise ParseFailed(f"ID PDF: unexpected header: {header[:5]}")

        col = {name: i for i, name in enumerate(header)}
        rows: list[NoticeRow] = []
        for raw_row in all_data_rows:
            employer = _first_line(raw_row[col["company"]])
            if not employer:
                continue
            notice_date = as_date(_first_line(raw_row[col["date of letter"]]))
            if notice_date is None:
                continue

            count_raw = _first_line(raw_row[col.get("no. of employees affected", -1)])
            m = _LEADING_INT.search(count_raw) if count_raw else None
            layoff_count = int(m.group()) if m else None

            eff_raw = _first_line(
                raw_row[col.get("effective or commencing date", -1)]
            )

            rows.append(
                NoticeRow(
                    state="ID",
                    employer=employer,
                    notice_date=notice_date,
                    effective_date=as_date(eff_raw) if eff_raw else None,
                    layoff_count=layoff_count,
                    city=as_str(_first_line(raw_row[col["city"]])),
                    zip=as_str(_first_line(raw_row[col["zip"]])),
                    source_url=_LANDING_URL,
                    extra={
                        "address": as_str(_first_line(raw_row[col["address"]])) or ""
                    },
                )
            )
        return rows


def _first_line(value) -> str:
    if value is None:
        return ""
    return str(value).split("\n")[0].strip()


register(IDScraper())
