"""Mississippi WARN scraper.

Source: https://mdes.ms.gov/information-center/warn-information/
Data:   Quarterly PDF reports; one PDF per quarter.

Schema (as of early 2026):
  Date of Notice | Company Name | City | County | Workforce Area |
  Event Number | NAICS CODE & Description | (merged cols) |
  Type of Action | Number Affected | Date of Action | Reason/Comments

fetch() discovers all quarterly PDF URLs from the landing page and downloads
the most recent one.  Each quarterly PDF covers roughly three months of
notices (15-30 rows).

Multi-line cells (Company Name, Workforce Area, etc.) are joined with a space.
Continuation rows where col 0 is None are skipped.
The Date of Action field occasionally uses "." instead of "/" as the separator
(e.g. "4/3.2026"); we normalise that before parsing.

Three layout eras:
  - PY2025+ ("modern"): one label per header cell, separate City/County columns.
  - PY2020-PY2022 ("merged"): employer and "City (County)" share one column.
  - PY2023-PY2024 ("stacked"): merged location plus header labels stacked
    across several rows and ghost grid columns; see
    _parse_stacked_header_tables().

Historical backfill (Wayback replay, see _discover_ms_archive_urls) adds a
fourth family, dispatched on the title's "PROGRAM YEAR <= 2019":
  - 2004-2006 + PY2010-PY2019 ("archive"): "# Affected" stacked under
    "Type of Action" with the count on its own continuation grid row, an
    "Impact Date"/"Date of Action" column, SIC+NAICS descriptions (2004-06),
    and a Reason/Comments column that flags non-WARN Rapid Response events
    ("Non-WARN ..."), which are filtered out; see _parse_archive_tables().
"""
from __future__ import annotations

import io
import re

import httpx
import pdfplumber
from bs4 import BeautifulSoup

from warn_v2.scrapers._helpers import as_date, as_str
from warn_v2.scrapers.base import NoticeRow, ParseFailed, ScrapeFailed
from warn_v2.scrapers.http_cache import conditional_get
from warn_v2.scrapers.registry import register

_LANDING_URL = "https://mdes.ms.gov/information-center/warn-information/"
_BASE_URL = "https://mdes.ms.gov"
_FALLBACK_URL = (
    "https://mdes.ms.gov/media/502986/warn-py2025-qtr-3-jan-mar-2026.pdf"
)

_UA = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) warn-v2/0.1"
    )
}

_PDF_HREF = re.compile(r"/media/\d+/warn[^\"']*\.pdf", re.I)
_LEADING_INT = re.compile(r"\d+")
_DATE_CELL_RE = re.compile(r"^\d{1,2}/\d{1,2}/\d{2,4}$")


def _discover_pdf_urls() -> list[str]:
    """Return all quarterly WARN PDF URLs from the landing page (most-recent first)."""
    try:
        r = httpx.get(_LANDING_URL, headers=_UA, timeout=30, follow_redirects=True)
        r.raise_for_status()
        soup = BeautifulSoup(r.content, "html.parser")
        urls: list[str] = []
        for a in soup.find_all("a", href=True):
            href: str = a["href"]
            if _PDF_HREF.match(href):
                url = href if href.startswith("http") else _BASE_URL + href
                if url not in urls:
                    urls.append(url)
        return urls or [_FALLBACK_URL]
    except httpx.HTTPError:
        return [_FALLBACK_URL]


