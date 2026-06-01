from __future__ import annotations

from pathlib import Path

import pytest

from warn_v2.pipeline.validate import validate
from warn_v2.scrapers.base import ParseFailed
from warn_v2.scrapers.registry import get_scraper

FIXTURE = (
    Path(__file__).resolve().parent.parent
    / "warn_v2"
    / "scrapers"
    / "fixtures"
    / "mi"
    / "sample.json"
)


@pytest.fixture
def mi_sample() -> bytes:
    return FIXTURE.read_bytes()


def test_mi_parses_fixture(mi_sample: bytes) -> None:
    scraper = get_scraper("MI")
    rows = scraper.parse(mi_sample)
    # Fixture has 101 API results. 10 cards carry an EMPTY <a class="content-title-link">
    # with the company name in an adjacent <h3>; these were previously misread as UI
    # wrapper divs and silently dropped. All 101 are real notices.
    assert len(rows) == 101
    assert all(r.state == "MI" for r in rows)
    first = rows[0]
    assert first.employer
    assert first.notice_date is not None
    # Spot-check first record from fixture (Our Next Energy, Novi, 2026-01-06)
    assert "Our Next Energy" in first.employer
    assert first.city == "Novi"
    assert first.county == "Oakland"
    # MI API only publishes the layoff date; both fields should be set to it.
    assert first.effective_date is not None
    assert first.effective_date == first.notice_date


def test_mi_layoff_counts_present(mi_sample: bytes) -> None:
    scraper = get_scraper("MI")
    rows = scraper.parse(mi_sample)
    with_count = [r for r in rows if r.layoff_count is not None]
    assert len(with_count) >= 5


def test_mi_validation_passes(mi_sample: bytes) -> None:
    scraper = get_scraper("MI")
    rows = scraper.parse(mi_sample)
    result = validate(scraper, rows)
    assert result.ok, result.reason


def test_mi_raises_on_bad_input() -> None:
    scraper = get_scraper("MI")
    with pytest.raises(ParseFailed):
        scraper.parse(b"not valid json at all")


# Regression: real card shape (captured from prod) where the anchor exists but is
# empty and the company name lives in <h3>. The old `find(a) or find(h3)` latched
# onto the empty anchor, so the h3 fallback never fired and the notice was dropped.
_EMPTY_ANCHOR_CARD = (
    '<div class="search-results__section-content">'
    '<div><a class="content-title-link" href="" target="_blank"></a></div>'
    "<div><h3>Compass Group USA, Inc.</h3>"
    "<p><strong>Type of company action:</strong>&nbsp;Layoff<br />"
    "<strong>Layoff date:</strong>&nbsp;7/1/26<br />"
    "<strong>Number of jobs impacted:</strong> 262</p></div></div>"
)


def test_mi_recovers_empty_anchor_card_from_h3() -> None:
    from warn_v2.scrapers.states.mi import _parse_card

    row = _parse_card(_EMPTY_ANCHOR_CARD)
    assert row is not None
    assert row.employer == "Compass Group USA, Inc."
    assert row.layoff_count == 262
    assert row.notice_date is not None
