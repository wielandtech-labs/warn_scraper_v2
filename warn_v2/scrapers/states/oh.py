"""Ohio WARN scraper.

Source: https://jfs.ohio.gov/job-workforce-services/job-programs-and-services/
        submit-a-warn-notice/current-public-notices-of-layoffs-and-closures
Administered by the Ohio Department of Job and Family Services (JFS).

In June 2026 JFS replaced its WebSphere portal with a Next.js site, retiring the
old deep-link (it now 404s) and the JS-rendered table. The current-notices page
references a plain CSV on the Cloudinary-backed asset host (dam.assets.ohio.gov);
fetch() scrapes that ``csvUrl`` off the page and downloads the CSV directly, so
no headless browser is needed any more. The CSV's ``URL`` column links the
per-notice PDF.

Schema (CSV header row, confirmed live June 2026):
  Company | Date Received | URL | City/County | Layoff/Closure |
  Potential Number Affected | Layoff Date(s) | Phone Number | Union
The CSV leads with a column-visibility row ("s"/"h" flags) and a blank row
before this header.
"""
from __future__ import annotations

import csv
import io
import re

import httpx
from bs4 import BeautifulSoup

from warn_v2.scrapers._helpers import as_date, as_int, as_str
from warn_v2.scrapers.base import NoticeRow, ParseFailed, ScrapeFailed
from warn_v2.scrapers.registry import register

SOURCE_URL = (
    "https://jfs.ohio.gov/job-workforce-services/job-programs-and-services/"
    "submit-a-warn-notice/current-public-notices-of-layoffs-and-closures"
)

# Realistic Chrome UA — the JFS site and historical Wayback fetches both prefer it.
_CHROME_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)

_DATE_RE = re.compile(r"\d{1,2}/\d{1,2}/\d{4}")
# The current-notices page embeds the data file as a dam.assets.ohio.gov CSV URL.
_CSV_URL_RE = re.compile(r"https://dam\.assets\.ohio\.gov/\S+?\.csv")


class OHScraper:
    state = "OH"
    source_url = SOURCE_URL
    expected_row_range = (5, 300)
    required_fields = frozenset({"employer", "notice_date"})
    raw_notice_url_is_pdf = True

    def fetch(self) -> bytes:
        """Scrape the CSV link off the current-notices page, then fetch the CSV."""
        try:
            with httpx.Client(
                headers={"User-Agent": _CHROME_UA}, timeout=60, follow_redirects=True
            ) as client:
                page = client.get(SOURCE_URL)
                page.raise_for_status()
                csv_url = _extract_csv_url(page.text)
                resp = client.get(csv_url)
                resp.raise_for_status()
                return resp.content
        except httpx.HTTPError as exc:
            raise ScrapeFailed(f"OH: {exc}") from exc

    def parse(self, raw: bytes) -> list[NoticeRow]:
        text = raw.decode("utf-8-sig", errors="replace")
        records = [r for r in csv.reader(io.StringIO(text)) if any(c.strip() for c in r)]

        # Skip the leading visibility row by locating the header via its
        # "Company" cell (the visibility row is just "s"/"h" flags).
        header_idx = next(
            (i for i, r in enumerate(records) if any(c.strip().lower() == "company" for c in r)),
            None,
        )
        if header_idx is None:
            raise ParseFailed(f"OH CSV: no header row found; first rows={records[:2]}")
        header = [c.strip().lower() for c in records[header_idx]]

        def _find(*needles: str) -> int | None:
            return next(
                (i for i, name in enumerate(header) if any(n in name for n in needles)),
                None,
            )

        i_company = _find("company")
        i_date = _find("received")
        if i_company is None or i_date is None:
            raise ParseFailed(f"OH CSV: unexpected header: {records[header_idx]}")
        i_url = _find("url")
        i_cc = _find("city", "county")
        i_type = _find("closure")
        i_count = _find("affected", "number")
        i_ldate = _find("layoff date")
        i_union = _find("union")

        def _cell(row: list[str], i: int | None) -> str:
            return row[i].strip() if i is not None and i < len(row) and row[i] else ""

        rows: list[NoticeRow] = []
        for row in records[header_idx + 1 :]:
            employer = as_str(_cell(row, i_company))
            notice_date = as_date(_cell(row, i_date))
            if not employer or notice_date is None:
                continue

            # City/County is "Toledo/Lucas" — split on "/"
            city = county = None
            cc = _cell(row, i_cc)
            if cc:
                parts = cc.split("/", 1)
                city = as_str(parts[0])
                county = as_str(parts[1]) if len(parts) > 1 else None

            m = _DATE_RE.search(_cell(row, i_ldate))
            url = _cell(row, i_url)
            extra: dict[str, str] = {}
            if _cell(row, i_union):
                extra["union"] = _cell(row, i_union)

            rows.append(
                NoticeRow(
                    state="OH",
                    employer=employer,
                    notice_date=notice_date,
                    effective_date=as_date(m.group(0)) if m else None,
                    layoff_count=as_int(_cell(row, i_count)),
                    closure_type=as_str(_cell(row, i_type)),
                    city=city,
                    county=county,
                    raw_notice_url=url if url.startswith("http") else None,
                    source_url=SOURCE_URL,
                    extra=extra,
                )
            )

        if not rows:
            raise ParseFailed("OH CSV: no data rows parsed")
        return rows


