"""Backfill effective_date = notice_date + 60 days for notices that have none.

The WARN Act requires a minimum of 60 calendar days notice, so this is a
legally-grounded estimate for the handful of states whose source data omits
the effective date.

Historical notices ingested before the 60-day derivation was added to
NoticeRow.__post_init__ have a NULL effective_date.  This script fills them in
so the field is useful for filtering and reporting across the full dataset.

Usage::

    warn-v2 backfill-effective-dates --dry-run         # preview count
    warn-v2 backfill-effective-dates                   # commit all states
    warn-v2 backfill-effective-dates --state KY        # one state only
"""
from __future__ import annotations

import logging

from sqlalchemy import func, select, update

from warn_v2.db.models import Notice
from warn_v2.db.session import session_scope

log = logging.getLogger(__name__)

_OFFSET_DAYS = 60


def backfill_effective_dates(
    *,
    dry_run: bool = True,
    state_filter: str | None = None,
) -> dict[str, int]:
    """Set effective_date = notice_date + 60 days where effective_date IS NULL.

    Returns ``{"updated": N}``.
    """
    stats: dict[str, int] = {"updated": 0}

    with session_scope() as session:
        # Count first so we can report sensibly in both dry-run and live modes.
        count_stmt = select(func.count(Notice.notice_id)).where(
            Notice.effective_date.is_(None),
            Notice.notice_date.is_not(None),
        )
        if state_filter:
            count_stmt = count_stmt.where(Notice.state == state_filter.upper())
        count: int = session.execute(count_stmt).scalar_one()

        stats["updated"] = count
        log.info(
            "%d notice(s) have notice_date but no effective_date%s",
            count,
            f" for state {state_filter.upper()}" if state_filter else "",
        )

        if count == 0 or dry_run:
            if dry_run and count:
                log.info("Dry run — no changes written.")
            return stats

        # Postgres supports UPDATE … SET effective_date = notice_date + INTERVAL.
        # SQLite (tests) needs the same: both engines handle date arithmetic via
        # SQLAlchemy's func.date() + timedelta-style expression, but the cleanest
        # cross-engine approach is to use a Python-side loop for correctness.
        # For production (Postgres at scale) we use a single UPDATE statement.
        from sqlalchemy.engine import Connection  # noqa: PLC0415

        dialect = session.bind.dialect.name if session.bind is not None else ""

        if dialect == "postgresql":
            from sqlalchemy import text  # noqa: PLC0415

            state_clause = "AND state = :state" if state_filter else ""
            params: dict = {"state": state_filter.upper()} if state_filter else {}
            session.execute(
                text(f"""
                    UPDATE notices
                    SET    effective_date = notice_date + INTERVAL '{_OFFSET_DAYS} days'
                    WHERE  effective_date IS NULL
                      AND  notice_date IS NOT NULL
                      {state_clause}
                """),
                params,
            )
        else:
            # SQLite / test path: iterate and update row-by-row.
            from datetime import timedelta  # noqa: PLC0415

            fetch_stmt = select(Notice).where(
                Notice.effective_date.is_(None),
                Notice.notice_date.is_not(None),
            )
            if state_filter:
                fetch_stmt = fetch_stmt.where(Notice.state == state_filter.upper())
            notices = session.execute(fetch_stmt).scalars().all()
            for notice in notices:
                notice.effective_date = notice.notice_date + timedelta(days=_OFFSET_DAYS)

        session.commit()
        log.info("Updated %d notice(s).", count)

    return stats
