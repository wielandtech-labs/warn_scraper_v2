"""North Carolina WARN scraper.

Source: https://www.commerce.nc.gov/.../report-workforce-warn-summary-list-{year}

Schema (live as of May 2026):
  County | Warn Number | Date of Notice | Date Received by NC | Effective Date |
  WARN Notice: WARN Notice Name | WARN notice type | Type of layoff or closure |
  Number affected at this location | Address 1 | City

The page URL embeds the year. Falls back to prior year when current year 404s.

Historical backfill (``backfill-historical --state NC``) reads the per-year
archive PDFs linked from the ``warn-summary-report-archives`` hub, back to 2014.
Three PDF layout eras exist (probed 2026-07-07); ``parse_nc_pdf`` dispatches on
detected content, not the year, so an unseen middle year still lands in the
right sub-parser:

* **2014-~2017** — "WARN Notice - Summary Count": flowing text with monthly
  subtotal lines, no table grid. Word-position parsing like ``nv.py``.
* **~2018-2021** — SSRS "WarnReportByCountyParish" grid: no separate City
  column (city+state+zip glued into the Address cell); one WARN number can
  repeat across several address lines carrying the same total count, so rows
  are collapsed by WARN number to avoid double-counting.
* **2022-2025** — "WARN Summary by County/Parish" grid: identical column
  schema to the live HTML table, so it shares ``_row_from_nc_grid`` with the
  live parser.
"""
from __future__ import annotations

import io
import re
from collections import defaultdict
from datetime import date

import httpx
import pdfplumber
from bs4 import BeautifulSoup

from warn_v2.scrapers._helpers import as_date, as_int, as_str
from warn_v2.scrapers.base import NoticeRow, ParseFailed, ScrapeFailed
from warn_v2.scrapers.registry import register

_URL = (
    "https://www.commerce.nc.gov/data-tools-reports/labor-market-data-tools"
    "/workforce-warn-reports/report-workforce-warn-summary-list-{year}"
)

_UA = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) warn-v2/0.1"
    )
}


def _source_url(year: int) -> str:
    return _URL.format(year=year)


class NCScraper:
    state = "NC"
    source_url = _URL.format(year=date.today().year)
    expected_row_range = (5, 2_000)
    required_fields = frozenset({"employer", "notice_date"})

    def fetch(self) -> bytes:
        year = date.today().year
        for yr in (year, year - 1):
            url = _source_url(yr)
            try:
                r = httpx.get(url, headers=_UA, timeout=60, follow_redirects=True)
                if r.status_code == 200 and b"<table" in r.content:
                    self.source_url = url
                    return r.content
            except httpx.HTTPError:
                pass
        raise ScrapeFailed(f"Could not fetch NC WARN page for {year} or {year - 1}")

    def parse(self, raw: bytes) -> list[NoticeRow]:
        soup = BeautifulSoup(raw, "html.parser")
        table = soup.find("table")
        if table is None:
            raise ParseFailed("no <table> found on NC WARN page")

        all_trs = table.find_all("tr")
        if not all_trs:
            raise ParseFailed("NC table has no rows")

        header_cells = [_text(td).lower() for td in all_trs[0].find_all(["td", "th"])]
        if not header_cells or not any("warn" in h for h in header_cells):
            raise ParseFailed(f"unexpected NC header: {header_cells[:6]}")
        col = {name: i for i, name in enumerate(header_cells)}

        # Employer column name contains a colon; find it by partial match.
        employer_col = next(
            (k for k in col if "warn notice name" in k or "warn notice:" in k),
            None,
        )
        if employer_col is None:
            raise ParseFailed(f"NC: could not find employer column; headers: {header_cells}")

        # "Address 1" is the street address of the layoff site; optional.
        address_col = next((k for k in col if "address" in k), None)

        rows: list[NoticeRow] = []
        for tr in all_trs[1:]:
            cells = tr.find_all(["td", "th"])
            if len(cells) < len(header_cells):
                continue
            row = _row_from_nc_grid(
                col, [_text(c) for c in cells], employer_col, address_col, self.source_url
            )
            if row is not None:
                rows.append(row)
        return rows


