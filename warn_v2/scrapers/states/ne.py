"""Nebraska WARN scraper.

Source: https://dol.nebraska.gov/ReemploymentServices/LayoffServices/LayoffsAndDownsizingWARN

Schema (live as of May 2026):
  Date | Company | Jobs Affected | Location

Static HTML table; company cell has an anchor linking to the individual
notice document at /webdocs/getfile/<uuid>.
"""
from __future__ import annotations

import functools
import re
from pathlib import Path

import httpx
from bs4 import BeautifulSoup

from warn_v2.scrapers._helpers import as_date, as_int, as_str, norm
from warn_v2.scrapers.base import NoticeRow, ParseFailed, ScrapeFailed
from warn_v2.scrapers.bundled import load_archive
from warn_v2.scrapers.registry import register

SOURCE_URL = (
    "https://dol.nebraska.gov/ReemploymentServices/LayoffServices/LayoffsAndDownsizingWARN"
)
_BASE_URL = "https://dol.nebraska.gov"

_UA = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) warn-v2/0.1"
    )
}


class NEScraper:
    state = "NE"
    source_url = SOURCE_URL
    expected_row_range = (5, 5_000)
    required_fields = frozenset({"employer", "notice_date"})

    def fetch(self) -> bytes:
        try:
            r = httpx.get(SOURCE_URL, headers=_UA, timeout=30, follow_redirects=True)
            r.raise_for_status()
            return r.content
        except httpx.HTTPError as e:
            raise ScrapeFailed(f"GET {SOURCE_URL}: {e}") from e

    def parse(self, raw: bytes) -> list[NoticeRow]:
        return _parse_ne_table(raw, SOURCE_URL)


def _parse_ne_table(raw: bytes, source_url: str) -> list[NoticeRow]:
    soup = BeautifulSoup(raw, "html.parser")
    table = soup.find("table")
    if table is None:
        raise ParseFailed("no <table> found on NE WARN page")

    all_trs = table.find_all("tr")
    if not all_trs:
        raise ParseFailed("NE table has no rows")

    # The live page's first row is the column header; the legacy per-year
    # report fragments prepend banner rows ("WARN Report" / "{Y} Events as
    # of ...") — scan for the row that names Company.
    header_idx: int | None = None
    header_cells: list[str] = []
    for i, tr in enumerate(all_trs):
        cells = [_text(td).lower() for td in tr.find_all(["td", "th"])]
        if "company" in cells:
            header_idx, header_cells = i, cells
            break
    if header_idx is None:
        raise ParseFailed("no NE header row naming 'company' found")
    col = {name: i for i, name in enumerate(header_cells)}

    rows: list[NoticeRow] = []
    for tr in all_trs[header_idx + 1 :]:
        cells = tr.find_all(["td", "th"])
        if len(cells) < 3:
            continue

        company_cell = cells[col["company"]]
        anchor = company_cell.find("a")
        employer = as_str(_text(anchor) if anchor else _text(company_cell))
        if not employer:
            continue
        notice_date = as_date(_text(cells[col["date"]]))
        if notice_date is None:
            continue

        notice_url: str | None = None
        if anchor and anchor.get("href"):
            href = anchor["href"]
            notice_url = href if href.startswith("http") else _BASE_URL + href

        # Live schema has only Location (which holds the city); the legacy
        # per-year fragments add a City column, with Location carrying the
        # worksite detail ("Omaha Distribution Center"). Keep the clean city
        # and stash a distinct Location in address so same-employer/date/city
        # worksite pairs merge with summed counts (_merge_worksite_rows).
        location = as_str(_text(cells[col["location"]]))
        address: str | None = None
        if "city" in col:
            city = as_str(_text(cells[col["city"]]))
            if location and norm(location) != norm(city or ""):
                address = location
        else:
            city = location

        raw_count = _text(cells[col["jobs affected"]]).replace(",", "")
        rows.append(
            NoticeRow(
                state="NE",
                employer=employer,
                notice_date=notice_date,
                layoff_count=as_int(raw_count),
                city=city,
                address=address,
                raw_notice_url=notice_url,
                source_url=source_url,
            )
        )
    return rows


def _text(cell) -> str:
    return " ".join(cell.get_text(" ", strip=True).replace("\xa0", " ").split())


register(NEScraper())


# ---------------------------------------------------------------------------
# Historical backfill: the frozen legacy per-year endpoint (Mode 3b)
# ---------------------------------------------------------------------------
# dol.nebraska.gov/LayoffServices/WARNReportData/?year={Y} still serves the
# 2010-2020 per-year report fragments (same table plus a City column, banner
# rows before the header). Snapshotted 2026-07-10 and bundled as
# warn_v2/scrapers/data/ne_archive.tar.gz. 2021-2022 exist only in Wayback
# captures of the rolling live page — not bundled here.

