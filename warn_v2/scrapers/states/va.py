"""Virginia WARN scraper.

Source: https://virginiaworks.gov/im-an-employer/retain-and-grow/warn-notices/
  (domain migrated from vec.virginia.gov as of 2026)

Schema (live as of May 2026):
  Company | Notice Date | Impact Date | Employees Affected | Location |
  Contact Person | Notice Type | Collective Bargaining Unit

The Company cell contains an <a> tag with the clean company name linking to the
filed WARN PDF, followed by the street address as raw text. We extract the link
text as employer and the href as raw_notice_url.

Location is "City, VA" — city is extracted by splitting on comma.

Historical backfill (Mode 3b bundled archive — see va_archive_files below):
VA published by program year (July-June) in three legacy formats, recovered
from the Wayback Machine and bundled as ``data/va_archive.tar.gz``:

  - PY1999: ``warnnot99.xls`` — legacy .xls, one numbered notice ("1."-"59.")
    per multi-row block (address/contact lines below the marker row); the
    notice date sits on the marker row and the impact date on the next row of
    the same column.
  - PY2002: ``warnlog03.pdf`` — 11-page PDF log; pdfplumber tables with the
    company + street address merged in the first cell.
  - PY2003: ``warnnot04_statewide.htm`` — the "Statewide" sheet of an Excel
    workbook saved as HTML (warnnot04_files/sheet001.htm). The workbook's four
    regional tabs repeat the statewide notices (verified: after date
    normalization the regional union is a subset of Statewide, modulo two
    amended-value variants), so only the statewide sheet is bundled/ingested.

PY2000-01 were never captured; the PY2004-PY2006 workbook data sheets exist in
the Wayback Machine but are not in this bundle (see docs/backfill-milestones.md).
"""
from __future__ import annotations

import io
import re

import httpx
import pdfplumber
import xlrd
from bs4 import BeautifulSoup

from warn_v2.scrapers._helpers import as_date, as_int, as_str
from warn_v2.scrapers.base import NoticeRow, ParseFailed, ScrapeFailed
from warn_v2.scrapers.bundled import DATA_DIR, load_archive
from warn_v2.scrapers.registry import register

SOURCE_URL = "https://virginiaworks.gov/im-an-employer/retain-and-grow/warn-notices/"

_UA = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) warn-v2/0.1"
    )
}


class VAScraper:
    state = "VA"
    source_url = SOURCE_URL
    # Cumulative table — ~1000+ rows.
    expected_row_range = (50, 20_000)
    required_fields = frozenset({"employer", "notice_date"})

    def fetch(self) -> bytes:
        try:
            r = httpx.get(SOURCE_URL, headers=_UA, timeout=60, follow_redirects=True)
            r.raise_for_status()
            return r.content
        except httpx.HTTPError as e:
            raise ScrapeFailed(f"GET {SOURCE_URL}: {e}") from e

    def parse(self, raw: bytes) -> list[NoticeRow]:
        soup = BeautifulSoup(raw, "html.parser")
        table = soup.find("table")
        if table is None:
            raise ParseFailed("no <table> found on VA WARN page")

        all_trs = table.find_all("tr")
        if not all_trs:
            raise ParseFailed("VA table has no rows")

        header_cells = [_text(td).lower() for td in all_trs[0].find_all(["td", "th"])]
        if not header_cells or "company" not in header_cells:
            raise ParseFailed(f"unexpected VA header: {header_cells[:6]}")
        col = {name: i for i, name in enumerate(header_cells)}

        rows: list[NoticeRow] = []
        for tr in all_trs[1:]:
            cells = tr.find_all(["td", "th"])
            if len(cells) < len(header_cells):
                continue

            # Company cell: <a> text = clean employer name; href = notice PDF.
            # The cell's plain text after the anchor is the street address.
            company_cell = cells[col["company"]]
            anchor = company_cell.find("a")
            if anchor:
                employer = as_str(anchor.get_text(" ", strip=True))
                notice_url: str | None = anchor.get("href") or None
                full_text = _text(company_cell)
                address = as_str(full_text.replace(employer or "", "", 1).strip(" ,"))
            else:
                employer = as_str(_text(company_cell))
                notice_url = None
                address = None

            if not employer:
                continue
            notice_date = as_date(_text(cells[col["notice date"]]))
            if notice_date is None:
                continue

            location = _text(cells[col["location"]])
            city = as_str(location.split(",")[0].strip()) if location else None

            rows.append(
                NoticeRow(
                    state="VA",
                    employer=employer,
                    notice_date=notice_date,
                    effective_date=as_date(_text(cells[col["impact date"]])),
                    layoff_count=as_int(_text(cells[col["employees affected"]])),
                    closure_type=as_str(_text(cells[col["notice type"]])),
                    city=city,
                    address=address,
                    raw_notice_url=notice_url,
                    source_url=SOURCE_URL,
                )
            )
        return rows