# Historical quarterlies the live hub no longer links, pinned to the Wayback
# captures verified offline on 2026-07-10 (docs/backfill-milestones.md "MS").
# One URL per distinct quarter: content-duplicate captures (the 6A/CH mirror
# pairs of 2004-06, the mislabeled py2014_q2/py2015_q3 re-uploads and the
# py2019_q2-named copy of PY2020-Q2) are collapsed, `_map.pdf` companions and
# PY2020+ quarters prod already has are excluded.  PY2023-Q4 is included:
# the hub run predates its publication.  Wayback redirects a near-miss
# timestamp to the closest capture, so replay follows redirects.
_WAYBACK_REPLAY = "https://web.archive.org/web/{ts}id_/{url}"
_ARCHIVE_CAPTURES: tuple[tuple[str, str], ...] = (
    # --- 2004-2006 era (filename year/quarter is unreliable; the in-PDF
    #     header carries the real period) ---
    ("20060929145342", "http://www.mdes.ms.gov/wps/PA_1_0_6A/docs/Employer/Warn2004Q1.pdf"),
    ("20060929145408", "http://www.mdes.ms.gov/wps/PA_1_0_6A/docs/Employer/Warn2004Q2.pdf"),
    ("20060929145304", "http://www.mdes.ms.gov/wps/PA_1_0_6A/docs/Employer/Warn2004Q3.pdf"),
    ("20060929145352", "http://www.mdes.ms.gov/wps/PA_1_0_6A/docs/Employer/Warn2004Q4.pdf"),
    ("20060929145333", "http://www.mdes.ms.gov/wps/PA_1_0_6A/docs/Employer/Warn2005Q1.pdf"),
    ("20060929145429", "http://www.mdes.ms.gov/wps/PA_1_0_6A/docs/Employer/WARN2005Q2.pdf"),
    ("20070509014836", "http://mdes.ms.gov:80/wps/PA_1_0_CH/docs/Employer/WARN2005Q3.pdf"),
    ("20070509014037", "http://mdes.ms.gov:80/wps/PA_1_0_CH/docs/Employer/WARN2005Q4.pdf"),
    ("20070509014344", "http://mdes.ms.gov:80/wps/PA_1_0_CH/docs/Employer/WARN2006Q1.pdf"),
    ("20070509015608", "http://mdes.ms.gov:80/wps/PA_1_0_CH/docs/Employer/WARN2006Q2.pdf"),
    ("20070509015301", "http://mdes.ms.gov:80/wps/PA_1_0_CH/docs/Employer/WARN2006Q3.pdf"),
    # --- PY2010-PY2019 quarterlies ---
    ("20260614000218", "https://mdes.ms.gov/media/26881/PY2010_Q1_WARN_Jul2010_Sep2010.pdf"),
    ("20250613034721", "https://mdes.ms.gov/media/26884/PY2010_Q2_WARN_Oct2010_Dec2010.pdf"),
    ("20161221092424", "http://mdes.ms.gov/media/26887/PY2010_Q3_WARN_Jan2011_Mar2011.pdf"),
    ("20250613034726", "https://mdes.ms.gov/media/26890/PY2010_Q4_WARN_Apr2011_Jun2011.pdf"),
    ("20250613034655", "https://mdes.ms.gov/media/26893/PY2011_Q1_WARN_July2011_Sep2011.pdf"),
    ("20260430183654", "https://mdes.ms.gov/media/26896/PY2011_Q2_WARN_Oct2011_Dec2011.pdf"),
    ("20260418060411", "https://mdes.ms.gov/media/26899/PY2011_Q3_WARN_Jan2012_Mar2012.pdf"),
    ("20250613034712", "https://mdes.ms.gov/media/26958/PY2011_Q4_WARN_Apr2012_Jun2012.pdf"),
    ("20250613034638", "https://mdes.ms.gov/media/26905/PY2012_Q1_WARN_Jul2012_Sep2012.pdf"),
    ("20260424102333", "https://mdes.ms.gov/media/26908/PY2012_Q2_WARN_Oct2012_Dec2012.pdf"),
    ("20250613034648", "https://mdes.ms.gov/media/26911/PY2012_Q3_WARN__Jan2013_Mar2013.pdf"),
    ("20260529141758", "https://mdes.ms.gov/media/29948/PY2012_Q4_WARN_Apr2013_Jun2013.pdf"),
    ("20250613034630", "https://mdes.ms.gov/media/30968/PY2013_Q1_WARN_Jul2013_Sep2013.pdf"),
    ("20250613034626", "https://mdes.ms.gov/media/31723/PY2013_Q2__WARN_Oct2013_Dec2013.pdf"),
    ("20250613034615", "https://mdes.ms.gov/media/33167/PY2013_Q3__WARN_Jan2014_Mar2014.pdf"),
    ("20260512203953", "https://mdes.ms.gov/media/35197/PY2013_Q4__WARN_Apr2014_Jun2014.pdf"),
    ("20260611074053", "https://mdes.ms.gov/media/36303/PY2014_Q1_WARN_Jul2014_Sep2014.pdf"),
    ("20260416220432", "https://mdes.ms.gov/media/37211/PY2014_Q2_WARN__Oct2014_Dec2014.pdf"),
    ("20260626125038", "https://mdes.ms.gov/media/67606/py2014_q3_warn__jan2015_mar2015.pdf"),
    ("20260512224436", "https://mdes.ms.gov/media/42390/py2014_q4__warn_apr2015_jun2015.pdf"),
    ("20250613034516", "https://mdes.ms.gov/media/50387/py2015_q1_warn_jul2015_sep2015.pdf"),
    ("20250613034507", "https://mdes.ms.gov/media/61193/py2015_q2_warn___oct2015_dec2015.pdf"),
    ("20250613034504", "https://mdes.ms.gov/media/73382/py2015_q3_warn__jan2016_mar2016.pdf"),
    ("20250613034456", "https://mdes.ms.gov/media/73387/py2015_q4_warn_apr2016_jun2016.pdf"),
    ("20250613034450", "https://mdes.ms.gov/media/77287/py2016_q1_warn_july2016_sept2016.pdf"),
    ("20250613034435", "https://mdes.ms.gov/media/85903/py2016_q2_warn_oct2016_dec2016.pdf"),
    ("20250613034426", "https://mdes.ms.gov/media/91268/py2016_q3_warn_jan2017_mar2017.pdf"),
    ("20250613034420", "https://mdes.ms.gov/media/96181/py2016_q4_warn_apr2017_jun2017.pdf"),
    ("20250613034414", "https://mdes.ms.gov/media/100974/py2017_q1_warn_july2017_sept2017.pdf"),
    ("20251024013145", "https://mdes.ms.gov/media/109393/py2017_q2_warn_oct2017_dec2017.pdf"),
    ("20260429054050", "https://mdes.ms.gov/media/118119/py2017_q3_warn_jan2018_mar2018.pdf"),
    ("20260602100558", "https://mdes.ms.gov/media/123921/py2017_q4_warn_apr2018_jun2018.pdf"),
    ("20260708134141", "https://mdes.ms.gov/media/128907/py2018_q1_warn_july2018_sept2018.pdf"),
    ("20250613034336", "https://mdes.ms.gov/media/141119/py2018_q2_warn_oct2018_dec2018.pdf"),
    ("20250613034327", "https://mdes.ms.gov/media/144111/py2018_q3_warn_jan2019_mar2019.pdf"),
    ("20250613034320", "https://mdes.ms.gov/media/152801/py2018_q4_warn_apr2019_jun2019.pdf"),
    ("20260413154539", "https://mdes.ms.gov/media/160518/py2019_q1_warn_july2019_sept2019.pdf"),
    ("20260609072807", "https://mdes.ms.gov/media/165147/py2019_q2_warn_oct2019_dec2019.pdf"),
    ("20250613034258", "https://mdes.ms.gov/media/180956/py2019_q3_warn_jan2020_mar2020.pdf"),
    ("20260622081811", "https://mdes.ms.gov/media/204780/py2019_q4_warn_apr2020_jun2020.pdf"),
    # --- PY2023-Q4 (Apr-Jun 2024) — the one PY2020+ quarter prod lacks ---
    ("20260418134650", "https://mdes.ms.gov/media/440515/py2023-q4-warn-apr2024-jun2024.pdf"),
)


