"""Florida WARN scraper.

Source: https://reactwarn.floridajobs.org/WarnList/Records?year={year}

Schema (live as of May 2026, unchanged since V1):
  Company Name | State Notification Date | Layoff Date | Employees Affected
    | Industry | Attachment

Per-row layout in the first <td>:
  <b>Company Name</b><br>123 Main St<br>CITY, FL, 32101
A hidden <input type="hidden" value="filename.pdf"> holds the Azure path that
gets appended to the download base URL to fetch the PDF.

Like NY and JobLink, we surface the PDF URL via `raw_notice_url` but do NOT
fetch the PDF here — per-PDF enrichment goes through Phase 4.

Historical backfill (1998-2019): the reactwarn site only serves 2020+, but
the predecessor site published one cumulative HTML page per year at
floridajobs.org/REACT/warn.asp?year=Y from 1998 through 2018 (dead since the
reactwarn migration), and Wayback holds post-year captures of every year plus
the two 2019 reactwarn result pages. `_fetch_fl_year` routes those years to
pinned replay captures; `parse_fl_warn_asp` handles the warn.asp table layout.
"""
from __future__ import annotations

import re
from datetime import datetime

import httpx
from bs4 import BeautifulSoup

from warn_v2.scrapers import wayback
from warn_v2.scrapers._helpers import as_date, as_int, as_str
from warn_v2.scrapers.base import NoticeRow, ParseFailed, ScrapeFailed
from warn_v2.scrapers.registry import register

URL_TEMPLATE = "https://reactwarn.floridajobs.org/WarnList/Records?year={year}"
DOWNLOAD_BASE = "https://reactwarn.floridajobs.org/WarnList/DownloadAzureFile?file="

_UA = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) warn-v2/0.1"
    ),
    "X-Requested-With": "XMLHttpRequest",
}

_ZIP_RE = re.compile(r"(\d{5})(?:-\d{4})?\s*$")


class FLScraper:
    state = "FL"
    expected_row_range = (5, 5_000)
    required_fields = frozenset({"employer", "notice_date"})

    def __init__(self) -> None:
        self.source_url = URL_TEMPLATE.format(year=datetime.now().year)

    def fetch(self) -> bytes:
        # FL paginates at 100 rows/page. Fetch every page for the current year
        # and concatenate the raw page bytes so parse() (which scans all
        # DataTables) sees the whole year. A single-page fetch would silently cap
        # the daily run at the newest 100 notices — older rows would never get
        # re-scraped, so a value that was once stored wrong (e.g. a layoff_count
        # mis-parse) could never be corrected. Reuses the historical paginator.
        chunks = _fetch_fl_year(self, datetime.now().year)
        if not chunks:
            raise ScrapeFailed(f"GET {self.source_url}: no result pages")
        return b"\n".join(chunks)

    def parse(self, raw: bytes) -> list[NoticeRow]:
        soup = BeautifulSoup(raw, "html.parser")
        # fetch() concatenates one HTML document per result page, so a parsed
        # blob can hold several DataTables — collect rows across all of them.
        tables = soup.find_all("table", id="DataTable") or soup.find_all("table")
        if not tables:
            raise ParseFailed("no <table> found in FL DataTable page")

        rows: list[NoticeRow] = []
        trs = [
            tr
            for table in tables
            for tr in (table.find("tbody") or table).find_all("tr")
        ]
        for tr in trs:
            cells = tr.find_all("td")
            if len(cells) < 5:
                continue

            employer = _employer_from_cell(cells[0])
            if not employer:
                continue

            notice_date = as_date(cells[1].get_text(strip=True).replace("-", "/"))
            if notice_date is None:
                # Skip header echoes / no-data placeholders
                continue

            effective_text = cells[2].get_text(strip=True)
            effective_date = _first_date(effective_text)

            city, zip_code = _city_zip_from_cell(cells[0])
            address = _address_from_cell(cells[0], employer)
            layoff_count = as_int(cells[3].get_text(strip=True))
            industry = as_str(cells[4].get_text(strip=True))

            hidden = tr.find("input", attrs={"type": "hidden"})
            raw_notice_url = (
                DOWNLOAD_BASE + hidden.get("value")
                if hidden and hidden.get("value")
                else None
            )

            rows.append(
                NoticeRow(
                    state="FL",
                    employer=employer,
                    notice_date=notice_date,
                    effective_date=effective_date,
                    layoff_count=layoff_count,
                    city=city,
                    zip=zip_code,
                    address=address,
                    source_url=self.source_url,
                    raw_notice_url=raw_notice_url,
                    extra={"industry": industry} if industry else {},
                )
            )
        return rows


