"""California WARN scraper.

Source: https://edd.ca.gov/Jobs_and_Training/warn/WARN_Report.xlsx
Format: XLSX, header on a row that is *not* row 0 (varies year-to-year).

Vs V1 (which used hardcoded `header=3` and `iloc[:-2, [0,1,2,4,5,8,10,12]]`),
this scraper finds the header row by name-matching and reads columns by name —
so a column reorder or extra blank top rows doesn't break it.
"""
from __future__ import annotations

import io
import re

import httpx
import pandas as pd

from warn_v2.scrapers._helpers import (
    ColumnMap,
    as_date,
    as_int,
    as_str,
    city_from_address,
    norm,
    zip_from,
)
from warn_v2.scrapers.base import NoticeRow, ParseFailed, ScrapeFailed
from warn_v2.scrapers.http_cache import conditional_get
from warn_v2.scrapers.registry import register

SOURCE_URL = "https://edd.ca.gov/Jobs_and_Training/warn/WARN_Report.xlsx"
_ARCHIVE_PAGE = "https://edd.ca.gov/Jobs_and_Training/Layoff_Services_WARN.htm"
_UA = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
    )
}

# --- Historical archive (pre-FY2014) via the Wayback Machine ---------------
# The live archive page only lists FY2014+ reports; EDD's calendar-year listings
# 2006-2014 survive only in web.archive.org.  We ingest the *detailed* listing
# variants (`eddwarncn{da,dbd,del,dmr,ds,dtz}{YY}.pdf`, an A-Z alphabet split) —
# unlike the simple `cn{YY}.pdf` they carry the real notice-received date and a
# street address, so every row gets a unique dedup hash.  See
# docs/historical-sources.md (CA row) for the probe write-up.
_CDX_API = "https://web.archive.org/cdx/search/cdx"
_WAYBACK_REPLAY = "https://web.archive.org/web/{ts}id_/{url}"
# Escalating backoff (seconds) between CDX discovery retries; 5 attempts total
# (the four gaps below + a final attempt) span ~110s to outlast a Wayback flap.
_CDX_RETRY_BACKOFFS = (5, 15, 30, 60)
# da(1-A) dbd(B-D) del(E-L) dmr(M-R) ds(S-S) dtz(T-Z); YY = 06..14.
_CA_DETAIL_RE = re.compile(r"eddwarncn(?:da|dbd|del|dmr|ds|dtz)(\d{2})\.pdf$", re.I)


def _discover_archive_urls() -> list[str]:
    """Scrape EDD WARN archive page; return absolute URLs for all historical files.

    EDD publishes fiscal-year WARN reports as PDFs (and occasionally XLSX).
    Excludes the current-year XLSX (WARN_Report.xlsx) handled by the regular scraper.
    """
    from bs4 import BeautifulSoup

    try:
        r = httpx.get(_ARCHIVE_PAGE, headers=_UA, timeout=30, follow_redirects=True)
        r.raise_for_status()
    except httpx.HTTPError as e:
        raise ScrapeFailed(f"CA archive page: {e}") from e

    soup = BeautifulSoup(r.text, "html.parser")
    base = "https://edd.ca.gov"
    urls: list[str] = []
    for a in soup.find_all("a", href=True):
        href: str = a["href"]
        lower = href.lower()
        if not (lower.endswith(".xlsx") or lower.endswith(".pdf")):
            continue
        if "warn" not in lower:
            continue
        if href == "/Jobs_and_Training/warn/WARN_Report.xlsx":
            continue
        full = href if href.startswith("http") else base + href
        if full not in urls:
            urls.append(full)
    return urls


# Keep the old name as an alias so existing code / tests don't break.
_discover_archive_xlsx_urls = _discover_archive_urls

# Purely-numeric token pattern — used to reject summary/total rows where the
# "Company" cell contains a count or total (e.g. "134", "1,292") rather than a
# real company name.  Real names always contain at least one letter.
_NUMERIC_RE = re.compile(r"^[\d,.\s]+$")


