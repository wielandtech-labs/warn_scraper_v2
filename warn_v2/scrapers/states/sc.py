"""South Carolina WARN scraper.

Source: https://dew.sc.gov/employers/employer-resources
Data:   Cumulative YTD PDF; URL discovered from the landing page.

Schema (as of May 2026):
  Company | County | Notice Date | Layoff/Closure Date | Impacted |
  Layoff/Closure | Address

The last row on page 0 is a "Total WARN: N  NNNN" summary row; we skip it.
Page 1 is a county-level summary table with a different schema; we skip it.

One edge case: when a company's county value is "Statewide - Multiple Counties",
pdfplumber's column detection merges part of that text with the adjacent Notice
Date column.  We handle this by stripping alpha characters from the garbled
Notice Date cell and re-parsing the remaining digits.

Historical backfill (2009-2025): per-year report PDFs in three layout eras,
recovered from Wayback (scworks.org, 2009-2019) and still-live-but-unlinked
dew.sc.gov / scworks.org URLs (2020-2025). See ``_SC_ARCHIVE_SOURCES`` and
``parse_sc_archive_pdf``.
"""
from __future__ import annotations

import io
import logging
import re
import statistics
from datetime import date

import httpx
import pdfplumber
from bs4 import BeautifulSoup

from warn_v2.scrapers._helpers import as_date, as_int, as_str
from warn_v2.scrapers.base import NoticeRow, ParseFailed, ScrapeFailed
from warn_v2.scrapers.registry import register
from warn_v2.scrapers.wayback import replay_url

log = logging.getLogger(__name__)

_LANDING_URL = "https://dew.sc.gov/employers/employer-resources"
_FALLBACK_URL = (
    "https://dew.sc.gov/sites/dew/files/Documents/"
    "2026%20South%20Carolina%20WARN_Report%2005132026.pdf"
)

_UA = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) warn-v2/0.1"
    )
}

_ZIP_RE = re.compile(r"\b(\d{5})(?:-\d{4})?\s*$")
_ALPHA_RE = re.compile(r"[A-Za-z]")


def _discover_pdf_url() -> str:
    try:
        r = httpx.get(_LANDING_URL, headers=_UA, timeout=30, follow_redirects=True)
        r.raise_for_status()
        soup = BeautifulSoup(r.content, "html.parser")
        for a in soup.find_all("a", href=True):
            href: str = a["href"]
            if "WARN_Report" in href:
                if href.startswith("/"):
                    href = "https://dew.sc.gov" + href
                return href
    except httpx.HTTPError:
        pass
    return _FALLBACK_URL


def _normalize_header(cell: object) -> str:
    if cell is None:
        return ""
    return " ".join(str(cell).lower().split())


def _extract_date_from_cell(cell_text: str) -> object:
    """Parse a date cell that may contain garbled interleaved text.

    When pdfplumber merges adjacent columns, date digits are interspersed with
    letters.  We strip alpha chars and try again.
    """
    if not cell_text:
        return None
    # Take the first date in a range like "5/1/2026 - 12/31/2026"
    first = cell_text.split(" - ")[0].strip()
    d = as_date(first)
    if d is not None:
        return d
    # Fallback: strip letters (handles merged county+date column)
    clean = _ALPHA_RE.sub("", first).strip()
    return as_date(clean) if clean else None


def _city_zip_from_address(address: str) -> tuple[str | None, str | None]:
    """Extract city and ZIP from a US address string."""
    m = _ZIP_RE.search(address)
    zip_code = m.group(1) if m else None
    # City is the last comma-delimited segment before state abbreviation
    parts = [p.strip() for p in address.split(",")]
    if len(parts) >= 2:
        # parts[-1] is "SC XXXXX", parts[-2] is city
        city = parts[-2].strip() or None
    else:
        city = None
    return city, zip_code


