"""Pennsylvania WARN scraper.

Source: https://www.pa.gov/agencies/dli/programs-services/workforce-development-home
        /warn-requirements/warn-notices

Data: CMS accordion page (Adobe Experience Manager).  Each accordion item is one
      employer filing covering Jan 2023 to present.  Multi-site filings repeat the
      address+label block within the same panel.

HTML structure:
  <h2>2026</h2>   <- year section, not used directly
  <h3 class="cmp-accordion__header">
    <button class="cmp-accordion__button">
      <span class="cmp-accordion__title">Employer Name</span>
    </button>
  </h3>
  <div class="cmp-accordion__panel">
    <div class="text">
      <div data-cmp-data-layer="{...,repo:modifyDate:2026-05-21T17:43:28Z,...}">
        <p>Street Address, City, PA  ZIP</p>
        <p>COUNTY: Name<br>
           # AFFECTED: N<br>
           EFFECTIVE DATE: M/D/YYYY<br>
           CLOSURE OR LAYOFF: Closure</p>
      </div>
    </div>
  </div>

notice_date is taken from the CMS repo:modifyDate field (the date the entry was
published / last updated -- the closest proxy for the WARN filing date available
on this page).
effective_date is parsed from the EFFECTIVE DATE: label; ranges like
"beginning M/D/YYYY; ending M/D/YYYY" use the start date.
"""
from __future__ import annotations

import functools
import json
import re
from datetime import date, datetime
from html import unescape

import httpx
from bs4 import BeautifulSoup

from warn_v2.scrapers._helpers import as_int, as_str, zip_from
from warn_v2.scrapers.base import NoticeRow, ParseFailed, ScrapeFailed
from warn_v2.scrapers.registry import register

_SOURCE_URL = (
    "https://www.pa.gov/agencies/dli/programs-services/workforce-development-home"
    "/warn-requirements/warn-notices"
)
_UA = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
    )
}

# "beginning M/D/YYYY; ending M/D/YYYY" -- capture the start date
_DATE_RANGE_RE = re.compile(r"beginning\s+(\d{1,2}/\d{1,2}/\d{2,4})", re.I)
_DATE_RE = re.compile(r"(\d{1,2}/\d{1,2}/\d{2,4})")
# "City, PA ZIP" -- last comma-segment before "PA \d"
_CITY_ZIP_RE = re.compile(r"^(.+),\s*PA\s+\d", re.I)
# Invisible Unicode characters injected by the CMS editor
_INVISIBLE_RE = re.compile(r"[​‌‍﻿]")

_LABEL_PREFIXES = ("COUNTY:", "# AFFECTED:", "EFFECTIVE DATE:", "CLOSURE OR LAYOFF:")

# "# AFFECTED" free-text values. A leading count is trusted when followed only
# by end-of-string, a parenthetical, or a PA-workers qualifier ("5 (within PA)",
# "9 Pennsylvania workers (209 total)") — but NOT by nationwide/total wording
# ("430 nationwide; unknown number of PA residents", "81 Total - 13 of which
# reside in PA"), where the leading number is not the PA count.
_AFFECTED_LEAD_RE = re.compile(r"^(\d[\d,]*)\s*(?=$|\(|pennsylvania\b|pa\b)", re.I)
# Per-location segments: "501 @ Etters location; 595 @ Philadelphia location"
_AFFECTED_AT_RE = re.compile(r"(\d[\d,]*)\s*@")


def _parse_affected(raw: str | None) -> int | None:
    """Parse the '# AFFECTED' value; None for unknown/TBD/ambiguous text."""
    if raw is None:
        return None
    n = as_int(raw)
    if n is not None:
        return n
    s = raw.strip()
    ats = _AFFECTED_AT_RE.findall(s)
    if len(ats) >= 2:
        return sum(int(a.replace(",", "")) for a in ats)
    m = _AFFECTED_LEAD_RE.match(s)
    if m:
        return int(m.group(1).replace(",", ""))
    return None


def _is_label(s: str) -> bool:
    return any(s.upper().startswith(p) for p in _LABEL_PREFIXES)


def _parse_effective_date(raw: str) -> date | None:
    """Parse EFFECTIVE DATE field; handles plain dates and beginning/ending ranges."""
    m = _DATE_RANGE_RE.search(raw)
    if not m:
        m = _DATE_RE.search(raw)
    if not m:
        return None
    parts = m.group(1).split("/")
    if len(parts) != 3:
        return None
    try:
        month, day, yr = int(parts[0]), int(parts[1]), int(parts[2])
        if yr < 100:
            yr += 2000
        return date(yr, month, day)
    except ValueError:
        return None


