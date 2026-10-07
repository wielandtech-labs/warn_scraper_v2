from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import httpx
import pytest
import respx

from warn_v2.pipeline.validate import validate
from warn_v2.scrapers.base import ParseFailed
from warn_v2.scrapers.registry import get_scraper

FIXTURE = (
    Path(__file__).resolve().parent.parent
    / "warn_v2"
    / "scrapers"
    / "fixtures"
    / "or"
    / "sample.json"
)


@pytest.fixture
def or_sample_json() -> bytes:
    return FIXTURE.read_bytes()


def test_or_parses_live_sample(or_sample_json: bytes) -> None:
    scraper = get_scraper("OR")
    rows = scraper.parse(or_sample_json)
    assert len(rows) >= 5
    assert all(r.state == "OR" for r in rows)


def test_or_first_row(or_sample_json: bytes) -> None:
    """Fred Meyer Multnomah 2025-07-17 is the most-recent notice in the fixture."""
    scraper = get_scraper("OR")
    rows = scraper.parse(or_sample_json)
    first = rows[0]
    assert "FRED MEYER" in first.employer
    assert first.notice_date == date(2025, 7, 17)
    assert first.layoff_count == 249
    assert first.city == "Portland"
    assert first.county == "Multnomah"


def test_or_closure_type(or_sample_json: bytes) -> None:
    """Closure type is the human-readable string from the HECC system."""
    scraper = get_scraper("OR")
    rows = scraper.parse(or_sample_json)
    with_type = [r for r in rows if r.closure_type]
    assert with_type, "expected rows with closure_type"
    # types include descriptive strings like 'Large Layoff - 10 or more workers'
    assert any("Layoff" in (r.closure_type or "") or "closure" in (r.closure_type or "").lower()
               for r in with_type)


def test_or_notice_url(or_sample_json: bytes) -> None:
    """Each row with a notice document links to the HECC UploadIndex page."""
    scraper = get_scraper("OR")
    rows = scraper.parse(or_sample_json)
    with_url = [r for r in rows if r.raw_notice_url]
    assert with_url, "expected rows with notice URLs"
    url = with_url[0].raw_notice_url
    assert "hecc.oregon.gov" in url
    assert "UploadIndex" in url


def test_or_track_number_in_extra(or_sample_json: bytes) -> None:
    scraper = get_scraper("OR")
    rows = scraper.parse(or_sample_json)
    assert all(r.extra.get("track_number") for r in rows)


def test_or_multiple_counties(or_sample_json: bytes) -> None:
    """Fixture contains notices from more than one county."""
    scraper = get_scraper("OR")
    rows = scraper.parse(or_sample_json)
    counties = {r.county for r in rows}
    assert len(counties) >= 2


def test_or_validation_passes(or_sample_json: bytes) -> None:
    scraper = get_scraper("OR")
    rows = scraper.parse(or_sample_json)
    result = validate(scraper, rows)
    assert result.ok, result.reason


def test_or_raises_on_bad_json() -> None:
    scraper = get_scraper("OR")
    with pytest.raises(ParseFailed):
        scraper.parse(b"not json <<<")


def test_or_raises_on_empty_rows() -> None:
    scraper = get_scraper("OR")
    payload = json.dumps({"rows": []}).encode()
    with pytest.raises(ParseFailed):
        scraper.parse(payload)


_LIST_UNFILTERED = FIXTURE.with_name("list_unfiltered_2026-10.html")
_LIST_MULTNOMAH = FIXTURE.with_name("list_multnomah_2026-10.html")


@respx.mock
def test_or_fetch_crawls_unfiltered_list_and_annotates_county() -> None:
    """Countyless notices must still be scraped.

    As of Oct 2026 no 2026 notice sits under any ?County= filter (e.g. track
    9637, Rainforest Routes, 2026-10-06), so the county-only crawl froze OR in
    mid-2026 with runs reporting ok / rows_new=0. The unfiltered list is the
    complete set; the county pass only labels the tracks it knows.
    """
    def page(request: httpx.Request) -> httpx.Response:
        county = request.url.params.get("County")
        n = request.url.params.get("page")
        if county is None:
            # Multnomah's notices sit deeper in the unfiltered list.
            body = {"1": _LIST_UNFILTERED, "2": _LIST_MULTNOMAH}.get(n)
        else:
            body = _LIST_MULTNOMAH if (county, n) == ("Multnomah", "1") else None
        return httpx.Response(200, content=body.read_bytes() if body else b"<html></html>")

    respx.get(url__startswith="https://ccwd.hecc.oregon.gov/Layoff/WARN").mock(side_effect=page)

    scraper = get_scraper("OR")
    rows = scraper.parse(scraper.fetch())
    by_track = {r.extra["track_number"]: r for r in rows}

    assert len(by_track) == 40
    newest = by_track["9637"]
    assert newest.notice_date == date(2026, 10, 6)
    assert newest.county is None
    assert by_track["9299"].county == "Multnomah"