def _discover_ms_archive_urls() -> list[str]:
    """Static Wayback replay list for the quarters the live hub no longer links."""
    return [_WAYBACK_REPLAY.format(ts=ts, url=url) for ts, url in _ARCHIVE_CAPTURES]


def parse_ms_archive_pdf(raw: bytes, url: str) -> list[NoticeRow]:
    """URL-aware entry point for the backfill: archive rows carry the replay URL."""
    return _parse_pdf(raw, source_url=url)


def _normalize_cell(value: object) -> str:
    """Join multi-line cell values with a space; return empty string for None."""
    if value is None:
        return ""
    return " ".join(str(value).split())


def _normalize_date(raw: str) -> object:
    """Parse a date string, tolerating '.' used as separator instead of '/'."""
    cleaned = raw.strip()
    # Replace lone dots used as date separators: "4/3.2026" -> "4/3/2026"
    cleaned = re.sub(r"(\d)\.", r"\1/", cleaned)
    return as_date(cleaned)


# Older quarterlies (PY2020-PY2022) merge employer and location into one
# "Company Name, City" column whose cell ends with a "City (County)" line.
_CITY_COUNTY_RE = re.compile(r"^(.+?)\s*\(([^)]+)\)$")
# Narrow PY2023-PY2024 cells wrap further, leaving "(County)" on its own line
# below the city.  Only the stacked-header parser opts into splitting these:
# older already-ingested quarterlies wrap mid-name too ("Stein Mart Madison" /
# "(Madison)"), and changing their parse would change existing notice_ids.
_COUNTY_ONLY_RE = re.compile(r"^\(([^)]+)\)$")


