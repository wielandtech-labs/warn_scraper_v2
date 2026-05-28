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
                layoff_count=(
                    as_int(lbl.get("# AFFECTED"))
                    if lbl.get("# AFFECTED") is not None
                    else None
                ),
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
