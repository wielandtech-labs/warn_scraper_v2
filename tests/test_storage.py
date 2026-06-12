from datetime import UTC, date, datetime, timedelta

import pytest

from warn_v2.db.models import Company, Location, Notice
from warn_v2.geo import zip_centroids
from warn_v2.pipeline.dedup import notice_id
from warn_v2.pipeline.storage import upsert_notices
from warn_v2.scrapers.base import NoticeRow


@pytest.fixture(autouse=True)
def _seed_centroids():
    """Make ZIP centroid lookups deterministic across this test module."""
    zip_centroids.reload_for_testing({
        "94607": (37.7944, -122.2724),  # Oakland CA
        "94089": (37.4030, -122.0146),  # Sunnyvale CA
        "10001": (40.7506, -73.9971),   # NYC
    })
    yield
    zip_centroids._cache = None  # type: ignore[attr-defined]


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


def test_upsert_derives_closure_category(db) -> None:
    """Freeform closure_type is batched into a normalized closure_category."""
    upsert_notices(db, [
        _row(employer="Plant Co", closure_type="Plant Closure"),
        _row(employer="Cut Co", closure_type="Temporary Layoff",
             notice_date=date(2026, 2, 1)),
        _row(employer="Vague Co", closure_type="Layoff and Closure",
             notice_date=date(2026, 3, 1)),
        _row(employer="None Co", closure_type=None, notice_date=date(2026, 4, 1)),
    ])
    db.commit()

    by_employer = {n.employer: n for n in db.query(Notice).all()}
    assert by_employer["Plant Co"].closure_category == "Closure"
    assert by_employer["Cut Co"].closure_category == "Layoff"
    assert by_employer["Vague Co"].closure_category is None  # ambiguous
    assert by_employer["None Co"].closure_category is None


def test_reupsert_fills_in_null_closure_category(db) -> None:
    """A re-scrape that adds closure_type backfills the normalized category."""
    upsert_notices(db, [_row(closure_type=None)])
    db.commit()
    assert db.query(Notice).one().closure_category is None

    seen, new = upsert_notices(db, [_row(closure_type="Closure")])
    db.commit()
    assert (seen, new) == (1, 0)  # fill-in, not a new row
    assert db.query(Notice).one().closure_category == "Closure"


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


def test_upsert_persists_address(db) -> None:
    rows = [_row(address="1 Main St, Oakland, CA 94607")]
    seen, new = upsert_notices(db, rows)
    db.commit()
    assert (seen, new) == (1, 1)
    notice = db.query(Notice).one()
    assert notice.address == "1 Main St, Oakland, CA 94607"


def test_reupsert_fills_in_null_address(db) -> None:
    """A re-scrape with newly-extracted address fills it in on the existing row."""
    # First scrape: no address
    upsert_notices(db, [_row(address=None)])
    db.commit()
    assert db.query(Notice).one().address is None

    # Second scrape: same notice_id, now with address
    seen, new = upsert_notices(db, [_row(address="1 Main St, Oakland, CA 94607")])
    db.commit()
    assert (seen, new) == (1, 0)  # not a new row, just a fill-in
    assert db.query(Notice).one().address == "1 Main St, Oakland, CA 94607"


def test_reupsert_does_not_overwrite_existing_address(db) -> None:
    """Re-upserting with a different address must NOT overwrite an existing value."""
    upsert_notices(db, [_row(address="1 Main St, Oakland, CA 94607")])
    db.commit()

    # New scrape returns a different address for the same notice_id
    upsert_notices(db, [_row(address="999 Other Way, Oakland, CA 94607")])
    db.commit()
    assert db.query(Notice).one().address == "1 Main St, Oakland, CA 94607"


def test_reupsert_does_not_overwrite_existing_nonnull_fields(db) -> None:
    """A NULL incoming value must not clear an existing count or date."""
    upsert_notices(db, [_row(layoff_count=50, effective_date=date(2026, 3, 1))])
    db.commit()

    upsert_notices(db, [_row(layoff_count=None, effective_date=None)])
    db.commit()
    notice = db.query(Notice).one()
    assert notice.layoff_count == 50
    assert notice.effective_date == date(2026, 3, 1)


def test_reupsert_updates_layoff_count_on_amendment(db) -> None:
    """An amendment with a new non-null count should overwrite the existing value."""
    upsert_notices(db, [_row(layoff_count=50)])
    db.commit()

    seen, new = upsert_notices(db, [_row(layoff_count=75)])
    db.commit()
    assert (seen, new) == (1, 0)  # not a new row
    assert db.query(Notice).one().layoff_count == 75


def test_reupsert_updates_effective_date_on_amendment(db) -> None:
    """An amendment with a revised effective_date should overwrite the existing value."""
    upsert_notices(db, [_row(effective_date=date(2026, 3, 1))])
    db.commit()

    upsert_notices(db, [_row(effective_date=date(2026, 4, 1))])
    db.commit()
    assert db.query(Notice).one().effective_date == date(2026, 4, 1)