def _is_numeric_token(s: str) -> bool:
    """Return True if *s* consists only of digits, commas, dots, and spaces.

    Used to skip EDD XLSX summary rows where the company cell holds a case-count
    or employee-total rather than an employer name.
    """
    return bool(_NUMERIC_RE.fullmatch(s))


# Tolerate minor renames; first match wins.
_COMPANY_KEYS = ("company", "employer", "company name")
_NOTICE_DATE_KEYS = ("notice date", "received date", "date received")
_EFFECTIVE_DATE_KEYS = ("effective date", "layoff date")
# "employees" (bare) matches the FY2019-20 archive PDF, whose header column is
# just "Employees" rather than "No. Of Employees" — without it that whole file
# parses to a zero layoff count.
_LAYOFF_COUNT_KEYS = (
    "no. of employees",
    "number of employees",
    "employees affected",
    "employees",
)
_COUNTY_KEYS = ("county/parish", "county")
_CITY_KEYS = ("city",)
_ZIP_KEYS = ("zip", "zip code")
_ADDRESS_KEYS = ("address", "location address")
# EDD wraps this header inside the cell ("Layoff/\nClosure"); norm() collapses
# the newline to a space, so the wrapped spelling is "layoff/ closure".
_TYPE_KEYS = ("layoff/closure", "layoff/ closure", "type", "closure type")


class CAScraper:
    state = "CA"
    source_url = SOURCE_URL
    expected_row_range = (10, 10_000)
    required_fields = frozenset({"employer", "notice_date"})

    def fetch(self) -> bytes:
        try:
            return conditional_get(self.source_url, state=self.state, timeout=60)
        except httpx.HTTPError as e:
            raise ScrapeFailed(f"GET {self.source_url}: {e}") from e

    def parse(self, raw: bytes) -> list[NoticeRow]:
        try:
            df = _read_with_header_detection(raw)
        except Exception as e:
            raise ParseFailed(f"could not read xlsx: {e}") from e
        return _parse_df(df)


def _parse_df(df: pd.DataFrame) -> list[NoticeRow]:
    """Convert a CA WARN DataFrame (from XLSX or PDF) to NoticeRows."""
    col = ColumnMap(df.columns)
    rows: list[NoticeRow] = []
    for _, r in df.iterrows():
        employer = col.get(r, _COMPANY_KEYS)
        employer_str = as_str(employer)
        if not employer_str:
            continue
        # Reject rows whose "company" cell is a bare number (digits/commas/dots).
        # These come from EDD summary/totals sections at the bottom of the sheet
        # (e.g. county case-counts "134", employee totals "1,292").  Real company
        # names always contain at least one letter.
        if _is_numeric_token(employer_str):
            continue
        notice_date = as_date(col.get(r, _NOTICE_DATE_KEYS))
        layoff_count = as_int(col.get(r, _LAYOFF_COUNT_KEYS))
        # Skip footer/summary rows: real notices always have at least one of
        # notice_date or layoff_count. Summary lines ("Total notices: N")
        # have neither.
        if notice_date is None and layoff_count is None:
            continue
        address = col.get(r, _ADDRESS_KEYS)
        rows.append(NoticeRow(
            state="CA",
            employer=employer_str,
            notice_date=notice_date,
            effective_date=as_date(col.get(r, _EFFECTIVE_DATE_KEYS)),
            layoff_count=layoff_count,
            closure_type=as_str(col.get(r, _TYPE_KEYS)),
            county=as_str(col.get(r, _COUNTY_KEYS)),
            city=as_str(col.get(r, _CITY_KEYS)) or city_from_address(address),
            zip=zip_from(col.get(r, _ZIP_KEYS), address),
            address=as_str(address),
            source_url=SOURCE_URL,
        ))
    return rows


