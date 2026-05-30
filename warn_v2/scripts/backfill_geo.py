"""Populate or upgrade ``locations.lat/lon`` using the best available source.

Geocoding priority per location:
  1. Street address from an associated Notice — most precise (Census geocoder).
  2. ZIP centroid — fast local lookup, city-block-level accuracy.
  3. City centroid — approximate, for city-only records.

Two modes:
  Default  — only targets locations where lat OR lon is NULL.
  --rerun-address — also re-geocodes locations that already have coordinates
    but have an associated notice with a street address, upgrading them from
    ZIP/city-centroid accuracy to Census street-level accuracy.

Run via:
  warn-v2 backfill-geo
  warn-v2 backfill-geo --rerun-address
  warn-v2 backfill-geo --dry-run
"""
from __future__ import annotations

import argparse
import logging
import sys

from sqlalchemy import exists, func, or_, select

from warn_v2.db.models import Location, Notice
from warn_v2.db.session import session_scope
from warn_v2.geo.geocoder import geocode

log = logging.getLogger(__name__)


def backfill(
    *,
    dry_run: bool = False,
    rerun_address: bool = False,
    state_filter: str | None = None,
    batch_size: int = 100,
) -> dict[str, int]:
    """Run the backfill; returns a stats dict.

    ``dry_run=True`` skips the commit so you can preview the impact.
    ``rerun_address=True`` also re-geocodes locations that already have
    coordinates but have a linked notice with a street address — upgrading
    from ZIP/city-centroid to Census street-level accuracy.
    """
    stats = {
        "considered": 0,
        "upgraded_address": 0,   # had coords, now Census-geocoded from address
        "filled_address": 0,     # was NULL, filled via Census geocoder
        "filled_zip": 0,         # was NULL, filled via ZIP/city centroid
        "no_coords": 0,
        "skipped_no_address": 0, # rerun mode: had coords, no address available
    }

    with session_scope() as session:
        if rerun_address:
            # Locations that have at least one associated notice with an address.
            # Includes those already geocoded (we'll upgrade them).
            has_address = exists().where(
                Notice.location_id == Location.id,
                Notice.address.is_not(None),
                Notice.address != "",
            )
            stmt = select(Location).where(has_address)
            if state_filter:
                stmt = stmt.where(Location.state == state_filter.upper())
            log.info(
                "Mode: --rerun-address — re-geocoding locations "
                "linked to a notice with a street address%s",
                f" (state={state_filter.upper()})" if state_filter else "",
            )
        else:
            # Default: only locations missing coordinates.
            stmt = select(Location).where(
                or_(Location.lat.is_(None), Location.lon.is_(None)),
            )
            if state_filter:
                stmt = stmt.where(Location.state == state_filter.upper())

        total = session.scalar(select(func.count()).select_from(stmt.subquery())) or 0
        stats["considered"] = total
        log.info("Found %d locations to process", total)

        # Defer _census_geocode import once rather than inside the hot loop.
        from warn_v2.geo.geocoder import _census_geocode  # type: ignore[attr-defined]

        for i, loc in enumerate(
            session.scalars(stmt.execution_options(yield_per=batch_size)), start=1
        ):
            # Find the most recent associated notice with a street address.
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
            had_coords = loc.lat is not None and loc.lon is not None

            # Use try/finally so the expunge at the end always runs — even on
            # early `continue` paths — preventing identity-map memory growth.
            try:
                if rerun_address and not address:
                    # Should not happen given the query filter, but guard anyway.
                    stats["skipped_no_address"] += 1
                    continue

                if rerun_address and address:
                    # Only call Census geocoder (Tier 1) — skip ZIP/city fallback.
                    # If Census can't resolve the address we keep existing coords.
                    pair = _census_geocode(address, loc.city, loc.state, loc.zip)
                    if pair is None:
                        log.debug(
                            "Census geocoder returned nothing for location %d "
                            "(address=%r) — keeping existing coords",
                            loc.id, address,
                        )
                        stats["skipped_no_address"] += 1
                        continue
                else:
                    pair = geocode(address, loc.city, loc.state, loc.zip)

                if pair is None:
                    stats["no_coords"] += 1
                    log.debug(
                        "No coordinates for location %d (city=%r zip=%r address=%r)",
                        loc.id, loc.city, loc.zip, address,
                    )
                    continue

                loc.lat, loc.lon = pair
                # Flush this individual change *before* the finally-block expunge
                # so pending writes aren't silently discarded on expunge.
                if not dry_run:
                    session.flush()

                if rerun_address and had_coords:
                    stats["upgraded_address"] += 1
                    log.debug(
                        "Upgraded location %d from centroid to Census: %r → (%.4f, %.4f)",
                        loc.id, address, loc.lat, loc.lon,
                    )
                elif address and notice_with_address:
                    stats["filled_address"] += 1
                    log.debug(
                        "Address geocoded location %d: %r → (%.4f, %.4f)",
                        loc.id, address, loc.lat, loc.lon,
                    )
                else:
                    stats["filled_zip"] += 1

            finally:
                # Always expunge processed objects so the SQLAlchemy identity
                # map stays bounded regardless of dataset size.
                if notice_with_address is not None:
                    session.expunge(notice_with_address)
                session.expunge(loc)

            if i % batch_size == 0:
                log.info(
                    "Progress: %d / %d (upgraded=%d filled_addr=%d "
                    "filled_zip=%d no_coords=%d)",
                    i, stats["considered"],
                    stats["upgraded_address"], stats["filled_address"],
                    stats["filled_zip"], stats["no_coords"],
                )

        if dry_run:
            session.rollback()
            log.info("Dry run — rolling back, no changes written.")
        else:
            session.commit()

    log.info(
        "Done: upgraded=%d filled_address=%d filled_zip=%d "
        "no_coords=%d skipped_no_address=%d total=%d",
        stats["upgraded_address"], stats["filled_address"], stats["filled_zip"],
        stats["no_coords"], stats["skipped_no_address"], stats["considered"],
    )
    return stats


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true",
                        help="Compute updates but don't commit")
    parser.add_argument(
        "--rerun-address",
        action="store_true",
        help=(
            "Re-geocode locations that already have coordinates but have "
            "a linked notice with a street address (upgrades ZIP/city-centroid "
            "accuracy to Census street-level accuracy)"
        ),
    )
    parser.add_argument("--state", default=None,
                        help="Limit to one state abbreviation, e.g. AZ")
    args = parser.parse_args()
    backfill(dry_run=args.dry_run, rerun_address=args.rerun_address,
             state_filter=args.state)
    return 0


if __name__ == "__main__":
    sys.exit(main())
