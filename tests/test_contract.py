"""Every registered scraper must satisfy the StateScraper protocol."""
from __future__ import annotations

from warn_v2.scrapers.base import StateScraper
from warn_v2.scrapers.registry import REGISTRY, all_states


def test_at_least_one_state_registered() -> None:
    assert all_states(), "no state scrapers registered"


def test_all_registered_states_satisfy_protocol() -> None:
    for code, scraper in REGISTRY.items():
        assert isinstance(scraper, StateScraper), f"{code} fails protocol"
        assert scraper.state.upper() == code
        assert scraper.source_url.startswith(("http://", "https://"))
        low, high = scraper.expected_row_range
        assert 0 < low <= high
        assert "employer" in scraper.required_fields, (
            f"{code}: 'employer' must be required"
        )
