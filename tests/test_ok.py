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
    / "ok"
    / "sample.json"
)


@pytest.fixture
def ok_sample_json() -> bytes:
    return FIXTURE.read_bytes()


def test_ok_parses_live_sample(ok_sample_json: bytes) -> None:
    scraper = get_scraper("OK")
    rows = scraper.parse(ok_sample_json)
    assert len(rows) >= 100
    assert all(r.state == "OK" for r in rows)


def test_ok_known_row(ok_sample_json: bytes) -> None:
    """Arvest Bank (Lowell, 72745) filed a Mass Layoff notice on 2026-05-04."""
    scraper = get_scraper("OK")
    rows = scraper.parse(ok_sample_json)
    arvest = [r for r in rows if r.employer == "Arvest Bank"]
    assert arvest, "expected Arvest Bank row"
    row = arvest[0]
    assert row.notice_date == date(2026, 5, 4)
    assert row.closure_type == "Mass Layoff"
    assert row.city == "Lowell"
    assert row.zip == "72745"
    assert row.extra["local_workforce_board"] == "Central"


def test_ok_zip_normalized_to_five_digits(ok_sample_json: bytes) -> None:
    """Some records carry malformed zips (e.g. 8-digit); only 5 digits survive."""
    scraper = get_scraper("OK")
    rows = scraper.parse(ok_sample_json)
    with_zip = [r for r in rows if r.zip]
    assert with_zip, "expected rows with zips"
    assert all(len(r.zip) == 5 and r.zip.isdigit() for r in with_zip)


def test_ok_validation_passes(ok_sample_json: bytes) -> None:
    scraper = get_scraper("OK")
    rows = scraper.parse(ok_sample_json)
    result = validate(scraper, rows)
    assert result.ok, result.reason


def test_ok_raises_on_bad_json() -> None:
    scraper = get_scraper("OK")
    with pytest.raises(ParseFailed):
        scraper.parse(b"not json {{{")


def test_ok_raises_on_empty_records() -> None:
    scraper = get_scraper("OK")
    payload = json.dumps(
        {"actions": [{"state": "SUCCESS", "returnValue": {"returnValue": []}}]}
    ).encode()
    with pytest.raises(ParseFailed):
        scraper.parse(payload)
