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
import logging
import re
from datetime import date

import httpx
import pdfplumber
from bs4 import BeautifulSoup

from warn_v2.scrapers._helpers import as_date, as_str
from warn_v2.scrapers.base import NoticeRow, ParseFailed, ScrapeFailed
from warn_v2.scrapers.bundled import DATA_DIR, load_archive
from warn_v2.scrapers.registry import register

log = logging.getLogger(__name__)

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

            # "Updates" column records receive/revision history as multi-line text,
            # e.g. "received 4/21/2026\nrevised 5/1/2026". Store raw for provenance.
            updates_idx = col.get("updates", -1)
            updates_raw = (
                str(raw_row[updates_idx]).strip()
                if 0 <= updates_idx < len(raw_row) and raw_row[updates_idx]
                else None
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
                    address=as_str(_first_line(raw_row[col["address"]])),
                    source_url=_LANDING_URL,
                    extra={"updates": updates_raw} if updates_raw else {},
                )
            )
        return rows


def _first_line(value) -> str:
    if value is None:
        return ""
    return str(value).split("\n")[0].strip()


register(IDScraper())


# ---------------------------------------------------------------------------
# Historical backfill: the 2008 cumulative log PDF (Mode 3b bundled)
# ---------------------------------------------------------------------------
# Idaho's log begins 2008-02, but its 2008 rows (incl. Micron Boise
# 1,400-1,600) were dropped from the current live log — the bundled Wayback
# capture (2009-04) is their only source. The capture also carries early-2009
# rows; those are filtered out (prod's live-log floor is 2009, so re-parsing
# them would mint near-duplicates with formatting drift).
#
# Same column semantics as the live log, but the file is an Excel print-out:
# a spreadsheet column-letter row (A/B/C/...) sits above the real header and
# a row-number column sits left of the data, so IDScraper.parse can't read it
# directly.

_ARCHIVE_SOURCE_URL = (
    "https://web.archive.org/web/20090418074939/"
    "http://labor.idaho.gov/pdf/WARNNotice.pdf"
)
_ARCHIVE_CUTOFF = date(2009, 1, 1)


def id_archive_files() -> list[tuple[str, bytes]]:
    """Members of the bundled ID historical archive (one 2008-era log PDF)."""
    return load_archive(DATA_DIR / "id_archive.tar.gz")


def parse_id_2008_pdf(raw: bytes) -> list[NoticeRow]:
    """Parse the 2008-era cumulative log, keeping only pre-2009 rows.

    Counts can be ranges ("1,400-1,600") or annotations ("88+26"): the
    leading integer (commas stripped) is stored. Effective dates that are
    ranges parse to None.
    """
    try:
        pdf = pdfplumber.open(io.BytesIO(raw))
    except Exception as e:
        raise ParseFailed(f"ID 2008 PDF: could not open: {e}") from e

    with pdf:
        grid: list[list] = []
        for page in pdf.pages:
            grid.extend(page.extract_table() or [])

    # Locate the real header row (the column-letter row precedes it) and the
    # offset introduced by the row-number column.
    header: dict[str, int] | None = None
    data_rows: list[list] = []
    for row in grid:
        if header is None:
            lowered = [
                "" if c is None else " ".join(str(c).split()).lower() for c in row
            ]
            if "company" in lowered:
                header = {name: i for i, name in enumerate(lowered)}
            continue
        data_rows.append(row)
    if header is None:
        raise ParseFailed("ID 2008 PDF: header row not found")

    rows: list[NoticeRow] = []
    excluded = 0
    for cells in data_rows:
        employer = _first_line(cells[header["company"]])
        if not employer:
            continue
        notice_date = as_date(_first_line(cells[header["date of letter"]]))
        if notice_date is None:
            continue
        if notice_date >= _ARCHIVE_CUTOFF:
            excluded += 1
            continue

        count_raw = _first_line(cells[header["no. of employees affected"]])
        m = _LEADING_INT.search(count_raw.replace(",", "")) if count_raw else None

        rows.append(
            NoticeRow(
                state="ID",
                employer=employer,
                notice_date=notice_date,
                effective_date=as_date(
                    _first_line(cells[header["effective or commencing date"]])
                ),
                layoff_count=int(m.group()) if m else None,
                city=as_str(_first_line(cells[header["city"]])),
                zip=as_str(_first_line(cells[header["zip"]])),
                address=as_str(_first_line(cells[header["address"]])),
                source_url=_ARCHIVE_SOURCE_URL,
            )
        )

    if not rows:
        raise ParseFailed("ID 2008 PDF: no pre-2009 data rows found")
    log.info(
        "ID 2008 PDF: kept %d pre-2009 rows, excluded %d rows >= %s "
        "(covered by the live log)",
        len(rows), excluded, _ARCHIVE_CUTOFF,
    )
    return rows