def _parse_modify_date(attr: str) -> date | None:
    """Extract date from the data-cmp-data-layer JSON attribute."""
    try:
        data = json.loads(unescape(attr))
        for obj in data.values():
            md = obj.get("repo:modifyDate")
            if md:
                return datetime.fromisoformat(md.replace("Z", "+00:00")).date()
    except Exception:
        pass
    return None


def _extract_city(address_lines: list[str]) -> str | None:
    """Parse city from the last address line that matches 'City, PA ZIP'."""
    for line in reversed(address_lines):
        m = _CITY_ZIP_RE.match(line.strip())
        if m:
            parts = m.group(1).split(",")
            return parts[-1].strip() or None
    return None


def _parse_panel(
    panel_div: BeautifulSoup, employer: str
) -> list[NoticeRow]:
    """Parse one accordion panel into one NoticeRow per location."""
    text_div = panel_div.select_one("div.text")
    if not text_div:
        return []

    # notice_date from CMS publish date
    dl_div = text_div.select_one("[data-cmp-data-layer]")
    notice_date = _parse_modify_date(dl_div.get("data-cmp-data-layer", "")) if dl_div else None

    # Collect text segments, one per line (p tags + br separators)
    segments: list[str] = []
    for p in text_div.find_all("p"):
        for line in p.get_text(separator="\n", strip=True).split("\n"):
            line = _INVISIBLE_RE.sub("", line).replace("\xa0", " ").strip()
            if line:
                segments.append(line)

    # Group into location blocks: each block = [address lines...] + {label: value}
    locations: list[tuple[list[str], dict[str, str]]] = []
    addr_lines: list[str] = []
    labels: dict[str, str] = {}

    def _flush() -> None:
        if labels:
            locations.append((list(addr_lines), dict(labels)))

    for seg in segments:
        if _is_label(seg):
            key, _, val = seg.partition(":")
            labels[key.strip().upper()] = val.strip()
        else:
            if labels:
                # non-label after labels -> start a new location block
                _flush()
                addr_lines = [seg]
                labels = {}
            else:
                addr_lines.append(seg)

    _flush()

    rows: list[NoticeRow] = []
    for addr, lbl in locations:
        if notice_date is None:
            continue
        # Join multi-line address lines into a single mailing address string.
        address = as_str(", ".join(addr)) if addr else None
        rows.append(
            NoticeRow(
                state="PA",
                employer=employer,
                notice_date=notice_date,
                effective_date=_parse_effective_date(lbl.get("EFFECTIVE DATE", "")),
                layoff_count=_parse_affected(lbl.get("# AFFECTED")),
                city=_extract_city(addr),
                county=as_str(lbl.get("COUNTY")) or None,
                zip=zip_from(None, address),
                address=address,
                closure_type=as_str(lbl.get("CLOSURE OR LAYOFF")) or None,
                source_url=_SOURCE_URL,
            )
        )
    return rows


class PAScraper:
    state = "PA"
    source_url = _SOURCE_URL
    expected_row_range = (100, 5_000)
    required_fields = frozenset({"employer", "notice_date"})

    def fetch(self) -> bytes:
        try:
            r = httpx.get(_SOURCE_URL, headers=_UA, timeout=60, follow_redirects=True)
            r.raise_for_status()
            return r.content
        except httpx.HTTPError as e:
            raise ScrapeFailed(f"PA: GET {_SOURCE_URL}: {e}") from e

    def parse(self, raw: bytes) -> list[NoticeRow]:
        try:
            soup = BeautifulSoup(raw, "html.parser")
        except Exception as e:
            raise ParseFailed(f"PA: HTML parse error: {e}") from e

        items = soup.select("h3.cmp-accordion__header")
        if not items:
            raise ParseFailed(
                "PA: no accordion items found -- page structure may have changed"
            )

        rows: list[NoticeRow] = []
        for h3 in items:
            title_el = h3.select_one(".cmp-accordion__title")
            if not title_el:
                continue
            employer = _INVISIBLE_RE.sub("", title_el.get_text(strip=True)).strip()
            if not employer:
                continue

            panel = h3.find_next_sibling("div", class_="cmp-accordion__panel")
            if not panel:
                continue

            rows.extend(_parse_panel(panel, employer))

        if not rows:
            raise ParseFailed("PA: no rows parsed -- page structure may have changed")
        return rows


register(PAScraper())


