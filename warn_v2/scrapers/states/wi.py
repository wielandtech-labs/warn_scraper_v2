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


# ---------------------------------------------------------------------------
# Historical backfill (2016-2019)
#
# The Google Sheet behind the live scraper is cumulative from 2020-01 only.
# Older years are static HTML pages at /dislocatedworker/warn/{year}/default.htm
# (verified 2016-2019), one small table per notice with the same columns as the
# sheet: Company | City | Affected Workers | Notice Received | Original Notice
# Type | Layoff Begin Date | County | Workforce Development Area.
# ---------------------------------------------------------------------------

_ARCHIVE_FIRST_YEAR = 2016
_ARCHIVE_LAST_YEAR = 2019  # 2020+ is in the cumulative Sheet the live scraper reads

_MDY_RE = re.compile(r"\b\d{1,2}/\d{1,2}/\d{4}\b")


def _archive_url(year: int) -> str:
    return f"https://dwd.wisconsin.gov/dislocatedworker/warn/{year}/default.htm"


def _fetch_wi_archive_year(year: int) -> bytes | None:
    """Fetch one static archive-year page; None outside the 2016-2019 era."""
    if not (_ARCHIVE_FIRST_YEAR <= year <= _ARCHIVE_LAST_YEAR):
        return None
    url = _archive_url(year)
    try:
        r = httpx.get(url, headers=_HDRS, timeout=60, follow_redirects=True)
        if r.status_code == 404:
            return None
        r.raise_for_status()
        return r.content
    except httpx.HTTPError as e:
        raise ScrapeFailed(f"GET {url}: {e}") from e


def parse_wi_archive_html(raw: bytes, year: int) -> list[NoticeRow]:
    """Parse a 2016-2019 static archive page (one table per notice)."""
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(raw, "html.parser")
    tables = soup.find_all("table")
    if not tables:
        raise ParseFailed(f"WI {year}: no tables on archive page")

    source_url = _archive_url(year)
    rows: list[NoticeRow] = []
    for table in tables:
        trs = table.find_all("tr")
        if len(trs) < 2:
            continue
        header = [
            " ".join(c.get_text(" ", strip=True).split()).lower()
            for c in trs[0].find_all(["th", "td"])
        ]
        col = {name: i for i, name in enumerate(header)}

        def _idx(*needles: str, _col=col) -> int | None:
            return next(
                (i for name, i in _col.items() if any(n in name for n in needles)),
                None,
            )

        i_company = _idx("company")
        i_notice = _idx("notice received", "noticercvd")
        if i_company is None or i_notice is None:
            continue  # layout/navigation table, not a notice table
        i_city = _idx("city")
        i_count = _idx("affected workers")
        i_type = _idx("notice type")
        i_begin = _idx("layoff begin")
        i_county = _idx("county")
        i_wda = _idx("workforce development")

        for tr in trs[1:]:
            cells = [
                " ".join(c.get_text(" ", strip=True).split())
                for c in tr.find_all(["td", "th"])
            ]

            def _cell(i: int | None, _cells=cells) -> str:
                return _cells[i] if i is not None and i < len(_cells) else ""

            employer = as_str(_strip_html(_cell(i_company)))
            if not employer:
                continue
            notice_date = as_date(_cell(i_notice))
            if notice_date is None:
                continue

            # The begin-date cell sometimes glues the NAICS description after
            # the date — take just the leading M/D/YYYY token.
            begin_match = _MDY_RE.search(_cell(i_begin))
            effective_date = as_date(begin_match.group(0)) if begin_match else None

            count_raw = _cell(i_count)
            rows.append(
                NoticeRow(
                    state="WI",
                    employer=employer,
                    notice_date=notice_date,
                    effective_date=effective_date,
                    layoff_count=as_int(count_raw) if count_raw.isdigit() else None,
                    city=as_str(_cell(i_city)) or None,
                    county=as_str(_cell(i_county)) or None,
                    closure_type=as_str(_cell(i_type)) or None,
                    source_url=source_url,
                    extra={"wda": _cell(i_wda)} if _cell(i_wda) else {},
                )
            )

    if not rows:
        raise ParseFailed(f"WI {year}: no notice rows parsed from archive page")
    return rows


register(WIScraper())
