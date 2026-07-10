"""Indiana WARN scraper.

Source: https://www.in.gov/dwd/warn-notices/current-warn-notices/

Schema (live as of May 2026):
  Company | City | Affected Workers | Notice Date | LO/CL Date |
  NAICS | Description of Work/Industry | Notice Type | (PDF link)

Notice Type is "LO" (Layoff) or "CL" (Closure). LO/CL Date is the
effective layoff or closure date. The last column is empty in the header
but contains a PDF link per row.

The table has id="table33066" (stable since V1, May 2021).
"""
from __future__ import annotations

import re

import httpx
from bs4 import BeautifulSoup

from warn_v2.scrapers._helpers import as_date, as_int, as_str
from warn_v2.scrapers.base import NoticeRow, ParseFailed, ScrapeFailed
from warn_v2.scrapers.registry import register
from warn_v2.scrapers.wayback import replay_url

SOURCE_URL = "https://www.in.gov/dwd/warn-notices/current-warn-notices/"

_UA = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) warn-v2/0.1"
    )
}

_BASE_URL = "https://www.in.gov"

_NOTICE_TYPE = {"lo": "Layoff", "cl": "Closure"}


class INScraper:
    state = "IN"
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
        table = soup.find("table", {"id": "table33066"})
        if table is None:
            # Fall back to first table if id changed.
            table = soup.find("table")
        if table is None:
            raise ParseFailed("no <table> found on IN WARN page")

        all_trs = table.find_all("tr")
        if not all_trs:
            raise ParseFailed("IN table has no rows")

        header_cells = [_text(td).lower() for td in all_trs[0].find_all(["td", "th"])]
        if not header_cells or "company" not in header_cells:
            raise ParseFailed(f"unexpected IN header: {header_cells[:6]}")
        col = {name: i for i, name in enumerate(header_cells)}

        rows: list[NoticeRow] = []
        for tr in all_trs[1:]:
            cells = tr.find_all(["td", "th"])
            if len(cells) < 4:
                continue
            employer = as_str(_text(cells[col["company"]]))
            if not employer:
                continue
            notice_date = as_date(_text(cells[col["notice date"]]))
            if notice_date is None:
                continue

            notice_type_raw = _text(cells[col["notice type"]]).lower()
            closure_type = _NOTICE_TYPE.get(notice_type_raw, as_str(notice_type_raw))

            # Last column may contain a PDF link.
            notice_url: str | None = None
            last_cell = cells[-1]
            anchor = last_cell.find("a")
            if anchor and anchor.get("href"):
                href = anchor["href"]
                notice_url = href if href.startswith("http") else _BASE_URL + href

            naics_idx = col.get("naics")
            industry_idx = col.get("description of work/industry")

            rows.append(
                NoticeRow(
                    state="IN",
                    employer=employer,
                    notice_date=notice_date,
                    effective_date=as_date(_text(cells[col["lo/cl date"]])),
                    layoff_count=as_int(_text(cells[col["affected workers"]])),
                    closure_type=closure_type,
                    city=as_str(_text(cells[col["city"]])),
                    raw_notice_url=notice_url,
                    source_url=SOURCE_URL,
                    extra={
                        "naics": (
                            as_str(_text(cells[naics_idx])) or ""
                            if naics_idx is not None else ""
                        ),
                        "industry": (
                            as_str(_text(cells[industry_idx])) or ""
                            if industry_idx is not None else ""
                        ),
                    },
                )
            )
        return rows


def _text(cell) -> str:
    return " ".join(cell.get_text(" ", strip=True).split())


# ---------------------------------------------------------------------------
# Historical backfill (2000-2007) — three archived generations of the DWD
# listing, replayed from pinned Wayback captures (no runtime CDX; captures
# verified offline 2026-07-10):
#
#   gen1  2000-2003  per-year tables `workforce_stats/warn/{year}.html`,
#                    SIC-coded. The archived 2000 page only lists Nov-Dec
#                    2000 (it is 1/4 the size of the other year pages — the
#                    listing appears to start there).
#   gen2  2003-2005  rolling current-year `workforce_stats/warn/notices.html`.
#                    The Oct-2003 capture carries one Sep-2003 notice the
#                    finalized 2003.html later dropped (Macsteel); the
#                    Oct-2004 capture is the only source for Jan-Oct 2004.
#                    The Aug-2005 capture is EXCLUDED: its only unique row is
#                    a misspelling ("Cequent Electircal") of a row the gen3
#                    capture carries corrected — everything else id-dedupes.
#   gen3  2005-2007  accumulating `employers/warn_notices.html`. Only the
#                    Sep-2007 capture is used: it holds all of 2005-2007 and
#                    supersedes the Nov-2005/Dec-2006 captures, whose extra
#                    rows are just later-corrected typos (misspelled
#                    employers/cities, and two "11/15/16" dates for 11/15/06).
#
# All generations render the same columns (gen1/gen2 behind a leading spacer
# column): Company | City | Affected Workers | Notice Date | LO/CL Date |
# SIC (NAICS from ~mid-2005) | Description of work | Notice Type. The markup
# is malformed — header <th> cells are closed by </TD>, so bs4's tree nests
# unpredictably — hence the parser keys on leaf cells grouped by nearest <tr>
# and a date-shaped 4th column rather than table/header structure.
#
# Known gaps (no capture exists): Jan-Oct 2000, Nov-Dec 2004, Oct-Dec 2007.
# Prod IN data starts 2008, so there is no overlap with live rows. Staged
# layoffs are listed one row per wave with the same (employer, city, notice
# date) and only the count/effective date varying; notice_id collapses those
# waves to one stored row (~44 of ~545 parsed rows).
# ---------------------------------------------------------------------------

