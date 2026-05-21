"""Maine WARN scraper — JobLink platform."""
from __future__ import annotations

from warn_v2.scrapers.job_link import JobLinkScraper
from warn_v2.scrapers.registry import register


class MEScraper(JobLinkScraper):
    state = "ME"
    host = "joblink.maine.gov"
    expected_row_range = (1, 500)


register(MEScraper())