def parse_sc_pdf(raw: bytes, source_url: str = _LANDING_URL) -> list[NoticeRow]:
    """Parse the current-era SC WARN report (2022+ layout, with Notice Date)."""
    try:
        pdf = pdfplumber.open(io.BytesIO(raw))
    except Exception as e:
        raise ParseFailed(f"SC PDF: could not open: {e}") from e

    with pdf:
        all_rows: list[list] = []
        header: list[str] | None = None
        for page in pdf.pages:
            t = page.extract_table()
            if not t:
                continue
            page_header = [_normalize_header(c) for c in t[0]]
            # Only process the main notice table (has "company" and "impacted")
            if "company" not in page_header or "impacted" not in page_header:
                continue
            if header is None:
                header = page_header
            all_rows.extend(t[1:])

    if header is None:
        raise ParseFailed("SC PDF: no notice table found")

    col = {name: i for i, name in enumerate(header)}
    rows: list[NoticeRow] = []
    for raw_row in all_rows:
        employer = as_str(raw_row[col["company"]])
        if not employer or employer.lower().startswith("total"):
            continue

        notice_date = _extract_date_from_cell(
            as_str(raw_row[col["notice date"]]) or ""
        )
        if notice_date is None:
            continue

        effective_raw = as_str(raw_row[col.get("layoff/closure date", -1)]) or ""
        effective_date = (
            as_date(effective_raw.split(" - ")[0].strip()) if effective_raw else None
        )

        count_raw = as_str(raw_row[col.get("impacted", -1)]) or ""
        count_m = re.search(r"\d+", count_raw)
        layoff_count = as_int(count_m.group()) if count_m else None

        closure_type = as_str(raw_row[col.get("layoff/closure", -1)])
        county = as_str(raw_row[col.get("county", -1)])
        address = as_str(raw_row[col.get("address", -1)]) or ""
        city, zip_code = _city_zip_from_address(address)

        rows.append(
            NoticeRow(
                state="SC",
                employer=employer,
                notice_date=notice_date,
                effective_date=effective_date,
                layoff_count=layoff_count,
                closure_type=closure_type,
                city=city,
                county=county,
                zip=zip_code,
                address=as_str(address),
                source_url=source_url,
            )
        )
    return rows


class SCScraper:
    state = "SC"
    source_url = _LANDING_URL
    expected_row_range = (5, 5_000)
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
        return parse_sc_pdf(raw)


register(SCScraper())


# ---------------------------------------------------------------------------
# Historical backfill (2009-2025)
#
# SC publishes one rolling year-to-date PDF per year; old editions disappear
# from the landing pages but the files survive — 2009-2019 in the Wayback
# Machine (scworks.org librariesprovider6), 2020-2025 at still-live unlinked
# dew.sc.gov / scworks.org URLs. For each year we pin the latest known
# edition, preferring post-year ones (verified against the cached 2026-07
# sweep files).
#
# Three layout eras:
#   * 2009-2012 "Layoff Notification Report" — monthly sections
#     ("1/1/2012 Through 1/31/2012"), text-only rows (pdfplumber finds no
#     table): Company | Location | Projected Closure/Layoff Date | Positions
#     Affected | closure/layoff | County | NAICS. No per-row notice date, so
#     rows carry the section month's first day as an approximate notice_date.
#   * 2013-2021 "WARN Notification Report {year}" — one cumulative year
#     table: Company | Location | Projected Closure/Layoff Date | Positions |
#     Closure or Layoff | NAICS (column order varies by year; no county, no
#     notice date). Rows carry Jan 1 of the report year as the approximate
#     notice_date; same-employer/city rows within a year hash together and
#     their counts are summed by the worksite merge.
#   * 2022+ current era (Notice Date + County + Address) — parse_sc_pdf.
#
# Known residual holes (the newest recovered edition cuts off early):
# Dec 2016 (after 11/28), late Dec 2017/2019, Dec 16-31 2022, Dec 2023.
# ---------------------------------------------------------------------------

_SC_ARCHIVE_LIB = (
    "https://scworks.org/docs/librariesprovider6/layoff-notification-reports/"
)

# (wayback_ts, original_url) — latest capture of each year's newest edition.
_SC_WAYBACK_SOURCES: tuple[tuple[str, str], ...] = (
    ("20200418065702", _SC_ARCHIVE_LIB + "2009_layoff_notifications.pdf?sfvrsn=a40ce9e8_4"),
    ("20200418074856", _SC_ARCHIVE_LIB + "2010_layoff_notifications.pdf?sfvrsn=957f0b84_4"),
    ("20200418073112", _SC_ARCHIVE_LIB + "2011_layoff_notifications.pdf?sfvrsn=5b0ceebc_4"),
    ("20200418074824", _SC_ARCHIVE_LIB + "2012_layoff_notifications.pdf?sfvrsn=d83615d7_4"),
    ("20200418071126", _SC_ARCHIVE_LIB + "2013_layoff_notifications.pdf?sfvrsn=8b2aa69d_4"),
    ("20200418060631", _SC_ARCHIVE_LIB + "2014_layoff_notifications.pdf?sfvrsn=a933cc6b_4"),
    ("20200418073110", _SC_ARCHIVE_LIB + "2015_layoff_notifications.pdf?sfvrsn=374db82b_4"),
    ("20200418074431", _SC_ARCHIVE_LIB + "2016_layoff_notifications_112816.pdf?sfvrsn=37da78b1_4"),
    ("20200418074547", _SC_ARCHIVE_LIB + "2017_layoff_notifications_120517.pdf?sfvrsn=8e0de563_4"),
    ("20200418081759", _SC_ARCHIVE_LIB + "2018_layoff_notifications_122718.pdf?sfvrsn=cb165671_4"),
    ("20200418074759", _SC_ARCHIVE_LIB + "2019-warn-report-(12-18-19).pdf?sfvrsn=c4b97917_0"),
)

