"""Upsert NoticeRows into Postgres."""
from __future__ import annotations

from collections.abc import Iterable
from datetime import UTC, datetime

from sqlalchemy import func, or_, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from warn_v2.db.models import Company, Location, Notice
from warn_v2.geo.geocoder import geocode as _geocode
from warn_v2.pipeline.dedup import notice_id
from warn_v2.scrapers.base import NoticeRow

# First non-null wins: once set, don't overwrite (geocoded location, address, type).
_FILL_IN_FIELDS: tuple[str, ...] = ("address", "closure_type", "location_id")

# Last non-null wins: amendments may update these fields, so prefer incoming value.
_UPDATE_FIELDS: tuple[str, ...] = ("layoff_count", "effective_date")


def upsert_notices(session: Session, rows: Iterable[NoticeRow]) -> tuple[int, int]:
    """Insert new notices; fill in nullable fields on existing rows.

    Returns ``(rows_seen, rows_new)``.  A notice is "new" iff its content-hash
    ``notice_id`` was absent before this call — re-upserts that only fill in
    previously-NULL fields don't bump the counter.

    On Postgres uses ``ON CONFLICT DO UPDATE`` with COALESCE semantics so that
    a re-scrape can backfill (e.g.) a newly-extracted ``address`` without
    overwriting any field the existing row already had.  On SQLite (used by
    tests) the same contract is implemented via SELECT-then-INSERT / fill-in.
    """
    seen = 0
    new = 0
    dialect = session.bind.dialect.name if session.bind is not None else ""
    now = datetime.now(UTC)

    for row in rows:
        seen += 1
        nid = notice_id(row)
        company = _get_or_create_company(session, row.employer)
        location = _get_or_create_location(session, row)

        payload = {
            "notice_id": nid,
            "state": row.state.upper(),
            "employer": row.employer,
            "notice_date": row.notice_date,
            "effective_date": row.effective_date,
            "layoff_count": row.layoff_count,
            "closure_type": row.closure_type,
            "address": row.address,
            "source_url": row.source_url,
            "raw_notice_url": row.raw_notice_url,
            "scraped_at": now,
            "company_id": company.id,
            "location_id": location.id if location else None,
        }

        # Pre-check to distinguish insert vs. fill-in update.  PG's
        # ON CONFLICT DO UPDATE returns rowcount=1 for both paths, so we
        # can't rely on it for the rows_new counter.
        existing = session.get(Notice, nid)

        if dialect == "postgresql":
            stmt = pg_insert(Notice).values(**payload)
            set_ = {
                f: func.coalesce(getattr(Notice, f), getattr(stmt.excluded, f))
                for f in _FILL_IN_FIELDS
            }
            set_.update({
                f: func.coalesce(getattr(stmt.excluded, f), getattr(Notice, f))
                for f in _UPDATE_FIELDS
            })
            stmt = stmt.on_conflict_do_update(
                index_elements=["notice_id"],
                set_=set_,
            )
            session.execute(stmt)
            if existing is None:
                new += 1
        else:
            if existing is None:
                session.add(Notice(**payload))
                new += 1
            else:
                for field in _FILL_IN_FIELDS:
                    if getattr(existing, field) is None:
                        new_val = payload.get(field)
                        if new_val is not None:
                            setattr(existing, field, new_val)
                for field in _UPDATE_FIELDS:
                    new_val = payload.get(field)
                    if new_val is not None:
                        setattr(existing, field, new_val)

    session.flush()
    return seen, new


def _get_or_create_company(session: Session, name: str) -> Company:
    stmt = select(Company).where(Company.name == name).limit(1)
    company = session.execute(stmt).scalar_one_or_none()
    if company is None:
        company = Company(name=name)
        session.add(company)
        session.flush()
    return company


def _zip_is_missing(col):
    """Filter expression matching a Location row with no usable ZIP."""
    return or_(col.is_(None), col == "")


def _get_or_create_location(session: Session, row: NoticeRow) -> Location | None:
    """Find or create the Location for this notice row.

    Backfill rule: when the row carries a non-empty zip but no exact match
    exists, and there's exactly one zip-less candidate for the same
    (state, city), update *that* row's zip in place rather than inserting a
    new one.  This preserves FKs from historical notices that were ingested
    before the scraper knew how to extract a ZIP.

    County-only path: states like KY and MT report only a county name (no
    city, no ZIP).  These notices get a Location keyed on (state, county)
    with county-centroid coordinates as a best-effort lat/lon.
    """
    if not row.city and not row.zip and not row.county:
        return None

    # County-only path: no city, no zip — only county is known.
    if not row.city and not row.zip and row.county:
        state = row.state.upper()
        existing = session.execute(
            select(Location).where(
                Location.state == state,
                Location.city.is_(None),
                Location.county == row.county,
            ).limit(1)
        ).scalar_one_or_none()
        if existing is not None:
            if existing.lat is None and existing.lon is None:
                pair = _geocode(None, None, state, None, row.county)
                if pair is not None:
                    existing.lat, existing.lon = pair
            return existing
        lat, lon = (None, None)
        pair = _geocode(None, None, state, None, row.county)
        if pair is not None:
            lat, lon = pair
        loc = Location(state=state, county=row.county, lat=lat, lon=lon)
        session.add(loc)
        session.flush()
        return loc
    state = row.state.upper()
    incoming_zip = row.zip or None  # normalize empty string → None

    # 1. exact match on (state, city, zip).  NULL == NULL is not true in SQL,
    # so branch on whether the row carries a zip.
    if incoming_zip:
        zip_filter = Location.zip == incoming_zip
    else:
        zip_filter = _zip_is_missing(Location.zip)
    exact = session.execute(
        select(Location).where(
            Location.state == state,
            Location.city == row.city,
            zip_filter,
        ).limit(1)
    ).scalar_one_or_none()
    if exact is not None:
        if row.county and not exact.county:
            exact.county = row.county
        # Backfill lat/lon if missing — try address first, ZIP centroid fallback.
        if exact.lat is None and exact.lon is None:
            pair = _geocode(row.address, row.city, row.state, exact.zip, row.county)
            if pair is not None:
                exact.lat, exact.lon = pair
        return exact

    # 2. promote a single zip-less candidate in place
    if incoming_zip:
        zipless = session.execute(
            select(Location).where(
                Location.state == state,
                Location.city == row.city,
                _zip_is_missing(Location.zip),
            )
        ).scalars().all()
        if len(zipless) == 1:
            loc = zipless[0]
            loc.zip = incoming_zip
            if row.county and not loc.county:
                loc.county = row.county
            if loc.lat is None and loc.lon is None:
                pair = _geocode(row.address, row.city, row.state, incoming_zip, row.county)
                if pair is not None:
                    loc.lat, loc.lon = pair
            session.flush()
            return loc

    # 3. fall through to insert
    lat, lon = (None, None)
    pair = _geocode(row.address, row.city, row.state, incoming_zip, row.county)
    if pair is not None:
        lat, lon = pair
    loc = Location(
        state=state,
        city=row.city,
        county=row.county,
        zip=incoming_zip,
        lat=lat,
        lon=lon,
    )
    session.add(loc)
    session.flush()
    return loc