def _text(cell) -> str:
    return " ".join(cell.get_text(" ", strip=True).split())


# ---------------------------------------------------------------------------
# Historical backfill — bundled archive (PY1999, PY2002, PY2003)
# ---------------------------------------------------------------------------

_ARCHIVE_PATH = DATA_DIR / "va_archive.tar.gz"

# Original locations of the bundled captures (Wayback Machine, 2003-2014).
_PY1999_URL = "http://www.vec.state.va.us/docs/xls/warnnot99.xls"
_PY2002_URL = "http://www.vec.state.va.us/pdf/warnlog03.pdf"
_PY2003_URL = (
    "http://www.vec.virginia.gov/vecportal/employer/docs/xls/warnlog/"
    "warnnot04_files/sheet001.htm"
)

_MDY_RE = re.compile(r"\d{1,2}/\d{1,2}/\d{2,4}$")
_CITY_VA_RE = re.compile(r"^[^,]+,\s*(VA|Va\.?|Virginia)\b")

# Location cells in the PY2002 PDF wrap onto two lines; most multi-line cells
# are genuine multi-city lists (we keep the first city), but these two are a
# single wrapped name. The source file is frozen, so a whitelist is exact.
_PDF_WRAPPED_CITIES = {"Newport News", "Reagan National Airport"}


def va_archive_files() -> list[tuple[str, bytes]]:
    return load_archive(_ARCHIVE_PATH)


def parse_va_archive_member(name: str):
    """Dispatch a bundle member to its era parser (backfill parse_for_url)."""
    if name.endswith(".xls"):
        return parse_va_py1999_xls
    if name.endswith(".pdf"):
        return parse_va_py2002_pdf
    if name.endswith(".htm"):
        return parse_va_excel_html
    return None


def parse_va_py1999_xls(raw: bytes) -> list[NoticeRow]:
    """PY1999 legacy .xls: numbered multi-row notice blocks.

    Marker rows carry "N." in col 0, company in col 1, location in col 3,
    Closing/RIF in col 10, EST/Actual counts in cols 11/12. Col 5 carries the
    notice date then the impact date on the following row — but a few blocks
    shift both down a row or two, so we take the block's col-5 dates in row
    order. Location may span two rows (street, then "City, VA ZIP").
    """
    wb = xlrd.open_workbook(file_contents=raw)
    sheet = next((s for s in wb.sheets() if s.nrows), None)
    if sheet is None:
        raise ParseFailed("VA PY1999 xls: no non-empty sheet")

    def cell(r: int, c: int) -> str:
        v = sheet.cell_value(r, c)
        if isinstance(v, float) and v == int(v):
            v = int(v)
        return str(v).strip()

    marker_rows = [
        r for r in range(sheet.nrows) if re.fullmatch(r"\d+\.", cell(r, 0))
    ]
    if not marker_rows:
        raise ParseFailed("VA PY1999 xls: no numbered notice rows found")

    rows: list[NoticeRow] = []
    for i, r in enumerate(marker_rows):
        block_end = marker_rows[i + 1] if i + 1 < len(marker_rows) else sheet.nrows
        employer = as_str(cell(r, 1))
        if not employer:
            continue
        dates = [
            d
            for rr in range(r, block_end)
            if cell(rr, 5) and (d := as_date(cell(rr, 5))) is not None
        ]
        if not dates:
            continue
        notice_date = dates[0]
        effective_date = dates[1] if len(dates) > 1 else None
        # Location block: a "City, VA [ZIP]" line names the city; otherwise
        # the first line without digits is a bare city name.
        loc_lines = [cell(rr, 3) for rr in range(r, block_end) if cell(rr, 3)]
        city_line = next(
            (line for line in loc_lines if _CITY_VA_RE.match(line)),
            None,
        ) or next(
            (line for line in loc_lines if not any(ch.isdigit() for ch in line)),
            None,
        )
        city = as_str(city_line.split(",")[0]) if city_line else None
        layoff_count = as_int(cell(r, 12)) or as_int(cell(r, 11))
        rows.append(
            NoticeRow(
                state="VA",
                employer=employer,
                notice_date=notice_date,
                effective_date=effective_date,
                layoff_count=layoff_count,
                closure_type=as_str(cell(r, 10)),
                city=city,
                source_url=_PY1999_URL,
            )
        )
    return rows


