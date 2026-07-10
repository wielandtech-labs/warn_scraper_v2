"""Massachusetts WARN scraper.

Source: https://www.mass.gov/info-details/warn-layoff-and-closure-updates
Administered by the Massachusetts Executive Office of Labor and Workforce Development.

Two-step approach:
  1. Playwright (Chrome UA) loads the index page to discover CSV download links — the
     index page blocks non-browser user agents.
  2. httpx with its *default* user agent downloads each CSV file.  The files are served
     from mass.gov/files/csv/ which is publicly accessible, but Akamai blocks Chrome
     UAs from server IPs (looks like a bot pretending to be a browser).  Using httpx's
     neutral "python-httpx/..." UA avoids that false-positive 403.

Each weekly CSV released on Friday contains ALL notices for the current fiscal year
(July - June), so one download covers the full current-year dataset.

Schema (confirmed from live site, May 2026):
  RECEIVED | EMPLOYER | CITY/TOWN | REGION | DATE(S) OF LAYOFFS | # EMPLOYEES IMPACTED
"""
from __future__ import annotations

import csv
import io
import json
import logging
import re
from collections.abc import Callable
from datetime import date, datetime

from warn_v2.scrapers._helpers import as_date, as_int, as_str
from warn_v2.scrapers.base import NoticeRow, ParseFailed, ScrapeFailed
from warn_v2.scrapers.playwright_base import PlaywrightScraper
from warn_v2.scrapers.registry import register

log = logging.getLogger(__name__)

SOURCE_URL = (
    "https://www.mass.gov/info-details/"
    "worker-adjustment-and-retraining-notification-act-warn-layoff-and-closure-updates"
)

_CHROME_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)

_DATE_RE = re.compile(r"\d{1,2}/\d{1,2}/\d{4}")
# Looser date for the historical XLSX parser: 1-/2-digit month & day, 2-/4-digit
# year (e.g. "8/15/26", "07/07/2021 - (08/30/2021)").
_LOOSE_DATE_RE = re.compile(r"(\d{1,2})[/-](\d{1,2})[/-](\d{2,4})")
_INT_RE = re.compile(r"\d[\d,]*")
# Strip trailing state label from CITY/TOWN values like "Boston, MA"
_STATE_SUFFIX_RE = re.compile(r",\s*(MA|Massachusetts)\s*$", re.IGNORECASE)
# Historical per-fiscal-year XLSX reports ("Previous WARN reports" on the page):
#   https://www.mass.gov/doc/fy22-warn-report/download  ...  fy26 (a -0 suffix).
_FY_DOC_RE = re.compile(r"/doc/fy(\d\d)-warn-report", re.IGNORECASE)
_FY_REPORT_URL = "https://www.mass.gov/doc/fy{yy:02d}-warn-report/download"


