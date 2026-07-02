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


# The SharePoint folders switched to cumulative CSV exports in 2025; the
# .xlsx workbooks uploaded alongside them carry one sheet per year back to
# 2017, so a single recent workbook holds the whole pre-CSV history.  Sheets
# for CSV-era years are skipped — those rows are already ingested from the
# CSVs, and the workbook renders some fields differently (county format),
# which would insert near-miss duplicates.
_CSV_ERA_START = 2025


def _discover_workbook_urls() -> list[str]:
    """Find the most recently modified .xlsx workbook for backfill-historical.

    Searches the current year's folder first, then back one year — CSV-only
    folders (no .xlsx) are skipped.  Returns at most one URL: any single
    workbook contains every historical year as its own sheet, so ingesting
    more than one would only re-insert the same rows.

    Only 2021-and-earlier folders hold .xls (pre-xml) files; those same years
    appear as sheets in the newer .xlsx workbooks, so xlrd is not needed.
    """
    from datetime import date

    year = date.today().year
    for y in (year, year - 1):
        api_url = _SP_API.format(year=y) + "?$select=Name,TimeLastModified"
        try:
            r = httpx.get(api_url, headers=_UA, timeout=30, follow_redirects=True)
            r.raise_for_status()
        except httpx.HTTPError:
            continue
        soup = BeautifulSoup(r.content, "xml")
        candidates: list[tuple[str, str]] = []  # (last_modified, name)
        for props in soup.find_all("properties"):
            name_tag = props.find("Name")
            mod_tag = props.find("TimeLastModified")
            if name_tag is None or not name_tag.text.lower().endswith(".xlsx"):
                continue
            candidates.append((mod_tag.text if mod_tag else "", name_tag.text))
        if candidates:
            latest = max(candidates)[1]
            path = f"/WARN notices/WARN Notices {y}/{latest}"
            return [_BASE_URL + path.replace(" ", "%20")]
    return []


def parse_ky_workbook(raw: bytes) -> list[NoticeRow]:
    """Parse the per-year sheets of a KY WARN workbook (pre-CSV-era years only).

    Sheet names are years; columns (2024-era, older sheets vary slightly):
      Date Received | Region | County | Company Name | NAICS Code | Employees |
      Closure or Layoff? | Projected Date | Trade | Notice URL | Notice Link
    """
    import openpyxl

    try:
        wb = openpyxl.load_workbook(io.BytesIO(raw), read_only=True, data_only=True)
    except Exception as e:
        raise ParseFailed(f"KY workbook: could not open: {e}") from e

    rows: list[NoticeRow] = []
    for ws in wb.worksheets:
        try:
            sheet_year = int(str(ws.title).strip())
        except ValueError:
            continue
        if sheet_year >= _CSV_ERA_START:
            continue

        col: dict[str, int] = {}
        for values in ws.iter_rows(values_only=True):
            if not col:
                header = [_normalize_header(str(c)) if c is not None else "" for c in values]
                # Old sheets title the county column "County: Local  Name".
                col = {
                    ("county" if h.startswith("county") else h): i
                    for i, h in enumerate(header)
                    if h
                }
                if "company name" not in col or "date received" not in col:
                    raise ParseFailed(
                        f"KY workbook sheet {ws.title!r}: unexpected header {header}"
                    )
                continue

            def _get(key: str, _col=col, _values=values) -> object:
                i = _col.get(key)
                return _values[i] if i is not None and i < len(_values) else None

            employer = as_str(_get("company name"))
            if not employer:
                continue
            notice_date = as_date(_get("date received"))
            if notice_date is None:
                continue
            rows.append(
                NoticeRow(
                    state="KY",
                    employer=employer,
                    notice_date=notice_date,
                    effective_date=as_date(_get("projected date")),
                    layoff_count=as_int(_get("employees")),
                    closure_type=as_str(_get("closure or layoff?")),
                    county=as_str(_get("county")),
                    raw_notice_url=as_str(_get("notice url")) or None,
                    source_url=_LANDING_URL,
                    extra={"wda": as_str(_get("region")) or ""},
                )
            )
    if not rows:
        raise ParseFailed("KY workbook: no pre-CSV-era rows parsed")
    return rows


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