# ---------------------------------------------------------------------------
# Historical backfill (2001-2022): archived per-month pages via Wayback
# ---------------------------------------------------------------------------
# Two retired hosts carry the same content template (a border="2" table whose
# <td> cells each hold one notice: <strong>Employer</strong>, address lines,
# COUNTY: / # AFFECTED: labels, a standalone bold closure line like
# "PLANT CLOSING", then EFFECTIVE DATE:):
#
#   portal.state.pa.us  /portal/server.pt/community/{yr}/10542/
#                       {month}_{year}_warn_notices/{id}     2001-2015
#   www.dli.pa.gov      /Individuals/Workforce-Development/warn/notices/
#                       Pages/{Month}-{Year}.aspx            2011-2024
#
# Discovery is CDX-driven (both hosts are dead/redirected live); overlapping
# years prefer the SharePoint capture. Month pages carry no per-notice filing
# date, so notice_date is the page month (first-of-month) — the same
# best-available-proxy tradeoff the live scraper makes with repo:modifyDate.
# Hard-capped at 2022: the live AEM era (2023+) stamps notice_date from its
# publish date, so re-parsing those months here would mint duplicate
# notice_ids for rows the regular scraper already stores.

_HIST_YEAR_END = 2022
_CDX_API = "https://web.archive.org/cdx/search/cdx"
_WAYBACK_REPLAY = "https://web.archive.org/web/{ts}id_/{url}"
_WAYBACK_DELAY = 3.0
_WAYBACK_BACKOFF = 30.0

_MONTH_NUM = {
    m: i + 1
    for i, m in enumerate(
        (
            "january", "february", "march", "april", "may", "june",
            "july", "august", "september", "october", "november", "december",
        )
    )
}
_MONTH_ALT = "|".join(_MONTH_NUM)
_PORTAL_MONTH_RE = re.compile(rf"/({_MONTH_ALT})_(\d{{4}})_warn_notices/", re.I)
_SP_MONTH_RE = re.compile(rf"/pages/({_MONTH_ALT})-(\d{{4}})\.aspx", re.I)
# Standalone closure line between the labels — "PLANT CLOSING", "CLOSING",
# "MASS LAYOFF", "PLANT CLOSURE AND MASS LAYOFF", ... Only consulted between
# labels (never for the employer line), so a keyword match is safe.
_CLOSURE_LINE_RE = re.compile(
    r"^(?=.{0,45}$)[^:]*\b(?:closing|closure|layoff)s?\b[^:]*$", re.I
)
# "City, PA" with no ZIP (early portal pages often omit it).
_CITY_NO_ZIP_RE = re.compile(r"^(.+),\s*PA\.?\s*$", re.I)

# Inline labels; the late SharePoint era (~2021+) labels the closure type
# ("CLOSING OR LAYOFF: Closure") instead of a standalone bold line.
_HIST_LABELS = (
    "COUNTY:", "# AFFECTED:", "EFFECTIVE DATE:",
    "CLOSING OR LAYOFF:", "CLOSURE OR LAYOFF:",
)


def _cdx_snapshots(url_pattern: str, month_re: re.Pattern) -> dict[tuple[int, int], str]:
    """(year, month) -> replay URL of the latest 200 capture matching month_re."""
    import time

    for attempt in (1, 2):
        time.sleep(_WAYBACK_DELAY)
        try:
            r = httpx.get(
                _CDX_API,
                params={
                    "url": url_pattern,
                    "matchType": "prefix",
                    "output": "json",
                    "fl": "timestamp,original",
                    "filter": "statuscode:200",
                    "collapse": "urlkey",
                    "limit": "5000",
                },
                headers=_UA,
                timeout=120,
            )
            r.raise_for_status()
            captures = r.json()
            break
        except (httpx.HTTPError, ValueError) as e:
            if attempt == 1:
                time.sleep(_WAYBACK_BACKOFF)
                continue
            raise ScrapeFailed(f"PA: CDX query {url_pattern}: {e}") from e
    best: dict[tuple[int, int], tuple[str, str]] = {}
    if not isinstance(captures, list):
        return {}
    for cap in captures[1:]:  # row 0 is the field-name header
        if not (isinstance(cap, list) and len(cap) == 2):
            continue
        ts, original = str(cap[0]), str(cap[1])
        m = month_re.search(original)
        if m is None:
            continue
        key = (int(m.group(2)), _MONTH_NUM[m.group(1).lower()])
        if key not in best or ts > best[key][0]:
            best[key] = (ts, original)
    return {
        key: _WAYBACK_REPLAY.format(ts=ts, url=original)
        for key, (ts, original) in best.items()
    }