def _text(cell) -> str:
    return " ".join(cell.get_text(" ", strip=True).split())


# ---------------------------------------------------------------------------
# Shared "WARN Summary by County/Parish" row builder (live HTML + 2022+ PDF).
# The live table and the modern archive PDF carry byte-identical column names,
# so both feed this one builder. `col` maps lowercased header name -> index;
# `cells` holds the same-index cell text (original case); `employer_col` and
# `address_col` are the resolved keys for those partial-match columns.
# ---------------------------------------------------------------------------
def _row_from_nc_grid(
    col: dict[str, int],
    cells: list[str],
    employer_col: str,
    address_col: str | None,
    source_url: str,
) -> NoticeRow | None:
    def cell(name: str) -> str:
        i = col.get(name)
        return cells[i] if i is not None and i < len(cells) else ""

    employer = as_str(cell(employer_col))
    if not employer:
        return None
    notice_date = as_date(cell("date of notice"))
    if notice_date is None:
        return None

    address = None
    if address_col is not None:
        address = as_str(cell(address_col))

    return NoticeRow(
        state="NC",
        employer=employer,
        notice_date=notice_date,
        effective_date=as_date(cell("effective date")),
        layoff_count=as_int(cell("number affected at this location")),
        closure_type=as_str(cell("type of layoff or closure")),
        city=as_str(cell("city")),
        county=as_str(cell("county")),
        address=address,
        source_url=source_url,
        extra={
            "warn_number": as_str(cell("warn number")) or "",
            "warn_notice_type": as_str(cell("warn notice type")) or "",
        },
    )


# ---------------------------------------------------------------------------
# Historical backfill — archive-hub discovery + per-era PDF parsers.
# ---------------------------------------------------------------------------
_BASE_URL = "https://www.commerce.nc.gov"
_ARCHIVE_HUB = (
    "https://www.commerce.nc.gov/data-tools-reports/labor-market-data-tools"
    "/workforce-warn-reports/warn-summary-report-archives"
)
# Per-year report links, three slug families, all ending "/open":
#   /warn-report-2014-0/open, /warn-report-2019/open,
#   /worker-adjustment-and-retraining-notification-warn-report-2021/open,
#   /...report-workforce-warn-listings-2025/open
_ARCHIVE_HREF_RE = re.compile(r"warn[\w-]*?(20(?:1[4-9]|2[0-5]))[\w-]*/open/?$", re.I)


def _discover_nc_pdf_urls() -> list[str]:
    """Return one absolute /open PDF URL per archive year (2014+), newest first."""
    try:
        r = httpx.get(_ARCHIVE_HUB, headers=_UA, timeout=60, follow_redirects=True)
        r.raise_for_status()
    except httpx.HTTPError:
        return []
    soup = BeautifulSoup(r.content, "html.parser")
    by_year: dict[int, str] = {}
    for a in soup.find_all("a", href=True):
        href = a["href"]
        m = _ARCHIVE_HREF_RE.search(href)
        if not m:
            continue
        year = int(m.group(1))
        url = href if href.startswith("http") else _BASE_URL + href
        by_year.setdefault(year, url)  # first (page lists newest first)
    return [by_year[y] for y in sorted(by_year, reverse=True)]


def parse_nc_pdf(raw: bytes, source_url: str) -> list[NoticeRow]:
    """Parse one archive-year PDF, dispatching on detected layout."""
    try:
        pdf = pdfplumber.open(io.BytesIO(raw))
    except Exception as e:
        raise ParseFailed(f"NC PDF {source_url}: could not open: {e}") from e

    with pdf:
        first = pdf.pages[0]
        table = first.extract_table()
        header_txt = " ".join((first.extract_text() or "").lower().split())
        joined = " ".join(
            " ".join(str(c or "").lower().split())
            for row in (table or [])
            for c in row
        )
        if "warn notice name" in joined or "number affected at this location" in joined:
            rows = _parse_nc_current_grid(pdf, source_url)
        elif "county/parish" in joined and "employees" in joined:
            rows = _parse_nc_ssrs_grid(pdf, source_url)
        elif table is None or "summary count" in header_txt:
            rows = _parse_nc_summary_count(pdf, source_url)
        else:
            raise ParseFailed(f"NC PDF {source_url}: unrecognized layout")

    if not rows:
        raise ParseFailed(f"NC PDF {source_url}: no data rows found")
    return rows


