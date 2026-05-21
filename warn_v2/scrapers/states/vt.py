"""Vermont WARN scraper — JobLink platform."""
from __future__ import annotations

from warn_v2.scrapers.job_link import JobLinkScraper
from warn_v2.scrapers.registry import register


class VTScraper(JobLinkScraper):
    state = "VT"
    host = "www.vermontjoblink.com"
    expected_row_range = (1, 500)


register(VTScraper())
