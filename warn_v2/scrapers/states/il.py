"""Illinois WARN scraper.

Source: https://www.illinoisworknet.com/LayoffRecovery/Pages/ArchivedWARNReports.aspx
Data:   Monthly Excel (.xlsx/.xls) files, one per calendar month.
        The archive page lists all available files; fetch() downloads the most
        recent one.

Excel columns (A-T, row 1 = header):
  COMPANY NAME | DBA | COMPANY ADDRESS | CITY, STATE, ZIP | UNION |
  BUMPING RIGHTS | LOCAL WORKFORCE AREA | REGION NUMBER | TYPE OF COMPANY |
  TYPE OF EVENT | WARN RECEIVED DATE | FIRST LAYOFF DATE |
  ENDING LAYOFF DATE | LAYOFF SCHEDULE | WORKERS AFFECTED | TYPE OF LAYOFF |
  EVENT CAUSES | CEJA RELATED | COUNTY | COMPANY NAICS

Dates in the Excel file are stored as Excel/Python datetime objects.

Archive files (2020 through mid-2025) title the workers column
"# WORKERS AFFECTED" and may carry extra COMPANY CONTACT / PHONE columns;
the header map handles both variants. Multi-worksite filings pack one
number per site into the workers cell ('27   4   2') — summed on parse.
Some archive rows (e.g. Feb 2021) are shifted: an extra layoff date sits in
the workers cell and the true count in TYPE OF LAYOFF — recovered on parse.

Historical PDF era (1999-2019): the same archive page lists one monthly PDF per
month back to 1999. Those are a two-column labeled *form* (not a table), parsed
by ``parse_il_pdf`` for the ``backfill-historical`` path — see that function.
"""
from __future__ import annotations

import io
import re
from datetime import date, datetime
from urllib.parse import unquote

import httpx
import openpyxl
import pdfplumber
from bs4 import BeautifulSoup

from warn_v2.scrapers._helpers import as_date, as_int, as_str, zip_from
from warn_v2.scrapers.base import NoticeRow, ParseFailed, ScrapeFailed
from warn_v2.scrapers.http_cache import conditional_get
from warn_v2.scrapers.registry import register

_ARCHIVE_URL = (
    "https://www.illinoisworknet.com/LayoffRecovery/Pages/ArchivedWARNReports.aspx"
)
_SOURCE_URL = _ARCHIVE_URL
_BASE_URL = "https://www.illinoisworknet.com"

_UA = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
    ),
    "Referer": _ARCHIVE_URL,
}

# Matches href containing MonthlyWARN or Monthly WARN (both .xlsx and .xls)
_XL_HREF_RE = re.compile(r"[Mm]onthly.?[Ww][Aa][Rr][Nn].*\.xlsx?", re.I)

# Workers-affected column header variants: current files use "WORKERS AFFECTED:",
# archive files from 2020 through mid-2025 use "# WORKERS AFFECTED:".
_WORKERS_KEYS = ("WORKERS AFFECTED", "# WORKERS AFFECTED")

# Thousands separator between digits ("1,604" -> "1604").
_THOUSANDS_RE = re.compile(r"(?<=\d),(?=\d{3}\b)")

# Date-shaped cell content: slash/dash-separated digits ('4/14/2021',
# '2021-02-16') or a month name ('Feb 16, 2021').
_DATE_SEP_RE = re.compile(r"\d\s*[/-]\s*\d")
_MONTH_NAME_RE = re.compile(
    r"\b(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\b", re.I
)


def _is_date_shaped(val: object) -> bool:
    """True when a cell holds a date rather than a workers count.

    Some archive files (e.g. Feb 2021) shift part of the row: an extra layoff
    date lands in the WORKERS AFFECTED column and the true count in TYPE OF
    LAYOFF. Digit-summing such a date fabricates a count (4/14/2021 -> 2039).
    """
    if isinstance(val, date):  # datetime is a date subclass
        return True
    s = as_str(val)
    if not s:
        return False
    return bool(_DATE_SEP_RE.search(s) or _MONTH_NAME_RE.search(s))


def _workers_count(val: object) -> int | None:
    """WORKERS AFFECTED cell value -> count.

    Multi-worksite filings pack one number per site into a single
    whitespace-padded cell ('27   4   2', mirroring the address cell) — sum them.
    Date-shaped cells (shifted rows, see _is_date_shaped) yield None.
    """
    if _is_date_shaped(val):
        return None
    n = as_int(val)
    if n is not None:
        return n
    s = as_str(val)
    if not s:
        return None
    tokens = re.findall(r"\d+", _THOUSANDS_RE.sub("", s))
    return sum(int(t) for t in tokens) if tokens else None


