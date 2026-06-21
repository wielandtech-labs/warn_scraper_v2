from __future__ import annotations

from datetime import date, datetime
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
    / "fl"
    / "sample.html"
)


@pytest.fixture
def fl_sample_html() -> bytes:
    return FIXTURE.read_bytes()


def test_fl_parses_live_sample(fl_sample_html: bytes) -> None:
    scraper = get_scraper("FL")
    rows = scraper.parse(fl_sample_html)
    # 100 results per page in the live source.
    assert 50 <= len(rows) <= 100

    first = rows[0]
    assert first.state == "FL"
    assert first.employer == "ACL Roofing"
    assert first.city == "Englewood"
    assert first.zip == "34223"
    assert first.notice_date == date(2026, 5, 16)
    assert first.effective_date == date(2026, 7, 14)
    assert first.layoff_count == 65
    assert first.extra["industry"] == "Construction"
    assert first.raw_notice_url == (
        "https://reactwarn.floridajobs.org/WarnList/DownloadAzureFile?file=ACL+Roofing.pdf"
    )


def test_fl_pdf_url_format(fl_sample_html: bytes) -> None:
    scraper = get_scraper("FL")
    rows = scraper.parse(fl_sample_html)
    pdf_urls = [r.raw_notice_url for r in rows if r.raw_notice_url]
    # Almost every row should have a PDF link.
    assert len(pdf_urls) >= len(rows) * 0.9
    for url in pdf_urls:
        assert url.startswith(
            "https://reactwarn.floridajobs.org/WarnList/DownloadAzureFile?file="
        )


def test_fl_validation_passes(fl_sample_html: bytes) -> None:
    scraper = get_scraper("FL")
    rows = scraper.parse(fl_sample_html)
    result = validate(scraper, rows)
    assert result.ok, result.reason


def test_fl_raises_without_table() -> None:
    scraper = get_scraper("FL")
    with pytest.raises(ParseFailed):
        scraper.parse(b"<html><body><p>error</p></body></html>")


def test_fl_parse_reads_all_concatenated_page_tables(fl_sample_html: bytes) -> None:
    # fetch() concatenates one HTML document per result page, so parse() must
    # read rows from every DataTable — not just the first. Doubling the fixture
    # stands in for a 2-page fetch.
    scraper = get_scraper("FL")
    single = scraper.parse(fl_sample_html)
    doubled = scraper.parse(fl_sample_html + b"\n" + fl_sample_html)
    assert len(doubled) == 2 * len(single)


@respx.mock
def test_fl_fetch_paginates_and_concatenates() -> None:
    # The live source caps at 100 rows/page; fetch() must walk every page and
    # concatenate the raw HTML so the daily run ingests the whole year (older
    # rows otherwise never get re-scraped or corrected).
    from warn_v2.scrapers.states.fl import URL_TEMPLATE, FLScraper

    year = datetime.now().year
    base = URL_TEMPLATE.format(year=year)
    page1 = (
        b"<html><table id='DataTable'><tbody></tbody></table>"
        + f"<a href='/WarnList/Records?year={year}&page=2'>2</a></html>".encode()
    )
    page2 = b"<html><table id='DataTable'><tbody></tbody></table></html>"
    respx.get(base).mock(return_value=httpx.Response(200, content=page1))
    respx.get(f"{base}&page=2").mock(return_value=httpx.Response(200, content=page2))

    assert FLScraper().fetch() == b"\n".join([page1, page2])