class MAScraper(PlaywrightScraper):
    state = "MA"
    source_url = SOURCE_URL
    expected_row_range = (5, 1_000)
    required_fields = frozenset({"employer", "notice_date"})

    def fetch(self) -> bytes:
        """Discover CSV links via Playwright, then download them in the same session.

        Akamai bot-detection gates both the index page and the CSV files.
        ``ctx.request.get()`` (fetch-style headers) and standalone httpx both
        return 403.  ``page.goto()`` passes the CDN check but triggers Playwright's
        download interception because the server responds with
        ``Content-Disposition: attachment``.  The correct pattern is to use
        ``page.expect_download()`` so Playwright saves the file to a temp path
        that we can read back as bytes.
        """
        try:
            from pathlib import Path

            from playwright.sync_api import sync_playwright

            from warn_v2.scrapers.playwright_base import _LAUNCH_ARGS

            files: list[dict[str, str]] = []
            with sync_playwright() as pw:
                browser = pw.chromium.launch(headless=True, args=_LAUNCH_ARGS)
                try:
                    # accept_downloads=True tells Playwright to save downloads
                    # to a temp directory and expose them via Download objects.
                    ctx = browser.new_context(
                        user_agent=_CHROME_UA, accept_downloads=True
                    )
                    page = ctx.new_page()

                    # Step 1: load index page and find the weekly-CSV download
                    # link(s).  Retries with a reload to clear Akamai's bot
                    # challenge (see _discover_csv_links).
                    csv_urls = _discover_csv_links(page)

                    if not csv_urls:
                        raise ScrapeFailed("MA: no CSV links found on mass.gov WARN page")

                    log.info("MA: found %d CSV link(s): %s", len(csv_urls), csv_urls)

                    # Step 2: navigate to each CSV URL as a full page navigation
                    # (passes Akamai) and capture the resulting file download.
                    for url in csv_urls:
                        try:
                            with page.expect_download(timeout=60_000) as dl_info:
                                try:
                                    page.goto(url, wait_until="commit", timeout=60_000)
                                except Exception:
                                    # Playwright raises "Download is starting" when
                                    # the server sends Content-Disposition: attachment.
                                    # The download is still captured by expect_download.
                                    pass
                            dl = dl_info.value
                            dl_path = dl.path()
                            if not dl_path:
                                log.warning("MA: download of %s produced no file", url)
                                continue
                            text = Path(dl_path).read_bytes().decode("utf-8-sig")
                            files.append({"url": url, "csv": text})
                            log.info("MA: downloaded %s (%d chars)", url, len(text))
                        except Exception as exc:
                            log.warning(
                                "MA: failed to download %s → %s: %s",
                                url, type(exc).__name__, exc,
                            )
                finally:
                    browser.close()

            if not files:
                raise ScrapeFailed("MA: could not download any CSV files")
            return json.dumps({"files": files}).encode()

        except ScrapeFailed:
            raise
        except Exception as exc:
            raise ScrapeFailed(f"MA: fetch failed: {exc}") from exc

    def parse(self, raw: bytes) -> list[NoticeRow]:
        try:
            data = json.loads(raw)
        except Exception as exc:
            raise ParseFailed(f"MA: raw bytes are not valid JSON: {exc}") from exc

        files = data.get("files", [])
        if not files:
            raise ParseFailed("MA: JSON payload contains no files")

        rows: list[NoticeRow] = []
        for file in files:
            csv_text = file.get("csv", "")
            url = file.get("url", SOURCE_URL)
            rows.extend(_parse_csv(csv_text, url))

        if not rows:
            raise ParseFailed("MA: no data rows parsed from any CSV file")
        return rows


def _match_columns(norm_header: list[str]) -> dict[str, int | None]:
    """Fuzzy-map WARN fields to column indices, tolerating both the live CSV
    headers (RECEIVED / EMPLOYER / # EMPLOYEES IMPACTED) and the historical XLSX
    variants (Date Received / Company Name / # Affected)."""
    def find(patterns: tuple[tuple[str, ...], ...]) -> int | None:
        for i, h in enumerate(norm_header):
            for pat in patterns:
                if all(s in h for s in pat):
                    return i
        return None

    return {
        "employer": find((("EMPLOYER",), ("COMPANY",))),
        "received": find((("RECEIVED",),)),
        "city": find((("CITY",), ("TOWN",))),
        "region": find((("REGION",),)),
        "layoff_date": find((("DATE", "LAYOFF"),)),
        "count": find((("IMPACTED",), ("EMPLOYEE",), ("AFFECTED",))),
    }


def _clean_employer(value: object) -> str | None:
    """Coerce to a name, stripping "*Updated*"/"*UDATED*" amendment markers
    (and the colon-form "UPDATED:"/"Update:" the FY2020-era reports used)."""
    employer = as_str(value)
    if not employer:
        return None
    if employer.startswith("*"):
        employer = re.sub(r"^\*[^*]+\*\s*", "", employer).strip() or employer
    employer = (
        re.sub(r"^UPDATED?\s*:\s*", "", employer, flags=re.IGNORECASE).strip()
        or employer
    )
    return employer


def _clean_city(value: object) -> str | None:
    """Coerce to a city, dropping a trailing ", MA"/", Massachusetts"."""
    city = as_str(value)
    if not city:
        return None
    return as_str(_STATE_SUFFIX_RE.sub("", city))


