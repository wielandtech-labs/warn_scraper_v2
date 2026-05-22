"""Hawaii WARN scraper.

Source: https://labor.hawaii.gov/wdc/{year}-warn-notices/
Data:   HTML page with <p> entries; one paragraph per notice.

Each paragraph follows the pattern:
  {Month D, YYYY} - [Conditional WARN -] <a href="...pdf">Employer Name</a>

Some entries have a "UPDATE -" prefix in the anchor text; we strip it.
Rescission notices appear as a parenthetical anchor with text "WARN Rescinded
- {date}" inside an existing entry's paragraph; those anchors are not used as
the employer link. Entries where the only anchor is a rescission notice have
the employer extracted from the paragraph text.

No count, city, county, or ZIP data is published on this page.
"""
from __future__ import annotations

import re
from datetime import date

import httpx
from bs4 import BeautifulSoup, Tag

from warn_v2.scrapers._helpers import as_date
from warn_v2.scrapers.base import NoticeRow, ParseFailed, ScrapeFailed
from warn_v2.scrapers.registry import register

# The HI page uses the Unicode en-dash (U+2013, &#8211;) as the date separator.
_EN_DASH = chr(0x2013)  # U+2013 EN DASH
_SOURCE_TMPL = "https://labor.hawaii.gov/wdc/{year}-warn-notices/"
# Build patterns using chr() to avoid a literal en-dash in source (ruff RUF001).
_UPDATE_PREFIX = re.compile("^UPDATE\\s*" + chr(0x2013) + "\\s*", re.I)
_COND_PREFIX = re.compile("^Conditional\\s+WARN\\s*" + chr(0x2013) + "\\s*", re.I)

_UA = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) warn-v2/0.1"
    )
}


def _source_url(year: int) -> str:
    return _SOURCE_TMPL.format(year=year)


def _parse_paragraph(p: Tag) -> tuple[str, str, str | None] | None:
    """Return (date_str, employer, raw_notice_url) or None to skip."""
    full_text = p.get_text(strip=True)
    if not full_text or _EN_DASH not in full_text:
        return None

    # Date is the segment before the first en-dash
    date_str = full_text.split(_EN_DASH)[0].strip()
    # Must look like "Month D, YYYY"
    if not re.match(r"[A-Za-z]+ \d+,\s*\d{4}$", date_str):
        return None

    # Find anchors; classify as main-WARN vs rescission
    anchors = p.find_all("a", href=True)
    main_anchor: Tag | None = None
    for a in anchors:
        anchor_text = a.get_text(strip=True).lower()
        if "rescinded" in anchor_text or "rescind" in anchor_text:
            continue
        main_anchor = a
        break

    if main_anchor:
        employer = main_anchor.get_text(strip=True)
        # Strip "UPDATE - " prefix from anchor text
        employer = _UPDATE_PREFIX.sub("", employer).strip()
        raw_url: str | None = main_anchor["href"]
        return date_str, employer, raw_url

    # No main anchor -- extract employer from paragraph text.
    # Format: "{date} - [{modifiers} -] {employer} [(notes)]"
    remainder = full_text[len(date_str):].strip()
    # Remove leading en-dashes and spaces
    remainder = remainder.lstrip(_EN_DASH + " ").strip()
    # Strip "Conditional WARN - " prefix
    if _COND_PREFIX.match(remainder):
        remainder = _COND_PREFIX.sub("", remainder).strip()
    # Take up to the first "(" parenthetical
    if "(" in remainder:
        remainder = remainder[: remainder.index("(")].strip()
    # Remove trailing en-dashes / spaces
    employer = remainder.strip(_EN_DASH + " ").strip()
    if not employer:
        return None
    return date_str, employer, None


class HIScraper:
    state = "HI"
    source_url = _source_url(date.today().year)
    expected_row_range = (1, 500)
    required_fields = frozenset({"employer", "notice_date"})

    def fetch(self) -> bytes:
        year = date.today().year
        url = _source_url(year)
        try:
            r = httpx.get(url, headers=_UA, timeout=30, follow_redirects=True)
            r.raise_for_status()
            return r.content
        except httpx.HTTPError as e:
            raise ScrapeFailed(f"GET {url}: {e}") from e

    def parse(self, raw: bytes) -> list[NoticeRow]:
        try:
            soup = BeautifulSoup(raw, "html.parser")
        except Exception as e:
            raise ParseFailed(f"HI HTML: could not parse: {e}") from e

        # Content lives in the Elementor text-editor widget
        container = soup.find(class_="elementor-widget-text-editor")
        if container is None:
            # Fallback: any main content div
            container = soup.find("div", id="container_main") or soup

        paragraphs = container.find_all("p")  # type: ignore[union-attr]
        if not paragraphs:
            raise ParseFailed("HI HTML: no <p> entries found in content")

        rows: list[NoticeRow] = []
        for p in paragraphs:
            result = _parse_paragraph(p)
            if result is None:
                continue
            date_str, employer, raw_url = result
            notice_date = as_date(date_str)
            if notice_date is None:
                continue
            # Infer year-based source URL from notice date
            src = _source_url(notice_date.year)
            rows.append(
                NoticeRow(
                    state="HI",
                    employer=employer,
                    notice_date=notice_date,
                    raw_notice_url=raw_url,
                    source_url=src,
                )
            )
        return rows


register(HIScraper())
