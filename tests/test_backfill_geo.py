"""Tests for backfill_geo — streaming (yield_per) and basic correctness."""
from __future__ import annotations

from datetime import date
from unittest.mock import patch

import pytest

from warn_v2.db.models import Location, Notice
from warn_v2.scripts.backfill_geo import backfill

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _location(db, *, state="TX", city="Houston", zip="77001", lat=None, lon=None) -> Location:
    loc = Location(state=state, city=city, zip=zip, lat=lat, lon=lon)
    db.add(loc)
    db.flush()
    return loc


def _notice(db, *, loc: Location, address: str | None = "100 Main St") -> Notice:
    n = Notice(
        notice_id=f"test-{loc.id}",
        state=loc.state,
        employer="Acme",
        notice_date=date(2026, 1, 1),
        location_id=loc.id,
        address=address,
    )
    db.add(n)
    db.flush()
    return n


# ---------------------------------------------------------------------------
# Default mode: fill NULL coords
# ---------------------------------------------------------------------------

def test_backfill_fills_null_coords(db) -> None:
    loc = _location(db)
    _notice(db, loc=loc)
    db.commit()

    with patch("warn_v2.scripts.backfill_geo.geocode", return_value=(29.76, -95.36, "zip")):
        result = backfill(dry_run=False)

    assert result["considered"] == 1
    db.expire_all()
    refreshed = db.get(Location, loc.id)
    assert float(refreshed.lat) == pytest.approx(29.76)
    assert refreshed.geocode_source == "zip"


def test_backfill_skips_already_geocoded(db) -> None:
    loc = _location(db, lat=29.76, lon=-95.36)
    _notice(db, loc=loc)
    db.commit()

    with patch("warn_v2.scripts.backfill_geo.geocode") as mock_geo:
        result = backfill(dry_run=False)

    assert result["considered"] == 0
    mock_geo.assert_not_called()


def test_backfill_dry_run_no_write(db) -> None:
    loc = _location(db)
    _notice(db, loc=loc)
    db.commit()

    with patch("warn_v2.scripts.backfill_geo.geocode", return_value=(29.76, -95.36, "zip")):
        backfill(dry_run=True)

    db.expire_all()
    assert db.get(Location, loc.id).lat is None


def test_backfill_state_filter(db) -> None:
    tx_loc = _location(db, state="TX")
    ca_loc = _location(db, state="CA")
    _notice(db, loc=tx_loc)
    _notice(db, loc=ca_loc)
    db.commit()

    with patch("warn_v2.scripts.backfill_geo.geocode", return_value=(29.76, -95.36, "zip")):
        result = backfill(dry_run=False, state_filter="TX")

    assert result["considered"] == 1
    db.expire_all()
    assert db.get(Location, tx_loc.id).lat is not None
    assert db.get(Location, ca_loc.id).lat is None


# ---------------------------------------------------------------------------
# --rerun-address mode: upgrade centroid to street-level
# ---------------------------------------------------------------------------

def test_rerun_address_upgrades_existing_coords(db) -> None:
    loc = _location(db, lat=29.70, lon=-95.30)  # existing centroid
    _notice(db, loc=loc, address="100 Main St, Houston, TX 77001")
    db.commit()

    census_coords = (29.7604, -95.3698)
    with patch("warn_v2.geo.geocoder._census_geocode", return_value=census_coords):
        result = backfill(dry_run=False, rerun_address=True)

    assert result["upgraded_address"] == 1
    db.expire_all()
    assert float(db.get(Location, loc.id).lat) == pytest.approx(29.7604)


def test_rerun_address_skips_location_without_address(db) -> None:
    loc = _location(db, lat=29.70, lon=-95.30)
    _notice(db, loc=loc, address=None)
    db.commit()

    # No notice has an address, so `has_address` filter excludes this location.
    result = backfill(dry_run=False, rerun_address=True)
    assert result["considered"] == 0


# ---------------------------------------------------------------------------
# Streaming: multiple locations processed correctly (exercises yield_per path)
# ---------------------------------------------------------------------------