def _parse_csv(csv_text: str, url: str) -> list[NoticeRow]:
    reader = csv.reader(io.StringIO(csv_text))
    try:
        header = next(reader)
    except StopIteration:
        return []

    norm_header = [h.strip().upper() for h in header]
    col = _match_columns(norm_header)
    emp_i, rec_i = col["employer"], col["received"]
    if emp_i is None or rec_i is None:
        return []

    rows: list[NoticeRow] = []
    for record in reader:
        if not record or len(record) <= max(emp_i, rec_i):
            continue
        employer = _clean_employer(record[emp_i])
        if not employer:
            continue

        notice_date = as_date(record[rec_i])
        if notice_date is None:
            continue

        city_i = col["city"]
        city = (
            _clean_city(record[city_i])
            if city_i is not None and city_i < len(record)
            else None
        )

        effective_date = None
        layoff_i = col["layoff_date"]
        if layoff_i is not None and layoff_i < len(record):
            m = _DATE_RE.search(record[layoff_i])
            if m:
                effective_date = as_date(m.group(0))

        extra: dict[str, str] = {}
        region_i = col["region"]
        if region_i is not None and region_i < len(record):
            region = as_str(record[region_i])
            if region:
                extra["region"] = region

        count_i = col["count"]
        rows.append(
            NoticeRow(
                state="MA",
                employer=employer,
                notice_date=notice_date,
                effective_date=effective_date,
                layoff_count=(
                    as_int(record[count_i])
                    if count_i is not None and count_i < len(record)
                    else None
                ),
                city=city,
                source_url=url,
                extra=extra,
            )
        )
    return rows


def _discover_links(page, href_substr: str = ".csv", attempts: int = 3) -> list[str]:
    """Return href URLs on the mass.gov WARN page matching ``href_substr``.

    The download anchors are server-rendered into the page, so a clean
    (residential) request finds them on the first load.  From datacenter IPs
    (the cluster) Akamai serves a bot-challenge page on the first navigation;
    its sensor JS then sets the clearance cookie, so a *reload* returns the
    real content.  We therefore reload-and-retry until an anchor appears,
    which is what fixes the recurring "no links found" cluster failure.
    """
    selector = f"a[href*='{href_substr}']"
    for attempt in range(1, attempts + 1):
        page.goto(SOURCE_URL, wait_until="load", timeout=60_000)
        try:
            # Wait for the anchor in the DOM (state="attached": it may live in a
            # collapsed download region and not be "visible").
            page.wait_for_selector(selector, state="attached", timeout=15_000)
        except Exception:
            pass  # fall through to the explicit check + reload below

        hrefs = page.eval_on_selector_all(selector, "els => els.map(e => e.href)")
        urls = list(dict.fromkeys(hrefs))  # deduplicate, keep order
        if urls:
            return urls

        log.warning(
            "MA: no %r link on attempt %d/%d; reloading to clear Akamai challenge",
            href_substr, attempt, attempts,
        )

    return []


def _discover_csv_links(page, attempts: int = 3) -> list[str]:
    """Weekly-CSV download URLs (live scraper); see :func:`_discover_links`."""
    return _discover_links(page, ".csv", attempts)


# ---------------------------------------------------------------------------
# Historical backfill — per-fiscal-year XLSX reports (FY22-FY25)
#
# The "Previous WARN reports" section links one XLSX per fiscal year. Two
# layouts occur: FY22/FY23 are one sheet *per region* (region = sheet name,
# a title row then a header at row 3, columns Date Received / Company Name /
# City / Layoff Date / # Affected); FY24+ are a single sheet whose row-1 header
# matches the live CSV (RECEIVED / EMPLOYER / CITY/TOWN / REGION / DATE(S) OF
# LAYOFFS / # EMPLOYEES IMPACTED). Downloads are Akamai-gated (httpx 403s from
# the cluster), so fetch via Playwright like the live scraper. Used by
# warn_v2.scripts.backfill_historical.
# ---------------------------------------------------------------------------

def _coerce_date(value: object) -> date | None:
    """Date from an openpyxl cell: real datetime, or the first m/d/y in a string
    (handles ranges like "07/07/2021 - (08/30/2021)" and 2-digit years)."""
    if isinstance(value, datetime):
        return as_date(value)
    if isinstance(value, date):
        return as_date(value)
    s = as_str(value)
    if not s:
        return None
    m = _LOOSE_DATE_RE.search(s)
    if not m:
        return as_date(s)
    month, day, year = (int(g) for g in m.groups())
    if year < 100:
        year += 2000
    try:
        return as_date(date(year, month, day))
    except ValueError:
        return None


def _first_int(value: object) -> int | None:
    """Count from a cell: a numeric cell, or the first integer in a string like
    "207 total locations" / "180 (1 resides in MA)"."""
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        try:
            return int(value)
        except (ValueError, OverflowError):
            return None
    s = as_str(value)
    if not s:
        return None
    n = as_int(s)
    if n is not None:
        return n
    m = _INT_RE.search(s)
    return int(m.group(0).replace(",", "")) if m else None


