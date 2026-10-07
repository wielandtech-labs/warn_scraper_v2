from collections import Counter
from datetime import date
from pathlib import Path

import httpx
import pandas as pd
import pytest
import respx

from warn_v2.db.models import Notice
from warn_v2.pipeline.storage import upsert_notices
from warn_v2.pipeline.validate import validate
from warn_v2.scrapers.base import ScrapeFailed
from warn_v2.scrapers.registry import get_scraper
from warn_v2.scrapers.states.ca import _parse_df


def test_ca_parses_golden_fixture(ca_golden_xlsx_bytes, ca_golden_expected) -> None:
    scraper = get_scraper("CA")
    rows = scraper.parse(ca_golden_xlsx_bytes)

    assert len(rows) == ca_golden_expected["row_count"]

    first = rows[0]
    assert first.state == "CA"
    assert first.employer == ca_golden_expected["first_employer"]
    assert first.notice_date == date.fromisoformat(
        ca_golden_expected["first_notice_date"]
    )
    assert first.zip == ca_golden_expected["first_zip"]
    # Address from the source spreadsheet should be promoted to first-class field.
    assert first.address == "1 Main St, Oakland, CA 94607"

    total_layoffs = sum(r.layoff_count or 0 for r in rows)
    assert total_layoffs == ca_golden_expected["total_layoffs"]

    # The "Layoff/\nClosure" header (EDD wraps it with a newline) must map to
    # closure_type — prod stored NULL for every CA notice while this was missed.
    assert [r.closure_type for r in rows] == ca_golden_expected["closure_types"]


def test_ca_golden_fixture_passes_validation(ca_golden_xlsx_bytes) -> None:
    scraper = get_scraper("CA")
    rows = scraper.parse(ca_golden_xlsx_bytes)
    result = validate(scraper, rows)
    assert result.ok, result.reason


def test_ca_numeric_summary_rows_are_dropped() -> None:
    """Purely-numeric company cells (EDD summary section) must be skipped."""
    # Simulates a sheet slice where two real-looking rows have bare numbers in
    # the company column — as seen in production (companies 8831-8837).
    data = {
        "Company": ["Acme Corp", "134", "1,292"],
        "Notice Date": [date(2026, 1, 15), date(2024, 4, 1), None],
        "Effective Date": [date(2026, 3, 15), date(2024, 5, 31), None],
        "No. Of Employees": [250, 0, None],
        "County/Parish": ["Alameda", "0", None],
        "City": ["Oakland", None, None],
        "Address": ["1 Main St", "3", None],
    }
    df = pd.DataFrame(data)
    rows = _parse_df(df)

    # Only "Acme Corp" survives; "134" and "1,292" are dropped.
    assert len(rows) == 1
    assert rows[0].employer == "Acme Corp"


def test_ca_employees_header_variant_is_parsed() -> None:
    """The FY2019-20 archive PDF labels the count column just 'Employees'.

    Without that key in _LAYOFF_COUNT_KEYS the whole file parsed to a 0 count.
    """
    df = pd.DataFrame({
        "Company": ["Harbor Bay Club", "MD2 Industries"],
        "Notice Date": [date(2020, 6, 10), date(2020, 3, 20)],
        "City": ["Alameda", "Long Beach"],
        "Employees": [80, 109],
        "Layoff/Closure": ["Layoff", "Closure"],
    })
    rows = _parse_df(df)

    assert [r.layoff_count for r in rows] == [80, 109]


def test_ca_end_to_end_persists(ca_golden_xlsx_bytes, ca_golden_expected, db) -> None:
    scraper = get_scraper("CA")
    rows = scraper.parse(ca_golden_xlsx_bytes)
    seen, new = upsert_notices(db, rows)
    db.commit()
    assert seen == new == len(rows)

    # EDD's "Layoff Permanent" / "Closure Temporary" values must normalize into
    # the filterable closure_category buckets at storage time.
    stored = db.query(Notice).filter(Notice.state == "CA").all()
    by_category = Counter(n.closure_category for n in stored)
    assert by_category == {
        "Layoff": ca_golden_expected["layoff_category_count"],
        "Closure": ca_golden_expected["closure_category_count"],
    }

    # Idempotent re-run
    seen2, new2 = upsert_notices(db, rows)
    db.commit()
    assert (seen2, new2) == (len(rows), 0)


_ARCHIVE_FIXTURE = (
    Path(__file__).resolve().parents[1]
    / "warn_v2" / "scrapers" / "fixtures" / "ca" / "archive_page_2026-10.html"
)


@respx.mock
def test_ca_fetch_follows_latest_report_link() -> None:
    """fetch() downloads the page's "Latest WARN report" link, not a fixed URL.

    For FY2026-27 EDD moved the current report to warn_report1.xlsx while the
    old WARN_Report.xlsx kept serving a stale file — so the hardcoded URL went
    `not_modified` from July to October 2026 with no error.
    """
    from warn_v2.scrapers.http_cache import bypass
    from warn_v2.scrapers.states.ca import _ARCHIVE_PAGE

    respx.get(_ARCHIVE_PAGE).mock(
        return_value=httpx.Response(200, content=_ARCHIVE_FIXTURE.read_bytes())
    )
    current = respx.get(
        "https://edd.ca.gov/siteassets/files/jobs_and_training/warn/warn_report1.xlsx"
    ).mock(return_value=httpx.Response(200, content=b"xlsx"))

    with bypass():
        assert get_scraper("CA").fetch() == b"xlsx"
    assert current.called


@respx.mock
def test_ca_archive_urls_exclude_latest_report() -> None:
    from warn_v2.scrapers.states.ca import _ARCHIVE_PAGE, _discover_archive_urls

    respx.get(_ARCHIVE_PAGE).mock(
        return_value=httpx.Response(200, content=_ARCHIVE_FIXTURE.read_bytes())
    )
    urls = _discover_archive_urls()
    assert not any(u.endswith(".xlsx") for u in urls)
    assert urls[0].endswith("warn-report-for-7-1-25-to-6-30-26.pdf")


@respx.mock
def test_ca_fetch_fails_loudly_without_latest_link() -> None:
    from warn_v2.scrapers.states.ca import _ARCHIVE_PAGE

    respx.get(_ARCHIVE_PAGE).mock(
        return_value=httpx.Response(200, content=b"<a href='/x/warn-old.pdf'>old</a>")
    )
    with pytest.raises(ScrapeFailed):
        get_scraper("CA").fetch()
