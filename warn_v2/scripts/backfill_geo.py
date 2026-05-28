"""One-off backfill: populate ``locations.lat/lon`` for rows missing it.

Geocoding priority per location:
  1. Street address from an associated Notice — most precise (Census geocoder).
  2. ZIP centroid — fast local lookup, city-block-level accuracy.

Run via the same ``kubectl run`` pattern documented in the README for
Alembic migrations, swapping the command for ``warn-v2 backfill-geo``
(or directly: ``python -m warn_v2.scripts.backfill_geo``).

Idempotent — re-running only updates rows that are still NULL.
"""
from __future__ import annotations

import argparse
import logging
import sys

from sqlalchemy import or_, select

from warn_v2.db.models import Location, Notice
from warn_v2.db.session import session_scope
from warn_v2.geo.geocoder import geocode

log = logging.getLogger(__name__)


def backfill(*, dry_run: bool = False, batch_size: int = 100) -> dict[str, int]:
    """Run the backfill; returns a stats dict.

    ``dry_run=True`` skips the commit so you can preview the impact.
    """
    stats = {
        "considered": 0,
        "filled_address": 0,
        "filled_zip": 0,
        "no_coords": 0,
    }

    with session_scope() as session:
        # Locations with null lat or lon (regardless of whether they have a ZIP).
        stmt = select(Location).where(
            or_(Location.lat.is_(None), Location.lon.is_(None)),
        )
        results = session.scalars(stmt).all()
        stats["considered"] = len(results)
        log.info("Found %d locations with missing coordinates", stats["considered"])

        for i, loc in enumerate(results, start=1):
            # Find the most recent associated notice that carries a street address.
            notice_with_address = session.scalar(
                select(Notice)
                .where(
                    Notice.location_id == loc.id,
                    Notice.address.is_not(None),
                    Notice.address != "",
                )
                .order_by(Notice.notice_date.desc())
                .limit(1)
            )
            address = notice_with_address.address if notice_with_address else None

            pair = geocode(address, loc.city, loc.state, loc.zip)
            if pair is None:
                stats["no_coords"] += 1
                log.debug(
                    "No coordinates for location %d (city=%r zip=%r address=%r)",
                    loc.id, loc.city, loc.zip, address,
                )
                continue

            loc.lat, loc.lon = pair
            if address and notice_with_address:
                stats["filled_address"] += 1
                log.debug(
                    "Address geocoded location %d: %r → (%.4f, %.4f)",
                    loc.id, address, loc.lat, loc.lon,
                )
            else:
                stats["filled_zip"] += 1

            if i % batch_size == 0:
                if not dry_run:
                    session.flush()
                log.info(
                    "Progress: %d / %d (address=%d zip=%d no_coords=%d)",
                    i, stats["considered"],
                    stats["filled_address"], stats["filled_zip"], stats["no_coords"],
                )

        if dry_run:
            session.rollback()
            log.info("Dry run — rolling back, no changes written.")
        else:
            session.commit()

    log.info(
        "Done: filled_address=%d filled_zip=%d no_coords=%d total=%d",
        stats["filled_address"], stats["filled_zip"],
        stats["no_coords"], stats["considered"],
    )
    return stats


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true",
                        help="Compute updates but don't commit")
    args = parser.parse_args()
    backfill(dry_run=args.dry_run)
    return 0


if __name__ == "__main__":
    sys.exit(main())
