from __future__ import annotations

import json
from datetime import date
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
    / "wi"
    / "sample.json"
)


@pytest.fixture
def wi_sample_json() -> bytes:
    return FIXTURE.read_bytes()


def test_wi_parses_live_sample(wi_sample_json: bytes) -> None:
    scraper = get_scraper("WI")
    rows = scraper.parse(wi_sample_json)
    assert len(rows) >= 50
    assert all(r.state == "WI" for r in rows)


def test_wi_known_row(wi_sample_json: bytes) -> None:
    """Associated Milk Producers appears in the fixture with correct values."""
    scraper = get_scraper("WI")
    rows = scraper.parse(wi_sample_json)
    milk = next((r for r in rows if "Milk Producers" in (r.employer or "")), None)
    assert milk is not None, "expected Associated Milk Producers row"
    assert milk.notice_date == date(2026, 1, 30)
    assert milk.layoff_count == 86
    assert milk.city == "Blair"
    assert milk.county == "Trempealeau"


def test_wi_html_stripped_from_company(wi_sample_json: bytes) -> None:
    """HTML tags and entities in Company cells must be stripped."""
    scraper = get_scraper("WI")
    rows = scraper.parse(wi_sample_json)
    for r in rows:
        assert "<" not in (r.employer or ""), f"HTML tag in employer: {r.employer!r}"
        assert "&amp;" not in (r.employer or ""), f"HTML entity in employer: {r.employer!r}"


def test_wi_notice_url(wi_sample_json: bytes) -> None:
    """PDF notice URLs should point to dwd.wisconsin.gov."""
    scraper = get_scraper("WI")
    rows = scraper.parse(wi_sample_json)
    with_url = [r for r in rows if r.raw_notice_url]
    assert with_url, "expected rows with notice URLs"
    url = with_url[0].raw_notice_url
    assert "dwd.wisconsin.gov/dislocatedworker/warn/" in url
    assert url.endswith(".pdf")


def test_wi_extra_fields(wi_sample_json: bytes) -> None:
    scraper = get_scraper("WI")
    rows = scraper.parse(wi_sample_json)
    milk = next((r for r in rows if "Milk Producers" in (r.employer or "")), None)
    assert milk is not None
    assert milk.extra.get("wda") == "Western"
    assert milk.extra.get("naics_description") == "Cheese Mfg"
    assert milk.extra.get("notice_type_code") == "WR"


def test_wi_effective_date(wi_sample_json: bytes) -> None:
    scraper = get_scraper("WI")
    rows = scraper.parse(wi_sample_json)
    milk = next((r for r in rows if "Milk Producers" in (r.employer or "")), None)
    assert milk is not None
    assert milk.effective_date == date(2026, 3, 31)


def test_wi_validation_passes(wi_sample_json: bytes) -> None:
    scraper = get_scraper("WI")
    rows = scraper.parse(wi_sample_json)
    result = validate(scraper, rows)
    assert result.ok, result.reason


def test_wi_raises_on_bad_json() -> None:
    scraper = get_scraper("WI")
    with pytest.raises(ParseFailed):
        scraper.parse(b"this is not json {{{")


def test_wi_raises_on_empty_sheet() -> None:
    """A Sheets response with only a header row raises ParseFailed."""
    scraper = get_scraper("WI")
    payload = json.dumps({"values": [["PK", "Company", "NoticeRcvd"]]}).encode()
    with pytest.raises(ParseFailed):
        scraper.parse(payload)