def parse_va_py2002_pdf(raw: bytes) -> list[NoticeRow]:
    """PY2002 PDF log: pdfplumber tables, company + address merged in col 0.

    Quirks: some pages emit an "echo" row (the whole line glued into col 0
    with every other column empty) before the real row — skipped by requiring
    a parseable notice date in col 1; a few rows also glue the date columns
    onto the company line, so col 0's first line is trimmed at the notice-date
    text.
    """
    rows: list[NoticeRow] = []
    with pdfplumber.open(io.BytesIO(raw)) as pdf:
        for page in pdf.pages:
            for table in page.extract_tables():
                for cells in table:
                    c = [(x or "").strip() for x in cells]
                    if len(c) < 7 or not c[0] or c[0].startswith("Company"):
                        continue
                    notice_date = as_date(c[1])
                    if notice_date is None:
                        continue  # echo/header/mega-cell rows
                    lines = [ln.strip() for ln in c[0].splitlines() if ln.strip()]
                    employer = lines[0]
                    if c[1] in employer:  # glued date columns
                        employer = employer.split(c[1])[0].strip()
                    address = as_str(", ".join(lines[1:]))
                    loc_lines = [
                        ln.strip() for ln in c[4].splitlines() if ln.strip()
                    ]
                    joined = " ".join(loc_lines)
                    if joined in _PDF_WRAPPED_CITIES:
                        loc_lines = [joined]
                    city = as_str(loc_lines[0]) if loc_lines else None
                    rows.append(
                        NoticeRow(
                            state="VA",
                            employer=employer,
                            notice_date=notice_date,
                            effective_date=as_date(c[2]),
                            layoff_count=as_int(c[3]),
                            closure_type=as_str(c[6]),
                            city=city,
                            address=address,
                            source_url=_PY2002_URL,
                        )
                    )
    if not rows:
        raise ParseFailed("VA PY2002 pdf: no notice rows extracted")
    return rows


def parse_va_excel_html(raw: bytes) -> list[NoticeRow]:
    """Excel-workbook-as-HTML statewide sheet (PY2003 era).

    A notice row has the company in col 0 and the notice date in col 1;
    the address lines follow in col 0 of continuation rows. One notice
    (Ericsson 9/22/03) was recorded on an address line — a row whose col 0
    starts with a digit but carries its own notice date inherits the previous
    notice's employer.
    """
    soup = BeautifulSoup(raw, "html.parser")
    trs = soup.find_all("tr")
    if not trs:
        raise ParseFailed("VA excel-html sheet: no <tr> rows")

    rows: list[NoticeRow] = []
    last_employer: str | None = None
    for tr in trs:
        c = [_text(td) for td in tr.find_all("td")]
        if len(c) < 7 or not c[0] or c[0].upper().startswith("TOTAL"):
            continue
        if not _MDY_RE.fullmatch(c[1]):
            # Continuation row: col 0 is an address line for the previous
            # notice.
            if rows and last_employer and not c[1] and not c[0].startswith("**"):
                prev = rows[-1]
                prev.address = f"{prev.address}, {c[0]}" if prev.address else c[0]
            continue
        notice_date = as_date(c[1])
        if notice_date is None:
            continue
        if c[0][0].isdigit() and last_employer:
            employer = last_employer  # notice recorded on an address line
        else:
            employer = c[0]
            last_employer = employer
        rows.append(
            NoticeRow(
                state="VA",
                employer=employer,
                notice_date=notice_date,
                effective_date=as_date(c[2]),
                layoff_count=as_int(c[3]),
                closure_type=as_str(c[6]),
                city=as_str(c[4].split(",")[0]) if c[4] else None,
                source_url=_PY2003_URL,
            )
        )
    if not rows:
        raise ParseFailed("VA excel-html sheet: no notice rows extracted")
    return rows


register(VAScraper())
