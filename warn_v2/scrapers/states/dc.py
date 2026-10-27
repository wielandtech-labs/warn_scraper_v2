"""District of Columbia WARN scraper.

Source: https://does.dc.gov/page/industry-closings-and-layoffs-warn-notifications-{year}

Schema (live as of May 2026):
  Notice Date | Organization Name | Number toEmployees Affected | Effective Layoff Date | Code Type

"Code Type" maps 1 → Layoff, 2 → Permanent Closures.
Dates are spelled out: "February 2, 2026".
DC does not publish city or ZIP in the WARN table (all notices are in DC).
"""
from __future__ import annotations

import re
from datetime import date

import httpx
from bs4 import BeautifulSoup

from warn_v2.scrapers._helpers import as_date, as_int, as_str
from warn_v2.scrapers.base import NoticeRow, ParseFailed, ScrapeFailed
from warn_v2.scrapers.registry import register
from warn_v2.scrapers.wayback import replay_url

_URL = "https://does.dc.gov/page/industry-closings-and-layoffs-warn-notifications-{year}"

_UA = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) warn-v2/0.1"
    )
}

_CODE_TYPE = {"1": "Layoff", "2": "Permanent Closures"}

# Count-column header variants across year pages: current pages run the words
# together ("toemployees"); older pages (e.g. 2020) spell it out.
_COUNT_HEADERS = (
    "number toemployees affected",
    "number to employees affected",
    "number of employees affected",
    "employees affected",
)


def _source_url(year: int) -> str:
    return _URL.format(year=year)


def _fetch_dc_year(year: int) -> bytes | None:
    """Fetch the DC WARN HTML table for a specific year.

    Returns the page bytes if the table is present, or None if the page exists
    but has no WARN data (empty year or future year).
    """
    url = _source_url(year)
    try:
        r = httpx.get(url, headers=_UA, timeout=60, follow_redirects=True)
        r.raise_for_status()
    except httpx.HTTPError:
        return None
    return r.content if b"Organization Name" in r.content else None


class DCScraper:
    state = "DC"
    source_url = _URL.format(year=date.today().year)
    expected_row_range = (1, 500)
    required_fields = frozenset({"employer", "notice_date"})

    def fetch(self) -> bytes:
        year = date.today().year
        for yr in (year, year - 1):
            url = _source_url(yr)
            try:
                r = httpx.get(url, headers=_UA, timeout=60, follow_redirects=True)
                r.raise_for_status()
                if b"Organization Name" in r.content or b"organization name" in r.content.lower():
                    self.source_url = url
                    return r.content
            except httpx.HTTPError:
                pass
        raise ScrapeFailed(f"Could not fetch DC WARN page for {year} or {year - 1}")

    def parse(self, raw: bytes) -> list[NoticeRow]:
        soup = BeautifulSoup(raw, "html.parser")
        table = soup.find("table")
        if table is None:
            raise ParseFailed("no <table> found on DC WARN page")

        all_trs = table.find_all("tr")
        if not all_trs:
            raise ParseFailed("DC table has no rows")

        header_cells = [_text(td).lower() for td in all_trs[0].find_all(["td", "th"])]
        if not header_cells or "organization name" not in header_cells:
            raise ParseFailed(f"unexpected DC header: {header_cells[:6]}")
        col = {name: i for i, name in enumerate(header_cells)}

        rows: list[NoticeRow] = []
        for tr in all_trs[1:]:
            cells = tr.find_all(["td", "th"])
            if len(cells) < len(header_cells):
                continue
            employer = as_str(_text(cells[col["organization name"]]))
            if not employer:
                continue
            notice_date = as_date(_text(cells[col["notice date"]]))
            if notice_date is None:
                continue

            code_col = col.get("code type")
            code = _text(cells[code_col]).strip() if code_col is not None else ""
            closure_type = _CODE_TYPE.get(code, as_str(code)) or None

            eff_col = col.get("effective layoff date")
            effective_date = (
                as_date(_text(cells[eff_col])) if eff_col is not None else None
            )

            count_col = next(
                (col[k] for k in _COUNT_HEADERS if k in col), None
            )
            layoff_count = (
                as_int(_text(cells[count_col])) if count_col is not None else None
            )

            rows.append(
                NoticeRow(
                    state="DC",
                    employer=employer,
                    notice_date=notice_date,
                    effective_date=effective_date,
                    layoff_count=layoff_count,
                    closure_type=closure_type,
                    source_url=self.source_url,
                )
            )
        return rows


