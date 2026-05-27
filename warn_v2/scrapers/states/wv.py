"""West Virginia WARN scraper.

Source: https://workforcewv.org/job-seeker/layoffs-downsizing/warn-listing/
Administered by WorkForce West Virginia.

The listing page is Cloudflare-protected so Playwright (headless Chromium) is used
to bypass the JS challenge and render the page.

Each WARN notice is published as a separate PDF download.  The listing page shows
every notice as a hyperlink whose anchor text encodes the company name and filing
date — no structured table exists and individual PDFs are not downloaded.

Anchor-text date patterns:
  "Company Name WARN M-D-YY[YY]"         (most common)
  "Company Name M-D-YY[YY]"              (no WARN keyword)
  "Company_WARN_State_Notice_MM_D_YYYY"  (underscore-separated filename)
  "Company Name 1-21-22 WARN"            (date before keyword)

Only employer name and notice date are reliably available from the listing page.
No city, county, or worker count is captured without downloading individual PDFs.
"""
from __future__ import annotations

import re

from bs4 import BeautifulSoup

from warn_v2.scrapers._helpers import as_date, as_str
from warn_v2.scrapers.base import NoticeRow, ParseFailed
from warn_v2.scrapers.playwright_base import PlaywrightScraper
from warn_v2.scrapers.registry import register

SOURCE_URL = "https://workforcewv.org/job-seeker/layoffs-downsizing/warn-listing/"
_BASE_URL = "https://workforcewv.org"

# Matches M-D-YY, M-D-YYYY, M_D_YYYY (underscore variant in filenames)
_DATE_RE = re.compile(r"\d{1,2}[-_]\d{1,2}[-_]\d{2,4}")

# Keywords that appear in anchor text but are not part of the employer name
_NOISE_RE = re.compile(
    r"\b(WARN|State\s+Notice|r\d+|Notice|Received|Update|Download|PDF)\b",
    re.IGNORECASE,
)


class WVScraper(PlaywrightScraper):
    state = "WV"
    source_url = SOURCE_URL
    expected_row_range = (5, 500)
    required_fields = frozenset({"employer", "notice_date"})

    def _navigate(self, page) -> None:  # type: ignore[override]
        """Navigate to the WARN listing page and wait for PDF links to appear."""
        page.goto(SOURCE_URL, wait_until="load", timeout=60_000)
        # Allow Cloudflare challenge to resolve and content to fully render
        try:
            page.wait_for_selector("a[href*='.pdf']", timeout=20_000)
        except Exception:
            pass  # Proceed even if selector times out; parse() will catch empty results

    def parse(self, raw: bytes) -> list[NoticeRow]:
        soup = BeautifulSoup(raw, "html.parser")
        pdf_links = [
            (a.get_text(strip=True), a.get("href", ""))
            for a in soup.find_all("a", href=True)
            if ".pdf" in a.get("href", "").lower()
        ]
        if not pdf_links:
            raise ParseFailed("WV: no PDF links found on WARN listing page")

        rows: list[NoticeRow] = []
        for text, href in pdf_links:
            row = _parse_notice_link(text, href)
            if row is not None:
                rows.append(row)

        if not rows:
            raise ParseFailed("WV: no parseable WARN notice links found")
        return rows


def _parse_notice_link(text: str, href: str) -> NoticeRow | None:
    """Parse one PDF anchor text into a NoticeRow, or return None if unparseable."""
    m = _DATE_RE.search(text)
    if not m:
        return None  # No date in anchor text — skip

    # Replace underscores (from filename-style links) so as_date can parse
    date_str = m.group().replace("_", "/")
    notice_date = as_date(date_str)
    if notice_date is None:
        return None

    # Employer: text preceding the date match, with noise words stripped
    prefix = text[: m.start()].replace("_", " ")
    employer = _NOISE_RE.sub("", prefix).strip(" -,_")
    employer = as_str(" ".join(employer.split()))
    if not employer:
        return None

    raw_notice_url = href if href.startswith("http") else _BASE_URL + href

    return NoticeRow(
        state="WV",
        employer=employer,
        notice_date=notice_date,
        raw_notice_url=raw_notice_url,
        source_url=SOURCE_URL,
    )


register(WVScraper())
