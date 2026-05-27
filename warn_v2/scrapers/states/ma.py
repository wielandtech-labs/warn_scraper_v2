"""Massachusetts WARN scraper.

Source: https://www.mass.gov/info-details/warn-layoff-and-closure-updates
Administered by the Massachusetts Executive Office of Labor and Workforce Development.

Mass.gov returns 403 to non-browser requests on the index page, so Playwright is used
to discover the current CSV link. The CSV itself is publicly downloadable with httpx.
Each weekly CSV released on Friday contains ALL notices for the current fiscal year
(July - June), so one download covers the full current-year dataset.

Schema (confirmed from live site, May 2026):
  RECEIVED | EMPLOYER | CITY/TOWN | REGION | DATE(S) OF LAYOFFS | # EMPLOYEES IMPACTED
"""
from __future__ import annotations

import csv
import io
import json
import re

from warn_v2.scrapers._helpers import as_date, as_int, as_str
from warn_v2.scrapers.base import NoticeRow, ParseFailed, ScrapeFailed
from warn_v2.scrapers.playwright_base import PlaywrightScraper
from warn_v2.scrapers.registry import register

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
        """Load the mass.gov page via Playwright, find and download CSV files.

        mass.gov returns 403 to plain httpx on the CSV download endpoints, so
        both the index page visit *and* the CSV downloads happen inside the same
        Playwright browser context — this way session cookies are shared and the
        CDN/WAF sees a consistent browser fingerprint throughout.
        """
        try:
            from playwright.sync_api import sync_playwright

            from warn_v2.scrapers.playwright_base import _LAUNCH_ARGS

            files: list[dict[str, str]] = []
            with sync_playwright() as pw:
                browser = pw.chromium.launch(headless=True, args=_LAUNCH_ARGS)
                try:
                    ctx = browser.new_context(user_agent=_CHROME_UA)
                    page = ctx.new_page()

                    # Step 1: discover CSV URLs from the index page
                    page.goto(SOURCE_URL, wait_until="load", timeout=60_000)
                    hrefs = page.eval_on_selector_all(
                        "a[href*='.csv']", "els => els.map(e => e.href)"
                    )
                    csv_urls: list[str] = list(dict.fromkeys(hrefs))

                    if not csv_urls:
                        raise ScrapeFailed("MA: no CSV links found on mass.gov WARN page")

                    # Step 2: download each CSV via the browser context's request API
                    # so that session cookies and headers are inherited from Step 1.
                    for url in csv_urls:
                        try:
                            resp = ctx.request.get(
                                url,
                                headers={"User-Agent": _CHROME_UA},
                                timeout=60_000,
                            )
                            if resp.ok:
                                text = resp.body().decode("utf-8-sig")
                                files.append({"url": url, "csv": text})
                        except Exception:
                            continue
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
