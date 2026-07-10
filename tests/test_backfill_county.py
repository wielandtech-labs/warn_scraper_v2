"""Tests for backfill_county — fills NULL locations.county from coordinates."""
from __future__ import annotations

from decimal import Decimal
from unittest.mock import patch

from warn_v2.db.models import Location
from warn_v2.geo import geocoder
from warn_v2.scripts.backfill_county import backfill_county, repair_county_names


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


# ---------------------------------------------------------------------------
# --repair-names mode: bare BASENAME → full Census NAME
# ---------------------------------------------------------------------------

def test_repair_rewrites_independent_city(db) -> None:
    """"Baltimore" (BASENAME fingerprint, wrong employment key) → "Baltimore city"."""
    loc = _location(db, state="MD", city="Baltimore", zip="21201", county="Baltimore",
                    lat=Decimal("39.2904"), lon=Decimal("-76.6122"))
    db.commit()

    with patch.object(geocoder, "_names_from_coords",
                      return_value=("Baltimore city", "Baltimore")):
        stats = repair_county_names(dry_run=False)

    assert stats == {"considered": 1, "repaired": 1, "unchanged": 0, "no_match": 0}
    db.expire_all()
    assert db.get(Location, loc.id).county == "Baltimore city"


def test_repair_rewrites_ct_planning_region(db) -> None:
    loc = _location(db, state="CT", city="Hartford", zip="06103", county="Capitol",
                    lat=Decimal("41.7658"), lon=Decimal("-72.6734"))
    db.commit()

    with patch.object(geocoder, "_names_from_coords",
                      return_value=("Capitol Planning Region", "Capitol")):
        stats = repair_county_names(dry_run=False)

    assert stats["repaired"] == 1
    db.expire_all()
    assert db.get(Location, loc.id).county == "Capitol Planning Region"


def test_repair_skips_cosmetic_county_suffix(db) -> None:
    """"Sedgwick" vs "Sedgwick County" normalize identically — no churn."""
    loc = _location(db, state="KS", city="Wichita", zip="67202", county="Sedgwick",
                    lat=Decimal("37.6889"), lon=Decimal("-97.3361"))
    db.commit()

    with patch.object(geocoder, "_names_from_coords",
                      return_value=("Sedgwick County", "Sedgwick")):
        stats = repair_county_names(dry_run=False)

    assert stats == {"considered": 1, "repaired": 0, "unchanged": 1, "no_match": 0}
    db.expire_all()
    assert db.get(Location, loc.id).county == "Sedgwick"


def test_repair_leaves_scraper_value_that_disagrees(db) -> None:
    """A stored county that isn't the lookup's BASENAME (scraper-provided,
    possibly disagreeing with centroid-derived coords) is never overwritten."""
    loc = _location(db, state="MO", city="Kansas City", zip="64106", county="Jackson",
                    lat=Decimal("39.0997"), lon=Decimal("-94.5786"))
    db.commit()

    with patch.object(geocoder, "_names_from_coords",
                      return_value=("Clay County", "Clay")):
        stats = repair_county_names(dry_run=False)

    assert stats == {"considered": 1, "repaired": 0, "unchanged": 1, "no_match": 0}
    db.expire_all()
    assert db.get(Location, loc.id).county == "Jackson"


def test_repair_skips_null_county_and_no_coords(db) -> None:
    _location(db, county=None)                                  # NULL county
    _location(db, city="Nowhere", zip="00000", county="Foo",
              lat=None, lon=None)                               # no coords
    db.commit()

    with patch.object(geocoder, "_names_from_coords") as mock_lookup:
        stats = repair_county_names(dry_run=False)

    assert stats["considered"] == 0
    mock_lookup.assert_not_called()


def test_repair_dry_run_no_write(db) -> None:
    loc = _location(db, state="MD", city="Baltimore", zip="21201", county="Baltimore",
                    lat=Decimal("39.2904"), lon=Decimal("-76.6122"))
    db.commit()

    with patch.object(geocoder, "_names_from_coords",
                      return_value=("Baltimore city", "Baltimore")):
        stats = repair_county_names(dry_run=True)

    assert stats["repaired"] == 1
    db.expire_all()
    assert db.get(Location, loc.id).county == "Baltimore"