def parse_ca_pdf(raw: bytes) -> list[NoticeRow]:
    """Parse a CA EDD historical WARN PDF report.

    EDD fiscal-year WARN PDFs contain a multi-page table with the same columns
    as the current-year XLSX. Uses pdfplumber to extract the table, then applies
    the same flexible column-name matching as the XLSX parser.
    """
    try:
        df = _read_ca_pdf(raw)
    except ParseFailed:
        raise
    except Exception as e:
        raise ParseFailed(f"CA PDF: {e}") from e
    return _parse_df(df)


def _read_ca_pdf(raw: bytes) -> pd.DataFrame:
    """Extract the WARN notice table from a CA EDD PDF report as a DataFrame."""
    import pdfplumber

    all_rows: list[list[str]] = []
    header: list[str] | None = None

    with pdfplumber.open(io.BytesIO(raw)) as pdf:
        for page in pdf.pages:
            table = page.extract_table()
            if not table:
                continue
            for row in table:
                if row is None:
                    continue
                cells = [str(c or "").strip() for c in row]
                if not any(cells):
                    continue
                cells_lower = [c.lower() for c in cells]
                if any(k in cells_lower for k in _COMPANY_KEYS):
                    if header is None:
                        header = cells  # preserve original case for ColumnMap
                    continue  # skip header rows, including repeated ones per page
                if header is not None:
                    all_rows.append(cells)

    if header is None:
        raise ParseFailed("CA PDF: could not find header row")
    if not all_rows:
        raise ParseFailed("CA PDF: no data rows found")

    n = len(header)
    padded = [row[:n] + [""] * max(0, n - len(row)) for row in all_rows]
    return pd.DataFrame(padded, columns=header)


def _read_with_header_detection(raw: bytes) -> pd.DataFrame:
    """Find the header row by scanning the first 10 rows for a known company-column name.

    EDD publishes a multi-sheet workbook (Index, WARN Report Summary,
    Detailed WARN Report). We pick the first sheet whose name contains
    'detail' (case-insensitive), falling back to the last sheet.
    """
    buf = io.BytesIO(raw)
    xf = pd.ExcelFile(buf, engine="openpyxl")
    sheet_name = next(
        (s for s in xf.sheet_names if "detail" in s.lower()),
        xf.sheet_names[-1],
    )
    probe = xf.parse(sheet_name, header=None, nrows=10)
    header_row = None
    for i, row in probe.iterrows():
        cells = [str(c).strip().lower() for c in row.tolist() if pd.notna(c)]
        if any(k in cells for k in _COMPANY_KEYS):
            header_row = i
            break
    if header_row is None:
        raise ParseFailed("could not locate header row containing 'Company'")
    df = xf.parse(sheet_name, header=header_row)
    # Drop trailing summary rows; detect by missing company.
    df = df.dropna(subset=[c for c in df.columns if norm(c) in _COMPANY_KEYS])
    return df


def _discover_ca_historical_urls() -> list[str]:
    """Wayback replay URLs for EDD's pre-FY2014 *detailed* WARN listing PDFs.

    Queries the CDX index for `edd.ca.gov/.../warn/` captures, keeps only the
    detailed alphabet-split files (`_CA_DETAIL_RE`, years 2006-2014), and returns
    the latest 200 capture per filename — the earlier captures are rolling
    year-to-date snapshots, so only the last one holds the complete calendar year.
    """
    import time

    # web.archive.org flaps under load — refusing connections (Errno 111) for
    # seconds at a time. Discovery is a single upfront call and a lost one
    # no-ops the whole run, so retry with escalating backoff (like the fetch
    # loop) to ride the flap out rather than the old 2-attempt/5s try.
    captures = None
    for backoff in (*_CDX_RETRY_BACKOFFS, None):
        try:
            r = httpx.get(
                _CDX_API,
                params={
                    "url": "edd.ca.gov/jobs_and_training/warn/",
                    "matchType": "prefix",
                    "output": "json",
                    "fl": "timestamp,original",
                    # Server-side filters keep the response under the row cap and
                    # spare us the simple/local variants we don't ingest.
                    "filter": ["statuscode:200", r"original:.*eddwarncnd.*\.pdf"],
                    "collapse": "urlkey",
                    "limit": "5000",
                },
                headers=_UA,
                timeout=120,
            )
            r.raise_for_status()
            captures = r.json()
            break
        except (httpx.HTTPError, ValueError) as e:
            if backoff is None:
                raise ScrapeFailed(f"CA: CDX query for historical PDFs: {e}") from e
            time.sleep(backoff)

    if not isinstance(captures, list):
        return []
    # filename -> (latest_ts, original_url); the ".pdf" match is on the filename
    # so scheme/host variants collapse together.
    best: dict[str, tuple[str, str]] = {}
    for cap in captures[1:]:  # row 0 is the field-name header
        if not (isinstance(cap, list) and len(cap) == 2):
            continue
        ts, original = str(cap[0]), str(cap[1])
        m = _CA_DETAIL_RE.search(original)
        if m is None:
            continue
        fname = m.group(0).lower()
        if fname not in best or ts > best[fname][0]:
            best[fname] = (ts, original)
    return [
        _WAYBACK_REPLAY.format(ts=ts, url=original)
        for _fname, (ts, original) in sorted(best.items())
    ]