def _extract_csv_url(html: str) -> str:
    m = _CSV_URL_RE.search(html)
    if m is None:
        raise ScrapeFailed("OH: no CSV link found on current-notices page")
    return m.group(0)


def _parse_oh_html_table(raw: bytes) -> list[NoticeRow]:
    """Parse a JFS WARN HTML table (the 2020-2022 archive.stm layout).

    The live scraper moved to CSV, but the historical backfill still replays
    archived ".stm" pages whose table matches the old live schema.
    """
    soup = BeautifulSoup(raw, "html.parser")
    table = soup.find("table")
    if table is None:
        raise ParseFailed("no <table> found on OH WARN page")

    all_trs = table.find_all("tr")
    if not all_trs:
        raise ParseFailed("OH WARN table has no rows")

    header_cells = [_text(td).lower() for td in all_trs[0].find_all(["td", "th"])]
    col = {name: i for i, name in enumerate(header_cells)}

    company_col = next((c for c in col if "company" in c), None)
    date_col = next((c for c in col if "received" in c), None)
    if company_col is None or date_col is None:
        raise ParseFailed(
            f"unexpected OH header — company or date column missing: {header_cells}"
        )

    city_col = next((c for c in col if "city" in c or "county" in c), None)
    type_col = next((c for c in col if "layoff" in c and "closure" in c), None)
    count_col = next((c for c in col if "affected" in c or "number" in c), None)
    layoff_date_col = next((c for c in col if "layoff" in c and "date" in c), None)

    rows: list[NoticeRow] = []
    for tr in all_trs[1:]:
        cells = tr.find_all(["td", "th"])
        if len(cells) <= max(col[company_col], col[date_col]):
            continue
        employer = as_str(_text(cells[col[company_col]]))
        if not employer:
            continue
        notice_date = as_date(_text(cells[col[date_col]]))
        if notice_date is None:
            continue

        # City/County is "Toledo/Lucas" — split on "/"
        city = county = None
        if city_col is not None and col[city_col] < len(cells):
            cc = _text(cells[col[city_col]])
            parts = cc.split("/", 1)
            city = as_str(parts[0])
            county = as_str(parts[1]) if len(parts) > 1 else None

        effective_date = None
        if layoff_date_col is not None and col[layoff_date_col] < len(cells):
            m = _DATE_RE.search(_text(cells[col[layoff_date_col]]))
            if m:
                effective_date = as_date(m.group(0))

        rows.append(
            NoticeRow(
                state="OH",
                employer=employer,
                notice_date=notice_date,
                effective_date=effective_date,
                layoff_count=(
                    as_int(_text(cells[col[count_col]]))
                    if count_col is not None and col[count_col] < len(cells)
                    else None
                ),
                closure_type=(
                    as_str(_text(cells[col[type_col]]))
                    if type_col is not None and col[type_col] < len(cells)
                    else None
                ),
                city=city,
                county=county,
                source_url=SOURCE_URL,
            )
        )

    if not rows:
        raise ParseFailed("OH WARN page: no data rows parsed from table")
    return rows


def _text(cell) -> str:
    return " ".join(cell.get_text(" ", strip=True).split())


