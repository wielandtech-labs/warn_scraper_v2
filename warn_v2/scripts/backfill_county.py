"""Populate ``locations.county`` by reverse-geocoding existing coordinates.

Most WARN sources don't publish a county column, so ``locations.county`` is
NULL outside the handful of states that do (KY, CA, MT, …) — which starves
the county-based features (e.g. /api/stats/county-impact).  This backfill
resolves the containing county for every location that already has
coordinates, via the Census ``geographies/coordinates`` endpoint (free, no
API key).  Lookups are memoized per coordinate pair, so the many locations
sharing a ZIP/city centroid cost one HTTP call each.

Locations without coordinates are skipped (there is nothing to reverse-look-up)
— run ``warn-v2 backfill-geo`` first to minimise those.

Going forward the live pipeline fills county at geocode time; this command is
a one-off for the existing stock (safe to re-run: it only fills NULLs).

``--repair-names`` instead repairs counties written by the first backfill,
which stored the Census BASENAME rather than the full NAME: "Baltimore city"
was stored as "Baltimore" (colliding with Baltimore County's employment key)
and CT's "Capitol Planning Region" as "Capitol" (matching no key at all).
Only rows carrying that exact fingerprint AND whose normalized employment key
would change are rewritten — cosmetic diffs ("Sedgwick" vs "Sedgwick County"
normalize identically) and scraper-provided values are left alone.

Run via:
  warn-v2 backfill-county
  warn-v2 backfill-county --dry-run
  warn-v2 backfill-county --state TX
  warn-v2 backfill-county --repair-names
"""
from __future__ import annotations

import argparse
import logging
import sys

from sqlalchemy import and_, func, or_, select, true

from warn_v2.db.models import Location
from warn_v2.db.session import session_scope
from warn_v2.geo import county_employment, geocoder

log = logging.getLogger(__name__)


def backfill_county(
    *,
    dry_run: bool = False,
    state_filter: str | None = None,
    batch_size: int = 100,
) -> dict[str, int]:
    """Fill NULL ``Location.county`` from coordinates; returns a stats dict.

    ``dry_run=True`` skips the commit so you can preview the impact.
    Never overwrites an existing county (scraper/enricher values win).
    """
    stats = {
        "considered": 0,
        "filled": 0,
        "no_match": 0,
        "skipped_no_coords": 0,
    }

    with session_scope() as session:
        missing_county = Location.county.is_(None)
        has_coords = and_(Location.lat.is_not(None), Location.lon.is_not(None))
        state_clause = (
            Location.state == state_filter.upper() if state_filter else true()
        )

        stats["skipped_no_coords"] = session.scalar(
            select(func.count()).select_from(Location).where(
                missing_county,
                or_(Location.lat.is_(None), Location.lon.is_(None)),
                state_clause,
            )
        ) or 0

        stmt = select(Location).where(missing_county, has_coords, state_clause)
        total = session.scalar(select(func.count()).select_from(stmt.subquery())) or 0
        stats["considered"] = total
        log.info(
            "Found %d locations missing county with coordinates "
            "(%d more lack coordinates — run backfill-geo first)",
            total, stats["skipped_no_coords"],
        )

        for i, loc in enumerate(
            session.scalars(stmt.execution_options(yield_per=batch_size)), start=1
        ):
            try:
                county = geocoder.county_from_coords(loc.lat, loc.lon, loc.state)
                if county is None:
                    stats["no_match"] += 1
                    log.debug(
                        "No county for location %d (%s, %.4f, %.4f)",
                        loc.id, loc.state, loc.lat, loc.lon,
                    )
                    continue
                loc.county = county
                stats["filled"] += 1
                # Flush this individual change *before* the finally-block expunge
                # so pending writes aren't silently discarded on expunge.
                if not dry_run:
                    session.flush()
            finally:
                # Always expunge processed objects so the SQLAlchemy identity
                # map stays bounded regardless of dataset size.
                session.expunge(loc)

            if i % batch_size == 0:
                log.info(
                    "Progress: %d / %d (filled=%d no_match=%d)",
                    i, stats["considered"], stats["filled"], stats["no_match"],
                )

        if dry_run:
            session.rollback()
            log.info("Dry run — rolling back, no changes written.")
        else:
            session.commit()

    log.info(
        "Done: filled=%d no_match=%d skipped_no_coords=%d total=%d",
        stats["filled"], stats["no_match"],
        stats["skipped_no_coords"], stats["considered"],
    )
    return stats