# --- Detailed-PDF block parser --------------------------------------------
# Fixed-column layout (verified 2006-2014): employer + address at x0<300, the
# count and effective (layoff) date in a 300-425 middle band, and the Local
# Workforce Investment Area wrapping down the right column at x0>=425.  The
# per-record job-title breakdown and the notice/closure metadata sit on their
# own labelled lines.  `extract_text` glues the LWIA column onto the address, so
# we parse from word positions instead.
_CID_RE = re.compile(r"\(cid:\d+\)")
_DATE_TOKEN_RE = re.compile(r"^\d{1,2}/\d{1,2}/\d{4}$")
_NOTICE_DATE_RE = re.compile(r"Date Notice Received:\s*(\d{1,2}/\d{1,2}/\d{4})")
_CLOSURE_RE = re.compile(r"Layoff or Closure:\s*([A-Za-z/ ]+?)(?:\s{2,}|$)")
_CITYLINE_RE = re.compile(r",\s*[A-Z]{2}\.?\s+\d{5}\b")
# The ZIP is the 5-digit group after the state code — not the first 5-digit run,
# which on these records is often a 5-digit street number (e.g. "26531 YNEZ RD").
_ZIP_AFTER_STATE_RE = re.compile(r"\b[A-Z]{2}\.?\s+(\d{5})(?:-\d{4})?\b")
_PAGE_CHROME_RE = re.compile(r"^(rev\.|page\s+\d+\s+of\s)", re.I)
# x-coordinate bands (page width 612).
_LEFT_MAX = 300.0   # employer / address column
_REGION_MIN = 425.0  # Local Workforce Investment Area column (dropped)


def _clean(text: str) -> str:
    return " ".join(_CID_RE.sub(" ", text).split())


def _detail_lines(raw: bytes) -> list[list[dict]]:
    """Return every text line as a list of ``{'text','x0'}`` words, in page order."""
    import pdfplumber

    lines: list[list[dict]] = []
    with pdfplumber.open(io.BytesIO(raw)) as pdf:
        for page in pdf.pages:
            rows: dict[int, list[dict]] = {}
            for w in page.extract_words(use_text_flow=False):
                text = _clean(w["text"])
                if not text:
                    continue
                rows.setdefault(round(w["top"]), []).append(
                    {"text": text, "x0": float(w["x0"])}
                )
            for top in sorted(rows):
                lines.append(sorted(rows[top], key=lambda d: d["x0"]))
    return lines


def _is_record_header(words: list[dict]) -> bool:
    """A record starts on the line carrying the effective date in the middle band.

    The 'Date Notice Received' line also holds a 4-digit date, but it lands in the
    right (LWIA) column at x0>=425, so the band check alone separates them; the
    keyword guard is belt-and-suspenders.
    """
    has_employer = any(w["x0"] < _LEFT_MAX for w in words)
    has_mid_date = any(
        _DATE_TOKEN_RE.match(w["text"]) and _LEFT_MAX <= w["x0"] < _REGION_MIN
        for w in words
    )
    if not (has_employer and has_mid_date):
        return False
    joined = " ".join(w["text"] for w in words).lower()
    return "date notice received" not in joined and "company contact" not in joined