# ---------------------------------------------------------------------------
# Historical backfill (1996-2024) — sources probed 2026-06-12, see
# docs/historical-sources.md. Four era formats, none needing Playwright:
#
#   1996-2006  per-year PDFs (jfs.ohio.gov/warn/WARN_{y}.pdf / Warn_{y}.pdf),
#              gone from the live site -> Wayback replay
#   2007-2019  per-year ".stm" files that actually serve Excel-exported PDFs,
#              slug naming drifted -> Wayback replay, try variants
#   2020-2022  archive.stm?year=Y HTML pages (same table layout the live
#              scraper parses) -> Wayback replay; 2021+ also live portal pages
#   2021-2024  live portal pages with the table embedded as JSON in
#              <div id="js-placeholder-json-data"> (includes per-notice PDFs)
#
# 2025 is unaccounted for anywhere (no live page, nothing in the CDX index).
# ---------------------------------------------------------------------------

_WAYBACK = "https://web.archive.org/web/{ts}id_/{url}"
_PORTAL_BASE = (
    "https://jfs.ohio.gov/job-services-and-unemployment/job-services/"
    "job-programs-and-services/submit-a-warn-notice"
)

_FETCH_UA = {"User-Agent": _CHROME_UA}

# Anchors for the PDF-era line parser.
_LEAD_DATE_RE = re.compile(r"^\d{1,2}/\d{1,2}/\d{2,4}$")
_WID_RE = re.compile(r"(\d{1,3}-\d{1,2}-\d{3,4})\s*$")
_PHONE_RE = re.compile(r"\(\d{3}\)\s*\d{3}\s*-?\s*\d{4}")
_COUNT_LDATE_RE = re.compile(r"\s(\d(?:[\d ,]*\d)?)\s+(\d{1,2}\s*/\s*\S.*)$")
_COUNT_ONLY_RE = re.compile(r"\s(\d(?:[\d ,]*\d)?)\s*$")
# Era PDFs use 2-digit years ("2/28/01"); the live-table regex requires 4.
_ANY_DATE_RE = re.compile(r"\d{1,2}/\d{1,2}/\d{2,4}")
# Greedy employer, single-word city before "(County)" — multi-word cities are
# recovered by shifting prefix words (East, New, ...) in _split_employer_city.
_CITY_COUNTY_RE = re.compile(
    r"^(?P<emp>.+)\s+(?P<city>[A-Za-z.'-]+)\s*\(\s*(?P<county>[A-Za-z .'-]+?)\s*\)$"
)
# Directional/compound prefixes for the era-A two-word-city heuristic.
_CITY_PREFIXES = frozenset({
    "east", "west", "north", "south", "new", "saint", "st.", "st",
    "upper", "lower", "mount", "mt.", "mt",
})


def _portal_url(year: int) -> str:
    # 2021/2022 parent slugs end "-sa"; 2023/2024 don't (verified live).
    stem = f"{year}-public-notices-of-layoffs-and-closures"
    sa = "-sa" if year <= 2022 else ""
    return f"{_PORTAL_BASE}/{stem}{sa}/{stem}"


def _oh_year_sources(year: int) -> list[str]:
    """Candidate URLs for one year, most preferred first."""
    if 1996 <= year <= 2003:
        return [_WAYBACK.format(ts="2005", url=f"http://jfs.ohio.gov/warn/WARN_{year}.pdf")]
    if 2004 <= year <= 2006:
        return [_WAYBACK.format(ts="2009", url=f"http://jfs.ohio.gov/warn/Warn_{year}.pdf")]
    if 2007 <= year <= 2019:
        slugs = (
            f"WARN_{year}.stm",
            f"WARN{year}.stm",
            f"WARN-{year}.stm",
            f"{year}WARNNotices.stm",
        )
        return [
            _WAYBACK.format(ts="2020", url=f"http://jfs.ohio.gov/warn/{slug}")
            for slug in slugs
        ]
    if 2020 <= year <= 2024:
        urls = []
        if year >= 2021:
            urls.append(_portal_url(year))
        if year <= 2022:
            urls.append(
                _WAYBACK.format(
                    ts="2023", url=f"https://jfs.ohio.gov/warn/archive.stm?year={year}"
                )
            )
        return urls
    return []  # 2025: no known source; current year: live scraper