def _build_xlsx_row(
    url: str,
    *,
    employer: object,
    received: object,
    city: object,
    region: object,
    layoff: object,
    count: object,
) -> NoticeRow | None:
    """Build a NoticeRow from raw XLSX cell values, or None when there's no
    employer (blank/spacer rows). notice_date is best-effort — a handful of
    historical rows carry no received date (the column is nullable)."""
    name = _clean_employer(employer)
    if not name:
        return None
    extra: dict[str, str] = {}
    region_str = as_str(region)
    if region_str:
        extra["region"] = region_str
    return NoticeRow(
        state="MA",
        employer=name,
        notice_date=_coerce_date(received),
        effective_date=_coerce_date(layoff),
        layoff_count=_first_int(count),
        city=_clean_city(city),
        source_url=url,
        extra=extra,
    )


def _cell(row: tuple, i: int | None) -> object:
    return row[i] if i is not None and i < len(row) else None


def _row_from_columns(row: tuple, col: dict[str, int | None], url: str) -> NoticeRow | None:
    """FY24+ layout: fields located by the row-1 header (region is a column)."""
    return _build_xlsx_row(
        url,
        employer=_cell(row, col["employer"]),
        received=_cell(row, col["received"]),
        city=_cell(row, col["city"]),
        region=_cell(row, col["region"]),
        layoff=_cell(row, col["layoff_date"]),
        count=_cell(row, col["count"]),
    )


def _row_positional(row: tuple, url: str, region: str | None) -> NoticeRow | None:
    """FY22/FY23 regional layout: fixed columns, region from the sheet name.
    Date Received | Company | City | Layoff Date | # Affected."""
    return _build_xlsx_row(
        url,
        employer=_cell(row, 1),
        received=_cell(row, 0),
        city=_cell(row, 2),
        region=region,
        layoff=_cell(row, 3),
        count=_cell(row, 4),
    )


def _parse_ma_sheet(ws, url: str) -> list[NoticeRow]:
    return _parse_ma_rows(as_str(ws.title), list(ws.iter_rows(values_only=True)), url)


def _parse_ma_rows(title: str | None, data: list[tuple], url: str) -> list[NoticeRow]:
    """Shared sheet-parsing core: ``data`` is the cell grid (dates already
    coerced to datetime), ``title`` the sheet name (= region in the FY22/FY23/
    FY2020 regional layout)."""
    header_idx: int | None = None
    layout: str | None = None
    col: dict[str, int | None] | None = None
    for i, row in enumerate(data[:6]):
        norm = [str(c).strip().upper() if c is not None else "" for c in row]
        has_received = any("RECEIVED" in c for c in norm)
        has_employer = any("EMPLOYER" in c for c in norm)
        has_company = any("COMPANY" in c for c in norm)
        if has_employer and has_received:  # live-CSV-style header, region column
            header_idx, layout, col = i, "columns", _match_columns(norm)
            break
        if has_company:  # regional sheet: positional columns, region = sheet name
            header_idx, layout = i, "positional"
            break
    if header_idx is None:
        return []

    region = title if layout == "positional" else None
    out: list[NoticeRow] = []
    for row in data[header_idx + 1:]:
        built = (
            _row_from_columns(row, col, url)
            if layout == "columns"
            else _row_positional(row, url, region)
        )
        if built is not None:
            out.append(built)
    return out


def parse_ma_xlsx(raw: bytes, year: int) -> list[NoticeRow]:
    """Parse a mass.gov FY WARN XLSX report (all region/year sheets)."""
    return _parse_ma_workbook(raw, _FY_REPORT_URL.format(yy=year % 100))


def _parse_ma_workbook(raw: bytes, url: str) -> list[NoticeRow]:
    import openpyxl

    try:
        wb = openpyxl.load_workbook(io.BytesIO(raw), read_only=True, data_only=True)
    except Exception as e:
        raise ParseFailed(f"MA xlsx: could not open workbook: {e}") from e

    rows: list[NoticeRow] = []
    for ws in wb.worksheets:
        rows.extend(_parse_ma_sheet(ws, url))
    if not rows:
        raise ParseFailed("MA xlsx: no data rows parsed from any sheet")
    return rows