def _discover_latest_url() -> str:
    """Scrape the archive page and return the URL of the most recent Excel file."""
    try:
        r = httpx.get(_ARCHIVE_URL, headers=_UA, timeout=30, follow_redirects=True)
        r.raise_for_status()
    except httpx.HTTPError as e:
        raise ScrapeFailed(f"IL: archive page fetch error: {e}") from e

    soup = BeautifulSoup(r.content, "lxml")
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if _XL_HREF_RE.search(href):
            # href may be a relative _layouts/download.aspx?SourceUrl=... wrapper
            # (SourceUrl itself may be absolute or site-relative) or a direct
            # /DownloadPrint/... path.
            if href.startswith("/_layouts"):
                m = re.search(r"SourceUrl=([^&]+)", href)
                if m:
                    url = m.group(1)
                    return url if url.startswith("http") else _BASE_URL + url
            if href.startswith("http"):
                return href
            return _BASE_URL + href
    raise ScrapeFailed("IL: could not find monthly WARN Excel link on archive page")


def _discover_archive_xlsx_urls() -> list[str]:
    """All monthly WARN Excel URLs from the archive page (2020+; page order).

    The archive also lists monthly PDFs back to 1999 — those need a dedicated
    PDF parser and are deliberately excluded here (Wave 3).
    """
    try:
        r = httpx.get(_ARCHIVE_URL, headers=_UA, timeout=60, follow_redirects=True)
        r.raise_for_status()
    except httpx.HTTPError as e:
        raise ScrapeFailed(f"IL: archive page fetch error: {e}") from e

    soup = BeautifulSoup(r.content, "lxml")
    urls: list[str] = []
    for a in soup.find_all("a", href=True):
        href = a["href"]
        # SharePoint wraps files in /_layouts/[15/]download.aspx?SourceUrl=<url>;
        # keep the percent-encoded form (filenames contain spaces).
        m = re.search(r"SourceUrl=([^&\"']+\.xlsx?)(?:&|$)", href, re.I)
        url = m.group(1) if m else None
        if url is not None:
            if not url.startswith("http"):
                url = _BASE_URL + url
        else:
            if re.search(r"\.xlsx?$", href, re.I):
                url = href if href.startswith("http") else _BASE_URL + href
            else:
                continue
        if url not in urls:
            urls.append(url)
    return urls


# ---------------------------------------------------------------------------
# Historical PDF era (monthly archive reports, 1999-2019)
# ---------------------------------------------------------------------------
#
# The PDFs are a two-column labeled form repeated per notice, e.g.
#     COMPANY NAME: Acme Corp            TYPE OF EVENT: Closing
#     COMPANY ADDRESS: 1 Main St         WARN NOTIFIED DATE: 12/2/19
#     CITY, STATE, ZIP: Chicago, IL ...  FIRST LAYOFF DATE: 1/31/20
# page.extract_text() flattens the two columns onto one physical line, gluing a
# left value to the following right label. Rather than split by x (the column
# geometry shifts/compresses between files — e.g. July 2003's right labels start
# ~8px left, bisecting them), we split each visual line at the left-most
# right-column label: the left segment is one left field, the right segment one
# right field. Both segments are then parsed with the same prefix matcher below.
_PDF_FIELD_LABELS = frozenset({
    "COMPANY NAME", "COMPANY ADDRESS", "CITY, STATE, ZIP", "CITY, STATE",
    "LOCAL WORKFORCE AREA", "SUBSTATE AREA & NUMBER",
    "TYPE OF EVENT", "PERMANENT OR TEMPORARY", "WARN NOTIFIED DATE",
    "FIRST LAYOFF DATE", "# WORKERS AFFECTED", "WORKERS AFFECTED",
    "EVENT CAUSES", "COMPANY SIC", "COMPANY NAICS", "COUNTY",
})
# Every label on the form, including ones we don't extract. Unmapped labels must
# still be recognized so they end the previous field instead of being appended to
# it as a wrapped-value continuation. Longest first so 'CITY, STATE, ZIP' wins
# over 'CITY, STATE' and 'COMPANY ADDRESS' over a bare prefix.
_PDF_BOUNDARY_LABELS = sorted(
    _PDF_FIELD_LABELS
    | {
        "COMPANY CONTACT", "TELEPHONE", "UNION", "BUMPING RIGHTS",
        "REGION NUMBER & NAME", "TYPE OF COMPANY", "ENDING LAYOFF DATE",
    },
    key=len,
    reverse=True,
)
# Right-column labels, always colon-terminated in the text — the split point for
# a flattened line. Requiring the colon avoids matching a bare "County" inside a
# left-column value (e.g. an "Orange County" employer name). Longer variants
# first so '# WORKERS AFFECTED' wins over 'WORKERS AFFECTED'.
_PDF_RIGHT_LABEL_RE = re.compile(
    r"(?:# ?WORKERS AFFECTED|WORKERS AFFECTED|TYPE OF EVENT|PERMANENT OR TEMPORARY|"
    r"WARN NOTIFIED DATE|FIRST LAYOFF DATE|ENDING LAYOFF DATE|EVENT CAUSES|"
    r"COMPANY SIC|COMPANY NAICS|COUNTY)\s*:",
    re.I,
)