def _text(cell) -> str:
    return " ".join(cell.get_text(" ", strip=True).split())


register(DCScraper())


# ---------------------------------------------------------------------------
# Historical backfill: the 2002 - Jan 2012 "Monthly WARN Notification Log"
# ---------------------------------------------------------------------------

# The old CWP site kept one growing log at an opaque URL. CDX has 50 distinct
# versions (2004-03 → 2012-05), compared offline 2026-10-26. The latest holds
# 147 notices from 2005-01 on. Only the two 2005 versions add notices it
# dropped (17, 2002-11 → 2005-12). The 2007 and 2009 versions add nothing
# but respellings of rows the latest keeps ("D.C Department of Health" vs
# "DC Department of Health", "HellerEhrman" vs "Heller Ehrman"), which would
# duplicate under the notice_id hash, so they are left out. Nothing is
# captured for Feb 2012 - 2014.
_LOG_URL = "http://does.dc.gov/does/cwp/view,a,1232,q,572897.asp"
_LOG_CAPTURES: tuple[str, ...] = ("20120514073024", "20051208073424", "20050408160035")

_LOG_DATE_RE = re.compile(r"^\d{1,2}/(?:\d{1,2}/)?\d{2,4}$")
_LEADING_INT_RE = re.compile(r"^\s*([\d,]+)")


def dc_log_urls() -> list[str]:
    return [replay_url(ts, _LOG_URL) for ts in _LOG_CAPTURES]


def _log_date(raw: str) -> date | None:
    """MM/DD/YY(YY), or month-only MM/YYYY (some 2008 rows) → 1st of month."""
    m = re.fullmatch(r"(\d{1,2})/(\d{4})", raw)
    return date(int(m.group(2)), int(m.group(1)), 1) if m else as_date(raw)


def parse_dc_log(raw: bytes, source_url: str) -> list[NoticeRow]:
    """Parse one capture of the monthly log.

    The markup nests tables and drops ``<tr>`` tags, so rows are read off the
    innermost ``<td>`` cells in document order: a record is five cells
    (notice date | organization | # affected | effective date | type code)
    starting at a date cell; month-name divider runs are skipped. Pre-2005
    organization cells end in a "WARN" link label, which is stripped. Counts
    keep their leading number ("8 ALPA Employees" → 8; "Unspecified
    Number" → None).
    """
    soup = BeautifulSoup(raw, "html.parser")
    cells = [_text(td) for td in soup.find_all("td") if not td.find("td")]
    rows: list[NoticeRow] = []
    i = 0
    while i + 4 < len(cells):
        date_raw, org, count_raw, eff_raw, code = cells[i : i + 5]
        notice_date = _log_date(date_raw) if _LOG_DATE_RE.match(date_raw) else None
        if notice_date is None or not org or _LOG_DATE_RE.match(org):
            i += 1
            continue
        m = _LEADING_INT_RE.match(count_raw)
        rows.append(
            NoticeRow(
                state="DC",
                employer=re.sub(r"\s+WARN$", "", org),
                notice_date=notice_date,
                effective_date=_log_date(eff_raw) if _LOG_DATE_RE.match(eff_raw) else None,
                layoff_count=as_int(m.group(1)) if m else None,
                closure_type=_CODE_TYPE.get(code.strip(), as_str(code)),
                source_url=source_url,
            )
        )
        i += 5
    if not rows:
        raise ParseFailed("DC WARN log: no notice rows parsed")
    return rows