def test_backfill_processes_many_locations(db) -> None:
    """20 null-coord locations all get filled — exercises the streaming loop."""
    locs = []
    for i in range(20):
        loc = _location(db, city=f"City{i}", zip=f"{77000 + i:05d}")
        _notice(db, loc=loc)
        locs.append(loc)
    db.commit()

    with patch("warn_v2.scripts.backfill_geo.geocode", return_value=(30.0, -95.0, "city")):
        result = backfill(dry_run=False, batch_size=5)

    assert result["considered"] == 20
    db.expire_all()
    for loc in locs:
        assert db.get(Location, loc.id).lat is not None


# ---------------------------------------------------------------------------
# --fix-out-of-state mode + rerun-address bbox guard
# ---------------------------------------------------------------------------

def test_fix_out_of_state_repairs_with_in_state_result(db) -> None:
    """GA location pinned in California is re-geocoded into Georgia."""
    from decimal import Decimal

    from warn_v2.geo.geocoder import GeoResult
    from warn_v2.scripts.backfill_geo import fix_out_of_state

    loc = _location(db, state="GA", city="Atlanta", zip="30301",
                    lat=37.7749, lon=-122.4194)  # San Francisco
    _notice(db, loc=loc)
    db.commit()

    in_state = GeoResult(Decimal("33.7490"), Decimal("-84.3880"), "zip")
    with patch("warn_v2.scripts.backfill_geo.geocode", return_value=in_state):
        stats = fix_out_of_state(dry_run=False)

    assert stats == {"considered": 1, "fixed": 1, "cleared": 0}
    db.expire_all()
    refreshed = db.get(Location, loc.id)
    assert float(refreshed.lat) == pytest.approx(33.749)
    assert refreshed.geocode_source == "zip"


def test_fix_out_of_state_clears_unresolvable(db) -> None:
    """No in-state result -> coords cleared (honest low_geo beats a wrong pin)."""
    from warn_v2.scripts.backfill_geo import fix_out_of_state

    loc = _location(db, state="GA", city=None, zip=None,
                    lat=37.7749, lon=-122.4194)
    db.commit()

    with patch("warn_v2.scripts.backfill_geo.geocode", return_value=None):
        stats = fix_out_of_state(dry_run=False)

    assert stats == {"considered": 1, "fixed": 0, "cleared": 1}
    db.expire_all()
    refreshed = db.get(Location, loc.id)
    assert refreshed.lat is None
    assert refreshed.lon is None
    assert refreshed.geocode_source is None


def test_fix_out_of_state_skips_in_state_locations(db) -> None:
    from warn_v2.scripts.backfill_geo import fix_out_of_state

    _location(db, state="TX", lat=29.76, lon=-95.36)  # Houston, in TX bbox
    db.commit()

    with patch("warn_v2.scripts.backfill_geo.geocode") as mock_geo:
        stats = fix_out_of_state(dry_run=False)

    assert stats == {"considered": 0, "fixed": 0, "cleared": 0}
    mock_geo.assert_not_called()


def test_fix_out_of_state_dry_run_no_write(db) -> None:
    from warn_v2.scripts.backfill_geo import fix_out_of_state

    loc = _location(db, state="GA", lat=37.7749, lon=-122.4194)
    db.commit()

    with patch("warn_v2.scripts.backfill_geo.geocode", return_value=None):
        stats = fix_out_of_state(dry_run=True)

    assert stats["cleared"] == 1
    db.expire_all()
    refreshed = db.get(Location, loc.id)
    assert refreshed.lat is not None  # rolled back


def test_rerun_address_keeps_coords_on_out_of_state_census(db) -> None:
    """The census upgrade must not replace in-state centroids with HQ pins."""
    from decimal import Decimal

    loc = _location(db, state="GA", city="Atlanta", zip="30301",
                    lat=33.7490, lon=-84.3880)
    _notice(db, loc=loc, address="1 Corporate Way, San Francisco, CA")
    db.commit()

    hq_pair = (Decimal("37.7749"), Decimal("-122.4194"))  # SF — out of GA
    with patch("warn_v2.scripts.backfill_geo._census_geocode", return_value=hq_pair, create=True):
        from warn_v2.geo import geocoder

        with patch.object(geocoder, "_census_geocode", return_value=hq_pair):
            stats = backfill(dry_run=False, rerun_address=True)

    assert stats["skipped_no_address"] == 1
    assert stats["upgraded_address"] == 0
    db.expire_all()
    refreshed = db.get(Location, loc.id)
    assert float(refreshed.lat) == pytest.approx(33.749)  # unchanged
