"""NY location city: corrected on the location only, never re-keying notices.

NY's legacy address parse (whose city feeds notice_id) yields street fragments
like "Floor New York" for addresses without a double space. The corrected city
rides in ``NoticeRow.location_city`` and existing rows move via relink-cities.
"""
from __future__ import annotations

from datetime import date

import pytest

from warn_v2.db.models import Location, Notice
from warn_v2.pipeline.dedup import notice_id
from warn_v2.pipeline.storage import upsert_notices
from warn_v2.scrapers.base import NoticeRow
from warn_v2.scrapers.states.ny import _parse_address, location_city
from warn_v2.scripts.relink_cities import relink_cities


@pytest.mark.parametrize(
    ("address", "city"),
    [
        ("2857 W 8th  Street Brooklyn, NY, 11224", "Brooklyn"),
        ("81-83 East 98th  Street Brooklyn, NY, 11212", "Brooklyn"),
        ("12 Main  Floor New York, NY, 10001", "New York"),
        ("5 Park  Avenue New York, NY, 10016", "New York"),
        ("9 Elm  St New York, NY, 10001", "New York"),
        # Real places that start with a street-like word keep it.
        ("1 Main Street  St James, NY, 11780", "St James"),
    ],
)
def test_location_city_drops_street_word_left_before_city(address, city):
    assert location_city(address) == city


@pytest.mark.parametrize(
    ("address", "city"),
    [
        # No double space: longest trailing run that names a known NY place.
        ("140 East 45th Street 12th Floor New York, NY, 10017", "New York"),
        ("Pure Fitness - Jackson Heights 78-14 Roosevelt Ave Jackson Heights, NY, 11372",
         "Jackson Heights"),
        ("Pure Fitness - Concourse Village 820 Concourse Village West Bronx, NY, 10451",
         "Bronx"),
        # Several double spaces: the city follows the last one.
        ("15 W. 43rd  Street  New York, NY, 10036", "New York"),
        ("425 Essjay Road  Suite 100  Williamsville, NY, 14221", "Williamsville"),
        # The source sometimes drops the ZIP.
        ("One Rockwood Road  Sleepy Hollow, NY,", "Sleepy Hollow"),
        # The source's usual spelling wins over the address's casing.
        ("1 Main St BROOKLYN, NY, 11201", "Brooklyn"),
        ("1 Main St  brooklyn, NY, 11201", "Brooklyn"),
        # Clean addresses agree with the legacy parse.
        ("420 Park Ave S  New York, NY, 10016", "New York"),
        # No confident city: keep whatever the location has.
        ("6515 Transit Road Suite 26 Xyzzyville, NY, 14026", None),
        ("955 Chesterbrook Blvd  Wayne, PA, 19087", None),
        ("", None),
        (None, None),
    ],
)
def test_location_city(address, city):
    assert location_city(address) == city


def _ny_row(address: str, **kw) -> NoticeRow:
    _addr, city, zip_ = _parse_address(address)
    base = dict(state="NY", employer="Knight Facilities Management, Inc.",
                notice_date=date(2026, 4, 22), layoff_count=2,
                address=address, city=city, zip=zip_, county="New York")
    base.update(kw)
    loc = location_city(address)
    base["location_city"] = loc if loc != city else None
    return NoticeRow(**base)


def test_parser_sets_location_city_and_keeps_legacy_city():
    from warn_v2.scrapers.registry import get_scraper

    csv = (
        b"Business Legal Name,Date of WARN Notice ,Impacted Site Address,"
        b"Number of Affected Workers\n"
        b'Junk Co,2026-04-22,"Pure Fitness - 125th 301 W 125th St New York, NY, 10027",1\n'
        b'Clean Co,2026-04-22,"420 Park Ave S  New York, NY, 10016",2\n'
    )
    junk, clean = get_scraper("NY").parse(csv)
    assert junk.city == "St New York"  # unchanged: it is hashed into notice_id
    assert junk.location_city == "New York"
    assert clean.city == "New York"
    assert clean.location_city is None


def test_new_row_lands_on_corrected_location(db):
    row = _ny_row("Pure Fitness - 125th 301 W 125th St New York, NY, 10027")
    upsert_notices(db, [row])
    db.commit()
    n = db.get(Notice, notice_id(row))
    assert (n.location.city, n.location.zip) == ("New York", "10027")


def test_relink_moves_legacy_ny_notice_and_is_idempotent(db):
    row = _ny_row("Pure Fitness - 125th 301 W 125th St New York, NY, 10027")
    # As ingested before this fix: location city = the legacy junk city.
    junk = Location(state="NY", city="St New York", zip="10027", county="New York")
    db.add(junk)
    db.flush()
    db.add(Notice(notice_id=notice_id(row), state="NY", employer=row.employer,
                  notice_date=row.notice_date, address=row.address, location_id=junk.id))
    db.commit()

    # A re-scrape alone can't move it: location_id is first-non-null-wins.
    upsert_notices(db, [row])
    db.commit()
    assert db.get(Notice, notice_id(row)).location.city == "St New York"

    assert relink_cities(db, "NY") == {"considered": 1, "relinked": 1, "no_city": 0}
    db.commit()
    n = db.get(Notice, notice_id(row))
    assert (n.location.city, n.location.zip, n.location.county) == (
        "New York", "10027", "New York"
    )
    assert db.query(Notice).count() == 1  # nothing re-keyed or duplicated
    assert relink_cities(db, "NY") == {"considered": 0, "relinked": 0, "no_city": 0}


def test_relink_leaves_unconfident_ny_city_alone(db):
    address = "6515 Transit Road Suite 26 Xyzzyville, NY, 14026"
    loc = Location(state="NY", city="Xyzzyville", zip="14026")
    db.add(loc)
    db.flush()
    db.add(Notice(notice_id="ny-x", state="NY", employer="Acme",
                  notice_date=date(2026, 1, 2), address=address, location_id=loc.id))
    db.commit()
    assert relink_cities(db, "NY") == {"considered": 0, "relinked": 0, "no_city": 1}
    assert db.get(Notice, "ny-x").location_id == loc.id
