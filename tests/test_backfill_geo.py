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

    with patch("warn_v2.scripts.backfill_geo.geocode", return_value=(29.76, -95.36)):
        result = backfill(dry_run=False)

    assert result["considered"] == 1
    db.expire_all()
    assert float(db.get(Location, loc.id).lat) == pytest.approx(29.76)


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

    with patch("warn_v2.scripts.backfill_geo.geocode", return_value=(29.76, -95.36)):
        backfill(dry_run=True)

    db.expire_all()
    assert db.get(Location, loc.id).lat is None


def test_backfill_state_filter(db) -> None:
    tx_loc = _location(db, state="TX")
    ca_loc = _location(db, state="CA")
    _notice(db, loc=tx_loc)
    _notice(db, loc=ca_loc)
    db.commit()

    with patch("warn_v2.scripts.backfill_geo.geocode", return_value=(29.76, -95.36)):
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

    with patch("warn_v2.scripts.backfill_geo.geocode", return_value=(30.0, -95.0)):
        result = backfill(dry_run=False, batch_size=5)

    assert result["considered"] == 20
    db.expire_all()
    for loc in locs:
        assert db.get(Location, loc.id).lat is not None
