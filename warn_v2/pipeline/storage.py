"""Upsert NoticeRows into Postgres."""
from __future__ import annotations

from collections.abc import Iterable
from datetime import UTC, datetime

from sqlalchemy import func, or_, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from warn_v2.db.models import Company, Location, Notice
from warn_v2.pipeline.dedup import notice_id
from warn_v2.scrapers.base import NoticeRow

# Fields that should be COALESCE'd in on re-upsert: never overwrite an existing
# non-NULL value, but fill in when the existing row's column is NULL.  Identity
# fields (notice_id, state, employer, notice_date, scraped_at) and already-
# immutable metadata (source_url, raw_notice_url) are intentionally excluded.
_FILL_IN_FIELDS = (
    "address",
    "effective_date",
    "layoff_count",
    "closure_type",
    "location_id",
)


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
                field: func.coalesce(
                    getattr(Notice, field), getattr(stmt.excluded, field)
                )
                for field in _FILL_IN_FIELDS
            }
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
    """
    if not row.city and not row.zip:
        return None
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
            session.flush()
            return loc

    # 3. fall through to insert
    loc = Location(
        state=state,
        city=row.city,
        county=row.county,
        zip=incoming_zip,
    )
    session.add(loc)
    session.flush()
    return loc