def _norm_cell(value: object) -> str:
    return " ".join(str(value or "").split())


def _parse_nc_current_grid(pdf, source_url: str) -> list[NoticeRow]:
    """2022+ grid — same column names as the live HTML table (header per page)."""
    col: dict[str, int] | None = None
    employer_col: str | None = None
    address_col: str | None = None
    rows: list[NoticeRow] = []
    for page in pdf.pages:
        table = page.extract_table()
        if not table:
            continue
        for raw_row in table:
            cells = [_norm_cell(c) for c in raw_row]
            lower = [c.lower() for c in cells]
            if any("warn notice name" in c for c in lower):
                col = {name: i for i, name in enumerate(lower)}
                employer_col = next(
                    (k for k in col if "warn notice name" in k or "warn notice:" in k),
                    None,
                )
                address_col = next((k for k in col if "address" in k), None)
                continue
            if col is None or employer_col is None:
                continue
            row = _row_from_nc_grid(col, cells, employer_col, address_col, source_url)
            if row is not None:
                rows.append(row)
    return rows


# Street elements that terminate the trailing city run in an SSRS address cell.
_STREET_SUFFIX = frozenset(
    {
        "st", "street", "ave", "avenue", "rd", "road", "dr", "drive", "blvd",
        "boulevard", "ln", "lane", "way", "ct", "court", "cir", "circle",
        "pkwy", "parkway", "hwy", "highway", "pl", "place", "ste", "suite",
        "unit", "fl", "floor", "trl", "trail", "loop", "run", "pike", "row",
    }
)


def _ssrs_city_zip(address: str) -> tuple[str | None, str | None]:
    """City + ZIP from an SSRS address ('... Charlotte NC 28262' -> Charlotte, 28262).

    Both are anchored on the trailing ``NC <zip>`` so the ZIP is the one that
    follows the state, not the first 5-digit run (which would grab a 5-digit
    street number like '10815 Quality Dr' or an out-of-state HQ ZIP glued into
    the cell). No comma delimits the city, so walk backward from the state
    token over alphabetic words until a street suffix or a numbered street
    element ends the run (handles two-word cities like 'Rocky Mount').
    """
    m = re.search(r"(.+?)\s+NC\s+(\d{5})", address, re.I)
    if not m:
        return None, None
    zip_code = m.group(2)
    parts: list[str] = []
    for tok in reversed(m.group(1).split()):
        cleaned = tok.strip(".,").lower()
        if any(ch.isdigit() for ch in tok) or cleaned in _STREET_SUFFIX or tok == "#":
            break
        parts.insert(0, tok)
        if len(parts) >= 3:
            break
    return (" ".join(parts) or None), zip_code


def _parse_nc_ssrs_grid(pdf, source_url: str) -> list[NoticeRow]:
    """2018-2021 SSRS grid; collapse repeated-address lines by WARN number."""
    col: dict[str, int] | None = None
    by_key: dict[str, NoticeRow] = {}
    order: list[str] = []
    for page in pdf.pages:
        table = page.extract_table()
        if not table:
            continue
        for raw_row in table:
            cells = [_norm_cell(c) for c in raw_row]
            lower = [c.lower() for c in cells]
            if "county/parish" in lower and any("employees" in c for c in lower):
                col = {name: i for i, name in enumerate(lower)}
                continue
            if col is None:
                continue

            def cell(name: str, _col=col, _cells=cells) -> str:
                i = _col.get(name)
                return _cells[i] if i is not None and i < len(_cells) else ""

            employer = as_str(cell("company"))
            notice_date = as_date(cell("notice date"))
            if not employer or notice_date is None:
                continue
            warn_no = cell("warn no.")
            key = warn_no or f"{employer}|{notice_date}"
            if key in by_key:
                continue  # same notice, another worksite line — count already counted

            address = as_str(cell("address"))
            city, zip_code = _ssrs_city_zip(address) if address else (None, None)
            by_key[key] = NoticeRow(
                state="NC",
                employer=employer,
                notice_date=notice_date,
                effective_date=as_date(cell("effective date")),
                layoff_count=as_int(cell("no. of employees")),
                closure_type=as_str(cell("layoff/closure")),
                city=city,
                county=as_str(cell("county/parish")),
                zip=zip_code,
                address=address,
                source_url=source_url,
                extra={"warn_number": warn_no} if warn_no else {},
            )
            order.append(key)
    return [by_key[k] for k in order]