def _parse_pdf(raw: bytes, source_url: str | None = None) -> list[NoticeRow]:
    try:
        pdf = pdfplumber.open(io.BytesIO(raw))
    except Exception as e:
        raise ParseFailed(f"MS PDF: could not open: {e}") from e

    with pdf:
        first_text = pdf.pages[0].extract_text() or "" if pdf.pages else ""
        tables = [t for page in pdf.pages if (t := page.extract_table())]

    # PY2019-and-earlier quarterlies (Wayback backfill) share header text with
    # the PY2020-22 era but put the "# Affected" count on continuation grid
    # rows the newer parsers drop — dispatch on the title's program year so
    # the archive parser handles them (and only them). Some 2004-06 titles
    # omit the year ("THIRD QUARTER PROGRAM YEAR"); their SIC CODE column is
    # an equally reliable pre-2007 marker.
    m = re.search(r"PROGRAM\s+YEAR\s+(\d{4})", first_text, re.I)
    if (m and int(m.group(1)) <= 2019) or re.search(r"SIC\s+CODE", first_text, re.I):
        return _parse_archive_tables(tables, source_url or _LANDING_URL)

    header: list[str] | None = None
    data_rows: list[list] = []
    for t in tables:
        page_hdr = [" ".join(str(c).lower().split()) if c else "" for c in t[0]]
        # Substring match: old quarterlies use "company name, city".
        if not any("company name" in h for h in page_hdr) or not any(
            "type of action" in h for h in page_hdr
        ):
            continue
        if header is None:
            header = page_hdr
        # Skip header row, add only non-continuation rows
        for row in t[1:]:
            if row[0] is None:
                continue
            data_rows.append(row)

    rows = _extract_rows(header, data_rows) if header is not None else []
    if not rows:
        # PY2023-PY2024 quarterlies stack header labels across several rows
        # ("Date of" / "WARN" / "Notice") and pad the grid with ghost columns,
        # so the single-row header check above either misses them or maps the
        # date column onto a ghost cell (0 rows). Retry with the stacked-header
        # layout before giving up.
        v3 = _parse_stacked_header_tables(tables)
        if v3 is not None:
            return v3
    if header is None:
        raise ParseFailed("MS PDF: no notice table found")
    return rows