_ARCHIVE_TGZ = Path(__file__).resolve().parent.parent / "data" / "ne_archive.tar.gz"
_ARCHIVE_URL = "https://dol.nebraska.gov/LayoffServices/WARNReportData/?year={year}"
_YEAR_RE = re.compile(r"\d{4}")


def ne_archive_files() -> list[tuple[str, bytes]]:
    """(member_name, bytes) for each bundled warnreportdata_<year>.html."""
    return load_archive(_ARCHIVE_TGZ)


def parse_ne_archive(raw: bytes, member_name: str) -> list[NoticeRow]:
    """Parse one bundled legacy fragment, stamping its per-year source URL."""
    m = _YEAR_RE.search(member_name)
    source_url = _ARCHIVE_URL.format(year=m.group()) if m else SOURCE_URL
    return _parse_ne_table(raw, source_url)


# ---------------------------------------------------------------------------
# Historical backfill: NDOL's Layoff and Closures report (Mode 3b, Non-WARN)
# ---------------------------------------------------------------------------
# Besides the WARN report, NDOL published a broader "Layoff and Closures"
# report: every layoff/closure event it learned of, of any size and from any
# source (newspapers, employer calls, WARN notices). Two eras, bundled as
# warn_v2/scrapers/data/ne_lc_archive.tar.gz:
#   lr_{Y}_q{N}.html  Wayback captures (all from the June-2010 crawl) of
#                     www.dol.nebraska.gov/nwd/employers/dislocated/
#                     layoffreport.cfm?report=QtrN&yr=Y, Jul-2008 -> Sep-2010.
#                     Columns: Company | Location | Event Date | Date NWD-DOL
#                     Notified | Layoff/Closure | Worker(s) Affected | Source
#                     of Notification. The quarterly pages equal the union of
#                     the monthly ones (365 rows), so only they are bundled.
#   lc_{Y}.html       the frozen live endpoint LayoffAndClosureReportData/
#                     ?year=2011..2020 (snapshotted 2026-10-18; other years
#                     are empty). Columns: Date | Company | Type | Jobs
#                     Affected | City | Location — Date is the event date.
# Rows are tagged extra["non_warn"] -> closure_category "Non-WARN" (aggregates
# exclude them), except 2008-2010 rows whose Source of Notification is WARN:
# those are WARN notices that predate the WARN report's 2010 floor.
#
# Every WARN-report notice reappears here under its layoff date, so rows that
# match a WARN-report row are dropped (see _matches_warn_row). Besides avoiding
# double counts, this keeps a Non-WARN row from ever hashing onto a WARN row's
# notice_id, where the upsert would overwrite its count and fill in its
# closure_category. The WARN-report bundle is all of prod's NE data before 2023
# (verified 2026-10-18: 102 rows, none dated 2021-2022), and every row here is
# dated 2020 or earlier, so it is the only set a row could collide with.
# A WARN notice can also be listed twice here, once per phase (Leon Plastics,
# Alda, 140 workers: notified 2008-11-12 and again 2008-11-17); the later
# source-WARN repeat is dropped so WARN totals count it once.

_LC_TGZ = Path(__file__).resolve().parent.parent / "data" / "ne_lc_archive.tar.gz"
_LC_LIVE_URL = "https://dol.nebraska.gov/LayoffServices/LayoffAndClosureReportData/?year={year}"
_LC_WAYBACK_URL = (
    "https://web.archive.org/web/{ts}/http://www.dol.nebraska.gov/nwd/employers/"
    "dislocated/layoffreport.cfm?report=Qtr{q}&yr={year}"
)
# Capture timestamp of each bundled quarterly page (latest 200 capture).
_LC_WAYBACK_TS = {
    (2008, 3): "20100601202522",
    (2008, 4): "20100601200620",
    (2009, 1): "20100601195549",
    (2009, 2): "20100601202040",
    (2009, 3): "20100601194505",
    (2009, 4): "20100601183248",
    (2010, 1): "20100601194106",
    (2010, 2): "20100601200839",
    (2010, 3): "20100601193759",
}
_LC_MEMBER_RE = re.compile(r"^(lc|lr)_(\d{4})(?:_q(\d))?\.html$")
# A WARN notice shows up in the Layoff and Closures report dated by its layoff
# (event) date, typically 30-90 days after the notice; the 2008-2010 era also
# carries the notified date, which sits within days of the notice date.
_LC_EVENT_WINDOW_DAYS = (0, 180)
_LC_NOTIFIED_WINDOW_DAYS = 14
_LC_REPEAT_WINDOW_DAYS = 120


def ne_lc_files() -> list[tuple[str, bytes]]:
    """(member_name, bytes) for each bundled Layoff and Closures report page."""
    return load_archive(_LC_TGZ)


def is_ne_lc_member(member_name: str) -> bool:
    return _LC_MEMBER_RE.match(member_name) is not None