# A monthly report PDF's filename always contains "WARN"; the WARN Act statute
# PDF (IllinoisWARNSB2665.pdf) also does, but carries no month/year and so is
# dropped by the year filter below.
_PDF_HREF_RE = re.compile(r"warn.*\.pdf$", re.I)
_YEAR_RE = re.compile(r"(?:19|20)\d\d")
_PDF_COUNTY_HDR_RE = re.compile(r"PRIMARY EVENT COUNTY:\s*(.+)", re.I)

# XLSX era; PDFs from this year on are skipped so the same months are not
# re-ingested in a second format.
_PDF_YEAR_END = 2019


def _discover_archive_pdf_urls(year_end: int = _PDF_YEAR_END) -> list[str]:
    """All monthly WARN report PDF URLs from the archive page (1999-``year_end``).

    Mirrors ``_discover_archive_xlsx_urls`` but for the PDF era. PDFs whose year
    is greater than ``year_end`` (the XLSX era, ingested separately) and the
    non-monthly statute PDF are skipped. Returns page order, de-duplicated; the
    percent-encoded form is kept (filenames contain spaces).
    """
    try:
        r = httpx.get(_ARCHIVE_URL, headers=_UA, timeout=60, follow_redirects=True)
        r.raise_for_status()
    except httpx.HTTPError as e:
        raise ScrapeFailed(f"IL: archive page fetch error: {e}") from e

    soup = BeautifulSoup(r.content, "lxml")
    urls: list[str] = []
    for a in soup.find_all("a", href=True):
        href = a["href"]
        m = re.search(r"SourceUrl=([^&\"']+\.pdf)(?:&|$)", href, re.I)
        url = m.group(1) if m else None
        if url is None:
            if re.search(r"\.pdf$", href, re.I):
                url = href if href.startswith("http") else _BASE_URL + href
            else:
                continue
        # Match/date-filter on the decoded filename (the encoded "%20" would let
        # the year regex read "2019" out of "%201999").
        name = unquote(url.rsplit("/", 1)[-1])
        if not _PDF_HREF_RE.search(name):
            continue
        ym = _YEAR_RE.search(name)
        if ym is None or int(ym.group()) > year_end:
            continue
        if url not in urls:
            urls.append(url)
    return urls


def _pdf_lines(words: list[dict]) -> list[list[dict]]:
    """Group extract_words() output into visual lines (by ``top``), each sorted
    left-to-right by ``x0``."""
    out: list[list[dict]] = []
    cur: list[dict] = []
    cy: float | None = None
    for w in sorted(words, key=lambda w: w["top"]):
        if cy is None or abs(w["top"] - cy) <= 3.0:
            cur.append(w)
            cy = cy if cy is not None else w["top"]
        else:
            out.append(sorted(cur, key=lambda w: w["x0"]))
            cur = [w]
            cy = w["top"]
    if cur:
        out.append(sorted(cur, key=lambda w: w["x0"]))
    return out


def _pdf_split_label(text: str) -> tuple[str | None, str]:
    """('COMPANY NAME: Foo') -> ('COMPANY NAME', 'Foo'); a line not starting with
    a known label returns (None, text) so it can continue the previous field."""
    up = text.upper()
    for lab in _PDF_BOUNDARY_LABELS:
        if up.startswith(lab):
            return lab, text[len(lab):].lstrip(": ").strip()
    return None, text


