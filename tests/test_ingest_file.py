"""Tests for ingest-file — generic tabular parser + scraper-parser path."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from warn_v2.db.models import Notice
from warn_v2.scripts.ingest_file import ingest_file

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _csv_bytes() -> bytes:
    return (
        b"Company,Notice Date,Effective Date,Employees Affected,City,Zip,WARN Type\n"
        b"Acme Mills,2015-03-02,2015-05-01,120,Columbia,29201,Closure\n"
        b"Palmetto Foods,2015-06-10,2015-08-09,45,Greenville,29601,Layoff\n"
    )


def _dc_html_bytes() -> bytes:
    """Minimal DC-format table (same shape the DC scraper parses)."""
    return (
        b"<table>"
        b"<tr><th>Notice Date</th><th>Organization Name</th>"
        b"<th>Number toEmployees Affected</th><th>Effective Layoff Date</th>"
        b"<th>Code Type</th></tr>"
        b"<tr><td>January 15, 2010</td><td>DC Agency</td>"
        b"<td>50</td><td>March 15, 2010</td><td>1</td></tr>"
        b"</table>"
    )


# ---------------------------------------------------------------------------
# Tabular parser
# ---------------------------------------------------------------------------

def test_ingest_file_tabular_csv_upserts(db, tmp_path) -> None:
    f = tmp_path / "sc_response.csv"
    f.write_bytes(_csv_bytes())

    with patch("warn_v2.scripts.backfill_historical.session_scope") as mock_scope:
        mock_scope.return_value.__enter__ = lambda _: db
        mock_scope.return_value.__exit__ = MagicMock(return_value=False)

        stats = ingest_file("SC", str(f), parser="tabular")

    assert stats["years_ok"] == 1
    assert stats["rows_seen"] == 2
    assert stats["rows_new"] == 2

    notices = db.query(Notice).order_by(Notice.notice_date).all()
    assert [n.employer for n in notices] == ["Acme Mills", "Palmetto Foods"]
    assert notices[0].state == "SC"
    assert notices[0].layoff_count == 120
    assert notices[0].closure_type == "Closure"
    assert notices[0].effective_date.isoformat() == "2015-05-01"
    assert notices[0].source_url == "file://sc_response.csv"


def test_ingest_file_tabular_missing_employer_column(db, tmp_path) -> None:
    f = tmp_path / "junk.csv"
    f.write_bytes(b"Foo,Bar\n1,2\n")

    with patch("warn_v2.scripts.backfill_historical.session_scope") as mock_scope:
        mock_scope.return_value.__enter__ = lambda _: db
        mock_scope.return_value.__exit__ = MagicMock(return_value=False)

        stats = ingest_file("SC", str(f), parser="tabular")

    assert stats["years_ok"] == 0
    assert stats["rows_seen"] == 0
    assert db.query(Notice).count() == 0


# ---------------------------------------------------------------------------
# Scraper parser (default) + dry run + unknown parser
# ---------------------------------------------------------------------------

def test_ingest_file_scraper_parser(db, tmp_path) -> None:
    f = tmp_path / "dc_2010.html"
    f.write_bytes(_dc_html_bytes())

    with patch("warn_v2.scripts.backfill_historical.session_scope") as mock_scope:
        mock_scope.return_value.__enter__ = lambda _: db
        mock_scope.return_value.__exit__ = MagicMock(return_value=False)

        stats = ingest_file("DC", str(f))  # parser defaults to "scraper"

    assert stats["rows_seen"] == 1
    assert db.query(Notice).filter(Notice.employer == "DC Agency").count() == 1


def test_ingest_file_dry_run_no_writes(db, tmp_path) -> None:
    f = tmp_path / "sc_response.csv"
    f.write_bytes(_csv_bytes())

    stats = ingest_file("SC", str(f), parser="tabular", dry_run=True)

    assert stats["years_ok"] == 1
    assert stats["rows_seen"] == 2
    assert stats["rows_new"] == 0
    assert db.query(Notice).count() == 0


def test_ingest_file_unknown_parser(tmp_path) -> None:
    f = tmp_path / "x.csv"
    f.write_bytes(b"a,b\n1,2\n")

    with pytest.raises(ValueError, match="unknown parser"):
        ingest_file("SC", str(f), parser="bogus")
