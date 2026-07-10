"""Tests for backfill_county — fills NULL locations.county from coordinates."""
from __future__ import annotations

from decimal import Decimal
from unittest.mock import patch

from warn_v2.db.models import Location
from warn_v2.geo import geocoder
from warn_v2.scripts.backfill_county import backfill_county


def _location(db, *, state="TX", city="Houston", zip="77001", county=None,
              lat=Decimal("29.76"), lon=Decimal("-95.36")) -> Location:
    loc = Location(state=state, city=city, zip=zip, county=county, lat=lat, lon=lon)
    db.add(loc)
    db.flush()
    return loc


def test_fills_null_county_from_coords(db) -> None:
    loc = _location(db)
    db.commit()

    with patch.object(geocoder, "county_from_coords", return_value="Harris") as mock_lookup:
        stats = backfill_county(dry_run=False)

    assert stats == {"considered": 1, "filled": 1, "no_match": 0, "skipped_no_coords": 0}
    mock_lookup.assert_called_once_with(loc.lat, loc.lon, "TX")
    db.expire_all()
    assert db.get(Location, loc.id).county == "Harris"


def test_skips_locations_with_existing_county(db) -> None:
    loc = _location(db, county="Harris")
    db.commit()

    with patch.object(geocoder, "county_from_coords") as mock_lookup:
        stats = backfill_county(dry_run=False)

    assert stats["considered"] == 0
    mock_lookup.assert_not_called()
    db.expire_all()
    assert db.get(Location, loc.id).county == "Harris"


def test_counts_locations_without_coords(db) -> None:
    _location(db, lat=None, lon=None)
    db.commit()

    with patch.object(geocoder, "county_from_coords") as mock_lookup:
        stats = backfill_county(dry_run=False)

    assert stats == {"considered": 0, "filled": 0, "no_match": 0, "skipped_no_coords": 1}
    mock_lookup.assert_not_called()


def test_no_match_leaves_county_null(db) -> None:
    loc = _location(db)
    db.commit()

    with patch.object(geocoder, "county_from_coords", return_value=None):
        stats = backfill_county(dry_run=False)

    assert stats == {"considered": 1, "filled": 0, "no_match": 1, "skipped_no_coords": 0}
    db.expire_all()
    assert db.get(Location, loc.id).county is None


def test_dry_run_no_write(db) -> None:
    loc = _location(db)
    db.commit()

    with patch.object(geocoder, "county_from_coords", return_value="Harris"):
        stats = backfill_county(dry_run=True)

    assert stats["filled"] == 1
    db.expire_all()
    assert db.get(Location, loc.id).county is None


def test_state_filter(db) -> None:
    tx_loc = _location(db)
    ca_loc = _location(db, state="CA", city="Oakland", zip="94607",
                       lat=Decimal("37.79"), lon=Decimal("-122.27"))
    db.commit()

    with patch.object(geocoder, "county_from_coords", return_value="Harris"):
        stats = backfill_county(dry_run=False, state_filter="TX")

    assert stats["considered"] == 1
    db.expire_all()
    assert db.get(Location, tx_loc.id).county == "Harris"
    assert db.get(Location, ca_loc.id).county is None


def test_streaming_many_locations(db) -> None:
    """20 locations all get filled — exercises the yield_per streaming loop."""
    locs = [
        _location(db, city=f"City{i}", zip=f"{77000 + i:05d}")
        for i in range(20)
    ]
    db.commit()

    with patch.object(geocoder, "county_from_coords", return_value="Harris"):
        stats = backfill_county(dry_run=False, batch_size=5)

    assert stats["considered"] == 20
    assert stats["filled"] == 20
    db.expire_all()
    for loc in locs:
        assert db.get(Location, loc.id).county == "Harris"