def _looks_like_oh_data(raw: bytes) -> bool:
    if raw[:4] == b"%PDF":
        return True
    if b"js-placeholder-json-data" in raw:
        return True
    lower = raw.lower()
    return b"date received" in lower or b"date rcd" in lower


# web.archive.org throttles request bursts (connection refusals after ~30
# rapid requests — observed 2026-06-12: the .stm era's 4-variants-per-year
# loop tripped it and every Wayback fetch failed for the rest of the run).
_WAYBACK_DELAY = 3.0
_WAYBACK_BACKOFF = 30.0


def _fetch_oh_year(year: int) -> bytes | None:
    import time

    import httpx

    for url in _oh_year_sources(year):
        is_wayback = "web.archive.org" in url
        for attempt in (1, 2):
            if is_wayback:
                time.sleep(_WAYBACK_DELAY)
            try:
                r = httpx.get(url, headers=_FETCH_UA, timeout=120, follow_redirects=True)
                r.raise_for_status()
            except httpx.HTTPError:
                if is_wayback and attempt == 1:
                    time.sleep(_WAYBACK_BACKOFF)
                    continue
                break
            if _looks_like_oh_data(r.content):
                return r.content
            break  # got a response, but it's a soft-404 shell — next candidate
    return None


def parse_oh_year(raw: bytes, year: int) -> list[NoticeRow]:
    """Dispatch on content shape: era PDF, embedded portal JSON, or HTML table."""
    if raw[:4] == b"%PDF":
        return _parse_oh_pdf(raw, year)
    if b"js-placeholder-json-data" in raw:
        return _parse_oh_portal_json(raw, year)
    # archive.stm pages match the live table layout, but carry extra
    # navigation tables — hand OHScraper.parse just the notices table.
    soup = BeautifulSoup(raw, "html.parser")
    for table in soup.find_all("table"):
        first = table.find("tr")
        header = " ".join(_text(c).lower() for c in first.find_all(["td", "th"])) if first else ""
        if "company" in header and "received" in header:
            return _parse_oh_html_table(str(table).encode())
    raise ParseFailed(f"OH {year}: no WARN table found in archive HTML")


def _parse_oh_portal_json(raw: bytes, year: int) -> list[NoticeRow]:
    import json

    soup = BeautifulSoup(raw, "html.parser")
    div = soup.find(id="js-placeholder-json-data")
    if div is None:
        raise ParseFailed(f"OH {year}: js-placeholder-json-data div not found")
    try:
        data = json.loads(div.get_text())["data"]
    except (ValueError, KeyError) as e:
        raise ParseFailed(f"OH {year}: bad embedded JSON: {e}") from e
    if len(data) < 3:
        raise ParseFailed(f"OH {year}: embedded JSON has no data rows")

    # data[0] is column-type tags, data[1] the header, the rest are rows.
    header = [str(h).lower() for h in data[1]]

    def _find(*needles: str) -> int | None:
        return next(
            (i for i, name in enumerate(header) if any(n in name for n in needles)),
            None,
        )

    i_company = _find("company")
    i_date = _find("received")
    if i_company is None or i_date is None:
        raise ParseFailed(f"OH {year}: unexpected embedded-JSON header: {header}")
    i_url = _find("url")
    i_cc = _find("city")
    i_count = _find("affected", "number")
    i_ldate = _find("layoff date")
    i_union = _find("union")
    i_wid = _find("notice id")

    def _cell(row: list, i: int | None) -> str:
        return str(row[i]).strip() if i is not None and i < len(row) and row[i] else ""

    source_url = _portal_url(year)
    rows: list[NoticeRow] = []
    for row in data[2:]:
        employer = as_str(_cell(row, i_company))
        notice_date = as_date(_cell(row, i_date))
        if not employer or notice_date is None:
            continue

        city = county = None
        cc = _cell(row, i_cc)
        if cc:
            parts = cc.split("/", 1)
            city = as_str(parts[0])
            county = as_str(parts[1]) if len(parts) > 1 else None

        m = _DATE_RE.search(_cell(row, i_ldate))
        url = _cell(row, i_url)
        extra = {}
        if _cell(row, i_union):
            extra["union"] = _cell(row, i_union)
        if _cell(row, i_wid):
            extra["warn_id"] = _cell(row, i_wid)

        rows.append(
            NoticeRow(
                state="OH",
                employer=employer,
                notice_date=notice_date,
                effective_date=as_date(m.group(0)) if m else None,
                layoff_count=as_int(_cell(row, i_count)),
                city=city,
                county=county,
                raw_notice_url=url if url.startswith("http") else None,
                source_url=source_url,
                extra=extra,
            )
        )
    return rows


