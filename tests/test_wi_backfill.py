"""WI 1996-2015 historical backfill — PCML .xls year logs via Wayback.

Fixtures are the real Wayback-captured files for 1997 (single-row era,
1996-2000 layout) and 2012 (multi-row era with Date of Notice / County / WDB
columns).
"""
from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from warn_v2.scrapers.base import ParseFailed
from warn_v2.scrapers.states.wi import _discover_wi_pcml_urls, parse_wi_pcml_xls

FIXTURES = (
    Path(__file__).resolve().parent.parent / "warn_v2" / "scrapers" / "fixtures" / "wi"
)


@pytest.fixture(scope="module")
def rows_1997():
    raw = (FIXTURES / "1997pcml_log.xls").read_bytes()
    return parse_wi_pcml_xls(raw, "https://example.test/1997pcml_log.xls")


@pytest.fixture(scope="module")
def rows_2012():
    raw = (FIXTURES / "2012pcml_log.xls").read_bytes()
    return parse_wi_pcml_xls(raw, "https://example.test/2012pcml_log.xls")


# ---------------------------------------------------------------------------
# URL discovery
# ---------------------------------------------------------------------------


def test_discover_urls_pinned_replay_list() -> None:
    urls = _discover_wi_pcml_urls()
    assert len(urls) == 20  # 1996-2015; 2016 is deliberately excluded
    assert urls[0] == (
        "https://web.archive.org/web/20170125232617id_/"
        "http://worknet.wisconsin.gov/worknet_info/downloads/PCML/1996pcml_log.xls"
    )
    assert all("id_/" in u for u in urls)
    assert not any("2016pcml" in u for u in urls)


# ---------------------------------------------------------------------------
# Single-row era (1996-2000)
# ---------------------------------------------------------------------------


def test_1997_row_count(rows_1997) -> None:
    assert len(rows_1997) == 86
    assert all(r.state == "WI" for r in rows_1997)
    assert all(r.employer and r.notice_date for r in rows_1997)
    assert all(r.notice_date.year == 1997 for r in rows_1997)


def test_1997_first_record_fields(rows_1997) -> None:
    first = rows_1997[0]
    assert first.employer == "Advance Transformer Co."
    assert first.notice_date == date(1997, 1, 9)
    assert first.effective_date == date(1997, 3, 4)
    assert first.layoff_count == 4
    assert first.city == "Platteville"
    assert first.closure_type == "closing"
    assert first.naics_code is None  # NAICS only exists 2001+
    assert first.extra["industry"] == "ballasts"
    # Corporate street + "City, State Zip" columns are joined.
    assert first.extra["corporate_address"] == "10275 W. Higgins Rd., Rosemont, IL 60018"


def test_1997_every_record_has_address_and_city(rows_1997) -> None:
    assert all(r.extra.get("corporate_address") for r in rows_1997)
    assert all(r.city for r in rows_1997)


# ---------------------------------------------------------------------------
# Multi-row era (2001-2016 layouts; 2012 has Date of Notice / County / WDB)
# ---------------------------------------------------------------------------


def test_2012_row_count_and_grouping(rows_2012) -> None:
    # 138 anchor rows; ~4 continuation rows each are folded into their record.
    assert len(rows_2012) == 138
    with_addr = [r for r in rows_2012 if r.extra.get("corporate_address")]
    assert len(with_addr) == 137


def test_2012_first_record_fields(rows_2012) -> None:
    first = rows_2012[0]
    assert first.employer == "Omnicare of Northern Illinois"
    assert first.notice_date == date(2012, 12, 27)  # Notice Received
    assert first.extra["date_of_notice"] == "2012-12-22"
    assert first.effective_date == date(2013, 2, 22)
    assert first.layoff_count == 78
    assert first.city == "Waukesha"
    assert first.county == "Waukesha"
    assert first.naics_code == "446110"
    assert first.closure_type == "New Closing"
    assert first.extra["industry"] == "Pharmacy"
    assert first.extra["wda"] == "3-W-O-W"  # 2012 heads the column "WDB"
    # Continuation address lines are grouped; contact/phone lines are dropped.
    assert first.extra["corporate_address"] == "407 Pilot Court, Suite 200, Waukesha, WI 53188"
    assert "contact" not in first.extra["corporate_address"].lower()


def test_2012_update_rows_kept_as_own_notices(rows_2012) -> None:
    updates = [r for r in rows_2012 if "update" in (r.closure_type or "").lower()]
    assert len(updates) == 58
    # Updates carry their own received date and count — they hash distinctly.
    assert all(r.notice_date for r in updates)


def test_2012_source_url_stamped(rows_2012) -> None:
    assert all(r.source_url == "https://example.test/2012pcml_log.xls" for r in rows_2012)


# ---------------------------------------------------------------------------
# Guards
# ---------------------------------------------------------------------------


def test_typo_year_rows_dropped(rows_2012) -> None:
    # Per-year logs: the modal-year guard drops records whose parsed date
    # lands far outside the file's year (2002's "6/6/4/02" cell → 2004).
    assert all(r.notice_date.year in (2011, 2012, 2013) for r in rows_2012)


def test_raises_on_garbage_bytes() -> None:
    with pytest.raises(ParseFailed):
        parse_wi_pcml_xls(b"this is not an xls \x00\x01", "https://example.test/x.xls")


# ---------------------------------------------------------------------------
# Registry wiring
# ---------------------------------------------------------------------------


def test_backfill_registry_routes_wi_pcml() -> None:
    from warn_v2.scripts.backfill_historical import _BACKFILL

    spec = _BACKFILL["WI"]
    assert spec.discover_urls is not None
    assert spec.fetch_year is None
    urls = spec.discover_urls()
    assert len(urls) == 20
    parse_fn = spec.parse_for_url(urls[0])
    assert parse_fn is not None
    raw = (FIXTURES / "1997pcml_log.xls").read_bytes()
    rows = parse_fn(raw)
    assert len(rows) == 86
    # Mode-2 rows carry the replay URL they were parsed from.
    assert rows[0].source_url == urls[0]
