"""Washington WARN scraper.

Source: https://fortress.wa.gov/esd/file/warn/Public/SearchWARN.aspx
        (ASP.NET GridView rendered as an HTML table).

Schema (live as of May 2026):
  Company | Location | Layoff Start Date | # of Workers | Closure Layoff |
  Type of Layoff | Received Date | Notice

The GridView (``ucPSW_gvMain``) paginates ~15 rows/page behind ASP.NET
``__doPostBack`` links (``__EVENTTARGET=ucPSW$gvMain``,
``__EVENTARGUMENT=Page$N``). A plain GET returns only the newest page, so
``fetch()`` replays the postback for each successive page — carrying forward
the fresh ``__VIEWSTATE``/``__EVENTVALIDATION`` tokens every response mints —
and concatenates the raw page bytes (like the FL paginator). ``parse()`` then
scans every ``ucPSW_gvMain`` table across the concatenated pages, so the daily
run captures the whole list instead of just the first page.
"""
from __future__ import annotations

import re

import httpx
from bs4 import BeautifulSoup

from warn_v2.scrapers._helpers import as_date, as_int, as_str
from warn_v2.scrapers.base import NoticeRow, ParseFailed, ScrapeFailed
from warn_v2.scrapers.registry import register

SOURCE_URL = "https://fortress.wa.gov/esd/file/warn/Public/SearchWARN.aspx"

_GRID_ID = "ucPSW_gvMain"
_EVENT_TARGET = "ucPSW$gvMain"
# The list is a few dozen pages; this only guards against a runaway loop if
# next-page detection ever misfires.
_MAX_PAGES = 500

_UA = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) warn-v2/0.1"
    )
}

_PAGE_RE = re.compile(r"Page\$(\d+)")
_REQUIRED_COLS = (
    "company",
    "location",
    "layoff start date",
    "# of workers",
    "type of layoff",
    "received date",
)


class WAScraper:
    state = "WA"
    source_url = SOURCE_URL
    # Depth is set by however many pages the site retains; the upper bound is
    # generous so the first full paginated run doesn't trip validation.
    expected_row_range = (5, 20_000)
    required_fields = frozenset({"employer", "notice_date"})

    def fetch(self) -> bytes:
        try:
            with httpx.Client(
                headers=_UA, timeout=60, follow_redirects=True
            ) as client:
                r = client.get(SOURCE_URL)
                r.raise_for_status()
                chunks = [r.content]
                soup = BeautifulSoup(r.content, "html.parser")

                page = 1
                while page < _MAX_PAGES:
                    nxt = page + 1
                    if nxt not in _page_targets(soup):
                        break
                    payload = _postback_payload(soup, f"Page${nxt}")
                    r = client.post(SOURCE_URL, data=payload)
                    r.raise_for_status()
                    chunks.append(r.content)
                    soup = BeautifulSoup(r.content, "html.parser")
                    page = nxt
        except httpx.HTTPError as e:
            raise ScrapeFailed(f"WA SearchWARN.aspx: {e}") from e

        return b"\n".join(chunks)

    def parse(self, raw: bytes) -> list[NoticeRow]:
        soup = BeautifulSoup(raw, "html.parser")
        # fetch() concatenates one HTML document per page, so a parsed blob can
        # hold several GridViews — collect rows across all of them. Selecting by
        # id skips the nested pager sub-tables; the fallback keeps a bare-table
        # capture (or the without-table error path) working.
        tables = soup.find_all("table", id=_GRID_ID) or soup.find_all("table")
        if not tables:
            raise ParseFailed("no <table> found on WA WARN page")

        rows: list[NoticeRow] = []
        for table in tables:
            rows.extend(_parse_grid(table))
        if not rows:
            raise ParseFailed("WA table: no data rows parsed")
        return rows


def _parse_grid(table) -> list[NoticeRow]:
    """Parse one GridView table into notice rows (empty list if it isn't one)."""
    all_trs = table.find_all("tr")

    # Find header row: the one containing a cell with text "Company".
    header_idx = None
    for i, tr in enumerate(all_trs):
        texts = [_text(td).lower() for td in tr.find_all(["td", "th"])]
        if "company" in texts:
            header_idx = i
            break
    if header_idx is None:
        return []

    header_cells = [_text(td).lower() for td in all_trs[header_idx].find_all(["td", "th"])]
    col = {name: i for i, name in enumerate(header_cells)}
    if not all(c in col for c in _REQUIRED_COLS):
        return []

    closure_idx = col.get("closure layoff")

    rows: list[NoticeRow] = []
    for tr in all_trs[header_idx + 1:]:
        cells = tr.find_all(["td", "th"])
        if len(cells) < len(header_cells):
            continue
        employer = as_str(_text(cells[col["company"]]))
        if not employer:
            continue
        # Skip pagination rows (employer cell is a bare page number / "...").
        bare = employer.replace(".", "").replace(" ", "")
        if bare.isdigit() or not employer[0].isalpha():
            continue

        notice_date = as_date(_text(cells[col["received date"]]))
        if notice_date is None:
            continue

        closure_layoff = (
            as_str(_text(cells[closure_idx]))
            if closure_idx is not None and closure_idx < len(cells)
            else None
        )

        rows.append(
            NoticeRow(
                state="WA",
                employer=employer,
                notice_date=notice_date,
                effective_date=as_date(_text(cells[col["layoff start date"]])),
                layoff_count=as_int(_text(cells[col["# of workers"]])),
                closure_type=as_str(_text(cells[col["type of layoff"]])),
                city=as_str(_text(cells[col["location"]])),
                source_url=SOURCE_URL,
                extra={"closure_layoff": closure_layoff or ""},
            )
        )
    return rows


def _page_targets(soup: BeautifulSoup) -> set[int]:
    """Page numbers reachable via ``Page$N`` postback links on this page."""
    targets: set[int] = set()
    for a in soup.find_all("a", href=True):
        for m in _PAGE_RE.finditer(a["href"]):
            targets.add(int(m.group(1)))
    return targets


def _postback_payload(soup: BeautifulSoup, event_argument: str) -> dict[str, str]:
    """Build the form body for a GridView pager postback.

    Carries forward every hidden field (``__VIEWSTATE``, ``__VIEWSTATEGENERATOR``,
    ``__EVENTVALIDATION`` …) plus the empty search box, and excludes the submit
    button so the postback pages rather than re-runs the search.
    """
    data: dict[str, str] = {}
    for inp in soup.find_all("input"):
        name = inp.get("name")
        if not name:
            continue
        itype = (inp.get("type") or "text").lower()
        if itype in ("submit", "button", "image", "reset"):
            continue
        data[name] = inp.get("value") or ""
    data["__EVENTTARGET"] = _EVENT_TARGET
    data["__EVENTARGUMENT"] = event_argument
    return data


def _text(cell) -> str:
    return " ".join(cell.get_text(" ", strip=True).split())


register(WAScraper())