@functools.lru_cache(maxsize=1)
def _month_snapshots() -> dict[tuple[int, int], str]:
    """Merged (year, month) -> replay URL; SharePoint captures win overlaps."""
    snaps = _cdx_snapshots(
        "portal.state.pa.us/portal/server.pt/community/", _PORTAL_MONTH_RE
    )
    snaps.update(
        _cdx_snapshots(
            "dli.pa.gov/Individuals/Workforce-Development/warn/notices/Pages/",
            _SP_MONTH_RE,
        )
    )
    return snaps


def _fetch_pa_year(year: int) -> list[bytes] | None:
    """Fetch every archived month page for *year*; None when none exist."""
    import time

    if year > _HIST_YEAR_END:
        return None
    snaps = _month_snapshots()
    chunks: list[bytes] = []
    for month in range(1, 13):
        url = snaps.get((year, month))
        if url is None:
            continue
        for attempt in (1, 2):
            time.sleep(_WAYBACK_DELAY)
            try:
                r = httpx.get(url, headers=_UA, timeout=120, follow_redirects=True)
                r.raise_for_status()
            except httpx.HTTPError:
                if attempt == 1:
                    time.sleep(_WAYBACK_BACKOFF)
                    continue
                break  # month lost to throttling — the re-run picks it up
            chunks.append(
                json.dumps({"month": month, "html": r.text}).encode("utf-8")
            )
            break
    return chunks or None


def _hist_city(addr_lines: list[str]) -> str | None:
    """City from 'City, PA ZIP' or the early pages' ZIP-less 'City, PA'."""
    city = _extract_city(addr_lines)
    if city:
        return city
    for line in reversed(addr_lines):
        m = _CITY_NO_ZIP_RE.match(line.strip())
        if m:
            return m.group(1).split(",")[-1].strip() or None
    return None


def _parse_month_cell(lines: list[str], year: int, month: int) -> list[NoticeRow]:
    """Parse one table cell's text lines into NoticeRows (usually one)."""
    notice_date = date(year, month, 1)
    rows: list[NoticeRow] = []
    addr_lines: list[str] = []
    labels: dict[str, str] = {}
    employer: str | None = None
    pending: str | None = None  # label whose value is on the next line

    def _flush() -> None:
        if not employer or not labels:
            return
        address = as_str(", ".join(addr_lines)) if addr_lines else None
        rows.append(
            NoticeRow(
                state="PA",
                employer=employer,
                notice_date=notice_date,
                effective_date=_parse_effective_date(labels.get("EFFECTIVE DATE", "")),
                layoff_count=_parse_affected(labels.get("# AFFECTED")),
                city=_hist_city(addr_lines),
                county=as_str(labels.get("COUNTY")) or None,
                zip=zip_from(None, address),
                address=address,
                closure_type=as_str(labels.get("CLOSURE")) or None,
                source_url=_SOURCE_URL,
            )
        )

    for line in lines:
        upper = line.upper()
        if any(upper.startswith(p) for p in _HIST_LABELS):
            key, _, val = line.partition(":")
            key = key.strip().upper()
            if key in ("CLOSING OR LAYOFF", "CLOSURE OR LAYOFF"):
                key = "CLOSURE"
            if val.strip():
                labels[key] = val.strip()
                pending = None
            else:
                pending = key
        elif pending is not None:
            labels[pending] = line
            pending = None
        elif labels and _CLOSURE_LINE_RE.match(line):
            labels["CLOSURE"] = line
        elif labels:
            # Non-label content after a completed block -> next notice.
            _flush()
            employer, addr_lines, labels = line, [], {}
        elif employer is None:
            employer = line
        else:
            addr_lines.append(line)

    _flush()
    return rows


def parse_pa_month(raw: bytes, year: int) -> list[NoticeRow]:
    """Parse one archived month page (JSON envelope from _fetch_pa_year)."""
    try:
        env = json.loads(raw)
        month = int(env["month"])
        soup = BeautifulSoup(env["html"], "html.parser")
    except (ValueError, KeyError, TypeError) as e:
        raise ParseFailed(f"PA archive: bad month envelope: {e}") from e

    rows: list[NoticeRow] = []
    for td in soup.find_all("td"):
        if "# AFFECTED" not in td.get_text().upper():
            continue
        if td.find("td") is not None:  # outer cell wrapping nested layout tables
            continue
        lines = [
            _INVISIBLE_RE.sub("", ln).replace("\xa0", " ").strip()
            for ln in td.get_text(separator="\n").split("\n")
        ]
        rows.extend(_parse_month_cell([ln for ln in lines if ln], year, month))
    return rows