_PAGE_PARAM_RE = re.compile(r"[?&]page=(\d+)")

# warn.asp era (1998-2018): latest post-year Wayback capture per year, from the
# 2026-07 backfill sweep. The 2012 capture is a header-only table (the site
# itself had dropped the 2012 rows by capture time) — it parses to 0 rows.
_ASP_CAPTURES: dict[int, tuple[str, str]] = {
    1998: ("20160623033351", "http://floridajobs.org/REACT/warn.asp?year=1998"),
    1999: ("20160622225353", "http://floridajobs.org/REACT/warn.asp?year=1999"),
    2000: ("20160622213326", "http://floridajobs.org/REACT/warn.asp?year=2000"),
    2001: ("20160623062611", "http://floridajobs.org/REACT/warn.asp?year=2001"),
    2002: ("20160623034732", "http://floridajobs.org/REACT/warn.asp?year=2002"),
    2003: ("20160623034736", "http://floridajobs.org/REACT/warn.asp?year=2003"),
    2004: ("20160623033355", "http://floridajobs.org/REACT/warn.asp?year=2004"),
    2005: ("20160622214052", "http://floridajobs.org/REACT/warn.asp?year=2005"),
    2006: ("20160623034741", "http://floridajobs.org/REACT/warn.asp?year=2006"),
    2007: ("20160622215615", "http://floridajobs.org/REACT/warn.asp?year=2007"),
    2008: ("20160623033343", "http://floridajobs.org/REACT/warn.asp?year=2008"),
    2009: ("20160623035546", "http://floridajobs.org/REACT/warn.asp?year=2009"),
    2010: ("20160623045834", "http://floridajobs.org/REACT/warn.asp?year=2010"),
    2011: ("20160623033348", "http://floridajobs.org/REACT/warn.asp?year=2011"),
    2012: ("20191120063637", "http://www.floridajobs.org/react/warn.asp?year=2012"),
    2013: ("20160623041024", "http://floridajobs.org/REACT/warn.asp?year=2013"),
    2014: ("20191120055606", "http://www.floridajobs.org:80/REACT/warn.asp?year=2014"),
    2015: ("20191120055934", "http://www.floridajobs.org:80/REACT/warn.asp?year=2015"),
    2016: ("20191210022836", "http://www.floridajobs.org/react/warn.asp?year=2016"),
    2017: ("20191120055949", "http://www.floridajobs.org:80/REACT/warn.asp?year=2017"),
    2018: ("20191207230734", "http://www.floridajobs.org/REACT/warn.asp?year=2018"),
}

# 2019: reactwarn served it (two result pages) but no longer does — pinned
# captures of page 1 (latest, 2025) and page 2 (2023). Verified offline
# 2026-07-10: this pair covers the full 150-notice union across all 46
# archived sort/page variants of the year.
_REACTWARN_2019_CAPTURES: list[tuple[str, str]] = [
    ("20250210193435", "https://reactwarn.floridajobs.org/WarnList/Records?year=2019"),
    (
        "20230725141811",
        "https://reactwarn.floridajobs.org/WarnList/Records?year=2019&page=2",
    ),
]