def parse_ne_lc(raw: bytes, member_name: str) -> list[NoticeRow]:
    """Parse one bundled Layoff and Closures page, minus WARN-report duplicates."""
    m = _LC_MEMBER_RE.match(member_name)
    if m is None:
        raise ParseFailed(f"unexpected NE layoff/closure member {member_name!r}")
    era, year, quarter = m.group(1), int(m.group(2)), m.group(3)
    if era == "lc":
        source_url = _LC_LIVE_URL.format(year=year)
    else:
        ts = _LC_WAYBACK_TS[(year, int(quarter))]
        source_url = _LC_WAYBACK_URL.format(ts=ts, q=quarter, year=year)
    rows = _parse_lc_table(raw, source_url)
    warn_index = _warn_report_index()
    return [
        r
        for r in rows
        if not any(_matches_warn_row(r, w) for w in warn_index.get(_match_key(r), ()))
        and not _is_warn_source_repeat(r)
    ]


def _parse_lc_table(raw: bytes, source_url: str) -> list[NoticeRow]:
    soup = BeautifulSoup(raw, "html.parser")
    header: dict[str, int] | None = None
    rows: list[NoticeRow] = []
    for tr in soup.find_all("tr"):
        cells = tr.find_all(["td", "th"])
        texts = [_text(c) for c in cells]
        if header is None:
            if "company" in (t.lower() for t in texts):
                header = {t.lower(): i for i, t in enumerate(texts)}
            continue
        if len(cells) < len(header):
            continue
        cell = functools.partial(_lc_cell, texts, header)
        employer = as_str(cell("company"))
        event_date = as_date(cell("event date", "date"))
        notified = as_date(cell("date nwd-dol notified"))
        if not employer or (event_date is None and notified is None):
            continue
        city = as_str(cell("city", "location"))
        location = as_str(cell("location")) if "city" in header else None
        address = location if location and norm(location) != norm(city or "") else None
        source = cell("source of notification")
        # "WARN" or "WARN / Trade Certification Pending"; anything else
        # (newspapers, phone calls, blank) is a Non-WARN event.
        extra = {} if source.upper().startswith("WARN") else {"non_warn": "1"}
        if source:
            extra["notification_source"] = source
        rows.append(
            NoticeRow(
                state="NE",
                employer=employer,
                notice_date=notified or event_date,
                effective_date=event_date,
                layoff_count=as_int(cell("worker(s) affected", "jobs affected").replace(",", "")),
                closure_type=as_str(cell("layoff/closure", "type")),
                city=city,
                address=address,
                source_url=source_url,
                extra=extra,
            )
        )
    if header is None:
        raise ParseFailed("no NE layoff/closure header row naming 'company' found")
    return rows


def _lc_cell(texts: list[str], header: dict[str, int], *names: str) -> str:
    """The first of ``names`` present in the header row, as cell text."""
    for n in names:
        if n in header:
            return texts[header[n]]
    return ""


@functools.cache
def _warn_report_rows() -> tuple[NoticeRow, ...]:
    """The bundled 2010-2020 WARN-report rows (prod's NE rows for those years)."""
    return tuple(
        row for name, raw in ne_archive_files() for row in parse_ne_archive(raw, name)
    )


@functools.cache
def _warn_report_index() -> dict[tuple[str, str], list[NoticeRow]]:
    index: dict[tuple[str, str], list[NoticeRow]] = {}
    for w in _warn_report_rows():
        index.setdefault(_match_key(w), []).append(w)
    return index


@functools.cache
def _lc_warn_source_rows() -> tuple[NoticeRow, ...]:
    """Every source-WARN row across the bundle (repeats span quarterly pages)."""
    return tuple(
        r
        for name, raw in ne_lc_files()
        for r in _parse_lc_table(raw, "")
        if "non_warn" not in r.extra
    )


def _is_warn_source_repeat(row: NoticeRow) -> bool:
    """A later listing of a source-WARN notice already listed (same employer,
    city and count, notified up to _LC_REPEAT_WINDOW_DAYS earlier)."""
    if "non_warn" in row.extra or row.notice_date is None:
        return False
    return any(
        _match_key(e) == _match_key(row)
        and e.layoff_count == row.layoff_count
        and e.notice_date is not None
        and 0 < (row.notice_date - e.notice_date).days <= _LC_REPEAT_WINDOW_DAYS
        for e in _lc_warn_source_rows()
    )


def _match_key(row: NoticeRow) -> tuple[str, str]:
    return re.sub(r"[^a-z0-9]", "", row.employer.lower()), norm(row.city or "")


def _matches_warn_row(row: NoticeRow, warn: NoticeRow) -> bool:
    """Same employer and city (the caller's index lookup) and dated as the same notice."""
    if warn.notice_date is None:
        return False
    if row.notice_date is not None and (
        abs((row.notice_date - warn.notice_date).days) <= _LC_NOTIFIED_WINDOW_DAYS
    ):
        return True
    lo, hi = _LC_EVENT_WINDOW_DAYS
    return row.effective_date is not None and (
        lo <= (row.effective_date - warn.notice_date).days <= hi
    )