_IN_ARCHIVE_CAPTURES: tuple[tuple[str, str], ...] = (
    ("20041024235304", "http://www.in.gov/dwd/workforce_stats/warn/2000.html"),
    ("20050413055230", "http://www.in.gov/dwd/workforce_stats/warn/2001.html"),
    ("20050409215029", "http://www.in.gov/dwd/workforce_stats/warn/2002.html"),
    ("20050714083408", "http://www.in.gov/dwd/workforce_stats/warn/2003.html"),
    ("20031006113401", "http://www.in.gov/dwd/workforce_stats/warn/notices.html"),
    ("20041015022632", "http://www.in.gov/dwd/workforce_stats/warn/notices.html"),
    ("20070923102333", "http://www.in.gov/dwd/employers/warn_notices.html"),
)

# The archived pages cover 2000-2007; a notice date outside that window is a
# source typo (the Dec-2006 capture rendered two 11/15/06 rows as 11/15/16).
_IN_ARCHIVE_YEARS = range(2000, 2008)

_ARCHIVE_DATE_RE = re.compile(r"^\d{1,2}/\d{1,2}/\d{2,4}$")
_NAICS_RE = re.compile(r"\d{5,6}")
_SIC_RE = re.compile(r"\d{2,4}")
# A code token with no letters adjacent ("W-L-CL", "LO/CL") still means layoff.
_LONE_L_RE = re.compile(r"(?<![a-z])l(?![a-z])")


def _discover_in_archive_urls() -> list[str]:
    """Static pinned Wayback `id_` replay URLs, one per selected capture."""
    return [replay_url(ts, url) for ts, url in _IN_ARCHIVE_CAPTURES]


def _archive_closure_type(raw: str) -> str | None:
    """Normalize era codes (W-CL, W/LO, W-LO-CL, LO/CL, W-PermLO, CL-LO, ...)
    to the live scraper's Layoff/Closure vocabulary; unknown codes pass
    through verbatim."""
    s = raw.lower()
    has_lo = "lo" in s or _LONE_L_RE.search(s) is not None
    has_cl = "cl" in s
    if has_lo and has_cl:
        return "Layoff/Closure"
    if has_cl:
        return "Closure"
    if has_lo:
        return "Layoff"
    return as_str(raw)


def parse_in_archive_html(raw: bytes, source_url: str) -> list[NoticeRow]:
    """Parse an archived DWD listing page (any of the three generations).

    Data rows are recognized by shape, not table position: leaf cells grouped
    under their nearest <tr>, leading spacer cells dropped, and a date-shaped
    4th column. Month separators, repeated headers, footnote rows, and blank
    filler rows all fail that test and are skipped.
    """
    soup = BeautifulSoup(raw, "html.parser")
    rows: list[NoticeRow] = []
    for tr in soup.find_all("tr"):
        cells = [
            c
            for c in tr.find_all(["td", "th"])
            if c.find_parent("tr") is tr and not c.find(["td", "th"])
        ]
        texts = [_text(c) for c in cells]
        while texts and not texts[0]:
            texts.pop(0)
        if len(texts) < 5:
            continue
        # Footnote markers ("Visteon Connersville *") are not part of the name.
        employer = texts[0].rstrip("* ")
        if not employer or not _ARCHIVE_DATE_RE.match(texts[3]):
            continue
        notice_date = as_date(texts[3])
        if notice_date is None or notice_date.year not in _IN_ARCHIVE_YEARS:
            continue

        effective_date = None
        if len(texts) > 4 and _ARCHIVE_DATE_RE.match(texts[4]):
            effective_date = as_date(texts[4])

        extra: dict[str, str] = {}
        code = texts[5] if len(texts) > 5 else ""
        if _NAICS_RE.fullmatch(code):
            extra["naics"] = code
        elif _SIC_RE.fullmatch(code):
            extra["sic_code"] = code
        if len(texts) > 6 and texts[6]:
            extra["industry"] = texts[6]

        rows.append(
            NoticeRow(
                state="IN",
                employer=employer,
                notice_date=notice_date,
                effective_date=effective_date,
                layoff_count=as_int(texts[2]),
                closure_type=(
                    _archive_closure_type(texts[7]) if len(texts) > 7 else None
                ),
                city=as_str(texts[1]),
                source_url=source_url,
                extra=extra,
            )
        )
    if not rows:
        raise ParseFailed("IN archive page: no data rows parsed")
    return rows


register(INScraper())