def parse_ca_detail_pdf(raw: bytes, source_url: str | None = None) -> list[NoticeRow]:
    """Parse an EDD *detailed* historical WARN PDF (2006-2014) into NoticeRows.

    One PDF is an alphabet slice (e.g. B-D) of a calendar year; the discovery
    layer supplies the six slices per year.  Dates come from the record itself,
    so the parser is year-agnostic.
    """
    try:
        lines = _detail_lines(raw)
    except Exception as e:
        raise ParseFailed(f"CA detail PDF: {e}") from e

    header_idx = [i for i, ln in enumerate(lines) if _is_record_header(ln)]
    if not header_idx:
        raise ParseFailed("CA detail PDF: no WARN record headers found")

    rows: list[NoticeRow] = []
    for k, start in enumerate(header_idx):
        end = header_idx[k + 1] if k + 1 < len(header_idx) else len(lines)
        row = _parse_detail_block(lines[start:end], source_url)
        if row is not None:
            rows.append(row)
    return rows


def _parse_detail_block(block: list[list[dict]], source_url: str | None) -> NoticeRow | None:
    header = block[0]
    date_word = next(
        (w for w in header if _DATE_TOKEN_RE.match(w["text"]) and w["x0"] < _REGION_MIN),
        None,
    )
    if date_word is None:
        return None
    effective_date = as_date(date_word["text"])

    # Count: the integer token in the middle band, left of the date. When the
    # employer didn't state it the cell reads "EDNS" (→ None). Employer text lives
    # in the fixed left column, so cut there — never sweep in the count/EDNS token.
    count = None
    for w in header:
        if _LEFT_MAX <= w["x0"] < date_word["x0"]:
            c = as_int(w["text"])
            if c is not None:
                count = c
                break
    employer_parts = [w["text"] for w in header if w["x0"] < _LEFT_MAX]

    address_lines: list[str] = []
    address_started = False
    notice_date = None
    closure = None
    for ln in block[1:]:
        joined = " ".join(w["text"] for w in ln)
        low = joined.lower()
        if _PAGE_CHROME_RE.match(low):
            continue
        if "date notice received" in low or "company contact" in low:
            m = _NOTICE_DATE_RE.search(joined)
            if m:
                notice_date = as_date(m.group(1))
            address_started = True  # metadata block begins; stop taking address
            continue
        if "layoff or closure" in low:
            m = _CLOSURE_RE.search(joined)
            if m:
                closure = m.group(1).strip()
            continue
        if "job title:" in low:
            break
        if notice_date is not None or closure is not None:
            continue  # already past the address, inside metadata / job titles
        left = " ".join(w["text"] for w in ln if w["x0"] < _REGION_MIN).strip()
        if not left:
            continue
        looks_addr = (
            left[:1].isdigit()
            or bool(_CITYLINE_RE.search(left))
            or left.upper().startswith(("PO BOX", "P.O", "P O"))
        )
        if looks_addr:
            address_lines.append(left)
            address_started = True
        elif not address_started:
            employer_parts.append(left)  # wrapped employer name
        # else: stray line after the address block — ignore

    employer = _clean(" ".join(employer_parts))
    if not employer:
        return None
    address = ", ".join(address_lines) or None
    zip_code = None
    if address:
        m = _ZIP_AFTER_STATE_RE.search(address)
        zip_code = m.group(1) if m else zip_from(None, address)
    return NoticeRow(
        state="CA",
        employer=employer,
        notice_date=notice_date,
        effective_date=effective_date,
        layoff_count=count,
        closure_type=closure,
        city=city_from_address(address),
        zip=zip_code,
        address=address,
        source_url=source_url or SOURCE_URL,
    )


register(CAScraper())
