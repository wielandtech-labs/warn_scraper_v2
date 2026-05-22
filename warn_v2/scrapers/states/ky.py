"""Kentucky WARN scraper.

Source:  https://kcc.ky.gov/employer/Pages/Business-Downsizing-Assistance---WARN.aspx
Data:    Cumulative YTD CSV files in a SharePoint document library.

The file listing page requires authentication, but the SharePoint REST API is
publicly accessible:
  https://kcc.ky.gov/_api/web/GetFolderByServerRelativeUrl(
      '/WARN notices/WARN Notices {year}')/Files

fetch() queries this API to discover the most recent CSV, then downloads it.
Each CSV is cumulative (all notices for the current year to date).

CSV columns (header quirk: first column is "Company: Company Name"):
  Company: Company Name | Notice Type | Notice: Notice Number |
  Closure or Layoff? | County | Date Received | NAICS | Notice URL |
  Number of Employees Affected | Projected Date | Trade |
  Type of Employees Affected | Workforce Board
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

_LANDING_URL = (
    "https://kcc.ky.gov/employer/Pages/Business-Downsizing-Assistance---WARN.aspx"
)
_SP_API = (
    "https://kcc.ky.gov/_api/web/GetFolderByServerRelativeUrl("
    "'/WARN notices/WARN Notices {year}')/Files"
)
_BASE_URL = "https://kcc.ky.gov"

_UA = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
    )
}

_DATE_YEAR_RE = re.compile(r"(\d{4})-(\d{2})-(\d{2})")
_LEADING_INT = re.compile(r"\d+")


def _discover_csv_url(year: int) -> str | None:
    """Query the SharePoint API to find the most recent CSV for *year*."""
    api_url = _SP_API.format(year=year)
    try:
        r = httpx.get(api_url, headers=_UA, timeout=30, follow_redirects=True)
        r.raise_for_status()
        # Parse the Atom feed to extract file names
        soup = BeautifulSoup(r.content, "xml")
        names = [tag.text for tag in soup.find_all("Name") if tag.text.endswith(".csv")]
        if not names:
            return None
        # Sort descending; ISO-like names sort correctly lexicographically
        names.sort(reverse=True)
        latest = names[0]
        path = f"/WARN notices/WARN Notices {year}/{latest}"
        return _BASE_URL + path.replace(" ", "%20")
    except httpx.HTTPError:
        return None


def _normalize_header(h: str) -> str:
    """Lowercase, collapse whitespace, strip 'company: ' prefix quirk."""
    key = " ".join(h.lower().split())
    # First column is "company: company name" — normalise to "company name"
    if key.startswith("company:"):
        key = key[key.index(":") + 1 :].strip()
    return key


class KYScraper:
    state = "KY"
    source_url = _LANDING_URL
    expected_row_range = (5, 5_000)
    required_fields = frozenset({"employer", "notice_date"})

    def fetch(self) -> bytes:
        from datetime import date

        for year in (date.today().year, date.today().year - 1):
            csv_url = _discover_csv_url(year)
            if csv_url:
                break
        if not csv_url:
            raise ScrapeFailed("KY: could not discover current CSV URL")
        try:
            r = httpx.get(csv_url, headers=_UA, timeout=60, follow_redirects=True)
            r.raise_for_status()
            return r.content
        except httpx.HTTPError as e:
            raise ScrapeFailed(f"GET {csv_url}: {e}") from e

    def parse(self, raw: bytes) -> list[NoticeRow]:
        try:
            text = raw.decode("utf-8-sig")  # BOM-safe
        except UnicodeDecodeError:
            try:
                text = raw.decode("latin-1")
            except Exception as e:
                raise ParseFailed(f"KY CSV: decode error: {e}") from e

        try:
            reader = csv.DictReader(io.StringIO(text))
            raw_rows = list(reader)
        except Exception as e:
            raise ParseFailed(f"KY CSV: parse error: {e}") from e

        if not raw_rows:
            raise ParseFailed("KY CSV: no data rows found")

        # Build normalised field-name map from the actual CSV header
        fieldnames = reader.fieldnames or []
        if not fieldnames:
            raise ParseFailed("KY CSV: missing header row")
        norm = {_normalize_header(f): f for f in fieldnames}

        def _get(raw_row: dict, key: str, *fallbacks: str) -> str:
            for k in (key, *fallbacks):
                orig = norm.get(k, k)
                if orig in raw_row:
                    return raw_row[orig].strip()
            return ""

        rows: list[NoticeRow] = []
        for raw_row in raw_rows:
            employer = _get(raw_row, "company name")
            if not employer:
                continue

            notice_date = as_date(_get(raw_row, "date received"))
            if notice_date is None:
                continue

            eff_raw = _get(raw_row, "projected date")
            effective_date = as_date(eff_raw) if eff_raw else None

            count_raw = _get(raw_row, "number of employees affected")
            m = _LEADING_INT.search(count_raw)
            layoff_count = as_int(m.group()) if m else None

            closure_type = as_str(_get(raw_row, "closure or layoff?"))
            county = as_str(_get(raw_row, "county"))
            raw_notice_url = as_str(_get(raw_row, "notice url")) or None
            wda = _get(raw_row, "workforce board")
            notice_num = _get(raw_row, "notice number", "notice: notice number")

            rows.append(
                NoticeRow(
                    state="KY",
                    employer=employer,
                    notice_date=notice_date,
                    effective_date=effective_date,
                    layoff_count=layoff_count,
                    closure_type=closure_type,
                    county=county,
                    raw_notice_url=raw_notice_url,
                    source_url=_LANDING_URL,
                    extra={
                        "wda": wda,
                        "notice_number": notice_num,
                    },
                )
            )
        return rows


register(KYScraper())
