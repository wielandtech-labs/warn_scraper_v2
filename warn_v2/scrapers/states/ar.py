"""Arkansas WARN scraper — deferred (no public data).

Arkansas Division of Workforce Services does not publish WARN notice listings.
Per A.C.A. § 11-10-314, specific company data received by the agency —
including WARN notices — is confidential and not publicly disclosed.

Employers file notices directly with:
  Arkansas Workforce Connections
  P.O. Box 2981, Little Rock, AR 72203

No machine-readable public source exists for AR WARN data.
This scraper is deregistered until an alternative source is identified.
"""
from __future__ import annotations

from warn_v2.scrapers.base import NoticeRow, ParseFailed, ScrapeFailed
from warn_v2.scrapers.registry import register  # noqa: F401


class ARScraper:
    state = "AR"
    source_url = "https://dws.arkansas.gov/workforce-services/employers/dislocated-worker-services/"
    expected_row_range = (1, 500)
    required_fields = frozenset({"employer", "notice_date"})

    def fetch(self) -> bytes:
        raise ScrapeFailed(
            "AR: WARN notices are confidential under A.C.A. § 11-10-314 "
            "and are not published publicly by the Arkansas Division of Workforce Services."
        )

    def parse(self, raw: bytes) -> list[NoticeRow]:
        raise ParseFailed("AR: no parseable WARN data source available")


# AR WARN data is legally confidential — deferred until an alternative source is found.
# register(ARScraper())
