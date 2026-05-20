from datetime import date

from warn_v2.db.models import Company, Location, Notice
from warn_v2.pipeline.storage import upsert_notices
from warn_v2.scrapers.base import NoticeRow


def _row(**kw) -> NoticeRow:
    base = {
        "state": "CA",
        "employer": "Acme Inc",
        "notice_date": date(2026, 1, 15),
        "city": "Oakland",
        "zip": "94607",
        "layoff_count": 50,
    }
    base.update(kw)
    return NoticeRow(**base)


def test_upsert_is_idempotent(db) -> None:
    rows = [_row(), _row(employer="Beta Inc"), _row(employer="Cascade")]
    seen1, new1 = upsert_notices(db, rows)
    db.commit()
    assert (seen1, new1) == (3, 3)

    seen2, new2 = upsert_notices(db, rows)
    db.commit()
    assert (seen2, new2) == (3, 0)

    assert db.query(Notice).count() == 3
    assert db.query(Company).count() == 3
    assert db.query(Location).count() == 1


def test_upsert_creates_distinct_locations(db) -> None:
    rows = [
        _row(employer="Acme Inc", city="Oakland", zip="94607"),
        _row(employer="Acme Inc", city="San Jose", zip="95110",
             notice_date=date(2026, 2, 1)),
    ]
    seen, new = upsert_notices(db, rows)
    db.commit()
    assert (seen, new) == (2, 2)
    assert db.query(Location).count() == 2
    # Same employer → reused company
    assert db.query(Company).count() == 1


def test_upsert_handles_missing_location(db) -> None:
    rows = [_row(city=None, zip=None)]
    seen, new = upsert_notices(db, rows)
    db.commit()
    assert (seen, new) == (1, 1)
    notice = db.query(Notice).one()
    assert notice.location_id is None
