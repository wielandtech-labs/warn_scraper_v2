"""Wyoming WARN scraper — deferred (no public structured data).

The Wyoming Department of Workforce Services (DWS) does not maintain a public
WARN notice listing.  The Business Expansion/Closing Services page
(dws.wyo.gov) links only to:
  1. An informational Google Drive PDF describing WARN Act requirements.
  2. The federal DOL WARN Act page (dol.gov/agencies/eta/layoffs/warn).

The dws.wyo.gov website is additionally Cloudflare-protected, blocking
programmatic access.

Employers file WY WARN notices with:
  Wyoming Department of Workforce Services
  1510 E. Pershing Blvd., Cheyenne, WY 82002

This scraper is deregistered until a public machine-readable source is identified.
"""
from __future__ import annotations

from warn_v2.scrapers.base import NoticeRow, ParseFailed, ScrapeFailed
from warn_v2.scrapers.registry import register  # noqa: F401


class WYScraper:
    state = "WY"
    source_url = "https://dws.wyo.gov/dws-division/workforce-center-program-operations/programs/business-expansion-closing-services/"
    expected_row_range = (1, 200)
    required_fields = frozenset({"employer", "notice_date"})

    def fetch(self) -> bytes:
        raise ScrapeFailed(
            "WY: no public WARN notice listing. dws.wyo.gov is Cloudflare-protected "
            "and only links to informational content, not a structured notice database."
        )

    def parse(self, raw: bytes) -> list[NoticeRow]:
        raise ParseFailed("WY: no parseable WARN data source available")


# WY has no public structured WARN listing — deferred until an online source exists.
# register(WYScraper())
