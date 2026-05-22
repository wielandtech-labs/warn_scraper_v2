"""Oregon WARN scraper.

Source: https://ccwd.hecc.oregon.gov/Layoff/WARN
Data:   Per-county paginated HTML tables served by the Oregon Rapid Response
        Activity Tracking System (HECC/OWI). The system retains records for
        six years.

There is no single-query "all notices" endpoint; results must be fetched
county-by-county with pagination (?County=Name&page=N).  fetch() iterates
all 36 Oregon counties and returns a JSON blob:
  {"rows": [{"track":..., "date":..., "type":..., "count":...,
             "employer":..., "city":..., "county":..., "notice_url":...}]}

parse() reads that blob and maps it to NoticeRow.

Notification Date format: "M/D/YYYY h:mm:ss AM"  (time component always midnight).
"""
from __future__ import annotations

import json
import re
from datetime import datetime

import httpx
from bs4 import BeautifulSoup

from warn_v2.scrapers._helpers import as_int, as_str
from warn_v2.scrapers.base import NoticeRow, ParseFailed, ScrapeFailed
from warn_v2.scrapers.registry import register

_SOURCE_URL = "https://ccwd.hecc.oregon.gov/Layoff/WARN"
_BASE_URL = "https://ccwd.hecc.oregon.gov"

_UA = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
    )
}

# All 36 Oregon counties
_OR_COUNTIES = [
    "Baker", "Benton", "Clackamas", "Clatsop", "Columbia", "Coos", "Crook",
    "Curry", "Deschutes", "Douglas", "Gilliam", "Grant", "Harney",
    "Hood River", "Jackson", "Jefferson", "Josephine", "Klamath", "Lake",
    "Lane", "Lincoln", "Linn", "Malheur", "Marion", "Morrow", "Multnomah",
    "Polk", "Sherman", "Tillamook", "Umatilla", "Union", "Wallowa", "Wasco",
    "Washington", "Wheeler", "Yamhill",
]

_DATE_RE = re.compile(r"(\d{1,2}/\d{1,2}/\d{4})")


def _parse_date(raw: str) -> object:
    """Parse 'M/D/YYYY h:mm:ss AM' or 'M/D/YYYY' to a date."""
    m = _DATE_RE.search(raw or "")
    if not m:
        return None
    try:
        return datetime.strptime(m.group(1), "%m/%d/%Y").date()
    except ValueError:
        return None


def _scrape_county(county: str, client: httpx.Client) -> list[dict]:
    """Fetch all pages for one county and return a list of row dicts."""
    rows: list[dict] = []
    seen: set[str] = set()
    page = 1
    county_param = county.replace(" ", "+")

    while True:
        url = f"{_SOURCE_URL}?County={county_param}&page={page}"
        try:
            r = client.get(url, timeout=20)
            r.raise_for_status()
        except httpx.HTTPError as e:
            raise ScrapeFailed(f"OR: GET {url}: {e}") from e

        soup = BeautifulSoup(r.content, "lxml")
        found_data = False

        for table in soup.find_all("table"):
            trows = table.find_all("tr")
            if len(trows) < 2:
                continue
            hdr = [td.get_text(strip=True) for td in trows[0].find_all(["th", "td"])]
            if "Track #" not in hdr:
                continue

            for tr in trows[1:]:
                tds = tr.find_all("td")
                if len(tds) < 6:
                    continue
                track = tds[0].get_text(strip=True)
                if not track.isdigit() or track in seen:
                    continue
                seen.add(track)
                link_tag = tds[6].find("a") if len(tds) > 6 else None
                notice_url = (
                    _BASE_URL + link_tag["href"]
                    if link_tag and link_tag.get("href")
                    else ""
                )
                rows.append(
                    {
                        "track": track,
                        "date": tds[1].get_text(strip=True),
                        "type": tds[2].get_text(strip=True),
                        "count": tds[3].get_text(strip=True),
                        "employer": tds[4].get_text(strip=True),
                        "city": tds[5].get_text(strip=True),
                        "county": county,
                        "notice_url": notice_url,
                    }
                )
                found_data = True

        has_next = any(
            f"page={page + 1}" in (a.get("href", ""))
            for a in soup.find_all("a", href=True)
        )
        if not found_data or not has_next:
            break
        page += 1

    return rows


class ORScraper:
    state = "OR"
    source_url = _SOURCE_URL
    expected_row_range = (5, 5_000)
    required_fields = frozenset({"employer", "notice_date"})

    def fetch(self) -> bytes:
        all_rows: list[dict] = []
        seen_tracks: set[str] = set()

        with httpx.Client(headers=_UA, follow_redirects=True) as client:
            for county in _OR_COUNTIES:
                county_rows = _scrape_county(county, client)
                for row in county_rows:
                    if row["track"] not in seen_tracks:
                        seen_tracks.add(row["track"])
                        all_rows.append(row)

        if not all_rows:
            raise ScrapeFailed("OR: no WARN notices found across all counties")
        return json.dumps({"rows": all_rows}).encode()

    def parse(self, raw: bytes) -> list[NoticeRow]:
        try:
            data = json.loads(raw)
        except Exception as e:
            raise ParseFailed(f"OR: JSON decode error: {e}") from e

        raw_rows = data.get("rows", [])
        if not raw_rows:
            raise ParseFailed("OR: no rows in JSON payload")

        rows: list[NoticeRow] = []
        for r in raw_rows:
            employer = as_str(r.get("employer", ""))
            if not employer:
                continue

            notice_date = _parse_date(r.get("date", ""))
            if notice_date is None:
                continue

            count_raw = r.get("count", "")
            layoff_count = as_int(count_raw) if str(count_raw).isdigit() else None

            notice_url = r.get("notice_url") or None

            rows.append(
                NoticeRow(
                    state="OR",
                    employer=employer,
                    notice_date=notice_date,
                    layoff_count=layoff_count,
                    city=as_str(r.get("city", "")) or None,
                    county=as_str(r.get("county", "")) or None,
                    closure_type=as_str(r.get("type", "")) or None,
                    raw_notice_url=notice_url,
                    source_url=_SOURCE_URL,
                    extra={"track_number": r.get("track", "")},
                )
            )
        return rows


register(ORScraper())
