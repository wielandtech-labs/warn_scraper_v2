"""Oklahoma WARN scraper — deferred.

okjobmatch.com (the JobLink host) is dead as of May 2026. The replacement
portal (employoklahoma.gov) is a Salesforce community requiring JavaScript
to render — not scrapable with plain httpx. Deferred until a Playwright-based
scraper or a public API endpoint is found.
"""
from __future__ import annotations

from warn_v2.scrapers.job_link import JobLinkScraper  # noqa: F401 (class kept for future use)


class OKScraper(JobLinkScraper):
    state = "OK"
    host = "okjobmatch.com"
    expected_row_range = (1, 500)


# register(OKScraper())  # deferred — see module docstring
