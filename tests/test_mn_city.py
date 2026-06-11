"""MN wide-format city recovery (scrapers/mn_city) + storage integration."""
from __future__ import annotations

from datetime import date

import pytest

from warn_v2.db.models import Location, Notice
from warn_v2.geo import city_centroids
from warn_v2.pipeline.storage import upsert_notices
from warn_v2.scrapers.base import NoticeRow
from warn_v2.scrapers.mn_city import split_city_from_label


@pytest.fixture(autouse=True)
def _seed_mn_cities():
    # Seed the handful of MN cities used here; the suite elsewhere wipes the real
    # bundled gazetteer via reload_for_testing({}), so seed explicitly. "St." with
    # a period mirrors the real Census key.
    city_centroids.reload_for_testing({
        "MN|maple grove": (45.1128, -93.463),
        "MN|minneapolis": (44.9633, -93.2683),
        "MN|st. paul": (44.9489, -93.1041),
        "MN|south st. paul": (44.888, -93.0405),
        "MN|mendota heights": (44.8789, -93.1339),
        "MN|duluth": (46.7745, -92.1341),
    })
    yield
    city_centroids.reload_for_testing({})


@pytest.mark.parametrize(
    ("label", "expected"),
    [
        ("Upsher-Smith 2025 Maple Grove Manufacturing", "Maple Grove"),
        ("Veyer 2025 Minneapolis Warehousing", "Minneapolis"),
        # "St" normalized to the gazetteer's "St." form
        ("Transaxle St Paul St Paul Manufacturing", "St. Paul"),
        ("The Sportsman Guide Inc South St Paul Wholesale", "South St. Paul"),
        # multi-word industry stripped before the city match
        ("Acme Co Mendota Heights Health Care/Social Assist", "Mendota Heights"),
        # trailing city wins over a same-name token inside the company name
        ("David's Bridal Duluth 2023 Duluth Retail", "Duluth"),
        # out-of-state HQ the source lists -> not an MN city -> None
        ("Block 2024 San Francisco Information", None),
        ("", None),
        (None, None),
    ],
)
def test_split_city_from_label(label, expected):
    assert split_city_from_label(label) == expected


def test_mn_wide_format_storage(db):
    row = NoticeRow(
        state="MN",
        employer="Upsher-Smith 2025 Maple Grove Manufacturing",
        notice_date=date(2026, 1, 5),
    )
    upsert_notices(db, [row])
    db.commit()

    notice = db.query(Notice).one()
    assert notice.location_id is not None
    loc = db.query(Location).one()
    assert loc.state == "MN"
    assert loc.city == "Maple Grove"
    assert loc.lat is not None and loc.lon is not None


def test_mn_out_of_state_hq_stays_unlocated(db):
    row = NoticeRow(
        state="MN",
        employer="Block 2024 San Francisco Information",
        notice_date=date(2026, 1, 6),
    )
    upsert_notices(db, [row])
    db.commit()
    assert db.query(Notice).one().location_id is None
    assert db.query(Location).count() == 0


def test_mn_clean_format_city_unchanged(db):
    """When the scraper already supplies a city, the deriver is not consulted."""
    row = NoticeRow(
        state="MN",
        employer="Clean Co",
        city="Minneapolis",
        notice_date=date(2026, 1, 7),
    )
    upsert_notices(db, [row])
    db.commit()
    loc = db.query(Location).one()
    assert loc.city == "Minneapolis"