# Live-but-unlinked editions (all verified 200 on 2026-07-10).
_SC_LIVE_SOURCES: tuple[str, ...] = (
    "https://scworks.org/sites/scworks/files/content/2020-warn-report-updated-06-18-2021.pdf",
    "https://scworks.org/sites/scworks/files/content/2021-warn-report-updated-05-11-2022.pdf",
    "https://scworks.org/sites/scworks/files/2022%20South%20Carolina%20WARN%20Report%2012152022.pdf",
    "https://dew.sc.gov/sites/dew/files/Documents/2023%20South%20Carolina%20WARN%20Report%2011282023.pdf",
    "https://scworks.org/sites/scworks/files/2024%20South%20Carolina%20WARN%20Report%2003072025.pdf",
    "https://scworks.org/sites/scworks/files/2025%20South%20Carolina%20WARN_Report%2001162026.pdf",
)


def _discover_sc_archive_urls() -> list[str]:
    """Static pinned URL list, one edition per year 2009-2025 (2026 is live)."""
    return [replay_url(ts, url) for ts, url in _SC_WAYBACK_SOURCES] + list(
        _SC_LIVE_SOURCES
    )


_DATE_SEARCH_RE = re.compile(r"(\d{1,2}/\d{1,2}/\d{4})")
_SECTION_RE = re.compile(
    r"(\d{1,2}/\d{1,2}/\d{4})\s+[Tt]hrough\s+\d{1,2}/\d{1,2}/\d{4}"
)
_TYPE_RE = re.compile(r"^(closure|layoff|closing)$", re.I)
_NAICS_RE = re.compile(r"^\d{4,6}$")
_YEAR_HEADER_RE = re.compile(r"WARN Notification Report\s*\n?\s*(\d{4})")
_FOOTNOTE_RE = re.compile(r"\s*\(\d\)\s*$")

_ERA_A_HEADER_VOCAB = frozenset({
    "company", "location", "projected", "closure/", "layoff", "date",
    "positions", "affected", "closure", "or", "county", "naics", "code",
    "notification", "report", "warn",
})


def parse_sc_archive_pdf(raw: bytes, source_url: str) -> list[NoticeRow]:
    """Era-dispatching parser for the pinned historical editions."""
    try:
        with pdfplumber.open(io.BytesIO(raw)) as pdf:
            first_text = pdf.pages[0].extract_text() or ""
    except Exception as e:
        raise ParseFailed(f"SC archive PDF: could not open: {e}") from e

    if "Layoff Notification Report" in first_text:
        return _parse_sc_monthly_pdf(raw, source_url)
    if "WARN Notification Report" in first_text:
        return _parse_sc_yearly_pdf(raw, source_url, first_text)
    return parse_sc_pdf(raw, source_url)


def _group_lines(words: list[dict], tol: float = 3.0) -> list[list[dict]]:
    """Group words into visual lines by their top coordinate."""
    out: list[list[dict]] = []
    for w in sorted(words, key=lambda w: (w["top"], w["x0"])):
        if out and abs(out[-1][0]["top"] - w["top"]) <= tol:
            out[-1].append(w)
        else:
            out.append([w])
    return [sorted(ln, key=lambda w: w["x0"]) for ln in out]


def _city_or_none(words: list[str]) -> str | None:
    city = " ".join(" ".join(words).split()) or None
    if city and "statewide" in city.lower():
        return None
    return city