def _fetch_fl_year(scraper, year: int) -> list[bytes] | None:
    """Fetch all result pages for one year (backfill-historical + live fetch).

    1998-2018 → pinned Wayback replay of the warn.asp year page;
    2019      → pinned Wayback replays of the two reactwarn result pages;
    2020+     → the live REACT site, following "next page" links until none
                remain. Returns one chunk per page, or None when the year has
                no page at all.
    """
    if year <= 2018:
        capture = _ASP_CAPTURES.get(year)
        if capture is None:
            return None
        url = wayback.replay_url(*capture)
        scraper.source_url = url
        raw = wayback.fetch(url)
        return None if raw is None else [raw]

    if year == 2019:
        chunks = [
            raw
            for ts, url in _REACTWARN_2019_CAPTURES
            if (raw := wayback.fetch(wayback.replay_url(ts, url)))
        ]
        # parse() stamps rows with scraper.source_url; point it at the year
        # page's replay (page-2 rows share it — one URL per year is enough
        # provenance here).
        scraper.source_url = wayback.replay_url(*_REACTWARN_2019_CAPTURES[0])
        return chunks or None

    base = URL_TEMPLATE.format(year=year)
    scraper.source_url = base  # parse() stamps rows with self.source_url
    chunks: list[bytes] = []
    page_num = 1
    while True:
        url = base if page_num == 1 else f"{base}&page={page_num}"
        try:
            r = httpx.get(url, headers=_UA, timeout=60, follow_redirects=True)
            if r.status_code == 404:
                return None if page_num == 1 else chunks
            r.raise_for_status()
        except httpx.HTTPError as e:
            raise ScrapeFailed(f"GET {url}: {e}") from e
        chunks.append(r.content)

        soup = BeautifulSoup(r.content, "html.parser")
        linked_pages = {
            int(m.group(1))
            for a in soup.find_all("a", href=True)
            if f"year={year}" in a["href"] and (m := _PAGE_PARAM_RE.search(a["href"]))
        }
        if page_num + 1 not in linked_pages or page_num >= 200:
            return chunks
        page_num += 1


def _address_from_cell(cell, employer: str) -> str | None:
    """Drop the leading <b>Employer Name</b> and return the remaining address text.

    Layout: <b>Acme Inc.</b><br>123 Main St<br>CITY, FL, 32101
    Returns: "123 Main St, CITY, FL, 32101"
    """
    text = cell.get_text("\n", strip=True)
    lines = [ln.strip() for ln in text.split("\n") if ln.strip()]
    if lines and lines[0] == employer:
        lines = lines[1:]
    if not lines:
        return None
    return as_str(", ".join(lines))


def _employer_from_cell(cell) -> str | None:
    b = cell.find("b")
    if b is not None and b.get_text(strip=True):
        return b.get_text(strip=True)
    # Fallback: take everything before the first <br>
    text = cell.get_text(" ", strip=True)
    return as_str(text.split(",")[0])


def _city_zip_from_cell(cell) -> tuple[str | None, str | None]:
    """Parse 'ACL Roofing 99 S. McCall Rd ENGLEWOOD, FL, 34223' → ('Englewood', '34223')."""
    text = cell.get_text(" ", strip=True)
    parts = [p.strip() for p in text.split(",")]
    city: str | None = None
    zip_code: str | None = None
    if len(parts) >= 3:
        # The city is in the part before "FL"
        # parts[-3] usually ends with the city, prefixed by address tokens
        city_token = parts[-3].split()
        if city_token:
            last = city_token[-2:] if len(city_token) >= 2 else city_token[-1:]
            city = " ".join(last).title()
            # Heuristic: single-word city → just title-case; multi-word → use last 1-2 tokens
            # In practice FL data has city as the last 1 or 2 ALL-CAPS words.
            city = _extract_city(parts[-3])
    m = _ZIP_RE.search(text)
    if m:
        zip_code = m.group(1)
    return city, zip_code


def _extract_city(token: str) -> str:
    """The city is the trailing run of ALL-CAPS words in `token`."""
    words = token.split()
    city_words: list[str] = []
    for w in reversed(words):
        if w.isupper() and w.isalpha():
            city_words.append(w)
        else:
            break
    if not city_words:
        return token.strip().title()
    return " ".join(reversed(city_words)).title()


def _first_date(text: str):
    """Parse the first date from strings like '07-14-26 thru 07-14-26'."""
    if not text:
        return None
    first = text.split("thru")[0].strip().replace("-", "/")
    return as_date(first)


