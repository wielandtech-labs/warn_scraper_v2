"""TX historical backfill (2004-2019).

Three real fixtures cover the three source eras:
  * sample_2006.xls          — legacy OLE2 .xls era (2004-2013 Wayback
    captures), float date serials, underscore headers. The 2012 capture is the
    lone header variant (spaces: "JOB SITE NAME") — covered by the alias
    tuples in tx.py and verified offline against the cached file.
  * sample_2014.xlsx         — .xlsx era (2014-2018 Wayback captures); same
    columns, a stray all-None trailing row.
  * sample_socrata_2019.json — data.texas.gov 8w53-c4f6 rows (2019 only);
    snake_case JSON mirroring the XLSX columns. The live dataset repeats a
    handful of records verbatim — parse keeps them (identical content hashes
    collapse at ingest).
"""
from __future__ import annotations

from datetime import date
from pathlib import Path

import httpx
import pytest
import respx

from warn_v2.pipeline.validate import validate
from warn_v2.scrapers.base import ParseFailed
from warn_v2.scrapers.registry import get_scraper
from warn_v2.scrapers.states.tx import (
    _WAYBACK_CAPTURES,
    SOCRATA_URL,
    TXScraper,
    _fetch_tx_year,
    parse_tx_socrata,
)

FIXTURES = Path(__file__).resolve().parent.parent / "warn_v2" / "scrapers" / "fixtures" / "tx"


@pytest.fixture
def xls_2006() -> bytes:
    return (FIXTURES / "sample_2006.xls").read_bytes()


@pytest.fixture
def xlsx_2014() -> bytes:
    return (FIXTURES / "sample_2014.xlsx").read_bytes()


@pytest.fixture
def socrata_2019() -> bytes:
    return (FIXTURES / "sample_socrata_2019.json").read_bytes()


def _scraper() -> TXScraper:
    s = TXScraper()
    s.source_url = "https://example.test/tx"
    return s


def test_xls_era_parses(xls_2006: bytes) -> None:
    rows = _scraper().parse(xls_2006)
    assert len(rows) == 159
    assert all(r.state == "TX" for r in rows)
    # Every archive row carries a notice date; xlrd float serials became dates.
    assert all(r.notice_date is not None for r in rows)
    assert {r.notice_date.year for r in rows} == {2006}


def test_xls_era_field_values(xls_2006: bytes) -> None:
    duke = _scraper().parse(xls_2006)[0]
    assert duke.employer == "Duke Energy North America"
    assert duke.notice_date == date(2006, 12, 28)
    assert duke.effective_date == date(2007, 12, 31)
    assert duke.layoff_count == 64
    assert duke.city == "Houston"
    assert duke.county == "Harris"


def test_xlsx_era_parses(xlsx_2014: bytes) -> None:
    rows = _scraper().parse(xlsx_2014)
    # 148 real notices; the workbook's all-None trailing row is dropped.
    assert len(rows) == 148
    schenker = rows[0]
    assert schenker.employer == "Schenker, Inc."
    assert schenker.notice_date == date(2014, 12, 30)
    assert schenker.effective_date == date(2015, 3, 2)
    assert schenker.layoff_count == 18
    assert schenker.city == "El Paso"


def test_xlsx_era_validates(xlsx_2014: bytes) -> None:
    rows = _scraper().parse(xlsx_2014)
    result = validate(get_scraper("TX"), rows)
    assert result.ok, result.reason


def test_socrata_parse(socrata_2019: bytes) -> None:
    rows = parse_tx_socrata(socrata_2019, "https://data.texas.gov/x")
    assert len(rows) == 6
    nestle = rows[0]
    assert nestle.state == "TX"
    assert nestle.employer == "Nestle USA"
    assert nestle.notice_date == date(2019, 1, 4)
    assert nestle.effective_date == date(2019, 3, 8)
    assert nestle.layoff_count == 42
    assert nestle.city == "Fort Worth"
    assert nestle.county == "Tarrant"
    assert nestle.source_url == "https://data.texas.gov/x"


def test_scraper_parse_dispatches_json(socrata_2019: bytes) -> None:
    # TXScraper.parse sniffs JSON bytes and routes to the Socrata parser,
    # stamping rows with the scraper's source_url.
    s = _scraper()
    rows = s.parse(socrata_2019)
    assert len(rows) == 6
    assert all(r.source_url == s.source_url for r in rows)


def test_socrata_rejects_bad_payloads() -> None:
    with pytest.raises(ParseFailed):
        parse_tx_socrata(b"[not json", None)
    with pytest.raises(ParseFailed):
        parse_tx_socrata(b'{"not": "a list"}', None)


@respx.mock
def test_fetch_year_wayback(monkeypatch, xls_2006: bytes) -> None:
    monkeypatch.setattr("time.sleep", lambda *a: None)  # skip wayback pacing
    ts, original = _WAYBACK_CAPTURES[2006]
    replay = f"https://web.archive.org/web/{ts}id_/{original}"
    respx.get(replay).mock(return_value=httpx.Response(200, content=xls_2006))

    s = _scraper()
    raw = _fetch_tx_year(s, 2006)
    assert raw == xls_2006
    assert s.source_url == replay
    assert len(s.parse(raw)) == 159


@respx.mock
def test_fetch_year_socrata_2019(socrata_2019: bytes) -> None:
    route = respx.get(SOCRATA_URL).mock(
        return_value=httpx.Response(200, content=socrata_2019)
    )
    s = _scraper()
    raw = _fetch_tx_year(s, 2019)
    # The query restricts strictly to notice-date year 2019 (the 2018 Wayback
    # file already bleeds into Jan 2019).
    where = route.calls.last.request.url.params["$where"]
    assert "2019-01-01" in where and "2019-12-31" in where
    assert s.source_url.startswith(SOCRATA_URL)
    assert len(s.parse(raw)) == 6


def test_registry_covers_2004() -> None:
    from warn_v2.scripts.backfill_historical import _BACKFILL

    spec = _BACKFILL["TX"]
    assert spec.year_start == 2004
    assert spec.fetch_year is _fetch_tx_year
    # Every backfill year 2004-2019 has a pinned capture or the Socrata path.
    assert sorted(_WAYBACK_CAPTURES) == list(range(2004, 2019))
