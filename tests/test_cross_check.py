"""Tests for the source cross-check (scripts/cross_check.py + CLI).

Cross-check re-fetches a state's live page and diffs it against stored notices:
``missing_from_db`` (on the page, not stored) and ``extra_in_db`` (stored but
gone from the page, within the page's date window). It must reuse the same
content-hash id and date filter the storage path uses, so the two sides line up.
"""
from __future__ import annotations

from datetime import UTC, date, datetime

from click.testing import CliRunner
from sqlalchemy import select

from warn_v2 import cli
from warn_v2.db.models import CrossCheckRun, Notice
from warn_v2.pipeline.storage import upsert_notices
from warn_v2.scrapers.base import NoticeRow, ParseFailed, ScrapeFailed
from warn_v2.scripts.cross_check import (
    CrossCheck,
    cross_check_state,
    persist,
)


class FakeScraper:
    """Minimal StateScraper whose parse() yields a fixed row set."""

    state = "ZZ"
    source_url = "https://example.test/warn"
    expected_row_range = (1, 1000)
    required_fields = frozenset({"employer"})
    raw_notice_url_is_pdf = True

    def __init__(self, rows, *, fail=False, parse_fail=False):
        self._rows = rows
        self._fail = fail
        self._parse_fail = parse_fail

    def fetch(self) -> bytes:
        if self._fail:
            raise ScrapeFailed("source unreachable")
        return b""

    def parse(self, raw: bytes) -> list[NoticeRow]:
        if self._parse_fail:
            raise ParseFailed("unparseable")
        return list(self._rows)


def _row(employer: str, d: date | None) -> NoticeRow:
    # No city/zip/county → no Location is created (keeps the test offline; the
    # notice_id still hashes deterministically over empty locality fields).
    return NoticeRow(state="ZZ", employer=employer, notice_date=d)


def _seed(db, rows) -> None:
    upsert_notices(db, rows)
    db.flush()


def test_missing_from_db_flags_unstored_live_rows(db) -> None:
    live = [
        _row("A Co", date(2026, 3, 1)),
        _row("B Co", date(2026, 3, 15)),
        _row("C Co", date(2026, 4, 1)),
    ]
    _seed(db, live[:2])  # store A and B; C is missing

    cc = cross_check_state(FakeScraper(live), db)

    assert cc.status == "ok"
    assert cc.live_rows == 3
    assert cc.db_active == 2
    assert {emp for _, emp, _ in cc.missing_from_db} == {"C Co"}
    assert cc.extra_in_db == []


def test_extra_in_db_is_windowed_to_the_live_page(db) -> None:
    live = [
        _row("A Co", date(2026, 3, 1)),
        _row("B Co", date(2026, 3, 15)),
        _row("C Co", date(2026, 4, 1)),
    ]
    extra_in_window = _row("Extra Co", date(2026, 3, 20))  # inside window, off page
    historical = _row("Old Co", date(2020, 1, 1))  # outside window — not drift
    _seed(db, [*live, extra_in_window, historical])

    cc = cross_check_state(FakeScraper(live), db)

    assert cc.missing_from_db == []
    # window is 2026-03-01..2026-04-01: Extra Co is flagged, Old Co is not.
    assert {emp for _, emp, _ in cc.extra_in_db} == {"Extra Co"}


def test_fetch_failure_records_status_and_skips_diff(db) -> None:
    _seed(db, [_row("A Co", date(2026, 3, 1))])

    cc = cross_check_state(FakeScraper([], fail=True), db)

    assert cc.status == "fetch_failed"
    assert cc.error
    assert cc.missing_from_db == [] and cc.extra_in_db == []


def test_parse_failure_records_status(db) -> None:
    cc = cross_check_state(FakeScraper([], parse_fail=True), db)
    assert cc.status == "parse_failed"


def test_empty_parse_is_unverifiable(db) -> None:
    cc = cross_check_state(FakeScraper([]), db)
    assert cc.status == "empty"
    assert cc.live_rows == 0


def test_future_date_row_matches_by_id_not_missing(db) -> None:
    # MI-style: a future notice_date is stored as effective_date with notice_date
    # rewritten to the scrape date, but notice_id stays hashed from the original
    # date (storage.py). The fresh parse must still match by id, not show missing.
    fut = _row("Future Co", date(2027, 12, 1))
    _seed(db, [fut])

    stored = db.get(Notice, db.execute(select(Notice.notice_id)).scalar_one())
    assert stored.notice_date == datetime.now(UTC).date()  # rewritten on insert

    cc = cross_check_state(FakeScraper([fut]), db)
    assert cc.missing_count == 0


def test_persist_writes_one_run_per_result(db) -> None:
    live = [_row("A Co", date(2026, 3, 1)), _row("C Co", date(2026, 4, 1))]
    _seed(db, live[:1])  # C Co will be missing
    results = [cross_check_state(FakeScraper(live), db)]

    persist(db, results, checked_at=datetime.now(UTC))
    db.flush()

    runs = db.execute(select(CrossCheckRun)).scalars().all()
    assert len(runs) == 1
    assert runs[0].state == "ZZ"
    assert runs[0].status == "ok"
    assert runs[0].missing_from_db == 1
    assert runs[0].sample is not None  # drift present → sample populated


# ----- CLI --fail-on-drift exit-code policy -----


def _patch_results(monkeypatch, results: list[CrossCheck]) -> None:
    from warn_v2.scripts import cross_check as cc_mod

    monkeypatch.setattr(
        cc_mod, "cross_check_states", lambda session, *, state_filter=None: results
    )


def test_fail_on_drift_exits_nonzero(db_session_factory, monkeypatch) -> None:
    _patch_results(
        monkeypatch,
        [CrossCheck(state="CA", status="ok", missing_from_db=[("id1", "X Co", None)])],
    )
    result = CliRunner().invoke(cli.main, ["cross-check", "--fail-on-drift", "0", "--no-store"])
    assert result.exit_code == 1, result.output
    assert "missing_from_db exceeds 0: CA(1)" in result.output


def test_fail_on_drift_below_threshold_exits_zero(db_session_factory, monkeypatch) -> None:
    _patch_results(monkeypatch, [CrossCheck(state="CA", status="ok")])
    result = CliRunner().invoke(cli.main, ["cross-check", "--fail-on-drift", "0", "--no-store"])
    assert result.exit_code == 0, result.output


def test_without_flag_drift_is_informational(db_session_factory, monkeypatch) -> None:
    _patch_results(
        monkeypatch,
        [CrossCheck(state="CA", status="ok", missing_from_db=[("id1", "X Co", None)])],
    )
    result = CliRunner().invoke(cli.main, ["cross-check", "--no-store"])
    assert result.exit_code == 0, result.output
