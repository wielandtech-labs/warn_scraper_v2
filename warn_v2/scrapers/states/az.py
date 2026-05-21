"""Arizona WARN scraper — JobLink platform."""
from __future__ import annotations

from warn_v2.scrapers.job_link import JobLinkScraper
from warn_v2.scrapers.registry import register


class AZScraper(JobLinkScraper):
    state = "AZ"
    host = "www.azjobconnection.gov"
    # AZ averages ~22 notices/yr per the V1 sheet; widen to absorb spike years.
    expected_row_range = (1, 500)


register(AZScraper())