def _parse_stacked_header_tables(tables: list[list[list]]) -> list[NoticeRow] | None:
    """Parse quarterlies whose header labels stack across rows (PY2023-PY2024).

    These grids pad real columns with ghost cells — an empty header label
    over a None data cell, not always in the same column — so cells are
    matched positionally after compaction: the Nth labelled header column
    lines up with the Nth non-None cell of each data row.  Returns None when
    no page carries a stacked-header notice table.
    """
    header: list[str] | None = None
    data_rows: list[list] = []
    for t in tables:
        width = max(len(r) for r in t)
        labels = [""] * width
        page_data: list[list] = []
        for row in t:
            first = next((c for c in row if c not in (None, "")), "")
            if not page_data and not _DATE_CELL_RE.match(_normalize_cell(first)):
                # Still in the stacked header: merge labels column-wise.
                for i, c in enumerate(row):
                    if c not in (None, ""):
                        labels[i] = f"{labels[i]} {_normalize_cell(c).lower()}".strip()
            else:
                page_data.append(row)
        compact = [name for name in labels if name]
        stripped = [name.replace(" ", "") for name in compact]
        if not any("companyname" in s for s in stripped) or not any(
            "typeofaction" in s for s in stripped
        ):
            continue  # summary/other tables
        if header is None:
            header = compact
        for row in page_data:
            cells = [c for c in row if c is not None]
            if len(cells) == len(header):
                data_rows.append(cells)
    if header is None:
        return None
    return _extract_rows(header, data_rows, split_county_wrap=True)


# ---------------------------------------------------------------------------
# Archive era (2004-2006 + PY2010-PY2019) — Wayback backfill only
# ---------------------------------------------------------------------------

# One line of a cell: the Type of Action ("Layoff", "Closure", sometimes with
# stray trailing punctuation), a standalone "# Affected" count, or a date-ish
# value ("12/31/10", "6/2013", "8/5&6/15").
_ARCHIVE_ACTION_RE = re.compile(r"^(layoff|closure|closing)s?\b[\s\W]*$", re.I)
_ARCHIVE_INT_RE = re.compile(r"^(?:\d{1,3}(?:,\d{3})+|\d{1,5})$")
_ARCHIVE_DATEISH_RE = re.compile(r"^[\d/&.\- ]*\d/[\d/&.\- ]*$")
# "June 30, 2006"-style Date of Action (2004-06 era); the year can wrap onto
# its own line, so this is matched against the whole cell.
_ARCHIVE_MONTH_DATE_RE = re.compile(
    r"\b(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s+\d{1,2},?\s+\d{4}",
    re.I,
)
# "Non-WARN ..." in all its punctuation variants (incl. one "Non. WARM" typo),
# plus the 2004-06 "Existing Business & Industry Listing" phrasing that some
# quarters use for the same class of event without the NON-WARN prefix.
_NON_WARN_RE = re.compile(
    r"^\s*(?:non\s*\W?\s*war[nm]|existing\s+business\s*&\s*industry\s+listing)", re.I
)
_ZIP_RE = re.compile(r"\b(\d{5})(?:-\d{4})?\b")
_PAREN_GROUP_RE = re.compile(r"\(([^()]*)\)?")  # tolerates unclosed "(38652"
# A plausible city/county name: title-case-ish, no digits ("MDOC" and zips fail).
_PLACE_RE = re.compile(r"[A-Z][a-z][A-Za-z .'\-]*")
_NAICS6_RE = re.compile(r"\b(\d{6})\b")
_HEADER_HINT_RE = re.compile(
    r"company name|date of|reason|workforce|naics|nacis|sic code|affected|notice|type of",
    re.I,
)
_NOT_A_PLACE = {"unknown", "tbd", "n/a"}


def _cell_lines(cell: object) -> list[str]:
    if cell is None:
        return []
    return [" ".join(ln.split()) for ln in str(cell).splitlines() if ln.strip()]


def _row_starts_record(row: list) -> bool:
    lines = _cell_lines(row[0]) if row else []
    return bool(lines) and _DATE_CELL_RE.match(lines[0]) is not None