def _parse_sc_monthly_pdf(raw: bytes, source_url: str) -> list[NoticeRow]:
    """2009-2012 era: monthly sections, word-position parsing.

    Rows are single text lines anchored by a closure/layoff keyword; long
    company names (and sometimes the county) wrap onto the adjacent lines, so
    unanchored fragment lines are folded into the vertically nearest row by
    column band. Column x-positions shift page to page — each page's
    Company/Location header midpoint is the company-vs-city boundary.
    """
    rows: list[NoticeRow] = []
    section_start: date | None = None
    boundary: float | None = None

    with pdfplumber.open(io.BytesIO(raw)) as pdf:
        for page in pdf.pages:
            data: list[dict] = []
            frags: list[list[dict]] = []
            for ln in _group_lines(page.extract_words()):
                texts = [w["text"] for w in ln]
                joined = " ".join(texts)
                m = _SECTION_RE.search(joined)
                if m:
                    d = as_date(m.group(1))
                    if d:
                        section_start = d.replace(day=1)
                    continue
                if {t.lower() for t in texts} <= _ERA_A_HEADER_VOCAB:
                    xs = {t.lower(): w["x0"] for t, w in zip(texts, ln, strict=True)}
                    if "company" in xs and "location" in xs:
                        boundary = (xs["company"] + xs["location"]) / 2
                    continue
                type_idxs = [i for i, t in enumerate(texts) if _TYPE_RE.match(t)]
                if type_idxs and len(texts) >= 4 and type_idxs[-1] >= 2:
                    data.append({"ln": ln, "top": ln[0]["top"], "section": section_start})
                    continue
                # Garbled section header: an underlying text layer interleaves
                # "Through" with other words ("ThPrrooujgehc"). Strip letters
                # and look for a leading date followed by more date debris.
                stripped = re.sub(r"[^\d/ ]", "", joined)
                gm = re.match(
                    r"\s*(\d{1,2}/\d{1,2}/\d{4})\s+[\d/ ]*\d/\s*\d{4}\s*$", stripped
                )
                if gm:
                    d = as_date(gm.group(1))
                    if d:
                        section_start = d.replace(day=1)
                    continue
                frags.append(ln)

            if not data:
                continue

            # Per-page column anchors from the data lines themselves.
            company_x = min(d["ln"][0]["x0"] for d in data)
            page_boundary = boundary if boundary is not None else company_x + 100
            date_xs: list[float] = []
            type_xs: list[float] = []
            for d in data:
                texts = [w["text"] for w in d["ln"]]
                ti = max(i for i, t in enumerate(texts) if _TYPE_RE.match(t))
                type_xs.append(d["ln"][ti]["x0"])
                date_xs.extend(
                    w["x0"] for w in d["ln"] if _DATE_SEARCH_RE.search(w["text"])
                )
            date_x = statistics.median(date_xs) if date_xs else None
            type_x = statistics.median(type_xs)

            # Fold fragment lines into the vertically nearest data row.
            for ln in frags:
                nearest = min(data, key=lambda d: abs(d["top"] - ln[0]["top"]))
                if abs(nearest["top"] - ln[0]["top"]) > 13:
                    log.debug("SC archive: dropping stray line %r",
                              " ".join(w["text"] for w in ln))
                    continue
                above = ln[0]["top"] < nearest["top"]
                for w in ln:
                    if w["x0"] > type_x + 5:
                        key = "naics_frag" if _NAICS_RE.match(w["text"]) else "county_frag"
                    elif w["x0"] < page_boundary:
                        key = "company_above" if above else "company_below"
                    else:
                        key = "city_above" if above else "city_below"
                    nearest.setdefault(key, []).append(w["text"])

            for d in data:
                row = _era_a_row(d, page_boundary, date_x, type_x, source_url)
                if row is not None:
                    rows.append(row)

    if not rows:
        raise ParseFailed("SC archive PDF: monthly era yielded no rows")
    return rows