def repair_county_names(
    *,
    dry_run: bool = False,
    state_filter: str | None = None,
    batch_size: int = 100,
) -> dict[str, int]:
    """Rewrite counties stored as bare Census BASENAMEs to the full NAME.

    For every coordinate-bearing location that has a county, re-resolve the
    county from the coordinates and overwrite only when BOTH hold:

    1. the stored value equals the reverse lookup's BASENAME — the exact
       fingerprint of what the pre-NAME code wrote for these coordinates, so
       scraper-provided counties that disagree with the lookup are untouched;
    2. the normalized employment key actually changes — so "Sedgwick" is NOT
       churned to "Sedgwick County" (identical after normalization), while
       "Baltimore" → "Baltimore city" and "Capitol" → "Capitol Planning
       Region" are repaired.
    """
    stats = {"considered": 0, "repaired": 0, "unchanged": 0, "no_match": 0}

    with session_scope() as session:
        stmt = select(Location).where(
            Location.county.is_not(None),
            Location.lat.is_not(None),
            Location.lon.is_not(None),
        )
        if state_filter:
            stmt = stmt.where(Location.state == state_filter.upper())

        total = session.scalar(select(func.count()).select_from(stmt.subquery())) or 0
        stats["considered"] = total
        log.info("Checking %d coordinate-bearing locations with a county", total)

        for i, loc in enumerate(
            session.scalars(stmt.execution_options(yield_per=batch_size)), start=1
        ):
            try:
                pair = geocoder._names_from_coords(loc.lat, loc.lon, loc.state)
                if pair is None:
                    stats["no_match"] += 1
                    continue
                name, basename = pair
                if (
                    loc.county != basename
                    or name == basename
                    or county_employment.normalize_key(loc.state, name)
                    == county_employment.normalize_key(loc.state, loc.county)
                ):
                    stats["unchanged"] += 1
                    continue
                log.info(
                    "location %d (%s): county %r → %r",
                    loc.id, loc.state, loc.county, name,
                )
                loc.county = name
                stats["repaired"] += 1
                if not dry_run:
                    session.flush()
            finally:
                session.expunge(loc)

            if i % batch_size == 0:
                log.info(
                    "Progress: %d / %d (repaired=%d unchanged=%d no_match=%d)",
                    i, stats["considered"],
                    stats["repaired"], stats["unchanged"], stats["no_match"],
                )

        if dry_run:
            session.rollback()
            log.info("Dry run — rolling back, no changes written.")
        else:
            session.commit()

    log.info(
        "repair-names done: repaired=%d unchanged=%d no_match=%d total=%d",
        stats["repaired"], stats["unchanged"], stats["no_match"], stats["considered"],
    )
    return stats


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true",
                        help="Compute updates but don't commit")
    parser.add_argument("--state", default=None,
                        help="Limit to one state abbreviation, e.g. AZ")
    parser.add_argument("--repair-names", action="store_true",
                        help="Rewrite bare-BASENAME counties to the full Census NAME")
    args = parser.parse_args()
    if args.repair_names:
        repair_county_names(dry_run=args.dry_run, state_filter=args.state)
    else:
        backfill_county(dry_run=args.dry_run, state_filter=args.state)
    return 0


if __name__ == "__main__":
    sys.exit(main())
