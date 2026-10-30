"""Relink city-less notices to a location carrying the city from their address.

One-shot repair for rows ingested before storage learned the address-tail
city rule (``geo.city_centroids.city_from_address_tail``): CA EDD writes
worksite addresses like "732 W Rancho Vista Blvd Palmdale CA 93551", so every
CA notice since ~2022 sits on a city-less (state, zip) location. Re-scraping
cannot fix them, because ``location_id`` is first-non-null-wins. This finds each
notice whose location has no city, derives the city from its address, and
points it at the (state, city, zip) location, creating one when needed.

``notice_id`` is untouched: the city lives on the location, not in the hash,
so nothing is re-keyed and no duplicates appear.

The new location is geocoded from its ZIP and county only (no street address),
so the run makes no Census calls; that is the same precision the shared
city-less ZIP location had. Locations left with no notices are not deleted.

Usage::

    warn-v2 relink-cities --state CA --dry-run
    warn-v2 relink-cities --state CA
"""
from __future__ import annotations

import logging

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from warn_v2.db.models import Location, Notice
from warn_v2.geo.city_centroids import city_from_address_tail
from warn_v2.pipeline.storage import _get_or_create_location
from warn_v2.scrapers._helpers import zip_from
from warn_v2.scrapers.base import NoticeRow

log = logging.getLogger(__name__)


def relink_cities(session: Session, state: str) -> dict[str, int]:
    """Relink ``state``'s city-less notices in ``session``; the caller commits.

    Returns counts: ``considered`` (city-less notices with an address),
    ``relinked``, and ``no_city`` (address tail matched no place).
    """
    state = state.upper()
    stats = {"considered": 0, "relinked": 0, "no_city": 0}
    notices = session.scalars(
        select(Notice)
        .outerjoin(Location, Notice.location_id == Location.id)
        .where(
            Notice.state == state,
            Notice.address.is_not(None),
            or_(Notice.location_id.is_(None), Location.city.is_(None)),
        )
        .order_by(Notice.notice_id)
    ).all()
    for notice in notices:
        stats["considered"] += 1
        city = city_from_address_tail(state, notice.address)
        if city is None:
            stats["no_city"] += 1
            continue
        old = notice.location
        row = NoticeRow(
            state=state,
            employer=notice.employer or "",
            city=city,
            zip=(old.zip if old else None) or zip_from(None, notice.address),
            county=old.county if old else None,
        )
        loc = _get_or_create_location(session, row)
        if loc is not None and loc.id != notice.location_id:
            notice.location = loc
            stats["relinked"] += 1
    session.flush()
    log.info("%s relink-cities: %s", state, stats)
    return stats