def _pdf_record_to_row(rec: dict[str, str], source_url: str | None) -> NoticeRow | None:
    """Build a NoticeRow from one collected notice block, or None if empty."""
    employer = as_str(rec.get("COMPANY NAME"))
    if not employer:
        return None
    employer = " ".join(employer.split())

    # Drop rows with no filing date (mirrors the XLSX parser and dedup, which key
    # on notice_date). This also discards the 1999 legend/instructions block,
    # whose label placeholders parse as a dateless pseudo-notice.
    notice_date = as_date(rec.get("WARN NOTIFIED DATE"))
    if notice_date is None:
        return None

    city_state_zip = rec.get("CITY, STATE, ZIP") or rec.get("CITY, STATE")
    workers = rec.get("# WORKERS AFFECTED") or rec.get("WORKERS AFFECTED")
    # PDF workers cells are a clean number or "Not Provided"; as_int drops the
    # latter to None.
    layoff_count = as_int(workers) if workers else None

    street = as_str(rec.get("COMPANY ADDRESS"))
    address = ", ".join(p for p in (street, as_str(city_state_zip)) if p) or None

    # SIC (1999-2005) and NAICS (2010+) are different taxonomies; keep SIC out of
    # naics_code (read as NAICS downstream) and stash it in extra instead.
    sic = as_str(rec.get("COMPANY SIC"))

    extra: dict[str, str] = {}
    layoff_type = as_str(rec.get("PERMANENT OR TEMPORARY"))
    if layoff_type:
        extra["layoff_type"] = layoff_type
    event_causes = as_str(rec.get("EVENT CAUSES"))
    if event_causes:
        extra["event_causes"] = event_causes
    workforce_area = as_str(rec.get("LOCAL WORKFORCE AREA")) or as_str(
        rec.get("SUBSTATE AREA & NUMBER")
    )
    if workforce_area:
        extra["workforce_area"] = workforce_area
    if sic:
        extra["sic_code"] = sic

    return NoticeRow(
        state="IL",
        employer=employer,
        notice_date=notice_date,
        effective_date=as_date(rec.get("FIRST LAYOFF DATE")),
        layoff_count=layoff_count,
        city=_parse_city(city_state_zip),
        county=as_str(rec.get("COUNTY")) or as_str(rec.get("_county_hdr")),
        zip=zip_from(city_state_zip),
        address=address,
        closure_type=as_str(rec.get("TYPE OF EVENT")),
        naics_code=as_str(rec.get("COMPANY NAICS")),
        source_url=source_url or _SOURCE_URL,
        extra=extra,
    )


def parse_il_pdf(raw: bytes, source_url: str | None = None) -> list[NoticeRow]:
    """Parse a monthly IL WARN archive PDF (1999-2019 label-form era).

    The report is a two-column labeled form repeated per notice. Each visual line
    is split at the left-most right-column label (see ``_PDF_RIGHT_LABEL_RE``)
    into a left field and a right field, and each ``LABEL: value`` pair is
    collected into the current notice block; a ``COMPANY NAME`` label starts a new
    block. A leading non-label segment continues the previous field on that side
    (wrapped company names / addresses / causes). 1999 has no per-notice county —
    notices sit under centered ``PRIMARY EVENT COUNTY`` section headers, tracked
    here and applied to those blocks.
    """
    try:
        pdf = pdfplumber.open(io.BytesIO(raw))
    except Exception as e:
        raise ParseFailed(f"IL PDF: could not open: {e}") from e

    records: list[dict[str, str]] = []
    cur: dict[str, str] | None = None
    county_hdr: str | None = None
    last_field: dict[str, str | None] = {"L": None, "R": None}

    with pdf:
        for page in pdf.pages:
            for lws in _pdf_lines(page.extract_words()):
                full = " ".join(w["text"] for w in lws).strip()
                # 1999 groups notices under centered county section headers
                # (checked before the split — the header itself ends in COUNTY:).
                m = _PDF_COUNTY_HDR_RE.match(full)
                if m:
                    county_hdr = m.group(1).strip()
                    continue
                if full.startswith("STATE OF ILLINOIS") or full.startswith("MONTH "):
                    continue  # page banner
                # Split the flattened line into its left field and right field at
                # the left-most right-column label.
                rm = _PDF_RIGHT_LABEL_RE.search(full)
                left = (full[: rm.start()] if rm else full).strip()
                right = (full[rm.start():] if rm else "").strip()
                for side, text in (("L", left), ("R", right)):
                    if not text:
                        continue
                    lab, val = _pdf_split_label(text)
                    if lab == "COMPANY NAME":
                        cur = {"_county_hdr": county_hdr} if county_hdr else {}
                        cur["COMPANY NAME"] = val
                        records.append(cur)
                        last_field["L"] = "COMPANY NAME"
                        last_field["R"] = None
                    elif cur is None:
                        continue
                    elif lab is not None:
                        cur[lab] = val
                        last_field[side] = lab
                    else:
                        prev = last_field[side]
                        if prev and val:
                            cur[prev] = (cur.get(prev, "") + " " + val).strip()

        rows = [
            row
            for row in (_pdf_record_to_row(rec, source_url) for rec in records)
            if row is not None
        ]

    if not rows:
        raise ParseFailed("IL PDF: no notices found")
    return rows


