"""Tests for backfill_notice_dates — clamp future notice_date to scrape date."""
from __future__ import annotations

from datetime import date, datetime

from warn_v2.db.models import Notice
from warn_v2.scripts.backfill_notice_dates import backfill_notice_dates


def _notice(
    db,
    *,
    notice_id: str,
    state: str = "MI",
    notice_date: date,
    effective_date: date | None = None,
    scraped_at: datetime,
) -> Notice:
    n = Notice(
        notice_id=notice_id,
        state=state,
        employer="Acme",
        notice_date=notice_date,
        effective_date=effective_date,
        scraped_at=scraped_at,
    )
    db.add(n)
    db.flush()
    return n


def test_future_notice_date_clamped_to_scraped_at(db) -> None:
    scraped = datetime(2026, 6, 1, 12, 0, 0)
    future = date(2026, 9, 15)
    _notice(
        db,
        notice_id="mi-future",
        notice_date=future,
        effective_date=future,  # MI carries the layoff date here too
        scraped_at=scraped,
    )
    db.commit()

    result = backfill_notice_dates(dry_run=False)
    assert result["updated"] == 1

    db.expire_all()
    n = db.get(Notice, "mi-future")
    assert n.notice_date == scraped.date()
    assert n.effective_date == future  # forward-looking date preserved


def test_future_notice_date_fills_null_effective_date(db) -> None:
    scraped = datetime(2026, 6, 1, 12, 0, 0)
    future = date(2026, 9, 15)
    _notice(
        db,
        notice_id="mi-null-eff",
        notice_date=future,
        effective_date=None,
        scraped_at=scraped,
    )
    db.commit()

    backfill_notice_dates(dry_run=False)

    db.expire_all()
    n = db.get(Notice, "mi-null-eff")
    assert n.notice_date == scraped.date()
    assert n.effective_date == future  # original future date moved here


def test_past_notice_date_untouched(db) -> None:
    scraped = datetime(2026, 6, 1, 12, 0, 0)
    past = date(2026, 1, 10)
    _notice(
        db,
        notice_id="mi-past",
        notice_date=past,
        effective_date=None,
        scraped_at=scraped,
    )
    db.commit()

    result = backfill_notice_dates(dry_run=False)
    assert result["updated"] == 0

    db.expire_all()
    n = db.get(Notice, "mi-past")
    assert n.notice_date == past
    assert n.effective_date is None


def test_dry_run_writes_nothing(db) -> None:
    scraped = datetime(2026, 6, 1, 12, 0, 0)
    future = date(2026, 9, 15)
    _notice(
        db,
        notice_id="mi-dry",
        notice_date=future,
        effective_date=future,
        scraped_at=scraped,
    )
    db.commit()

    result = backfill_notice_dates(dry_run=True)
    assert result["updated"] == 1  # counted

    db.expire_all()
    n = db.get(Notice, "mi-dry")
    assert n.notice_date == future  # unchanged


def test_state_filter_scopes_updates(db) -> None:
    scraped = datetime(2026, 6, 1, 12, 0, 0)
    future = date(2026, 9, 15)
    _notice(db, notice_id="mi-x", state="MI", notice_date=future,
            effective_date=future, scraped_at=scraped)
    _notice(db, notice_id="ca-x", state="CA", notice_date=future,
            effective_date=future, scraped_at=scraped)
    db.commit()

    result = backfill_notice_dates(dry_run=False, state_filter="MI")
    assert result["updated"] == 1

    db.expire_all()
    assert db.get(Notice, "mi-x").notice_date == scraped.date()
    assert db.get(Notice, "ca-x").notice_date == future  # untouched