def parse_ma_xls(raw: bytes, url: str) -> list[NoticeRow]:
    """Parse a legacy .xls FY report (the FY2020 Wayback capture) — same
    six-regional-sheet layout as FY22/FY23, read via xlrd. Date cells arrive
    as Excel serials; coerce them to datetime so the shared core sees the
    same values openpyxl would produce."""
    import xlrd

    try:
        wb = xlrd.open_workbook(file_contents=raw)
    except Exception as e:
        raise ParseFailed(f"MA xls: could not open workbook: {e}") from e

    def cell(ws, r: int, c: int) -> object:
        value = ws.cell_value(r, c)
        if ws.cell_type(r, c) == xlrd.XL_CELL_DATE:
            try:
                return xlrd.xldate_as_datetime(value, wb.datemode)
            except Exception:
                return value
        return value

    rows: list[NoticeRow] = []
    for ws in wb.sheets():
        data = [
            tuple(cell(ws, r, c) for c in range(ws.ncols)) for r in range(ws.nrows)
        ]
        rows.extend(_parse_ma_rows(as_str(ws.name), data, url))
    if not rows:
        raise ParseFailed("MA xls: no data rows parsed from any sheet")
    return rows


# ---------------------------------------------------------------------------
# Bundled backfill — FY2020 + early-FY2021 Wayback captures (Mode 3b)
#
# mass.gov's "Previous WARN reports" section starts at FY22; the only archived
# older documents are one Wayback capture of the FY2020 report (legacy .xls,
# Jul 2019 - Jun 2020) and one of the FY2021 weekly cumulative through
# 2020-08-21 (.xlsx, same regional layout). Zero WARN docs were crawled
# between 2020-08-28 and 2021-11-30, so Sep 2020 - Mar 2021 and pre-FY2020
# remain email-request only (see docs/backfill-milestones.md).
# ---------------------------------------------------------------------------

_MA_ARCHIVE_URLS = {
    "warn-report-fy2020.xls": (
        "https://web.archive.org/web/20200828043125/"
        "https://www.mass.gov/doc/warn-report-for-fy-2020/download"
    ),
    "warn-report-week-ending-08-21-20.xlsx": (
        "https://web.archive.org/web/20200828041524/"
        "https://www.mass.gov/doc/warn-report-for-week-ending-08-21-20/download"
    ),
}


def ma_archive_files() -> list[tuple[str, bytes]]:
    """Members of the bundled MA snapshot (warn_v2/scrapers/data/ma_archive.tar.gz)."""
    from warn_v2.scrapers.bundled import DATA_DIR, load_archive

    return load_archive(DATA_DIR / "ma_archive.tar.gz")


def parse_ma_archive_member(name: str) -> Callable[[bytes], list[NoticeRow]]:
    """Parser for one bundled member: xlrd for the legacy .xls, openpyxl
    otherwise. Rows carry the Wayback replay URL as source_url."""
    url = _MA_ARCHIVE_URLS.get(name, SOURCE_URL)
    if name.lower().endswith(".xls"):
        return lambda raw: parse_ma_xls(raw, url)
    return lambda raw: _parse_ma_workbook(raw, url)


def _download_file(page, url: str) -> bytes | None:
    """Navigate to a mass.gov download URL and return the file bytes.

    The server replies with ``Content-Disposition: attachment``, so
    ``page.goto`` raises "Download is starting"; the file is captured by
    ``expect_download`` regardless (same pattern as the live CSV fetch)."""
    from pathlib import Path

    with page.expect_download(timeout=60_000) as dl_info:
        try:
            page.goto(url, wait_until="commit", timeout=60_000)
        except Exception:
            pass
    dl_path = dl_info.value.path()
    return Path(dl_path).read_bytes() if dl_path else None


def _fetch_ma_fy(year: int) -> bytes | None:
    """Download the FY<year> WARN XLSX report via Playwright, or None if the
    page has no report for that fiscal year (year-loop skips it)."""
    yy = year % 100
    try:
        from playwright.sync_api import sync_playwright

        from warn_v2.scrapers.playwright_base import _LAUNCH_ARGS

        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True, args=_LAUNCH_ARGS)
            try:
                ctx = browser.new_context(user_agent=_CHROME_UA, accept_downloads=True)
                page = ctx.new_page()
                fy_urls: dict[int, str] = {}
                for href in _discover_links(page, "/doc/"):
                    m = _FY_DOC_RE.search(href)
                    if m:
                        fy_urls.setdefault(int(m.group(1)), href)
                url = fy_urls.get(yy)
                if url is None:
                    log.info("MA: no FY%02d report link on the WARN page", yy)
                    return None
                log.info("MA: downloading FY%02d report %s", yy, url)
                return _download_file(page, url)
            finally:
                browser.close()
    except Exception as exc:
        raise ScrapeFailed(f"MA: FY{yy:02d} fetch failed: {exc}") from exc


register(MAScraper())