# ---------------------------------------------------------------------------
# warn.asp era parser (1998-2018)
# ---------------------------------------------------------------------------

# Last address line: "Jupiter, FL  33458", "Dallas, TX  75219" (out-of-state
# HQ filings), "Miami, FL  331866208" (unhyphenated ZIP+4), "New Bern
# (Headquarters), NC  00000". ZIP is optional — a handful of rows omit it.
_ASP_LOCATION_RE = re.compile(
    r"^(?P<city>.+?)[,\s]+(?P<st>[A-Z]{2})[.,]?(?:\s+(?P<zip>\d{5})(?:-?\d{4})?)?\s*$"
)


def parse_fl_warn_asp(raw: bytes, year: int) -> list[NoticeRow]:
    """Parse one floridajobs.org/REACT/warn.asp?year=Y page (1998-2018 era).

    Columns: COMPANY NAME | NOTICE DATE | LAYOFF DATE | EMPLOYEES AFFECTED |
    INDUSTRY. The first cell glues company name and street address together:
    <font face="Arial Black">Name</font><br>street<br>City, FL  ZIP.
    Layoff dates are often a "start <I>thru</I> end" range — keep the start.
    """
    soup = BeautifulSoup(raw, "html.parser")
    # The data table nests inside a layout table whose single <tr> re-exposes
    # the first data row's cells — pick the table that directly owns the
    # COMPANY NAME header and only walk its direct rows, or the first data row
    # would be ingested twice.
    data_table = None
    for th in soup.find_all("th"):
        if "COMPANY NAME" in th.get_text(" ", strip=True).upper():
            data_table = th.find_parent("table")
            break
    if data_table is None:
        raise ParseFailed(f"no COMPANY NAME table in FL warn.asp page for {year}")

    capture = _ASP_CAPTURES.get(year)
    source_url = wayback.replay_url(*capture) if capture else None

    rows: list[NoticeRow] = []
    for tr in data_table.find_all("tr"):
        if tr.find_parent("table") is not data_table:
            continue
        cells = tr.find_all("td")
        if len(cells) < 5:
            continue

        # First cell: employer in the lone <font>/<b> tag, address after <br>s.
        name_tag = cells[0].find("font") or cells[0].find("b")
        lines = [
            ln.strip()
            for ln in cells[0].get_text("\n", strip=True).split("\n")
            if ln.strip()
        ]
        employer = (
            name_tag.get_text(" ", strip=True)
            if name_tag is not None
            else (lines[0] if lines else None)
        )
        if not employer:
            continue
        if lines and lines[0] == employer:
            lines = lines[1:]

        notice_date = as_date(cells[1].get_text(" ", strip=True))
        if notice_date is None:
            continue

        city = zip_code = None
        for ln in reversed(lines):
            m = _ASP_LOCATION_RE.match(ln)
            if m:
                city, zip_code = m.group("city").strip(), m.group("zip")
                # A few source rows double the ", FL ZIP" suffix
                # ("St. Petersburg, FL 33701, FL  33701") — strip nested ones.
                while m := _ASP_LOCATION_RE.match(city):
                    city = m.group("city").strip()
                    zip_code = zip_code or m.group("zip")
                break

        effective_date = _first_date(cells[2].get_text(" ", strip=True))
        layoff_count = as_int(cells[3].get_text(" ", strip=True))
        industry = as_str(cells[4].get_text(" ", strip=True))
        if industry and industry.lower() == "industry not provided":
            industry = None

        rows.append(
            NoticeRow(
                state="FL",
                employer=employer,
                notice_date=notice_date,
                effective_date=effective_date,
                layoff_count=layoff_count,
                city=city,
                zip=zip_code,
                address=as_str(", ".join(lines)),
                source_url=source_url,
                extra={"industry": industry} if industry else {},
            )
        )
    return rows


def parse_fl_year(raw: bytes, year: int) -> list[NoticeRow]:
    """Backfill parse dispatch: warn.asp era vs reactwarn HTML (2019+)."""
    if year <= 2018:
        return parse_fl_warn_asp(raw, year)
    return _SCRAPER.parse(raw)


_SCRAPER = register(FLScraper())
