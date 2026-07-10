"""SD historical backfill — the bundled 1997-2005 frozen cumulative PDF (Mode 3b)."""
from __future__ import annotations

from collections import Counter
from datetime import date

import pytest

from warn_v2.db.models import Notice
from warn_v2.scrapers.base import ParseFailed
from warn_v2.scrapers.states.sd import (
    _ARCHIVE_SOURCE_URL,
    parse_sd_archive_pdf,
    sd_archive_files,
)
from warn_v2.scripts.backfill_historical import _BACKFILL, _SUPPORTED, backfill_historical


@pytest.fixture(scope="module")
def archive_rows():
    members = sd_archive_files()
    assert [name for name, _ in members] == ["WARN_Notices_Received.pdf"]
    return parse_sd_archive_pdf(members[0][1])


def test_parse_matches_the_pdfs_combined_total(archive_rows) -> None:
    """The PDF's own trailing summary row says 60 notices / 8,232 workers."""
    assert len(archive_rows) == 60
    assert sum(r.layoff_count or 0 for r in archive_rows) == 8_232


def test_per_year_counts(archive_rows) -> None:
    per_year = Counter(r.notice_date.year for r in archive_rows)
    assert dict(sorted(per_year.items())) == {
        1997: 5, 1998: 4, 1999: 8, 2000: 8, 2001: 4,
        2002: 10, 2003: 5, 2004: 13, 2005: 3,
    }


def test_out_of_order_row_is_keyed_by_its_own_date(archive_rows) -> None:
    """One 2004 Gateway notice is filed among the 2002 rows — its printed
    date, not its position, must decide the year."""
    ooo = [r for r in archive_rows if r.notice_date == date(2004, 1, 29)]
    assert len(ooo) == 1
    assert ooo[0].employer == "Gateway"
    assert ooo[0].layoff_count == 479
    assert ooo[0].city == "North Sioux City"


def test_row_fields(archive_rows) -> None:
    first = archive_rows[0]
    assert first.state == "SD"
    assert first.employer == "SKF, USA"
    assert first.notice_date == date(2005, 7, 8)
    assert first.layoff_count == 210
    assert first.city == "Springfield"
    assert first.closure_type == "Closure"
    assert first.source_url == _ARCHIVE_SOURCE_URL

    # Action capitalisation is normalised ("layoff" → "Layoff").
    assert Counter(r.closure_type for r in archive_rows) == {"Closure": 50, "Layoff": 10}
    assert all(r.state == "SD" and r.source_url == _ARCHIVE_SOURCE_URL for r in archive_rows)


def test_parse_raises_on_garbage() -> None:
    with pytest.raises(ParseFailed):
        parse_sd_archive_pdf(b"this is not a pdf")


def test_registry_spec_routes_members_to_the_archive_parser() -> None:
    assert "SD" in _SUPPORTED
    spec = _BACKFILL["SD"]
    assert spec.bundled_files is sd_archive_files
    assert spec.parse_for_url("WARN_Notices_Received.pdf") is parse_sd_archive_pdf


def test_backfill_historical_sd_dry_run(db) -> None:
    stats = backfill_historical("SD", dry_run=True)
    assert stats["years_attempted"] == 1
    assert stats["years_ok"] == 1
    assert stats["rows_seen"] == 60
    assert db.query(Notice).count() == 0