def _parse_archive_tables(
    tables: list[list[list]], source_url: str, *, include_non_warn: bool = False
) -> list[NoticeRow]:
    """Parse 2004-2006 / PY2010-PY2019 quarterlies.

    These grids stack "# Affected" under "Type of Action" and print the count
    on a continuation row, pad with ghost columns whose position varies per
    page, and (2004-06) add SIC+NAICS description lines.  Cells are therefore
    read semantically per record: rows are grouped by the date in column 0,
    merged column-wise, and the fields between the company cell and the
    trailing Reason/Comments cell are classified by content (action word /
    standalone count / date).  Reason/Comments flags non-WARN Rapid Response
    events, which are dropped unless ``include_non_warn`` (debug/tests) —
    those rows then carry ``extra["non_warn"] = "1"``.
    """
    records: list[list[list]] = []
    for t in tables:
        start = next((i for i, r in enumerate(t) if _row_starts_record(r)), None)
        if start is None:
            continue  # summary/totals table
        pre = t[:start]
        header_text = " ".join(
            " ".join(str(c).lower().split()) for row in pre for c in row if c
        )
        if "company name" not in header_text:
            continue
        # A record can spill onto the next page: rows above that page's
        # repeated header belong to the previous record. Stop at the first
        # label row — anything below it is stacked-header continuation
        # fragments ("Type of" / "Action #"), not data.
        for row in pre:
            cells = [str(c) for c in row if c not in (None, "")]
            if not cells:
                continue
            if any(_HEADER_HINT_RE.search(c) for c in cells):
                break
            if records:
                records[-1].append(row)
        for row in t[start:]:
            if _row_starts_record(row):
                records.append([row])
            elif records:
                records[-1].append(row)

    rows: list[NoticeRow] = []
    for rec in records:
        row = _archive_record_to_row(rec, source_url, include_non_warn=include_non_warn)
        if row is not None:
            rows.append(row)
    return rows


def _archive_record_to_row(
    rec: list[list], source_url: str, *, include_non_warn: bool
) -> NoticeRow | None:
    # Merge the record's rows column-wise into lists of lines.
    cols: dict[int, list[str]] = {}
    for row in rec:
        for i, cell in enumerate(row):
            lines = _cell_lines(cell)
            if lines:
                cols.setdefault(i, []).extend(lines)

    idxs = sorted(cols)
    if not idxs or idxs[0] != 0:
        return None
    notice_date = _normalize_date(cols[0][0])
    if notice_date is None:
        return None

    body = idxs[1:]
    if not body:
        return None
    company_i = body[0]
    rest = body[1:]

    # Reason/Comments = last populated cell, unless the row has no comment and
    # the last cell is really a date/count/action value.
    reason_i = None
    if rest:
        last_lines = cols[rest[-1]]
        if re.search(r"[A-Za-z]{3}", " ".join(last_lines)) and not all(
            _ARCHIVE_ACTION_RE.match(ln) for ln in last_lines
        ):
            reason_i = rest[-1]
    reason = " ".join(cols[reason_i]) if reason_i is not None else ""
    non_warn = _NON_WARN_RE.match(reason) is not None
    if non_warn and not include_non_warn:
        return None

    closure_type: str | None = None
    counts: list[int] = []
    eff_lines: list[str] = []
    wda: str | None = None
    naics: str | None = None
    for i in rest:
        if i == reason_i:
            continue
        lines = cols[i]
        cell_text = " ".join(lines)
        if wda is None and not any(ch.isdigit() for ch in cell_text):
            place_lines = [
                ln
                for ln in lines
                if not _ARCHIVE_ACTION_RE.match(ln) and ln.lower() not in _NOT_A_PLACE
            ]
            if place_lines and len(cell_text) <= 40:
                wda = " ".join(place_lines)
        for ln in lines:
            bare = ln.strip("()")  # estimated counts print as "(250)"
            bare = re.sub(r",\s+(?=\d{3}\b)", ",", bare)  # "1, 451" -> "1,451"
            if _ARCHIVE_ACTION_RE.match(ln):
                if closure_type is None:
                    closure_type = re.match(
                        r"(layoff|closure|closing)", ln, re.I
                    ).group(1).title()
            elif _ARCHIVE_INT_RE.match(bare):
                n = int(bare.replace(",", ""))
                if not 1990 <= n <= 2059:  # a wrapped year line, not a count
                    counts.append(n)
            elif _ARCHIVE_DATEISH_RE.match(ln):
                eff_lines.append(ln)
        m = _ARCHIVE_MONTH_DATE_RE.search(cell_text)
        if m:
            eff_lines.append(m.group())
        if naics is None:
            m = _NAICS6_RE.search(cell_text)
            if m:
                naics = m.group(1)

    employer, city, county, zip_code = _split_archive_company(cols[company_i])
    if not employer or _ARCHIVE_ACTION_RE.match(employer):
        # A record whose company cell fell outside the detected table grid
        # leaves only the action word behind (seen once, PY2010-Q2) — drop it.
        return None

    effective_date = _normalize_date(eff_lines[-1]) if eff_lines else None
    extra: dict[str, str] = {}
    if wda:
        extra["wda"] = wda
    if include_non_warn:  # debug/tests only — never set on ingested rows
        if non_warn:
            extra["non_warn"] = "1"
        extra["reason"] = reason
    return NoticeRow(
        state="MS",
        employer=employer,
        notice_date=notice_date,
        effective_date=effective_date,
        layoff_count=counts[-1] if counts else None,
        closure_type=closure_type,
        city=city,
        county=county,
        zip=zip_code,
        naics_code=naics,
        source_url=source_url,
        extra=extra,
    )


