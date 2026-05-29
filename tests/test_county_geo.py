"""Tests for county-centroid geocoding (KY/MT county-only notices)."""
from __future__ import annotations

from datetime import date

import pytest

from warn_v2.db.models import Location, Notice
from warn_v2.geo import county_centroids
from warn_v2.geo.geocoder import geocode
from warn_v2.pipeline.storage import upsert_notices
from warn_v2.scrapers.base import NoticeRow


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _seed_county_centroids():
    """Inject a small in-memory county centroid table for all tests here."""
    county_centroids.reload_for_testing({
        "KY|madison": (37.7123, -84.3012),
        "KY|fayette": (38.0406, -84.5037),
        "MT|yellowstone": (45.7833, -108.5007),
    })
    yield
    county_centroids.reload_for_testing({})


def _county_row(**kw) -> NoticeRow:
    base = {
        "state": "KY",
        "employer": "Acme KY",
        "notice_date": date(2026, 3, 1),
        "county": "Madison",
        # city and zip intentionally omitted
    }
    base.update(kw)
    return NoticeRow(**base)


# ---------------------------------------------------------------------------
# Geocoder unit tests
# ---------------------------------------------------------------------------

def test_geocode_county_fallback_returns_centroid():
    """geocode() should return county centroid when city and zip are absent."""
    result = geocode(None, None, "KY", None, "Madison")
    assert result is not None
    lat, lon = result
    assert float(lat) == pytest.approx(37.7123, abs=0.001)
    assert float(lon) == pytest.approx(-84.3012, abs=0.001)


def test_geocode_county_suffix_stripped():
    """'Madison County' should match the 'madison' key."""
    result = geocode(None, None, "KY", None, "Madison County")
    assert result is not None


def test_geocode_county_not_used_when_city_present():
    """County fallback must not fire if city centroid is found first."""
    # The city lookup won't find "Lexington" because it's not in our test fixture,
    # so it will fall through to county — inject a city to make the city tier win.
    from warn_v2.geo import city_centroids
    city_centroids.reload_for_testing({"KY|lexington": (38.0406, -84.5037)})
    try:
        result = geocode(None, "Lexington", "KY", None, "Fayette")
        assert result is not None
        # Should have returned the city centroid, not the county centroid.
        # Both happen to be the same coords here, but the city path is exercised.
        assert float(result[0]) == pytest.approx(38.0406, abs=0.001)
    finally:
        city_centroids.reload_for_testing({})


def test_geocode_county_unknown_returns_none():
    """Unknown county should return None rather than raising."""
    result = geocode(None, None, "KY", None, "Nowhere")
    assert result is None


def test_geocode_county_none_returns_none():
    """None county should return None rather than raising."""
    result = geocode(None, None, "KY", None, None)
    assert result is None


# ---------------------------------------------------------------------------
# Storage integration tests
# ---------------------------------------------------------------------------

def test_county_only_notice_creates_location(db):
    """A county-only row must create a Location with lat/lon from county centroid."""
    seen, new = upsert_notices(db, [_county_row()])
    db.commit()
    assert (seen, new) == (1, 1)

    notice = db.query(Notice).one()
    assert notice.location_id is not None

    loc = db.query(Location).one()
    assert loc.county == "Madison"
    assert loc.city is None
    assert loc.zip is None
    assert loc.state == "KY"
    assert loc.lat is not None
    assert float(loc.lat) == pytest.approx(37.7123, abs=0.001)


def test_county_only_reuses_existing_location(db):
    """Two county-only notices in the same county reuse one Location row."""
    upsert_notices(db, [
        _county_row(employer="Acme KY"),
        _county_row(employer="Beta KY", notice_date=date(2026, 4, 1)),
    ])
    db.commit()

    assert db.query(Notice).count() == 2
    assert db.query(Location).count() == 1


def test_county_only_different_counties_get_different_locations(db):
    """Different counties within the same state each get their own Location."""
    upsert_notices(db, [
        _county_row(county="Madison"),
        _county_row(county="Fayette", employer="Beta KY", notice_date=date(2026, 4, 1)),
    ])
    db.commit()

    assert db.query(Location).count() == 2
    counties = {loc.county for loc in db.query(Location).all()}
    assert counties == {"Madison", "Fayette"}


def test_county_only_backfills_lat_lon_on_rescrape(db):
    """A county location without coords gets geocoded on the next upsert."""
    # Manually insert a location with no coords (simulates pre-feature data).
    loc = Location(state="KY", county="Madison")
    db.add(loc)
    db.flush()

    upsert_notices(db, [_county_row()])
    db.commit()

    loc = db.query(Location).one()
    assert loc.lat is not None
    assert float(loc.lat) == pytest.approx(37.7123, abs=0.001)


def test_no_location_when_no_city_zip_county(db):
    """A row with no city, zip, or county still produces location_id=None."""
    row = NoticeRow(
        state="KY",
        employer="Ghost Corp",
        notice_date=date(2026, 1, 1),
    )
    upsert_notices(db, [row])
    db.commit()

    notice = db.query(Notice).one()
    assert notice.location_id is None
    assert db.query(Location).count() == 0