def _split_employer_city(blob: str) -> tuple[str, str | None, str | None]:
    """Split the PDF-era "Company City" blob into (employer, city, county).

    2007+ files carry "City (County)" — unambiguous. Earlier files have a bare
    city name: take the last word, or the last two when the second-to-last is a
    directional/compound prefix (East Liverpool, New Philadelphia, Mount Vernon).
    """
    m = _CITY_COUNTY_RE.match(blob)
    if m:
        emp_words = m.group("emp").split()
        city_words = [m.group("city")]
        # Pull directional/compound prefixes back into the city name
        # ("... East" + "Liverpool (Columbiana)" -> "East Liverpool").
        while len(emp_words) > 1 and emp_words[-1].lower() in _CITY_PREFIXES:
            city_words.insert(0, emp_words.pop())
        return " ".join(emp_words), as_str(" ".join(city_words)), as_str(m.group("county"))
    words = blob.split()
    if len(words) < 2:
        return blob, None, None
    take = 2 if len(words) > 2 and words[-2].lower() in _CITY_PREFIXES else 1
    employer = " ".join(words[:-take])
    city = " ".join(words[-take:])
    return employer, as_str(city), None


def _parse_oh_pdf_line(date_str: str, line: str, year: int) -> NoticeRow | None:
    notice_date = as_date(date_str)
    if notice_date is None:
        return None

    extra = {}
    m = _WID_RE.search(line)
    if m:
        extra["warn_id"] = m.group(1)
        line = line[: m.start()].rstrip()

    union = None
    phones = list(_PHONE_RE.finditer(line))
    if phones:
        last = phones[-1]
        union = as_str(line[last.end():])
        line = line[: last.start()].rstrip()

    layoff_count = None
    effective_date = None
    m = _COUNT_LDATE_RE.search(line)
    if m:
        layoff_count = as_int(m.group(1).replace(" ", "").replace(",", ""))
        # Text extraction can insert spaces around slashes: "2/28 /11".
        ldate = re.sub(r"\s*/\s*", "/", m.group(2))
        dm = _ANY_DATE_RE.search(ldate)
        effective_date = as_date(dm.group(0)) if dm else None
        line = line[: m.start()].rstrip()
    else:
        m = _COUNT_ONLY_RE.search(line)
        if m:
            layoff_count = as_int(m.group(1).replace(" ", "").replace(",", ""))
            line = line[: m.start()].rstrip()

    employer, city, county = _split_employer_city(line)
    employer = as_str(employer)
    if not employer:
        return None
    if union:
        extra["union"] = union

    return NoticeRow(
        state="OH",
        employer=employer,
        notice_date=notice_date,
        effective_date=effective_date,
        layoff_count=layoff_count,
        city=city,
        county=county,
        source_url=f"http://jfs.ohio.gov/warn/ ({year} archive)",
        extra=extra,
    )


def _parse_oh_pdf(raw: bytes, year: int) -> list[NoticeRow]:
    """Parse a 1996-2019 era per-year PDF.

    extract_text preserves word spacing (table extraction splits words across
    cells); each notice is one line starting with the received date.
    """
    import io

    import pdfplumber

    rows: list[NoticeRow] = []
    try:
        with pdfplumber.open(io.BytesIO(raw)) as pdf:
            for page in pdf.pages:
                for line in (page.extract_text() or "").split("\n"):
                    line = line.strip()
                    parts = line.split(None, 1)
                    if len(parts) < 2 or not _LEAD_DATE_RE.match(parts[0]):
                        continue
                    parsed = _parse_oh_pdf_line(parts[0], parts[1], year)
                    if parsed:
                        rows.append(parsed)
    except ParseFailed:
        raise
    except Exception as e:
        raise ParseFailed(f"OH {year}: PDF parse error: {e}") from e
    return rows


register(OHScraper())
