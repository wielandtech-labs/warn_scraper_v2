"""City from comma-less "<street> <City> <ST> <zip>" addresses (CA EDD since ~2022).

The city goes on the *location* only, never into notice_id, so existing rows
are relinked by ``relink-cities`` instead of being re-keyed into duplicates.
"""
from __future__ import annotations

from datetime import date

import pytest

from warn_v2.db.models import Location, Notice
from warn_v2.geo import city_centroids
from warn_v2.geo.city_centroids import city_from_address_tail
from warn_v2.pipeline.dedup import notice_id
from warn_v2.pipeline.storage import upsert_notices
from warn_v2.scrapers.base import NoticeRow
from warn_v2.scripts.relink_cities import relink_cities


@pytest.fixture(autouse=True)
def _seed_places():
    city_centroids.reload_for_testing({
        "CA|palmdale": (34.58, -118.12),
        "CA|san francisco": (37.77, -122.42),
        "CA|south san francisco": (37.65, -122.42),
        "CA|santa fe springs": (33.93, -118.06),
    })
    yield
    city_centroids.reload_for_testing({})


@pytest.mark.parametrize(
    ("address", "city"),
    [
        ("732 W Rancho Vista Blvd Palmdale CA 93551", "Palmdale"),
        ("181 Oyster Point Blvd. South San Francisco CA 94080", "South San Francisco"),
        ("415 Mission Street  San Francisco CA 94105-2533", "San Francisco"),
        ("13443 E. FREEWAY DRIVE, SANTA FE SPRINGS, CA 90670", "Santa Fe Springs"),
        ("11798 Foothill Blvd. Sylmar CA 91342", None),  # not a Census place
        ("47400 Kato Road Fremotn CA 94538", None),  # source typo
        ("415 Mission Street San Francisco", None),  # no "<ST> <zip>" tail
        (None, None),
    ],
)
def test_city_from_address_tail(address, city):
    assert city_from_address_tail("CA", address) == city


def test_other_state_code_does_not_match():
    assert city_from_address_tail("NV", "732 W Rancho Vista Blvd Palmdale CA 93551") is None


def _ca_row(address: str, **kw) -> NoticeRow:
    base = {
        "state": "CA",
        "employer": "Acme",
        "notice_date": date(2025, 3, 3),
        "layoff_count": 50,
        "zip": "93551",
        "county": "Los Angeles County",
        "address": address,
    }
    base.update(kw)
    return NoticeRow(**base)


def test_new_row_gets_city_on_location_without_rekey(db):
    row = _ca_row("732 W Rancho Vista Blvd Palmdale CA 93551")
    upsert_notices(db, [row])
    db.commit()
    notice = db.query(Notice).one()
    assert notice.notice_id == notice_id(row)  # hashed from the city-less row
    assert notice.location.city == "Palmdale"
    assert notice.location.zip == "93551"


def _legacy_citiless(db, row: NoticeRow) -> Notice:
    """A notice as stored before the address-tail rule: on a city-less location."""
    loc = Location(state="CA", city=None, zip=row.zip, county=row.county, lat=34.6, lon=-118.1)
    db.add(loc)
    db.flush()
    n = Notice(
        notice_id=notice_id(row),
        state="CA",
        employer=row.employer,
        notice_date=row.notice_date,
        layoff_count=row.layoff_count,
        address=row.address,
        location_id=loc.id,
    )
    db.add(n)
    db.commit()
    return n


def test_relink_moves_citiless_notice_and_is_idempotent(db):
    row = _ca_row("732 W Rancho Vista Blvd Palmdale CA 93551")
    n = _legacy_citiless(db, row)
    old_id = n.notice_id

    stats = relink_cities(db, "ca")
    db.commit()
    assert stats == {"considered": 1, "relinked": 1, "no_city": 0}
    n = db.get(Notice, old_id)
    assert (n.location.city, n.location.zip, n.location.county) == (
        "Palmdale", "93551", "Los Angeles County"
    )
    assert db.query(Notice).count() == 1  # nothing re-keyed or duplicated

    # A re-scrape of the same row now lands on the same notice and location.
    upsert_notices(db, [row])
    db.commit()
    assert db.query(Notice).count() == 1

    assert relink_cities(db, "CA") == {"considered": 0, "relinked": 0, "no_city": 0}


def test_relink_leaves_unmatched_addresses_alone(db):
    n = _legacy_citiless(db, _ca_row("11798 Foothill Blvd. Sylmar CA 91342", zip="91342"))
    loc_id = n.location_id
    assert relink_cities(db, "CA") == {"considered": 1, "relinked": 0, "no_city": 1}
    assert db.get(Notice, n.notice_id).location_id == loc_id


def test_relink_notice_without_location_takes_zip_from_address(db):
    row = _ca_row("181 Oyster Point Blvd. South San Francisco CA 94080", zip=None, county=None)
    db.add(Notice(
        notice_id=notice_id(row), state="CA", employer=row.employer,
        notice_date=row.notice_date, address=row.address, location_id=None,
    ))
    db.commit()
    assert relink_cities(db, "CA") == {"considered": 1, "relinked": 1, "no_city": 0}
    loc = db.get(Notice, notice_id(row)).location
    assert (loc.city, loc.zip) == ("South San Francisco", "94080")


def test_rule_is_limited_to_relinked_states(db):
    city_centroids.reload_for_testing({"NV|reno": (39.5, -119.8)})
    row = NoticeRow(
        state="NV", employer="Acme", notice_date=date(2025, 3, 3), zip="89501",
        county="Washoe County", address="1 Virginia St Reno NV 89501",
    )
    upsert_notices(db, [row])
    db.commit()
    assert db.query(Notice).one().location.city is None


def test_relink_refuses_states_without_the_storage_rule(db):
    with pytest.raises(ValueError, match="NV"):
        relink_cities(db, "NV")
