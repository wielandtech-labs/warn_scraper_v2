"""Oklahoma WARN scraper — JobLink platform.

Note: as of May 2026, `okjobmatch.com` returns 404 — the source is currently
down. The scraper will surface `fetch_failed` ScraperRun rows until the host
is reachable again or moves elsewhere.
"""
from __future__ import annotations

from warn_v2.scrapers.job_link import JobLinkScraper
from warn_v2.scrapers.registry import register


class OKScraper(JobLinkScraper):
    state = "OK"
    host = "okjobmatch.com"
    expected_row_range = (1, 500)


register(OKScraper())
