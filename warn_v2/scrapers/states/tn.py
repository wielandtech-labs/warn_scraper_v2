"""Tennessee WARN scraper.

Source: https://www.tn.gov/workforce/general-resources/major-publications0/major-publications-redirect/reports.html

Schema (live as of May 2026):
  Date of Posting | Company | County | Affected Workers |
  Closure/Layoff Date | Notice/Type

The page has two tables: one for the current year and one for the archive.
Both use the same column structure; we parse both and combine them.
Company cell has an anchor tag linking to a per-notice PDF hosted on tn.gov.

Notice/Type contains a notice number (e.g. "#202500055"), not a layoff type;
we capture it in extra["notice_number"].

Note: tn.gov's WAF resets the TLS connection (Errno 104) for non-browser TLS
fingerprints — a plain httpx GET succeeds from a residential browser but is RST
from server/container deployments (same IP, different ClientHello). We fetch via
curl_cffi with ``impersonate="chrome"`` so the handshake matches a real Chrome,
which the WAF accepts.
"""
from __future__ import annotations

import time

from bs4 import BeautifulSoup
from curl_cffi import requests as cffi_requests
from curl_cffi.requests.exceptions import RequestException

from warn_v2.scrapers._helpers import as_date, as_int, as_str
from warn_v2.scrapers.base import NoticeRow, ParseFailed, ScrapeFailed
from warn_v2.scrapers.registry import register

SOURCE_URL = (
    "https://www.tn.gov/workforce/general-resources/"
    "major-publications0/major-publications-redirect/reports.html"
)
_BASE_URL = "https://www.tn.gov"

# The WAF still RSTs a fraction (~1 in 4) of otherwise-valid Chrome handshakes,
# so a single GET is flaky even with impersonation; retry a few times.
_FETCH_ATTEMPTS = 4
_FETCH_BACKOFF = 2.0


class TNScraper:
    state = "TN"
    source_url = SOURCE_URL
    expected_row_range = (5, 10_000)
    required_fields = frozenset({"employer", "notice_date"})

    def fetch(self) -> bytes:
        last_exc: RequestException | None = None
        for attempt in range(1, _FETCH_ATTEMPTS + 1):
            try:
                r = cffi_requests.get(
                    SOURCE_URL, impersonate="chrome", timeout=30, allow_redirects=True
                )
                r.raise_for_status()
                return r.content
            except RequestException as e:
                last_exc = e
                if attempt < _FETCH_ATTEMPTS:
                    time.sleep(_FETCH_BACKOFF)
        raise ScrapeFailed(f"GET {SOURCE_URL}: {last_exc}") from last_exc

    def parse(self, raw: bytes) -> list[NoticeRow]:
        soup = BeautifulSoup(raw, "html.parser")
        tables = soup.find_all("table")
        if not tables:
            raise ParseFailed("no <table> found on TN WARN page")

        rows: list[NoticeRow] = []
        for table in tables:
            rows.extend(_parse_table(table))

        if not rows:
            raise ParseFailed("TN WARN page: no data rows found in any table")
        return rows


def _parse_table(table) -> list[NoticeRow]:
    all_trs = table.find_all("tr")
    if not all_trs:
        return []

    header_cells = [_text(td).lower() for td in all_trs[0].find_all(["td", "th"])]
    if "company" not in header_cells or "county" not in header_cells:
        return []
    col = {name: i for i, name in enumerate(header_cells)}

    rows: list[NoticeRow] = []
    for tr in all_trs[1:]:
        cells = tr.find_all(["td", "th"])
        if len(cells) < 4:
            continue

        company_cell = cells[col["company"]]
        anchor = company_cell.find("a")
        employer = as_str(_text(anchor) if anchor else _text(company_cell))
        if not employer:
            continue
        notice_date = as_date(_text(cells[col["date of posting"]]))
        if notice_date is None:
            continue

        notice_url: str | None = None
        if anchor and anchor.get("href"):
            href = anchor["href"]
            notice_url = href if href.startswith("http") else _BASE_URL + href

        notice_type_idx = col.get("notice/type")
        notice_number = (
            as_str(_text(cells[notice_type_idx])) if notice_type_idx is not None else None
        )

        rows.append(
            NoticeRow(
                state="TN",
                employer=employer,
                notice_date=notice_date,
                effective_date=as_date(_text(cells[col["closure/layoff date"]])),
                layoff_count=as_int(_text(cells[col["affected workers"]])),
                county=as_str(_text(cells[col["county"]])),
                raw_notice_url=notice_url,
                source_url=SOURCE_URL,
                extra={"notice_number": notice_number or ""},
            )
        )
    return rows


def _text(cell) -> str:
    return " ".join(cell.get_text(" ", strip=True).split())


register(TNScraper())
