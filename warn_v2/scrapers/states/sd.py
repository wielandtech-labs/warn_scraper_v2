"""South Dakota WARN scraper.

Source: https://dlr.sd.gov/workforce_services/businesses/warn_notices.aspx

Schema (live as of May 2026):
  Company | Location | Date Received | Employees Affected

Static HTML table; company cell has an anchor linking to a per-notice PDF
at /workforce_services/businesses/warn_notices/<slug>.pdf on dlr.sd.gov.

Location can be a comma-separated list of cities; city is set to the first.
Employees Affected can have a non-numeric suffix like "(nationwide)" — we
extract only the leading integer.
"""
from __future__ import annotations

import io
import re
import time

import httpx
import pdfplumber
from bs4 import BeautifulSoup

from warn_v2.scrapers._helpers import as_date, as_int, as_str
from warn_v2.scrapers.base import NoticeRow, ParseFailed, ScrapeFailed
from warn_v2.scrapers.bundled import DATA_DIR, load_archive
from warn_v2.scrapers.registry import register

SOURCE_URL = "https://dlr.sd.gov/workforce_services/businesses/warn_notices.aspx"
_BASE_URL = "https://dlr.sd.gov"

_UA = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) warn-v2/0.1"
    )
}

_LEADING_INT = re.compile(r"^\d+")

# dlr.sd.gov intermittently returns 503 on this page while the site root stays
# up (~40-50% of requests in a 2026-07-04 probe), so a single GET is flaky;
# retry a few times.
_FETCH_ATTEMPTS = 5
_FETCH_BACKOFF = 3.0


class SDScraper:
    state = "SD"
    source_url = SOURCE_URL
    expected_row_range = (5, 5_000)
    required_fields = frozenset({"employer", "notice_date"})

    def fetch(self) -> bytes:
        last_exc: httpx.HTTPError | None = None
        for attempt in range(1, _FETCH_ATTEMPTS + 1):
            try:
                r = httpx.get(SOURCE_URL, headers=_UA, timeout=30, follow_redirects=True)
                r.raise_for_status()
                return r.content
            except httpx.HTTPError as e:
                last_exc = e
                if attempt < _FETCH_ATTEMPTS:
                    time.sleep(_FETCH_BACKOFF)
        raise ScrapeFailed(f"GET {SOURCE_URL}: {last_exc}") from last_exc

    def parse(self, raw: bytes) -> list[NoticeRow]:
        soup = BeautifulSoup(raw, "html.parser")
        table = soup.find("table")
        if table is None:
            raise ParseFailed("no <table> found on SD WARN page")

        all_trs = table.find_all("tr")
        if not all_trs:
            raise ParseFailed("SD table has no rows")

        header_cells = [_text(td).lower() for td in all_trs[0].find_all(["td", "th"])]
        if not header_cells or "company" not in header_cells:
            raise ParseFailed(f"unexpected SD header: {header_cells[:5]}")
        col = {name: i for i, name in enumerate(header_cells)}

        rows: list[NoticeRow] = []
        for tr in all_trs[1:]:
            cells = tr.find_all(["td", "th"])
            if len(cells) < 3:
                continue

            company_cell = cells[col["company"]]
            anchor = company_cell.find("a")
            employer = as_str(_text(anchor) if anchor else _text(company_cell))
            if not employer:
                continue
            notice_date = as_date(_text(cells[col["date received"]]))
            if notice_date is None:
                continue

            notice_url: str | None = None
            if anchor and anchor.get("href"):
                href = anchor["href"]
                notice_url = href if href.startswith("http") else _BASE_URL + href

            location_raw = _text(cells[col["location"]])
            city = as_str(location_raw.split(",")[0].strip()) if location_raw else None

            count_raw = _text(cells[col["employees affected"]])
            m = _LEADING_INT.match(count_raw)
            layoff_count = int(m.group()) if m else None

            rows.append(
                NoticeRow(
                    state="SD",
                    employer=employer,
                    notice_date=notice_date,
                    layoff_count=layoff_count,
                    city=city,
                    raw_notice_url=notice_url,
                    source_url=SOURCE_URL,
                )
            )
        return rows


def _text(cell) -> str:
    return " ".join(cell.get_text(" ", strip=True).split())


register(SDScraper())


# ---------------------------------------------------------------------------
# Historical backfill: 1997-2005 frozen cumulative PDF (Mode 3b bundled)
# ---------------------------------------------------------------------------
# state.sd.us froze "WARN Notices Received.pdf" at PY-05 (Jul-1997 → Dec-2005,
# 60 notices / 8,232 workers across three program-year sections); the file is
# bundled from its Wayback capture. The gap 2006 → Apr-2007 is real — the
# successor page (today's live scraper) starts at 05/2007. Rows are keyed by
# their own date, NOT their section/position: one 2004 notice is filed among
# the 2002 rows.

_ARCHIVE_SOURCE_URL = (
    "https://web.archive.org/web/20070114121809/"
    "http://www.state.sd.us/dol/WIA/WIA%20Handbook/WARN%20Notices%20Received.pdf"
)


def sd_archive_files() -> list[tuple[str, bytes]]:
    """Members of the bundled SD historical archive (one frozen PDF)."""
    return load_archive(DATA_DIR / "sd_archive.tar.gz")


def parse_sd_archive_pdf(raw: bytes) -> list[NoticeRow]:
    """Parse the frozen 1997-2005 cumulative PDF.

    Grid columns: Date | Company | Location | # Workers | Action. Section
    headers, repeated column-label rows, blank spacers, and per-section
    "Total" rows are skipped — a data row is any row whose first cell parses
    as a date. The trailing "combined total" row (notice count + worker sum)
    is checked against what we parsed so a silent extraction drift fails loud.
    """
    try:
        pdf = pdfplumber.open(io.BytesIO(raw))
    except Exception as e:
        raise ParseFailed(f"SD archive PDF: could not open: {e}") from e

    rows: list[NoticeRow] = []
    expected: tuple[int, int] | None = None  # (notices, workers) from "combined total"
    with pdf:
        for page in pdf.pages:
            for cells in page.extract_table() or []:
                cells = [(" ".join(str(c).split()) if c else "") for c in cells]
                if len(cells) < 5:
                    continue
                if cells[0].lower() == "combined total":
                    expected = (as_int(cells[1]), as_int(cells[3]))
                    continue
                notice_date = as_date(cells[0])
                if notice_date is None:
                    continue  # section header / column labels / Total / spacer
                employer = as_str(cells[1])
                if not employer:
                    continue
                action = as_str(cells[4])
                rows.append(
                    NoticeRow(
                        state="SD",
                        employer=employer,
                        notice_date=notice_date,
                        layoff_count=as_int(cells[3]),
                        closure_type=action.capitalize() if action else None,
                        city=as_str(cells[2].split(",")[0]),
                        source_url=_ARCHIVE_SOURCE_URL,
                    )
                )

    if not rows:
        raise ParseFailed("SD archive PDF: no data rows found")
    if expected is not None:
        got = (len(rows), sum(r.layoff_count or 0 for r in rows))
        if got != expected:
            raise ParseFailed(
                f"SD archive PDF: parsed {got[0]} notices / {got[1]} workers, "
                f"but the PDF's combined-total row says {expected[0]} / {expected[1]}"
            )
    return rows