def _as_date(val: object) -> date | None:
    """Convert an openpyxl cell value (datetime or None) to a date."""
    if val is None:
        return None
    if isinstance(val, datetime):
        return val.date()
    if isinstance(val, date):
        return val
    # fallback: try string
    from warn_v2.scrapers._helpers import as_date

    return as_date(str(val))


def _parse_city(city_state_zip: str | None) -> str | None:
    """Extract city from 'City, IL 60544' formatted strings."""
    if not city_state_zip:
        return None
    return city_state_zip.split(",")[0].strip() or None


class ILScraper:
    state = "IL"
    source_url = _SOURCE_URL
    expected_row_range = (1, 10_000)
    required_fields = frozenset({"employer", "notice_date"})

    def fetch(self) -> bytes:
        # Discovery GET stays unconditional; the monthly XLSX download is
        # conditional (a new month means a new URL, i.e. a plain first fetch).
        xl_url = _discover_latest_url()
        try:
            return conditional_get(xl_url, state=self.state, headers=_UA, timeout=60)
        except httpx.HTTPError as e:
            raise ScrapeFailed(f"IL: GET {xl_url}: {e}") from e

    def parse(self, raw: bytes) -> list[NoticeRow]:
        try:
            wb = openpyxl.load_workbook(io.BytesIO(raw), data_only=True, read_only=True)
        except Exception as e:
            raise ParseFailed(f"IL Excel: could not open: {e}") from e

        ws = wb.active
        rows: list[NoticeRow] = []
        header: dict[str, int] = {}
        workers_key: str | None = None

        for row_idx, row in enumerate(ws.iter_rows(values_only=True)):
            # Build header map from first row
            if row_idx == 0:
                for col_idx, val in enumerate(row):
                    if val is not None:
                        key = " ".join(str(val).split()).upper().rstrip(":")
                        header[key] = col_idx
                workers_key = next((k for k in _WORKERS_KEYS if k in header), None)
                continue

            current_row = row  # bind loop variable for closure

            def _col(name: str, _r: tuple = current_row) -> object:
                idx = header.get(name, -1)
                return _r[idx] if 0 <= idx < len(_r) else None

            employer_raw = _col("COMPANY NAME")
            if employer_raw is None:
                continue
            employer = " ".join(str(employer_raw).split())
            if not employer:
                continue

            notice_date = _as_date(_col("WARN RECEIVED DATE"))
            if notice_date is None:
                continue

            effective_date = _as_date(_col("FIRST LAYOFF DATE"))
            workers_raw = _col(workers_key) if workers_key else None
            layoff_count = _workers_count(workers_raw)
            layoff_type = as_str(_col("TYPE OF LAYOFF")) or None
            if layoff_count is None and _is_date_shaped(workers_raw):
                # Shifted row: the count sits one column right, in TYPE OF
                # LAYOFF (which then holds no real layoff type).
                shifted = as_int(_col("TYPE OF LAYOFF"))
                if shifted is not None:
                    layoff_count = shifted
                    layoff_type = None

            city_state_zip = as_str(_col("CITY, STATE, ZIP")) or None
            city = _parse_city(city_state_zip)
            zip_code = zip_from(city_state_zip)
            county = as_str(_col("COUNTY")) or None
            company_address = as_str(_col("COMPANY ADDRESS")) or None
            # Combine street + "City, State ZIP" into one mailing-address string.
            address_parts = [p for p in (company_address, city_state_zip) if p]
            address = ", ".join(address_parts) if address_parts else None
            closure_type = as_str(_col("TYPE OF EVENT")) or None
            event_causes = as_str(_col("EVENT CAUSES")) or None
            naics_raw = _col("COMPANY NAICS")
            if isinstance(naics_raw, (int, float)):
                naics = str(int(naics_raw))
            else:
                naics = as_str(naics_raw) or None

            rows.append(
                NoticeRow(
                    state="IL",
                    employer=employer,
                    notice_date=notice_date,
                    effective_date=effective_date,
                    layoff_count=layoff_count,
                    city=city,
                    county=county,
                    zip=zip_code,
                    address=address,
                    closure_type=closure_type,
                    naics_code=naics,
                    source_url=_SOURCE_URL,
                    extra={
                        "layoff_type": layoff_type,
                        "event_causes": event_causes,
                        "workforce_area": as_str(_col("LOCAL WORKFORCE AREA")) or None,
                    },
                )
            )

        wb.close()

        if not rows:
            raise ParseFailed("IL Excel: no data rows found")
        return rows


register(ILScraper())