def _split_archive_company(
    lines: list[str],
) -> tuple[str, str | None, str | None, str | None]:
    """Split the merged company cell into (employer, city, county, zip).

    2004-06 puts city, county and zip each in parens ("(Walls) (Desoto)
    (38680)"); PY2010-PY2019 uses "City (County) 38924" with the city often
    wrapped onto the county's line or the line above ("Tyson Foods, Vicksburg"
    / "(Warren) 39183").
    """
    zips: list[str] = []
    cleaned: list[str] = []
    for ln in lines:
        stripped = _ZIP_RE.sub(lambda m: zips.append(m.group(1)) or "", ln)
        stripped = " ".join(stripped.split())
        if stripped:
            cleaned.append(stripped)
    zip_code = zips[-1] if zips else None

    joined = " ".join(cleaned)
    places = [
        (m.start(), m.group(1).strip())
        for m in _PAREN_GROUP_RE.finditer(joined)
        if _PLACE_RE.fullmatch(m.group(1).strip())
    ]

    city = county = None
    if len(places) >= 2:  # 2004-06: "(City) (County)"
        city, county = places[0][1], places[1][1]
        employer = joined[: places[0][0]]
    elif len(places) == 1:  # PY2010+: "City (County)"
        county = places[0][1]
        # Locate the line holding the county's "(" (offset into the joined
        # string — the paren can sit anywhere, even split from its name).
        paren_at = places[0][0]
        pos = 0
        li = 0
        for i, ln in enumerate(cleaned):
            if pos <= paren_at < pos + len(ln):
                li = i
                break
            pos += len(ln) + 1  # +1 for the joining space
        pre = joined[pos:paren_at].strip(" ,")
        emp_lines = cleaned[:li]
        if not pre and emp_lines:
            pre = emp_lines.pop()
        remnant, _, candidate = pre.rpartition(",")
        candidate = candidate.strip()
        if candidate and not emp_lines and not remnant.strip() and " " in candidate:
            # Single-line cell ("Foo Inc Jackson (Hinds)"): keep the last word
            # as the city so the employer is not swallowed.
            words = candidate.split()
            emp_lines.append(" ".join(words[:-1]))
            candidate = words[-1]
        if candidate.split() and candidate.split()[-1] in ("MS", "Ms") and len(
            candidate.split()
        ) > 1:
            candidate = candidate.rsplit(None, 1)[0]
        if candidate:
            city = candidate
        if remnant.strip():
            emp_lines.append(remnant.strip())
        employer = " ".join(emp_lines)
    else:
        employer = joined

    employer = " ".join(employer.replace("(", " ").replace(")", " ").split())
    return employer.strip(" ,-"), city, county, zip_code


