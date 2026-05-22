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
    / "ct"
    / "sample.json"
)


@pytest.fixture
def ct_sample_json() -> bytes:
    return FIXTURE.read_bytes()


def test_ct_parses_live_sample(ct_sample_json: bytes) -> None:
    scraper = get_scraper("CT")
    rows = scraper.parse(ct_sample_json)
    assert len(rows) >= 10
    assert all(r.state == "CT" for r in rows)


def test_ct_first_row(ct_sample_json: bytes) -> None:
    """IDEX Health & Science LLC (Bristol) 5-5-2026 is the first item in fixture."""
    scraper = get_scraper("CT")
    rows = scraper.parse(ct_sample_json)
    first = rows[0]
    assert "IDEX" in first.employer
    assert first.notice_date == date(2026, 5, 5)
    assert first.city == "Bristol"


def test_ct_city_parsed(ct_sample_json: bytes) -> None:
    """City is extracted from the parenthesised portion of the filename."""
    scraper = get_scraper("CT")
    rows = scraper.parse(ct_sample_json)
    with_city = [r for r in rows if r.city]
    assert len(with_city) > len(rows) // 2, "expected most rows to have a city"


def test_ct_notice_url(ct_sample_json: bytes) -> None:
    """Notice URLs point to the CT DOL ViewBlob endpoint."""
    scraper = get_scraper("CT")
    rows = scraper.parse(ct_sample_json)
    with_url = [r for r in rows if r.raw_notice_url]
    assert with_url, "expected rows with notice URLs"
    assert "ViewBlob" in with_url[0].raw_notice_url
    assert "blobToken=" in with_url[0].raw_notice_url


def test_ct_two_digit_year(ct_sample_json: bytes) -> None:
    """Filenames with two-digit years (e.g. '4-2-21') are parsed as 20xx."""
    scraper = get_scraper("CT")
    rows = scraper.parse(ct_sample_json)
    modivcares = [r for r in rows if "ModivCare" in (r.employer or "")]
    assert modivcares, "expected ModivCare Solutions row"
    assert modivcares[0].notice_date.year == 2021


def test_ct_fallback_to_modified_date(ct_sample_json: bytes) -> None:
    """Records without a date in the filename use modifiedDate as notice_date."""
    scraper = get_scraper("CT")
    rows = scraper.parse(ct_sample_json)
    # OneSpaWorld has no date in filename; should still parse
    onespas = [r for r in rows if "OneSpaWorld" in (r.employer or "")]
    assert onespas, "expected OneSpaWorld row"
    assert onespas[0].notice_date is not None


def test_ct_blob_name_in_extra(ct_sample_json: bytes) -> None:
    scraper = get_scraper("CT")
    rows = scraper.parse(ct_sample_json)
    assert all("blob_name" in r.extra for r in rows)


def test_ct_validation_passes(ct_sample_json: bytes) -> None:
    scraper = get_scraper("CT")
    rows = scraper.parse(ct_sample_json)
    result = validate(scraper, rows)
    assert result.ok, result.reason


def test_ct_raises_on_bad_json() -> None:
    scraper = get_scraper("CT")
    with pytest.raises(ParseFailed):
        scraper.parse(b"not json {{{")


def test_ct_raises_on_empty_items() -> None:
    scraper = get_scraper("CT")
    payload = json.dumps({"blobItems": []}).encode()
    with pytest.raises(ParseFailed):
        scraper.parse(payload)
