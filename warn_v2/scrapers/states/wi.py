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
from collections import Counter
from datetime import date

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


# ---------------------------------------------------------------------------
# Historical backfill (1996-2015): PCML XLS logs via Wayback
#
# Before the static year pages, DWD published one legacy-binary .xls "Plant
# Closing and Mass Layoff" log per year at
# worknet.wisconsin.gov/worknet_info/downloads/PCML/{year}pcml_log.xls
# (host dead since ~2017; every year 1996-2016 has a Wayback capture).
# Three layout eras, all header-driven here:
#   1996-2000  one row per record; corporate street / "City, State Zip" in
#              their own columns under a merged "Contact Information" header.
#   2001-2011  multi-row records: the notice row is anchored by a date in
#              "Notice Received"; 4 continuation rows below carry the
#              corporate address / contact / phone in the Company column.
#              NAICS appears; County/WDA appear in 2011.
#   2012-2016  adds a "Date of Notice" column before "Notice Received"
#              (2012 says "WDB" for "WDA" and puts Comments last).
# The 2016 file is deliberately NOT ingested: DWD stopped maintaining the log
# in Feb 2016 (13 records, Jan 6 - Feb 2) and prod already holds full-year
# 2016 from the static archive-page route above.
# ---------------------------------------------------------------------------

_PCML_URL = (
    "http://worknet.wisconsin.gov/worknet_info/downloads/PCML/{year}pcml_log.xls"
)

# Pinned post-year Wayback captures, one per year (verified complete-year
# content 2026-07-10; the excluded 2016 capture is 20161228173739).
_PCML_CAPTURES = {
    1996: "20170125232617",
    1997: "20170125232550",
    1998: "20170125232517",
    1999: "20170125232512",
    2000: "20170125232504",
    2001: "20170316164420",
    2002: "20170316164418",
    2003: "20170316164416",
    2004: "20170316164414",
    2005: "20170316164412",
    2006: "20170316164411",
    2007: "20170316164409",
    2008: "20170316164408",
    2009: "20170316164405",
    2010: "20170316164402",
    2011: "20170316164400",
    2012: "20170316164355",
    2013: "20170316164353",
    2014: "20170316164350",
    2015: "20170316164347",
}


def _discover_wi_pcml_urls() -> list[str]:
    """Static pinned Wayback replay URLs for the 1996-2015 PCML year logs."""
    from warn_v2.scrapers.wayback import replay_url

    return [
        replay_url(ts, _PCML_URL.format(year=year))
        for year, ts in sorted(_PCML_CAPTURES.items())
    ]


# Loose M/D/YY(YY) token for text date cells ("5/3/01 to", "TBD - 8/31/14",
# "12/13/10 & 1/31/11" — first token wins).
_LOOSE_MDY_RE = re.compile(r"\b\d{1,2}/\d{1,2}/\d{2,4}\b")
_LEADING_INT_RE = re.compile(r"\d[\d,]*")


def _pcml_date(book, cell) -> date | None:
    """Date from an xlrd cell: real date cells, else date-like text."""
    import xlrd

    if cell.ctype == xlrd.XL_CELL_DATE:
        try:
            dt = xlrd.xldate_as_datetime(cell.value, book.datemode)
        except Exception:
            return None
        # Funnel through as_date for the plausible-year guard (one 1996
        # schedule cell decodes to the year 896).
        return as_date(dt.date().isoformat())
    if cell.ctype == xlrd.XL_CELL_TEXT:
        text = cell.value.strip()
        if not text:
            return None
        d = as_date(text)
        if d is not None:
            return d
        m = _LOOSE_MDY_RE.search(text)
        return as_date(m.group(0)) if m else None
    return None


def _pcml_text(cell) -> str:
    """Cell as trimmed text; integral floats lose the '.0'."""
    v = cell.value
    if isinstance(v, float) and v == int(v):
        v = int(v)
    return " ".join(str(v).split()) if v not in ("", None) else ""


def _pcml_count(cell) -> int | None:
    """# Affected: number cells, or the leading integer of text ('37 FT', '70*')."""
    if isinstance(cell.value, float):
        return as_int(cell.value)
    m = _LEADING_INT_RE.search(str(cell.value))
    return as_int(m.group(0)) if m else None


_CONTACT_LINE_RE = re.compile(r"^\s*contact\s*:", re.IGNORECASE)


class _EmptyCell:
    """Stand-in for cells in columns a layout era doesn't have."""

    ctype = 0  # xlrd.XL_CELL_EMPTY
    value = ""


_EMPTY_CELL = _EmptyCell()


