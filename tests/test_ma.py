from __future__ import annotations

from pathlib import Path

import pytest

from warn_v2.pipeline.validate import validate
from warn_v2.scrapers.base import ParseFailed
from warn_v2.scrapers.registry import get_scraper
from warn_v2.scrapers.states.ma import _discover_csv_links

FIXTURE = (
    Path(__file__).resolve().parent.parent
    / "warn_v2"
    / "scrapers"
    / "fixtures"
    / "ma"
    / "sample.json"
)


@pytest.fixture
def ma_sample() -> bytes:
    return FIXTURE.read_bytes()


def test_ma_parses_fixture(ma_sample: bytes) -> None:
    scraper = get_scraper("MA")
    rows = scraper.parse(ma_sample)
    assert len(rows) >= 5
    assert all(r.state == "MA" for r in rows)

    first = rows[0]
    assert first.employer
    assert first.notice_date is not None
    assert first.city is not None


def test_ma_layoff_counts_present(ma_sample: bytes) -> None:
    scraper = get_scraper("MA")
    rows = scraper.parse(ma_sample)
    with_count = [r for r in rows if r.layoff_count is not None]
    assert len(with_count) >= 5


def test_ma_validation_passes(ma_sample: bytes) -> None:
    scraper = get_scraper("MA")
    rows = scraper.parse(ma_sample)
    result = validate(scraper, rows)
    assert result.ok, result.reason


def test_ma_raises_on_bad_input() -> None:
    scraper = get_scraper("MA")
    with pytest.raises(ParseFailed):
        scraper.parse(b"not valid json")


class _FakePage:
    """Minimal Playwright Page stub for _discover_csv_links.

    Yields no CSV anchor for the first ``empty_loads`` navigations (mimicking
    Akamai's bot-challenge page from a datacenter IP) and the real link
    afterwards.
    """

    def __init__(self, empty_loads: int) -> None:
        self.empty_loads = empty_loads
        self.goto_calls = 0

    def goto(self, url: str, **kwargs: object) -> None:
        self.goto_calls += 1

    def wait_for_selector(self, selector: str, **kwargs: object) -> None:
        if self.goto_calls <= self.empty_loads:
            raise TimeoutError("no anchor yet")

    def eval_on_selector_all(self, selector: str, script: str) -> list[str]:
        if self.goto_calls <= self.empty_loads:
            return []
        return ["https://www.mass.gov/files/csv/2026-06/WARN%20Report.csv"]


def test_ma_discover_retries_past_akamai_challenge() -> None:
    # First navigation returns the challenge page (no link); a reload clears it.
    page = _FakePage(empty_loads=1)
    urls = _discover_csv_links(page, attempts=3)
    assert urls == ["https://www.mass.gov/files/csv/2026-06/WARN%20Report.csv"]
    assert page.goto_calls == 2  # reloaded once before the link appeared


def test_ma_discover_returns_empty_after_exhausting_attempts() -> None:
    page = _FakePage(empty_loads=99)
    urls = _discover_csv_links(page, attempts=3)
    assert urls == []
    assert page.goto_calls == 3  # tried every attempt, then gave up
