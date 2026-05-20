"""Upsert NoticeRows into Postgres."""
from __future__ import annotations

from collections.abc import Iterable
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from warn_v2.db.models import Company, Location, Notice
from warn_v2.pipeline.dedup import notice_id
from warn_v2.scrapers.base import NoticeRow


def upsert_notices(session: Session, rows: Iterable[NoticeRow]) -> tuple[int, int]:
    """Insert new notices; return (rows_seen, rows_new).

    Uses Postgres `ON CONFLICT DO NOTHING` keyed on the content-hash `notice_id`.
    On non-Postgres backends (SQLite for tests) falls back to a SELECT-then-INSERT
    so the contract is identical from the caller's perspective.
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
            "source_url": row.source_url,
            "raw_notice_url": row.raw_notice_url,
            "scraped_at": now,
            "company_id": company.id,
            "location_id": location.id if location else None,
        }

        if dialect == "postgresql":
            stmt = pg_insert(Notice).values(**payload).on_conflict_do_nothing(
                index_elements=["notice_id"]
            )
            result = session.execute(stmt)
            if result.rowcount:
                new += 1
        else:
            exists = session.get(Notice, nid)
            if exists is None:
                session.add(Notice(**payload))
                new += 1

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


def _get_or_create_location(session: Session, row: NoticeRow) -> Location | None:
    if not row.city and not row.zip:
        return None
    stmt = (
        select(Location)
        .where(
            Location.state == row.state.upper(),
            Location.city == row.city,
            Location.zip == row.zip,
        )
        .limit(1)
    )
    location = session.execute(stmt).scalar_one_or_none()
    if location is None:
        location = Location(
            state=row.state.upper(),
            city=row.city,
            county=row.county,
            zip=row.zip,
        )
        session.add(location)
        session.flush()
    return location