def parse_wi_pcml_xls(raw: bytes, source_url: str) -> list[NoticeRow]:
    """Parse one PCML year log (all three 1996-2016 layout eras)."""
    import xlrd

    try:
        book = xlrd.open_workbook(file_contents=raw)
    except Exception as e:
        raise ParseFailed(f"WI PCML: not a readable .xls: {e}") from e

    sheet = next((s for s in book.sheets() if s.nrows), None)
    if sheet is None:
        raise ParseFailed("WI PCML: workbook has no data sheets")

    # Header row: the one naming "Notice Received".
    header_row = next(
        (
            r
            for r in range(min(sheet.nrows, 10))
            if any(
                "notice received" in _pcml_text(sheet.cell(r, c)).lower()
                for c in range(sheet.ncols)
            )
        ),
        None,
    )
    if header_row is None:
        raise ParseFailed("WI PCML: no 'Notice Received' header row found")

    header = [_pcml_text(sheet.cell(header_row, c)).lower() for c in range(sheet.ncols)]

    def _col(*needles: str) -> int | None:
        return next(
            (i for i, name in enumerate(header) if any(n in name for n in needles)),
            None,
        )

    i_received = _col("notice received")
    i_dated = _col("date of notice")
    i_company = _col("company")
    i_location = _col("wisconsin location")
    i_industry = _col("industry")  # 2013 has two; the first (description) wins
    i_naics = _col("naics")
    i_type = _col("type of notice")
    i_count = _col("affected")
    i_schedule = _col("schedule")
    i_comments = _col("comments")
    i_county = _col("county")
    i_wda = _col("wda", "wdb")
    # 1996-2000 single-row era: corporate street + "City, State Zip" columns
    # under a merged "Contact Information" header (street col; city col + 1).
    i_street = _col("contact information")
    if i_company is None or i_received is None:
        raise ParseFailed("WI PCML: header row lacks Company / Notice Received")

    def _cell(r: int, i: int | None):
        return sheet.cell(r, i) if i is not None and i < sheet.ncols else _EMPTY_CELL

    # Group rows into records: an anchor row starts a record (a date in the
    # received/date-of-notice column, or company + location both present — the
    # latter catches anchors whose date cell is a typo like 2002's "6/6/4/02");
    # following rows are continuations carrying corporate-address and comment
    # lines. A fully blank row closes the record (stale remnant rows sit far
    # below the data in the 2016 file).
    records: list[dict] = []
    current: dict | None = None
    for r in range(header_row + 1, sheet.nrows):
        cells = [sheet.cell(r, c) for c in range(sheet.ncols)]
        if all(_pcml_text(c) == "" for c in cells):
            current = None
            continue
        company = _pcml_text(_cell(r, i_company))
        if company.startswith("<"):  # "<Auto Filter Enabled ...>" banner row
            continue
        received = _pcml_date(book, _cell(r, i_received))
        dated = _pcml_date(book, _cell(r, i_dated))
        location = _pcml_text(_cell(r, i_location))
        is_anchor = (received or dated) is not None or (
            company != "" and location != ""
        )
        if is_anchor:
            current = {
                "row": r,
                "received": received,
                "dated": dated,
                "employer": company,
                "location": location,
                "address_lines": [],
                "comment_lines": [_pcml_text(_cell(r, i_comments))],
            }
            records.append(current)
        elif current is not None:
            if company:
                current["address_lines"].append(company)
            comment = _pcml_text(_cell(r, i_comments))
            if comment:
                current["comment_lines"].append(comment)

    # Each file is a single-year log; a date far outside the modal year is a
    # source typo (2002 has "6/6/4/02", which would otherwise parse to 2004).
    year_counts = Counter(
        (rec["received"] or rec["dated"]).year
        for rec in records
        if rec["received"] or rec["dated"]
    )
    modal_year = year_counts.most_common(1)[0][0] if year_counts else None

    rows: list[NoticeRow] = []
    for rec in records:
        employer = as_str(rec["employer"])
        notice_date = rec["received"] or rec["dated"]
        if not employer or notice_date is None:
            continue
        if modal_year is not None and abs(notice_date.year - modal_year) > 1:
            continue
        r = rec["row"]

        if i_street is not None:
            # Single-row era: street + "City, State Zip" columns.
            addr = [_pcml_text(_cell(r, i_street)), _pcml_text(_cell(r, i_street + 1))]
            corporate_address = ", ".join(p for p in addr if p)
        else:
            # Multi-row era: address lines precede the "contact:" / phone lines.
            addr = []
            for line in rec["address_lines"]:
                if _CONTACT_LINE_RE.match(line):
                    break
                addr.append(line)
            # Trailing phone-only line when no contact line was present.
            if addr and not re.search(r"[a-zA-Z]", addr[-1]):
                addr.pop()
            corporate_address = ", ".join(addr)

        naics = _pcml_text(_cell(r, i_naics))

        extra: dict[str, str] = {}
        for key, value in (
            ("industry", _pcml_text(_cell(r, i_industry))),
            ("wda", _pcml_text(_cell(r, i_wda))),
            ("corporate_address", corporate_address),
            ("comments", " ".join(c for c in rec["comment_lines"] if c)),
            (
                "date_of_notice",
                rec["dated"].isoformat() if rec["dated"] is not None else "",
            ),
        ):
            if value:
                extra[key] = value

        rows.append(
            NoticeRow(
                state="WI",
                employer=employer,
                notice_date=notice_date,
                effective_date=_pcml_date(book, _cell(r, i_schedule)),
                layoff_count=_pcml_count(_cell(r, i_count)),
                city=as_str(rec["location"]) or None,
                county=as_str(_pcml_text(_cell(r, i_county))) or None,
                naics_code=naics if naics.isdigit() else None,
                closure_type=as_str(_pcml_text(_cell(r, i_type))) or None,
                source_url=source_url,
                extra=extra,
            )
        )

    if not rows:
        raise ParseFailed("WI PCML: no notice rows parsed")
    return rows


register(WIScraper())