def _extract_rows(
    header: list[str], data_rows: list[list], *, split_county_wrap: bool = False
) -> list[NoticeRow]:
    def _find(needle: str) -> int | None:
        exact = next((i for i, name in enumerate(header) if needle in name), None)
        if exact is not None:
            return exact
        # Stacked headers wrap mid-word ("Workforc e Area") or interleave
        # tokens ("Date of WARN Notice") — match ignoring spaces, then by
        # token subset.
        stripped = needle.replace(" ", "")
        for i, name in enumerate(header):
            if stripped in name.replace(" ", ""):
                return i
        tokens = set(needle.split())
        return next(
            (i for i, name in enumerate(header) if tokens <= set(name.split())),
            None,
        )

    i_company = _find("company name")
    i_date = _find("date of notice")
    i_action = _find("type of action")
    i_count = _find("number affected")
    i_eff = _find("date of action")
    i_wda = _find("workforce area")
    if i_company is None:
        return []
    # In the merged old format, "city" would match the company column —
    # location is split out of the company cell instead.
    merged_location = "city" in header[i_company]
    i_city = None if merged_location else _find("city")
    i_county = None if merged_location else _find("county")

    def _cell(row: list, i: int | None) -> str:
        return _normalize_cell(row[i]) if i is not None and i < len(row) else ""

    rows: list[NoticeRow] = []
    for raw_row in data_rows:
        city = county = None
        if merged_location:
            # Cell layout: employer line(s), then a final "City (County)" line.
            lines = [ln.strip() for ln in str(raw_row[i_company] or "").splitlines() if ln.strip()]
            m = _CITY_COUNTY_RE.match(lines[-1]) if lines else None
            county_only = (
                _COUNTY_ONLY_RE.match(lines[-1])
                if split_county_wrap and len(lines) >= 3 and not m
                else None
            )
            if m:
                city, county = as_str(m.group(1)), as_str(m.group(2))
                lines = lines[:-1]
            elif county_only:
                city, county = as_str(lines[-2]), as_str(county_only.group(1))
                lines = lines[:-2]
            employer = " ".join(lines)
        else:
            employer = _cell(raw_row, i_company)
            city = as_str(_cell(raw_row, i_city))
            county = as_str(_cell(raw_row, i_county))

        if not employer or employer.lower().startswith("date of"):
            continue

        notice_date = _normalize_date(_cell(raw_row, i_date))
        if notice_date is None:
            continue

        eff_raw = _cell(raw_row, i_eff)
        effective_date = _normalize_date(eff_raw) if eff_raw else None

        count_raw = _cell(raw_row, i_count)
        m = _LEADING_INT.search(count_raw)
        layoff_count = int(m.group()) if m else None

        closure_type = as_str(_cell(raw_row, i_action))
        wda = _cell(raw_row, i_wda)

        rows.append(
            NoticeRow(
                state="MS",
                employer=employer,
                notice_date=notice_date,
                effective_date=effective_date,
                layoff_count=layoff_count,
                closure_type=closure_type,
                city=city,
                county=county,
                source_url=_LANDING_URL,
                extra={"wda": wda} if wda else {},
            )
        )
    return rows


class MSScraper:
    state = "MS"
    source_url = _LANDING_URL
    expected_row_range = (1, 5_000)
    required_fields = frozenset({"employer", "notice_date"})

    def fetch(self) -> bytes:
        # The landing-page discovery GET stays unconditional (small, needed to
        # find the latest quarterly); only the PDF download is conditional.
        urls = _discover_pdf_urls()
        pdf_url = urls[0] if urls else _FALLBACK_URL
        try:
            return conditional_get(pdf_url, state=self.state, headers=_UA, timeout=60)
        except httpx.HTTPError as e:
            raise ScrapeFailed(f"GET {pdf_url}: {e}") from e

    def parse(self, raw: bytes) -> list[NoticeRow]:
        return _parse_pdf(raw)


register(MSScraper())
