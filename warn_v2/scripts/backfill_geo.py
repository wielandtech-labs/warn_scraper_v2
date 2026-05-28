"""One-off backfill: populate ``locations.lat/lon`` for rows missing it.

Iterates over every Location with a non-empty ZIP and NULL lat/lon, looks
up the centroid in ``warn_v2.geo.zip_centroids``, and writes it back.

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

from warn_v2.db.models import Location
from warn_v2.db.session import session_scope
from warn_v2.geo.zip_centroids import lookup_decimal

log = logging.getLogger(__name__)


def backfill(*, dry_run: bool = False, batch_size: int = 500) -> dict[str, int]:
    """Run the backfill; returns a stats dict.

    ``dry_run=True`` skips the commit so you can preview the impact.
    """
    stats = {"considered": 0, "filled": 0, "no_centroid": 0}

    with session_scope() as session:
        stmt = (
            select(Location)
            .where(
                Location.zip.is_not(None),
                Location.zip != "",
                or_(Location.lat.is_(None), Location.lon.is_(None)),
            )
        )
        results = session.scalars(stmt).all()
        stats["considered"] = len(results)
        log.info("Found %d locations to consider", stats["considered"])

        for i, loc in enumerate(results, start=1):
            pair = lookup_decimal(loc.zip)
            if pair is None:
                stats["no_centroid"] += 1
                continue
            loc.lat, loc.lon = pair
            stats["filled"] += 1
            if i % batch_size == 0:
                if not dry_run:
                    session.flush()
                log.info("Progress: %d / %d", i, stats["considered"])

        if dry_run:
            session.rollback()
            log.info("Dry run — rolling back, no changes written.")
        else:
            session.commit()

    log.info("Done: filled=%d, no_centroid=%d, total=%d",
             stats["filled"], stats["no_centroid"], stats["considered"])
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
