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
from warn_v2.scrapers.states.co import (
    _KNOWN_SHEETS,
    SOURCE_URL,
    _fetch_co_year,
    _parse_co_year,
)

FIXTURE_DIR = (
    Path(__file__).resolve().parent.parent / "warn_v2" / "scrapers" / "fixtures" / "co"
)

# sample.csv is the 2021 sheet (a raw Google-Form response dump); the year-named
# files are real exports of the other schema families (simple list / headerless
# 2019 / 2020 breakdown / 2022 form dump / modern curated).
_FIXTURE_YEARS = {
    2015: "2015.csv",
    2019: "2019.csv",
    2020: "2020.csv",
    2021: "sample.csv",
    2022: "2022.csv",
    # The curated 2026 sheet doubles as the "current year" sheet so the
    # staleness guard passes no matter when the suite runs.
    date.today().year: "2026.csv",
}


def _envelope(years: dict[int, str] | None = None) -> bytes:
    sheets = [
        {
            "year": year,
            "url": f"https://docs.google.com/spreadsheets/d/fixture-{year}/export?format=csv",
            "csv": (FIXTURE_DIR / name).read_text(encoding="utf-8-sig"),
        }
        for year, name in (years or _FIXTURE_YEARS).items()
    ]
    return json.dumps({"sheets": sheets}).encode()


@pytest.fixture
def co_rows():
    return get_scraper("CO").parse(_envelope())


def test_co_parses_all_schema_families(co_rows) -> None:
    # ~500 notices across the six fixture sheets.
    assert len(co_rows) >= 400
    assert all(r.state == "CO" for r in co_rows)
    assert all(r.employer for r in co_rows)
    assert all(r.notice_date is not None for r in co_rows)
    years = {r.notice_date.year for r in co_rows}
    assert {2015, 2019, 2020, 2021, 2022, 2026} <= years


def test_co_parses_headerless_2019_sheet(co_rows) -> None:
    abm = next(r for r in co_rows if r.employer == "ABM Aviation, Inc.")
    assert abm.notice_date == date(2019, 9, 22)
    assert abm.layoff_count == 79
    assert abm.effective_date == date(2019, 9, 22)
    assert abm.extra["workforce_area"] == "Denver"


def test_co_modern_sheet_prefers_co_specific_count(co_rows) -> None:
    tiaa = next(r for r in co_rows if r.employer == "TIAA")
    assert tiaa.notice_date == date(2026, 1, 2)
    assert tiaa.layoff_count == 101
    assert tiaa.extra["naics"] == "52: Finance and Insurance"


def test_co_form_dump_sums_perm_and_temp(co_rows) -> None:
    # 2021 sheet: no total column, layoff_count = permanent + temporary.
    hss = next(r for r in co_rows if r.employer == "HSS Inc.")
    assert hss.notice_date == date(2021, 11, 29)
    assert hss.layoff_count == 94


def test_co_2022_sheet_recovers_corrupt_naics_header(co_rows) -> None:
    dpi = next(r for r in co_rows if r.employer == "DPI Specialty Foods")
    assert dpi.extra["naics"] == "Sector 42: Wholesale Trade"
    assert dpi.layoff_count == 122


def test_co_impossible_dates_dropped(co_rows) -> None:
    # The 2021 form dump contains a junk submission dated 7/19/1957.
    assert all(r.notice_date.year >= 1988 for r in co_rows)
    assert not any(r.employer == "Lizzy Jacobs" for r in co_rows)


def test_co_zip_extracted_from_form_address(co_rows) -> None:
    assert any(r.zip and r.address for r in co_rows)


def test_co_validation_passes(co_rows) -> None:
    result = validate(get_scraper("CO"), co_rows)
    assert result.ok, result.reason


def test_co_stale_sheets_raise(co_rows) -> None:
    # Only pre-current-year sheets parseable → the source has moved; fail loudly
    # rather than reporting "ok" forever (the pre-2026 CO failure mode).
    with pytest.raises(ParseFailed, match="probably moved"):
        get_scraper("CO").parse(_envelope({2021: "sample.csv"}))


def test_co_back_compat_bare_csv_snapshot() -> None:
    # Raw snapshots taken before the multi-sheet envelope are the bare 2021 CSV.
    raw = (FIXTURE_DIR / "sample.csv").read_bytes()
    rows = get_scraper("CO").parse(raw)
    assert len(rows) >= 10
    assert all(r.state == "CO" for r in rows)


def test_co_raises_on_empty_input() -> None:
    with pytest.raises(ParseFailed):
        get_scraper("CO").parse(b"")


_LISTING_HTML = (
    b'<a href="https://docs.google.com/spreadsheets/d/id-2026/edit?gid=111#gid=111">'
    b"View Real-Time 2026 Warns</a>"
    b'<a href="https://docs.google.com/spreadsheets/d/id-2025/edit?usp=sharing">'
    b"View 2025 WARN List</a>"
    b'<a href="https://docs.google.com/spreadsheets/d/id-2024/edit?usp=sharing">'
    b"View 2024 WARN List</a>"
)

_MINI_CSV = "Company,WARN Date,CO Layoffs\nAcme,1/2/26,10\n"


@respx.mock
def test_co_fetch_downloads_only_two_newest_sheets() -> None:
    respx.get(SOURCE_URL).mock(return_value=httpx.Response(200, content=_LISTING_HTML))
    respx.get("https://docs.google.com/spreadsheets/d/id-2026/export?format=csv&gid=111").mock(
        return_value=httpx.Response(200, text=_MINI_CSV)
    )
    respx.get("https://docs.google.com/spreadsheets/d/id-2025/export?format=csv").mock(
        return_value=httpx.Response(200, text=_MINI_CSV)
    )
    # respx raises on any request without a mock, so a 2024-or-older download
    # (discovered or from the registry) would fail this test.
    raw = get_scraper("CO").fetch()
    sheets = json.loads(raw)["sheets"]
    assert [s["year"] for s in sheets] == [2026, 2025]


@respx.mock
def test_co_backfill_year_fetch_and_parse() -> None:
    respx.get(_KNOWN_SHEETS[2015]).mock(
        return_value=httpx.Response(
            200,
            text="Company Name,Layoff Total,Workforce Region,WARN Date,Reason for Layoff\n"
                 "Albertsons #632,38,Mesa County,6/4/2015,Closure\n",
        )
    )
    raw = _fetch_co_year(2015)
    assert raw is not None
    rows = _parse_co_year(raw, 2015)
    assert len(rows) == 1
    assert rows[0].employer == "Albertsons #632"
    assert rows[0].notice_date == date(2015, 6, 4)
    assert rows[0].layoff_count == 38


def test_co_backfill_year_returns_none_before_first_sheet() -> None:
    with respx.mock:
        respx.get(SOURCE_URL).mock(return_value=httpx.Response(200, content=_LISTING_HTML))
        assert _fetch_co_year(2014) is None
