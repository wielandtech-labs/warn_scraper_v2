"""ID historical backfill — the bundled 2008 cumulative log PDF (Mode 3b)."""
from __future__ import annotations

import logging
from datetime import date

import pytest

from warn_v2.db.models import Notice
from warn_v2.scrapers.base import ParseFailed
from warn_v2.scrapers.states.id import (
    _ARCHIVE_SOURCE_URL,
    id_archive_files,
    parse_id_2008_pdf,
)
from warn_v2.scripts.backfill_historical import _BACKFILL, _SUPPORTED, backfill_historical


@pytest.fixture(scope="module")
def archive_rows():
    members = id_archive_files()
    assert [name for name, _ in members] == ["WARNNotice_2008.pdf"]
    return parse_id_2008_pdf(members[0][1])


def test_parse_keeps_only_pre_2009_rows(archive_rows) -> None:
    """The 2009-04 capture carries early-2009 rows too; those duplicate the
    live log (prod floor 2009) and must be filtered out."""
    assert len(archive_rows) == 16
    assert all(r.notice_date.year == 2008 for r in archive_rows)
    assert all(r.state == "ID" and r.source_url == _ARCHIVE_SOURCE_URL for r in archive_rows)


def test_parse_logs_the_excluded_2009_row_count(caplog) -> None:
    caplog.set_level(logging.INFO, logger="warn_v2.scrapers.states.id")
    members = id_archive_files()
    parse_id_2008_pdf(members[0][1])
    assert "kept 16 pre-2009 rows, excluded 8 rows" in caplog.text


def test_micron_boise_row(archive_rows) -> None:
    """The headline row the live log dropped: Micron Boise, 1,400-1,600."""
    micron = [r for r in archive_rows if "Micron" in r.employer]
    assert len(micron) == 1
    m = micron[0]
    assert m.employer == "Micron Technology Inc"
    assert m.notice_date == date(2008, 10, 9)
    assert m.layoff_count == 1_400  # leading int of the "1,400-1,600" range
    assert m.city == "Boise"
    assert m.zip == "83707"
    assert m.address == "8000 S Federal Way"
    assert m.effective_date is None  # "10/20/08-12/01/08" range → None


def test_count_annotations_and_non_numeric_counts(archive_rows) -> None:
    naf = next(r for r in archive_rows if r.employer == "North American Foods")
    assert naf.layoff_count == 88  # "88+26" → leading int

    isp = next(r for r in archive_rows if r.employer == "Idaho State Police Assn")
    assert isp.layoff_count is None  # "CDG Mgmt will operate" → no count


def test_effective_dates(archive_rows) -> None:
    stimson = next(r for r in archive_rows if r.employer == "Stimson Lumber Company")
    assert stimson.effective_date == date(2008, 5, 19)

    # Only notice_date is filtered at 2009 — a 2008 notice whose layoff lands
    # in 2009 keeps its effective date.
    baf = next(r for r in archive_rows if r.employer == "Basic American Foods")
    assert baf.notice_date == date(2008, 11, 24)
    assert baf.effective_date == date(2009, 2, 1)


def test_parse_raises_on_garbage() -> None:
    with pytest.raises(ParseFailed):
        parse_id_2008_pdf(b"this is not a pdf")


def test_registry_spec_routes_members_to_the_archive_parser() -> None:
    assert "ID" in _SUPPORTED
    spec = _BACKFILL["ID"]
    assert spec.bundled_files is id_archive_files
    assert spec.parse_for_url("WARNNotice_2008.pdf") is parse_id_2008_pdf


def test_backfill_historical_id_dry_run(db) -> None:
    stats = backfill_historical("ID", dry_run=True)
    assert stats["years_attempted"] == 1
    assert stats["years_ok"] == 1
    assert stats["rows_seen"] == 16
    assert db.query(Notice).count() == 0
