"""Michigan WARN scraper.

Source: Michigan LEO (Labor and Economic Opportunity) Sitecore search API.
URL: https://www.michigan.gov/leo/bureaus-agencies/wd/data-public-notices/warn-notices

The public search page uses a Sitecore SXA search component. Calling the search
API endpoint directly with httpx (p=200) returns all WARN records in a single JSON
response — no Playwright needed.

API response: {"Count": 101, "Results": [{"Id": ..., "Html": "<div>...</div>"}, ...]}

Each HTML fragment contains:
  <a class="content-title-link">Company Name</a>
  <p>
    <strong>Type of company action:</strong> Layoff<br/>
    <strong>City:</strong> Novi, Michigan<br/>
    <strong>County:</strong> Oakland<br/>
    <strong>Layoff date:</strong> January 6, 2026<br/>
    <strong>Number of jobs impacted:</strong> 29
  </p>
"""
from __future__ import annotations

import json
import re
from datetime import date

import httpx
from bs4 import BeautifulSoup, NavigableString

from warn_v2.scrapers._helpers import as_date, as_int, as_str
from warn_v2.scrapers.base import NoticeRow, ParseFailed, ScrapeFailed
from warn_v2.scrapers.registry import register

_API_URL = "https://www.michigan.gov/leo/sxa/search/results/"
_API_PARAMS = {
    "v": "{1FFFCC21-5151-4A2B-ABFC-F7FE4E5C9783}",
    "s": "{8E97AB1D-D2D4-47F8-8CC4-3F1039C8854F}",
    "p": 300,  # request more than current total to get everything in one call
    "autoFireSearch": "true",
    "itemid": "{BE81F7C2-36A8-4FDE-853C-B05B6E090055}",
}

_UA = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    )
}

SOURCE_URL = "https://www.michigan.gov/leo/bureaus-agencies/wd/data-public-notices/warn-notices"

# Strip state suffix from city values: "Novi, Michigan" → "Novi"
_STATE_SUFFIX_RE = re.compile(r",\s*(Michigan|MI)\s*$", re.IGNORECASE)

# Extract first M/D/YY or M/D/YYYY from prose date strings like "Beginning April 21, 2025"
_DATE_SLASH_RE = re.compile(r"\d{1,2}/\d{1,2}/\d{2,4}")


def _extract_date(raw: str) -> date | None:
    """Parse a date from raw strings that may contain prose prefixes or ranges.

    Handles:
      - "Beginning April 21, 2025" → strip first word → pandas parses "April 21, 2025"
      - "5/9/26-6/19/26"           → extract first slashed date "5/9/26"
      - "12/5/25, 1/16/26, ..."    → extract first slashed date "12/5/25"
      - "Commencing June 2025"     → strip first word → pandas parses "June 2025" as June 1
    """
    if not raw:
        return None
    d = as_date(raw)
    if d is not None:
        return d
    # Extract first M/D/YY or M/D/YYYY pattern (handles ranges and comma-lists)
    m = _DATE_SLASH_RE.search(raw)
    if m:
        return as_date(m.group(0))
    # Strip leading prose word (e.g. "Beginning"/"Commencing") and retry
    parts = raw.strip().split(None, 1)
    if len(parts) == 2:
        return as_date(parts[1])
    return None


class MIScraper:
    state = "MI"
    source_url = SOURCE_URL
    expected_row_range = (5, 500)
    required_fields = frozenset({"employer", "notice_date"})

    def fetch(self) -> bytes:
        try:
            r = httpx.get(
                _API_URL, params=_API_PARAMS, headers=_UA, timeout=60, follow_redirects=True
            )
            r.raise_for_status()
            return r.content
        except httpx.HTTPError as exc:
            raise ScrapeFailed(f"MI: Sitecore API error: {exc}") from exc

    def parse(self, raw: bytes) -> list[NoticeRow]:
        try:
            data = json.loads(raw)
        except Exception as exc:
            raise ParseFailed(f"MI: response is not valid JSON: {exc}") from exc

        results = data.get("Results", [])
        if not results:
            raise ParseFailed("MI: Sitecore API returned no results")

        rows: list[NoticeRow] = []
        for item in results:
            html_fragment = item.get("Html", "")
            if not html_fragment:
                continue
            row = _parse_card(html_fragment)
            if row is not None:
                rows.append(row)

        if not rows:
            raise ParseFailed("MI: no valid rows parsed from API results")
        return rows


def _parse_card(html: str) -> NoticeRow | None:
    """Parse one Sitecore HTML card fragment into a NoticeRow."""
    soup = BeautifulSoup(html, "html.parser")

    # Company name: prefer <a class="content-title-link">, fall back to <h3>
    name_el = soup.find("a", class_="content-title-link") or soup.find("h3")
    employer = as_str(name_el.get_text(strip=True)) if name_el else None
    if not employer:
        return None

    # Extract labeled fields from <p><strong>Label:</strong> Value<br/>...</p>
    # or from <li><strong>Label:</strong> Value</li>
    labels: dict[str, str] = {}
    for strong in soup.find_all("strong"):
        label_text = strong.get_text(strip=True).rstrip(":").strip()
        # Value follows the strong element as a text node (sibling after br or in same p)
        sibling = strong.next_sibling
        if sibling is None:
            continue
        if isinstance(sibling, NavigableString):
            value = str(sibling).strip().lstrip("\xa0").strip()
        else:
            value = sibling.get_text(strip=True).lstrip("\xa0").strip()
        if label_text and value:
            labels[label_text.lower()] = value

    # Also try <li> format for older cards (site address, county, etc.)
    for li in soup.find_all("li"):
        strong = li.find("strong")
        if not strong:
            continue
        label_text = strong.get_text(strip=True).rstrip(":").strip().lower()
        value = li.get_text(strip=True).replace(strong.get_text(strip=True), "").strip()
        if label_text and value:
            labels.setdefault(label_text, value)

    # Map fields — date key varies across card vintages; values may include prose
    date_raw = (
        labels.get("layoff date")
        or labels.get("layoff dates")
        or labels.get("commencing date")
        or labels.get("closure date")
        or ""
    )
    notice_date = _extract_date(date_raw)
    if notice_date is None:
        return None  # skip cards without a parseable date

    city_raw = labels.get("city", "")
    city = as_str(_STATE_SUFFIX_RE.sub("", city_raw)) if city_raw else None

    county = as_str(labels.get("county", "").replace("\xa0", "").strip())
    closure_type = as_str(labels.get("type of company action", ""))

    # "Number of jobs impacted" is the layoff count field
    count_raw = labels.get("number of jobs impacted", labels.get("number of workers", ""))
    layoff_count = as_int(count_raw)

    # MI's API only publishes the layoff occurrence date ("Layoff date:" label).
    # We store it as both notice_date (for the content-hash dedup key) and
    # effective_date (the semantically correct field).  A separate filing date
    # is not available from this source.
    return NoticeRow(
        state="MI",
        employer=employer,
        notice_date=notice_date,
        effective_date=notice_date,
        layoff_count=layoff_count,
        closure_type=closure_type,
        city=city,
        county=county,
        source_url=SOURCE_URL,
    )


register(MIScraper())
