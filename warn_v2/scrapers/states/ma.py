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
# Strip trailing state label from CITY/TOWN values like "Boston, MA"
_STATE_SUFFIX_RE = re.compile(r",\s*(MA|Massachusetts)\s*$", re.IGNORECASE)


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

                    # Step 1: load index page to establish Akamai session.
                    page.goto(SOURCE_URL, wait_until="load", timeout=60_000)
                    hrefs = page.eval_on_selector_all(
                        "a[href*='.csv']", "els => els.map(e => e.href)"
                    )
                    csv_urls = list(dict.fromkeys(hrefs))  # deduplicate, keep order

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


def _parse_csv(csv_text: str, url: str) -> list[NoticeRow]:
    reader = csv.reader(io.StringIO(csv_text))
    try:
        header = next(reader)
    except StopIteration:
        return []

    # Normalize headers
    norm_header = [h.strip().upper() for h in header]
    col: dict[str, int] = {h: i for i, h in enumerate(norm_header)}

    employer_col = next((c for c in col if "EMPLOYER" in c), None)
    date_col = next((c for c in col if "RECEIVED" in c), None)
    if employer_col is None or date_col is None:
        return []

    city_col = next((c for c in col if "CITY" in c or "TOWN" in c), None)
    region_col = next((c for c in col if "REGION" in c), None)
    layoff_date_col = next((c for c in col if "DATE" in c and "LAYOFF" in c), None)
    count_col = next((c for c in col if "IMPACTED" in c or "EMPLOYEE" in c), None)

    rows: list[NoticeRow] = []
    for record in reader:
        if not record or len(record) <= max(col[employer_col], col[date_col]):
            continue
        employer = as_str(record[col[employer_col]])
        if not employer:
            continue
        # Strip "Updated*" prefix markers like "*Updated* Company Name"
        if employer.startswith("*"):
            employer = re.sub(r"^\*[^*]+\*\s*", "", employer).strip() or employer

        notice_date = as_date(record[col[date_col]])
        if notice_date is None:
            continue

        city_raw = (
            record[col[city_col]].strip()
            if city_col is not None and col[city_col] < len(record)
            else None
        )
        city = as_str(_STATE_SUFFIX_RE.sub("", city_raw)) if city_raw else None

        effective_date = None
        if layoff_date_col is not None and col[layoff_date_col] < len(record):
            m = _DATE_RE.search(record[col[layoff_date_col]])
            if m:
                effective_date = as_date(m.group(0))

        extra: dict[str, str] = {}
        if region_col is not None and col[region_col] < len(record):
            region = as_str(record[col[region_col]])
            if region:
                extra["region"] = region

        rows.append(
            NoticeRow(
                state="MA",
                employer=employer,
                notice_date=notice_date,
                effective_date=effective_date,
                layoff_count=(
                    as_int(record[col[count_col]])
                    if count_col is not None and col[count_col] < len(record)
                    else None
                ),
                city=city,
                source_url=url,
                extra=extra,
            )
        )
    return rows


register(MAScraper())