def test_future_notice_date_clamped_to_scrape_date(db) -> None:
    """A future notice_date is stored as the scrape date; the original moves to
    effective_date (MI-style sources publish only the layoff date)."""
    future = date.today() + timedelta(days=120)
    # MI carries the same date in both fields.
    row = _row(notice_date=future, effective_date=future)
    upsert_notices(db, [row])
    db.commit()

    notice = db.query(Notice).one()
    today = datetime.now(UTC).date()
    assert notice.notice_date == today
    assert notice.effective_date == future  # forward-looking date preserved


def test_future_notice_date_keeps_hash_stable_no_duplicate(db) -> None:
    """Clamping the stored date must not change the content hash, so re-scrapes
    map to the same row instead of churning a new one each night."""
    future = date.today() + timedelta(days=200)
    row = _row(notice_date=future, effective_date=future)

    seen1, new1 = upsert_notices(db, [row])
    db.commit()
    assert (seen1, new1) == (1, 1)

    notice = db.query(Notice).one()
    # PK is the hash of the ORIGINAL (future-dated) row, not the stored date.
    assert notice.notice_id == notice_id(row)

    # Re-scrape the same source row → update, not a new insert.
    seen2, new2 = upsert_notices(db, [row])
    db.commit()
    assert (seen2, new2) == (1, 0)
    assert db.query(Notice).count() == 1


def test_past_notice_date_is_not_clamped(db) -> None:
    """A normal past notice_date is stored unchanged."""
    past = date(2020, 6, 1)
    upsert_notices(db, [_row(notice_date=past, effective_date=None)])
    db.commit()

    notice = db.query(Notice).one()
    assert notice.notice_date == past
    # 60-day fallback still applies since effective_date was None.
    assert notice.effective_date == past + timedelta(days=60)


def test_location_zip_merged_in_place(db) -> None:
    """A zip-less location should be upgraded in place when a real ZIP arrives."""
    upsert_notices(db, [_row(city="Oakland", zip=None)])
    db.commit()
    loc = db.query(Location).one()
    assert loc.zip in (None, "")
    loc_id = loc.id

    upsert_notices(db, [
        _row(employer="Acme Inc 2", city="Oakland", zip="94607",
             notice_date=date(2026, 2, 1)),
    ])
    db.commit()

    # Should still be one location, now with the ZIP populated.
    assert db.query(Location).count() == 1
    loc = db.query(Location).one()
    assert loc.id == loc_id
    assert loc.zip == "94607"


def test_new_location_gets_lat_lon_from_zip(db) -> None:
    """A brand-new Location with a known ZIP should get its centroid filled in."""
    upsert_notices(db, [_row(city="Oakland", zip="94607")])
    db.commit()
    loc = db.query(Location).filter(Location.zip == "94607").one()
    assert loc.lat is not None
    assert loc.lon is not None
    assert float(loc.lat) == pytest.approx(37.79, abs=0.01)
    assert float(loc.lon) == pytest.approx(-122.27, abs=0.01)


def test_unknown_zip_leaves_lat_lon_null(db) -> None:
    """A ZIP not in the centroid table should still create the row, with NULL coords."""
    upsert_notices(db, [_row(city="Mars City", zip="99999")])
    db.commit()
    loc = db.query(Location).filter(Location.zip == "99999").one()
    assert loc.lat is None
    assert loc.lon is None


def test_zip_promotion_fills_lat_lon(db) -> None:
    """When a zip-less row is upgraded with a real ZIP, its lat/lon are populated."""
    db.add(Location(state="CA", city="Sunnyvale", zip=None))
    db.commit()

    upsert_notices(db, [_row(city="Sunnyvale", zip="94089")])
    db.commit()

    loc = db.query(Location).filter(Location.zip == "94089").one()
    assert float(loc.lat) == pytest.approx(37.40, abs=0.01)


def test_location_zip_merge_skipped_when_ambiguous(db) -> None:
    """If two zip-less rows exist for the same (state, city), skip the merge."""
    # Create two zip-less locations for the same (state, city) by inserting
    # manually — the unique constraint normally prevents this, but in real
    # production data NULL+NULL can collide because NULLs are distinct.
    db.add(Location(state="CA", city="Oakland", zip=None))
    db.add(Location(state="CA", city="Oakland", zip=None))
    db.commit()
    assert db.query(Location).count() == 2

    upsert_notices(db, [_row(city="Oakland", zip="94607")])
    db.commit()
    # Merge skipped → a third row was inserted with the real ZIP.
    assert db.query(Location).count() == 3
    assert (
        db.query(Location).filter(Location.zip == "94607").count() == 1
    )


def test_upsert_sanitizes_multi_value_naics(db) -> None:
    """A source cell holding several NAICS codes must not overflow VARCHAR(8).

    Regression: an IL monthly xlsx carried "423990             321918" in the
    NAICS column, aborting the whole upsert batch in prod.
    """
    upsert_notices(db, [
        _row(employer="Two Codes Co", naics_code="423990             321918"),
        _row(employer="Clean Co", naics_code="321918",
             notice_date=date(2026, 2, 1)),
        _row(employer="Junk Co", naics_code="n/a",
             notice_date=date(2026, 3, 1)),
    ])
    db.commit()

    by_name = {c.name: c for c in db.query(Company).all()}
    assert by_name["Two Codes Co"].naics_code == "423990"
    assert by_name["Clean Co"].naics_code == "321918"
    assert by_name["Junk Co"].naics_code is None
