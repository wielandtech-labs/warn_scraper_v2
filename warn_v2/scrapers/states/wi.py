"""Wisconsin WARN scraper.

Source: https://dwd.wisconsin.gov/dislocatedworker/warn/
Data:   Google Sheets (public key locked to dwd.wisconsin.gov Referer).

The WARN listing page renders its data via JavaScript that calls the
Google Sheets API:
  https://sheets.googleapis.com/v4/spreadsheets/{SHEET_ID}/values/Originals
    ?key={API_KEY}

The API key is embedded in Keys.js on the DWD site and is restricted to
requests that carry `Referer: https://dwd.wisconsin.gov/dislocatedworker/warn/`.

Google Sheets columns (Originals sheet):
  PK | FK | PDF | Company | City | AffectedWorkers | NoticeRcvd |
  NoticeType | LayoffBeginDate | NAICSDescription | County | WDA | HasUpdates

NoticeRcvd:     YYYYMMDD  (e.g. "20260130")
LayoffBeginDate: M/D/YYYY  (e.g. "3/31/2026")
NoticeType:     "CL" = Facility Closure, "WR" = Workforce Reduction
Company:        may contain HTML tags/entities (stripped before use)
PDF:            key used to build the notice PDF URL:
                https://dwd.wisconsin.gov/dislocatedworker/warn/{year}/{pdf}.pdf
"""
from __future__ import annotations

import html
import json
import re

import httpx

from warn_v2.scrapers._helpers import as_date, as_int, as_str
from warn_v2.scrapers.base import NoticeRow, ParseFailed, ScrapeFailed
from warn_v2.scrapers.registry import register

_SOURCE_URL = "https://dwd.wisconsin.gov/dislocatedworker/warn/"
_SHEET_ID = "1cyZiHZcepBI7ShB3dMcRprUFRG24lbwEnEDRBMhAqsA"
_API_KEY = "AIzaSyB__fZmuycL7IedOivEHYtBobCo-ehze4k"
_SHEETS_URL = (
    f"https://sheets.googleapis.com/v4/spreadsheets/{_SHEET_ID}"
    f"/values/Originals?key={_API_KEY}"
)
_PDF_BASE = "https://dwd.wisconsin.gov/dislocatedworker/warn"

_HDRS = {
    # The Google API key is restricted to this Referer origin.
    "Referer": "https://dwd.wisconsin.gov/dislocatedworker/warn/",
    "Origin": "https://dwd.wisconsin.gov",
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
    ),
}

_HTML_TAG_RE = re.compile(r"<[^>]+>")
_YYYYMMDD_RE = re.compile(r"^\d{8}$")


def _strip_html(text: str) -> str:
    """Remove HTML tags and unescape entities from a cell value."""
    cleaned = _HTML_TAG_RE.sub(" ", text or "")
    cleaned = html.unescape(cleaned)
    return " ".join(cleaned.split())


def _parse_yyyymmdd(raw: str) -> object:
    """Parse a compact YYYYMMDD string to a date, or None."""
    if not _YYYYMMDD_RE.match(raw or ""):
        return None
    return as_date(f"{raw[:4]}-{raw[4:6]}-{raw[6:]}")


def _pdf_url(pdf_key: str, notice_rcvd: str) -> str | None:
    """Build the DWD notice PDF URL from the PDF key and receipt date."""
    if not pdf_key or not _YYYYMMDD_RE.match(notice_rcvd or ""):
        return None
    year = notice_rcvd[:4]
    return f"{_PDF_BASE}/{year}/{pdf_key}.pdf"


class WIScraper:
    state = "WI"
    source_url = _SOURCE_URL
    expected_row_range = (50, 10_000)
    required_fields = frozenset({"employer", "notice_date"})

    def fetch(self) -> bytes:
        try:
            r = httpx.get(_SHEETS_URL, headers=_HDRS, timeout=30)
            r.raise_for_status()
            return r.content
        except httpx.HTTPError as e:
            raise ScrapeFailed(f"WI Sheets API: {e}") from e

    def parse(self, raw: bytes) -> list[NoticeRow]:
        try:
            data = json.loads(raw)
        except Exception as e:
            raise ParseFailed(f"WI: JSON decode error: {e}") from e

        values = data.get("values", [])
        if len(values) < 2:
            raise ParseFailed("WI: no data rows in Sheets response")

        header = values[0]
        col = {name: i for i, name in enumerate(header)}

        def _cell(row: list, name: str) -> str:
            idx = col.get(name, -1)
            if idx < 0 or idx >= len(row):
                return ""
            return str(row[idx]).strip()

        rows: list[NoticeRow] = []
        for raw_row in values[1:]:
            employer = _strip_html(_cell(raw_row, "Company"))
            if not employer:
                continue

            notice_rcvd = _cell(raw_row, "NoticeRcvd")
            notice_date = _parse_yyyymmdd(notice_rcvd)
            if notice_date is None:
                continue

            effective_date = as_date(_cell(raw_row, "LayoffBeginDate"))

            count_raw = _cell(raw_row, "AffectedWorkers")
            layoff_count = as_int(count_raw) if count_raw.isdigit() else None

            pdf_key = _cell(raw_row, "PDF")
            notice_url = _pdf_url(pdf_key, notice_rcvd)

            notice_type = _cell(raw_row, "NoticeType")
            # Map abbreviated codes to human-readable closure type
            closure_type = as_str(notice_type) or None

            extra: dict[str, str] = {
                "wda": _cell(raw_row, "WDA"),
                "naics_description": _cell(raw_row, "NAICSDescription"),
                "notice_type_code": notice_type,
            }
            # "Y" when a WI notice has had at least one amendment filed.
            has_updates = _cell(raw_row, "HasUpdates")
            if has_updates:
                extra["has_updates"] = has_updates

            rows.append(
                NoticeRow(
                    state="WI",
                    employer=employer,
                    notice_date=notice_date,
                    effective_date=effective_date,
                    layoff_count=layoff_count,
                    city=as_str(_cell(raw_row, "City")) or None,
                    county=as_str(_cell(raw_row, "County")) or None,
                    closure_type=closure_type,
                    raw_notice_url=notice_url,
                    source_url=_SOURCE_URL,
                    extra=extra,
                )
            )
        return rows


register(WIScraper())
