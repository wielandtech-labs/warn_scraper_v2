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

Historical backfill (``warn-v2 backfill-historical --state OR``) ingests two
complementary sources (see the "Historical backfill" section below):

* **Socrata** — the official dataset ``data.oregon.gov/resource/ijbz-jpx8``
  (2020-03+, ~2-month publish lag). One row per worksite *and* layoff phase;
  ``parse_or_socrata`` re-groups them per (warn #, company, city) so
  same-site phases don't collide on ``notice_id``. ``company_name`` here is
  often a *facility* label ("Walker Rd - Hillsboro") where the HECC list view
  (and therefore the live scraper / existing prod rows) shows the legal
  employer — expect near-miss duplicates against live-scraped rows at
  dry-run time and plan a ``mark-superseded`` review pass.
* **Bundled capture union** — ``warn_v2/scrapers/data/or_archive.tar.gz``
  holds ``or_hecc_union.csv``, a frozen union of 2024-2026 Wayback captures
  of this very list app taken while it still held full history (the live app
  purged everything pre-2020 around Nov 2025). Regeneration procedure: for
  every cached capture of ``/Layoff/WARN?page=N&SortOrder=X`` (pages 1-22 x
  13 sort variants x several crawl epochs; local cache
  ``backfill-cache-2026-07/or/``), extract rows with
  ``parse_hecc_list_page``, union them by track number preferring (a) a
  variant with a non-empty date over a dateless one, then (b) the newest
  capture; drop rows whose date cell is empty (the ~390 oldest, 1990s-era —
  their dates exist only in per-notice scan PDFs); drop tracks present in
  the Socrata dataset (so the two backfill members never overlap); write the
  survivors to CSV sorted by track. A single 2025-05/06 crawl epoch already
  recovers 1,045 of the ~1,050 rows the app reported, so the union is
  effectively the complete dated history (1989-2020-03 plus a few dozen
  rows Socrata is missing, mostly Jan-Mar 2020).
"""
from __future__ import annotations

import csv
import io
import json
import re
from datetime import date, datetime
from pathlib import Path

import httpx
from bs4 import BeautifulSoup

from warn_v2.scrapers._helpers import as_int, as_str
from warn_v2.scrapers.base import NoticeRow, ParseFailed, ScrapeFailed
from warn_v2.scrapers.bundled import load_archive
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


# ---------------------------------------------------------------------------
# Historical backfill: Socrata dataset + bundled Wayback capture union
# ---------------------------------------------------------------------------
# See the module docstring for source semantics and the union regeneration
# procedure.

_SOCRATA_URL = "https://data.oregon.gov/resource/ijbz-jpx8.json"
_SOCRATA_PAGE_SIZE = 1000
# Member name used for the live-fetched Socrata payload in Mode-3b dispatch.
SOCRATA_MEMBER = "socrata_ijbz-jpx8.json"
_ARCHIVE_TGZ = Path(__file__).resolve().parent.parent / "data" / "or_archive.tar.gz"


def parse_hecc_list_page(html: bytes | str) -> list[dict]:
    """Extract raw row dicts from one HECC WARN list-view page.

    The list view (no County filter) shows the same 7-column table the live
    scraper reads per-county, minus the county context: Track # /
    Notification Date / Layoff Type / Count / Employer / City / NoticeLink.
    Dateless rows (empty Notification Date cell) are returned as-is — the
    union build step decides what to drop. Used by the or_archive.tar.gz
    regeneration tooling and its tests, not by the live scraper.
    """
    soup = BeautifulSoup(html, "lxml")
    out: list[dict] = []
    for table in soup.find_all("table"):
        trs = table.find_all("tr")
        if len(trs) < 2:
            continue
        hdr = [c.get_text(strip=True) for c in trs[0].find_all(["th", "td"])]
        if "Track #" not in hdr:
            continue
        for tr in trs[1:]:
            tds = tr.find_all("td")
            if len(tds) < 6:
                continue
            track = tds[0].get_text(strip=True)
            if not track.isdigit():
                continue
            link = tds[6].find("a") if len(tds) > 6 else None
            out.append(
                {
                    "track": track,
                    "date": tds[1].get_text(strip=True),
                    "type": tds[2].get_text(strip=True),
                    "count": tds[3].get_text(strip=True),
                    "employer": tds[4].get_text(strip=True),
                    "city": tds[5].get_text(strip=True),
                    "notice_path": link["href"] if link and link.get("href") else "",
                }
            )
    return out


def _fetch_or_socrata() -> bytes:
    """Fetch the full Socrata dataset, paginated, as one JSON list."""
    rows: list[dict] = []
    offset = 0
    while True:
        params = {
            "$limit": _SOCRATA_PAGE_SIZE,
            "$offset": offset,
            "$order": ":id",
        }
        try:
            r = httpx.get(
                _SOCRATA_URL, params=params, headers=_UA,
                timeout=60, follow_redirects=True,
            )
            r.raise_for_status()
        except httpx.HTTPError as e:
            raise ScrapeFailed(f"OR: GET {_SOCRATA_URL} offset={offset}: {e}") from e
        page = r.json()
        rows.extend(page)
        if len(page) < _SOCRATA_PAGE_SIZE:
            break
        offset += _SOCRATA_PAGE_SIZE
    return json.dumps(rows).encode()


def _iso_date(raw: object) -> date | None:
    """Parse Socrata's '2026-05-13T00:00:00.000' floating timestamps."""
    s = as_str(raw) or ""
    if len(s) < 10:
        return None
    try:
        return date.fromisoformat(s[:10])
    except ValueError:
        return None


def parse_or_socrata(raw: bytes) -> list[NoticeRow]:
    """Parse the Socrata dataset into one NoticeRow per (warn #, company, city).

    The dataset publishes one row per worksite *and* per layoff phase of the
    same notice (e.g. one warn # can carry 19 Kroger store rows, or 6 phased
    reductions at a single Sulzer site). Same-site phases share (employer,
    received_date, city) and would collide on ``notice_id``, so each group is
    collapsed: layoff counts are summed and ``effective_date`` is the earliest
    phase's layoff_date (when job losses begin); ``closure_type`` comes from
    the largest phase. Distinct worksites keep their own rows.
    """
    try:
        data = json.loads(raw)
    except Exception as e:
        raise ParseFailed(f"OR socrata: JSON decode error: {e}") from e
    if not isinstance(data, list) or not data:
        raise ParseFailed("OR socrata: no rows in payload")

    groups: dict[tuple[str, str, str], list[dict]] = {}
    for r in data:
        if not isinstance(r, dict):
            continue
        key = (
            as_str(r.get("warn")) or "",
            as_str(r.get("company_name")) or "",
            as_str(r.get("city")) or "",
        )
        groups.setdefault(key, []).append(r)

    rows: list[NoticeRow] = []
    for (warn, employer, city), grp in groups.items():
        if not employer:
            continue
        notice_date = _iso_date(grp[0].get("received_date"))
        if notice_date is None:
            continue
        counts = [
            int(g["laid_off"]) for g in grp if str(g.get("laid_off", "")).isdigit()
        ]
        effective = min(
            (d for d in (_iso_date(g.get("layoff_date")) for g in grp) if d),
            default=None,
        )
        largest = max(
            grp,
            key=lambda g: int(g["laid_off"]) if str(g.get("laid_off", "")).isdigit() else -1,
        )
        rows.append(
            NoticeRow(
                state="OR",
                employer=employer,
                notice_date=notice_date,
                effective_date=effective,
                layoff_count=sum(counts) if counts else None,
                city=city or None,
                closure_type=as_str(largest.get("layoff_type")),
                source_url=_SOCRATA_URL,
                extra={"track_number": warn},
            )
        )
    return rows


def parse_or_archive_csv(raw: bytes) -> list[NoticeRow]:
    """Parse the bundled or_hecc_union.csv (normalized capture-union snapshot).

    Columns: track, notice_date (ISO), employer, city, layoff_type,
    layoff_count, notice_url. Rows are HECC list-view *master* rows — legal
    employer name, HQ city (sometimes out-of-state, as the live scraper also
    stores), total count, no county / effective date.
    """
    try:
        reader = csv.DictReader(io.StringIO(raw.decode("utf-8")))
        parsed = list(reader)
    except Exception as e:
        raise ParseFailed(f"OR archive: CSV decode error: {e}") from e
    if not parsed:
        raise ParseFailed("OR archive: no rows in CSV")

    rows: list[NoticeRow] = []
    for r in parsed:
        employer = as_str(r.get("employer"))
        if not employer:
            continue
        try:
            notice_date = date.fromisoformat(r.get("notice_date") or "")
        except ValueError:
            continue
        count = as_str(r.get("layoff_count")) or ""
        rows.append(
            NoticeRow(
                state="OR",
                employer=employer,
                notice_date=notice_date,
                layoff_count=as_int(count) if count.isdigit() else None,
                city=as_str(r.get("city")),
                closure_type=as_str(r.get("layoff_type")),
                raw_notice_url=as_str(r.get("notice_url")),
                source_url=_SOURCE_URL,
                extra={"track_number": as_str(r.get("track")) or ""},
            )
        )
    return rows


def or_backfill_files() -> list[tuple[str, bytes]]:
    """Backfill Mode-3b members: the bundled union CSV + a live Socrata fetch.

    Socrata is fetched first so a transient outage fails the run before
    anything ingests — just rerun. The union member sorts first for
    deterministic ingest order.
    """
    socrata = _fetch_or_socrata()
    files = load_archive(_ARCHIVE_TGZ)
    files.append((SOCRATA_MEMBER, socrata))
    return files


register(ORScraper())