# Summary-count column x-boundaries (612pt letter page, measured 2026-07-07):
#   x < 90  Notice Date | < 160 Effective Date | < 308 Company |
#   < 396 City | < 465 # Emp. Affected | else Layoff/Closure
# The company|city split sits at 308: company suffix words top out at ~306
# ("... North America LLC") while city values float 308-338 (they render a few
# pt further left on continuation pages than the header suggests). 308 keeps
# every 2014-2017 row's city intact with no suffix bleeding into the city.
_SUM_DATE_RE = re.compile(r"^\d{1,2}/\d{1,2}/\d{4}$")
_ROW_BUCKET = 4


def _assign_summary_word(cur: dict, x: float, text: str, *, cont: bool) -> None:
    if x < 90:
        if not cont:
            cur["notice"] = text
    elif x < 160:
        if not cont:
            cur["eff"] = text
    elif x < 308:
        cur["emp"].append(text)
    elif x < 396:
        cur["city"].append(text)
    elif x < 465:
        if not cont:
            cur["count"] = (cur["count"] or "") + text
    elif not cont and cur["ctype"] is None:
        cur["ctype"] = text


def _parse_nc_summary_count(pdf, source_url: str) -> list[NoticeRow]:
    """2014-~2017 flowing-text report; word-position columns, wrap-aware.

    A visual row beginning with a date at x<90 starts a record; a dateless row
    whose first word sits in the Company column (x>=155) is a wrapped
    continuation of the current record; anything else (monthly subtotals,
    repeated headers, the title/date-range banner) ends the current record.
    """
    rows: list[NoticeRow] = []
    cur: dict | None = None

    def flush() -> None:
        nonlocal cur
        if cur is not None:
            employer = as_str(" ".join(cur["emp"]))
            notice_date = as_date(cur["notice"])
            if employer and notice_date is not None:
                rows.append(
                    NoticeRow(
                        state="NC",
                        employer=employer,
                        notice_date=notice_date,
                        effective_date=as_date(cur["eff"]) if cur["eff"] else None,
                        layoff_count=as_int(cur["count"]) if cur["count"] else None,
                        closure_type=as_str(cur["ctype"]),
                        city=as_str(" ".join(cur["city"])) or None,
                        source_url=source_url,
                    )
                )
        cur = None

    for page in pdf.pages:
        row_map: dict[int, list] = defaultdict(list)
        for w in page.extract_words():
            row_map[round(w["top"] / _ROW_BUCKET) * _ROW_BUCKET].append(w)
        for y_key in sorted(row_map):
            words = sorted(row_map[y_key], key=lambda w: w["x0"])
            first = words[0]
            if first["x0"] < 90 and _SUM_DATE_RE.match(first["text"]):
                flush()
                cur = {
                    "notice": None, "eff": None, "emp": [], "city": [],
                    "count": None, "ctype": None,
                }
                for w in words:
                    _assign_summary_word(cur, w["x0"], w["text"], cont=False)
            elif cur is not None and first["x0"] >= 155:
                for w in words:
                    _assign_summary_word(cur, w["x0"], w["text"], cont=True)
            else:
                flush()
    flush()
    return rows


register(NCScraper())
