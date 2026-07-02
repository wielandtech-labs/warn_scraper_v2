"""Delete stored notices whose notice_date is impossible.

``pipeline.validate.filter_bad_dates`` drops rows dated before the WARN Act
(1988) or more than two years in the future at scrape time, but rows ingested
before that guard existed are still in the DB — e.g. Colorado's junk citizen
form submission dated 7/19/1957 (the 2021 CDLE sheet was an open Google Form).
The scrape-time guard means purged rows cannot come back.

Usage::

    warn-v2 purge-impossible-dates --dry-run     # preview (default in doubt)
    warn-v2 purge-impossible-dates               # delete for all states
    warn-v2 purge-impossible-dates --state CO
"""
from __future__ import annotations

import logging
from datetime import UTC, datetime

from sqlalchemy import delete, extract, or_, select

from warn_v2.db.models import Notice
from warn_v2.db.session import session_scope
from warn_v2.pipeline.validate import _MAX_NOTICE_YEAR_OFFSET, _MIN_NOTICE_YEAR

log = logging.getLogger(__name__)


def purge_impossible_dates(
    dry_run: bool = False, state_filter: str | None = None
) -> dict[str, int]:
    max_year = datetime.now(UTC).year + _MAX_NOTICE_YEAR_OFFSET
    impossible = or_(
        extract("year", Notice.notice_date) < _MIN_NOTICE_YEAR,
        extract("year", Notice.notice_date) > max_year,
    )
    with session_scope() as session:
        stmt = select(Notice).where(impossible)
        if state_filter:
            stmt = stmt.where(Notice.state == state_filter.upper())
        matches = session.execute(stmt).scalars().all()
        for n in matches:
            log.info(
                "%s %s | %s | %s | notice_date=%s",
                "would delete" if dry_run else "deleting",
                n.notice_id, n.state, n.employer, n.notice_date,
            )
        if not dry_run and matches:
            session.execute(
                delete(Notice).where(
                    Notice.notice_id.in_([n.notice_id for n in matches])
                )
            )
    return {"matched": len(matches), "deleted": 0 if dry_run else len(matches)}
