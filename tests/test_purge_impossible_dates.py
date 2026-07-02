"""Tests for purge_impossible_dates — removes pre-WARN-Act / far-future rows."""
from __future__ import annotations

from datetime import UTC, date, datetime

from sqlalchemy import select

from warn_v2.db.models import Notice
from warn_v2.scripts.purge_impossible_dates import purge_impossible_dates

_SCRAPED = datetime(2026, 1, 10, 0, 0, tzinfo=UTC)


def _notice(db, notice_id: str, notice_date: date, state: str = "CO") -> Notice:
    n = Notice(
        notice_id=notice_id,
        state=state,
        employer="Emp " + notice_id,
        notice_date=notice_date,
        scraped_at=_SCRAPED,
    )
    db.add(n)
    db.flush()
    return n


def test_purges_only_impossible_dates(db) -> None:
    _notice(db, "junk-1957", date(1957, 7, 19))
    _notice(db, "junk-future", date(2099, 1, 1))
    _notice(db, "keep-normal", date(2021, 12, 30))
    db.commit()

    stats = purge_impossible_dates()
    assert stats == {"matched": 2, "deleted": 2}
    remaining = db.execute(select(Notice.notice_id)).scalars().all()
    assert remaining == ["keep-normal"]


def test_dry_run_deletes_nothing(db) -> None:
    _notice(db, "junk-1957", date(1957, 7, 19))
    db.commit()

    stats = purge_impossible_dates(dry_run=True)
    assert stats == {"matched": 1, "deleted": 0}
    assert db.execute(select(Notice.notice_id)).scalars().all() == ["junk-1957"]


def test_state_filter(db) -> None:
    _notice(db, "co-junk", date(1957, 7, 19), state="CO")
    _notice(db, "ia-junk", date(1900, 1, 1), state="IA")
    db.commit()

    stats = purge_impossible_dates(state_filter="co")
    assert stats == {"matched": 1, "deleted": 1}
    assert db.execute(select(Notice.notice_id)).scalars().all() == ["ia-junk"]