def _era_a_row(
    d: dict,
    page_boundary: float,
    date_x: float | None,
    type_x: float,
    source_url: str,
) -> NoticeRow | None:
    ln = d["ln"]
    texts = [w["text"] for w in ln]
    type_i = max(i for i, t in enumerate(texts) if _TYPE_RE.match(t))
    ctype = texts[type_i]

    # County + NAICS sit right of the closure/layoff keyword.
    naics = None
    county_words: list[str] = []
    for w in ln[type_i + 1:]:
        if _NAICS_RE.match(w["text"]) and w["x0"] > type_x + 20:
            naics = w["text"]
        else:
            county_words.append(w["text"])
    county_words += d.get("county_frag", [])
    naics = naics or next(iter(d.get("naics_frag", [])), None)
    county = " ".join(county_words) or None
    if county and county.upper() == "FALSE":
        county = None

    # Rightmost integer before the type keyword is the positions count.
    count = None
    count_i = None
    for i in range(type_i - 1, 0, -1):
        if texts[i].replace(",", "").isdigit():
            count = as_int(texts[i].replace(",", ""))
            count_i = i
            break

    # Rightmost date-like token before the count. The city is sometimes glued
    # to the date ("(Harbison)3/31/2009"); strip the non-date debris and keep
    # it for the city.
    stop = count_i if count_i is not None else type_i
    effective = None
    date_i = None
    date_prefix = ""
    for i in range(stop - 1, 0, -1):
        tok = texts[i]
        m = _DATE_SEARCH_RE.search(tok)
        if m is None and re.search(r"\d/\d{4}$", tok):
            m = _DATE_SEARCH_RE.search(re.sub(r"[^\d/]", "", tok))
            if m:
                date_prefix = re.match(r"^(\D*)", tok).group(1)
        elif m:
            date_prefix = tok[: m.start()]
        if m:
            dt = as_date(m.group(1))
            if dt and dt.year > 1990:
                effective = dt
            date_i = i
            break

    # Everything left of the date column is company + city.
    pre = ln[:date_i] if date_i is not None else ln[:stop]
    if date_x is not None:
        pre = [w for w in pre if w["x0"] < date_x - 15]
    # Stray date-column junk (a "TBD", or a duplicated type keyword).
    pre = [w for w in pre if not _TYPE_RE.match(w["text"]) and w["text"] != "TBD"]

    if pre and pre[0]["x0"] > page_boundary:
        # Line starts at the Location column: the company is entirely on
        # wrapped fragment lines.
        company_words: list[str] = []
        city_words = [w["text"] for w in pre]
    else:
        # Company is left-aligned, the city column is centered — the last
        # significant x-gap separates them.
        split = None
        for i in range(1, len(pre)):
            if pre[i]["x0"] - pre[i - 1]["x1"] >= 12:
                split = i
        company_words = [w["text"] for w in (pre[:split] if split else pre)]
        city_words = [w["text"] for w in pre[split:]] if split else []
    if date_prefix.strip():
        city_words.append(date_prefix.strip())

    employer = " ".join(
        d.get("company_above", []) + company_words + d.get("company_below", [])
    ).strip()
    if not employer:
        return None
    city = _city_or_none(d.get("city_above", []) + city_words + d.get("city_below", []))

    return NoticeRow(
        state="SC",
        employer=employer,
        notice_date=d["section"],
        effective_date=effective,
        layoff_count=count,
        closure_type=ctype,
        city=city,
        county=county,
        naics_code=naics,
        source_url=source_url,
    )


def _parse_sc_yearly_pdf(raw: bytes, source_url: str, first_text: str) -> list[NoticeRow]:
    """2013-2021 era: one cumulative "WARN Notification Report {year}" table.

    Column order varies by year (2020 swaps the date/count/type columns), so
    cells after Company and Location are classified by content. The source
    publishes no notice date; rows carry Jan 1 of the report year.
    """
    m = _YEAR_HEADER_RE.search(first_text)
    if m is None:
        # Filename year ("/2013_layoff_notifications.pdf") — not the Wayback
        # timestamp, which also starts with 20xx.
        m = re.search(r"/(20\d{2})[-_]", source_url)
    if m is None:
        raise ParseFailed("SC archive PDF: cannot determine report year")
    notice = date(int(m.group(1)), 1, 1)

    rows: list[NoticeRow] = []
    with pdfplumber.open(io.BytesIO(raw)) as pdf:
        for page in pdf.pages:
            for table in page.extract_tables():
                if not table or max(len(r) for r in table) < 6:
                    continue
                for raw_row in table:
                    cells = [c for c in (as_str(c) for c in raw_row) if c]
                    if len(cells) < 3:
                        continue
                    first = cells[0].lower()
                    if "warn notification report" in first or first == "company":
                        continue
                    employer = _FOOTNOTE_RE.sub("", " ".join(cells[0].split()))
                    rest = cells[1:]
                    city = None
                    if as_date(rest[0].split(" - ")[0]) is None:
                        city = _city_or_none([rest[0]])
                        rest = rest[1:]
                    effective = None
                    count = None
                    ctype = None
                    naics = None
                    for i, cell in enumerate(rest):
                        cell = " ".join(cell.split())
                        if _TYPE_RE.match(cell):
                            ctype = cell
                            continue
                        digits = cell.replace(",", "")
                        if digits.isdigit():
                            if i == len(rest) - 1 and _NAICS_RE.match(digits):
                                naics = digits
                            else:
                                count = as_int(digits)
                            continue
                        # Tolerate typos like "12/31//2015".
                        d = as_date(re.sub(r"/{2,}", "/", cell.split(" - ")[0]))
                        if d:
                            effective = d
                    if not employer:
                        continue
                    rows.append(
                        NoticeRow(
                            state="SC",
                            employer=employer,
                            notice_date=notice,
                            effective_date=effective,
                            layoff_count=count,
                            closure_type=ctype,
                            city=city,
                            naics_code=naics,
                            source_url=source_url,
                        )
                    )

    if not rows:
        raise ParseFailed("SC archive PDF: yearly era yielded no rows")
    return rows
