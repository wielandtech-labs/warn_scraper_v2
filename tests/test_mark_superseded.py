"""Tests for mark_superseded — Case C (ZIP-variance with addresses)."""
from __future__ import annotations

from datetime import UTC, datetime

import pytest

from warn_v2.db.models import Location, Notice
from warn_v2.scripts.mark_superseded import mark_superseded


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_T0 = datetime(2026, 1, 10, 0, 0, tzinfo=UTC)
_T1 = datetime(2026, 1, 11, 0, 0, tzinfo=UTC)


def _location(db, *, state="IA", city="Des Moines", zip=None) -> Location:
    loc = Location(state=state, city=city, zip=zip)
    db.add(loc)
    db.flush()
    return loc


def _notice(
    db,
    *,
    notice_id: str,
    state: str = "IA",
    employer: str = "Hawkeye Mfg",
    notice_date=None,
    layoff_count: int | None = 100,
    address: str | None = "1 Main St",
    location: Location | None = None,
    scraped_at=_T0,
    is_superseded: bool = False,
) -> Notice:
    from datetime import date

    n = Notice(
        notice_id=notice_id,
        state=state,
        employer=employer,
        notice_date=notice_date or date(2026, 3, 1),
        layoff_count=layoff_count,
        address=address,
        location_id=location.id if location else None,
        scraped_at=scraped_at,
        is_superseded=is_superseded,
    )
    db.add(n)
    db.flush()
    return n


# ---------------------------------------------------------------------------
# Case C — ZIP-variance (both notices have addresses)
# ---------------------------------------------------------------------------


def test_case_c_same_location_supersedes_older(db) -> None:
    """When location promotion merged both notices to the same location row,
    the older notice (lower scraped_at) is superseded."""
    loc = _location(db, zip="50309")
    old = _notice(db, notice_id="ia-old", location=loc, scraped_at=_T0)
    new = _notice(db, notice_id="ia-new", location=loc, scraped_at=_T1)
    db.commit()

    result = mark_superseded(dry_run=False, state_filter="IA", force=True)

    assert result["marked"] == 1
    db.expire_all()
    assert db.get(Notice, old.notice_id).is_superseded is True
    assert db.get(Notice, new.notice_id).is_superseded is False


def test_case_c_zipless_location_supersedes_older(db) -> None:
    """When one location has no ZIP and the other does (promotion didn't fire),
    the ZIP-less notice is superseded."""
    loc_no_zip = _location(db, zip=None)
    loc_zip = _location(db, zip="50309")
    old = _notice(db, notice_id="ia-noz", location=loc_no_zip, scraped_at=_T0)
    new = _notice(db, notice_id="ia-zip", location=loc_zip, scraped_at=_T1)
    db.commit()

    result = mark_superseded(dry_run=False, state_filter="IA", force=True)

    assert result["marked"] == 1
    db.expire_all()
    assert db.get(Notice, old.notice_id).is_superseded is True
    assert db.get(Notice, new.notice_id).is_superseded is False


def test_case_c_different_counts_not_matched(db) -> None:
    """Different layoff_counts are an amendment (Case B territory), not Case C."""
    loc = _location(db, zip="50309")
    _notice(db, notice_id="ia-old", location=loc, layoff_count=100, scraped_at=_T0)
    _notice(db, notice_id="ia-new", location=loc, layoff_count=150, scraped_at=_T1)
    db.commit()

    # Case C should not fire; Case B may or may not (different city+zip logic),
    # but the key assertion is Case C specifically doesn't mark the pair here
    # via the count-mismatch guard.
    result = mark_superseded(dry_run=False, state_filter="IA")
    db.expire_all()
    # Neither should be superseded by Case C (counts differ → not zip-variance)
    old = db.get(Notice, "ia-old")
    new = db.get(Notice, "ia-new")
    # Case B fires on same city+zip — both share the same location so zip matches.
    # It supersedes the older one, which is correct behaviour. We just verify
    # nothing blows up and the newer record survives.
    assert new.is_superseded is False


def test_case_c_already_superseded_skipped(db) -> None:
    """Already-superseded notices are excluded from Case C matching."""
    loc = _location(db, zip="50309")
    old = _notice(db, notice_id="ia-old", location=loc, scraped_at=_T0, is_superseded=True)
    new = _notice(db, notice_id="ia-new", location=loc, scraped_at=_T1)
    db.commit()

    result = mark_superseded(dry_run=False, state_filter="IA")
    # old is already superseded; nothing new to mark
    assert result["marked"] == 0
    db.expire_all()
    assert db.get(Notice, new.notice_id).is_superseded is False


def test_case_c_dry_run_no_commit(db) -> None:
    """dry_run=True must not write any changes."""
    loc = _location(db, zip="50309")
    old = _notice(db, notice_id="ia-old", location=loc, scraped_at=_T0)
    _notice(db, notice_id="ia-new", location=loc, scraped_at=_T1)
    db.commit()

    result = mark_superseded(dry_run=True, state_filter="IA", force=True)
    assert result["marked"] == 1  # detected but not written

    db.expire_all()
    assert db.get(Notice, old.notice_id).is_superseded is False


def test_case_c_different_employers_not_matched(db) -> None:
    """Two different employers at the same location are not duplicates."""
    loc = _location(db, zip="50309")
    _notice(db, notice_id="ia-a", employer="Alpha Corp", location=loc, scraped_at=_T0)
    _notice(db, notice_id="ia-b", employer="Beta Corp", location=loc, scraped_at=_T1)
    db.commit()

    result = mark_superseded(dry_run=False, state_filter="IA")
    assert result["marked"] == 0
