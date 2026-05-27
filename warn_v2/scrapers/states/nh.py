"""New Hampshire WARN scraper — deferred (no public online listing).

The NH Department of Employment Security (NHES) receives WARN notices at
masslayoff@nhes.nh.gov but does not publish a public listing online.
Per McLane Middleton (2024), "notices are obtained solely via public
records requests" rather than a downloadable table or page.

The nhes.nh.gov website also blocks non-browser server IPs (Akamai Bot Manager),
preventing programmatic access even if data were published there.

Contact: masslayoff@nhes.nh.gov
Rapid Response: Nicholas.J.Masi@livefree.nh.gov

This scraper is deregistered until a public machine-readable source is available.
"""
from __future__ import annotations

from warn_v2.scrapers.base import NoticeRow, ParseFailed, ScrapeFailed
from warn_v2.scrapers.registry import register  # noqa: F401


class NHScraper:
    state = "NH"
    source_url = "https://www.nhes.nh.gov/employers/business-compliance"
    expected_row_range = (1, 300)
    required_fields = frozenset({"employer", "notice_date"})

    def fetch(self) -> bytes:
        raise ScrapeFailed(
            "NH: nhes.nh.gov blocks server IPs and no public WARN notice listing exists. "
            "Notices are available only via public records request to masslayoff@nhes.nh.gov."
        )

    def parse(self, raw: bytes) -> list[NoticeRow]:
        raise ParseFailed("NH: no parseable WARN data source available")


# NH WARN data requires a public records request — deferred until an online source exists.
# register(NHScraper())
