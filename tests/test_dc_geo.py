"""DC single-locality default: notices with no source locality geocode to Washington.

The DC WARN source publishes no city/ZIP/address (all notices are in the
District). Storage defaults the *location* city to "Washington" so they geocode at
city level — without affecting notice_id (so no re-keying of existing rows).
"""
from __future__ import annotations

from datetime import date

import pytest

from warn_v2.db.models import Location, Notice
from warn_v2.geo import city_centroids
from warn_v2.pipeline.dedup import notice_id
from warn_v2.pipeline.storage import upsert_notices
from warn_v2.scrapers.base import NoticeRow


@pytest.fixture(autouse=True)
def _seed_dc_city_centroid():
    # Seed the Washington centroid so the test is independent of suite ordering
    # (other tests call city_centroids.reload_for_testing({}), wiping the real
    # bundled data).
    city_centroids.reload_for_testing({"DC|washington": (38.9042, -77.0165)})
    yield
    city_centroids.reload_for_testing({})


def _dc_row(**kw) -> NoticeRow:
    base = {"state": "DC", "employer": "Acme DC", "notice_date": date(2026, 2, 1)}
    base.update(kw)
    return NoticeRow(**base)


def test_dc_notice_defaults_to_washington_location(db):
    upsert_notices(db, [_dc_row()])
    db.commit()

    notice = db.query(Notice).one()
    assert notice.location_id is not None

    loc = db.query(Location).one()
    assert loc.state == "DC"
    assert loc.city == "Washington"
    assert loc.lat is not None and loc.lon is not None


def test_dc_default_does_not_change_notice_id(db):
    # The id must be hashed from the original city-less row, so existing DC rows
    # keep their id and merely get location_id filled in (no re-key / churn).
    row = _dc_row()
    expected = notice_id(row)
    upsert_notices(db, [row])
    db.commit()
    assert db.query(Notice).one().notice_id == expected


def test_dc_notices_share_one_location(db):
    upsert_notices(db, [
        _dc_row(employer="Acme DC"),
        _dc_row(employer="Beta DC", notice_date=date(2026, 3, 1)),
    ])
    db.commit()
    assert db.query(Notice).count() == 2
    assert db.query(Location).count() == 1


def test_dc_locationless_notice_backfilled_on_rescrape(db):
    # Simulate a pre-feature DC notice with no location, then re-scrape.
    row = _dc_row()
    db.add(Notice(
        notice_id=notice_id(row), state="DC", employer="Acme DC",
        notice_date=date(2026, 2, 1), location_id=None,
    ))
    db.commit()
    assert db.query(Notice).one().location_id is None

    upsert_notices(db, [row])  # same id -> fill-in path sets location_id
    db.commit()
    assert db.query(Notice).one().location_id is not None


def test_non_dc_no_locality_still_has_no_location(db):
    upsert_notices(db, [
        NoticeRow(state="KY", employer="Ghost Corp", notice_date=date(2026, 1, 1)),
    ])
    db.commit()
    assert db.query(Notice).one().location_id is None
    assert db.query(Location).count() == 0
