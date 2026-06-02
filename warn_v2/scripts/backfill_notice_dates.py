"""Backfill notice_date for rows where it is in the future (clamp to scrape date).

A WARN notice is *filed* on a real past/present date, so a stored notice_date
that lies after the scrape date is wrong.  It happens when a source publishes
only the layoff/effective date and the scraper stores that as notice_date
(e.g. MI — see warn_v2.scrapers.states.mi).  New inserts are corrected at
storage time (warn_v2.pipeline.storage.upsert_notices); this script fixes rows
that were ingested before that guard existed.

For each affected notice: preserve the forward-looking date in effective_date
(only when effective_date is currently NULL — MI already carries it), then set
notice_date = scraped_at::date (the first-seen date).  The primary key
(notice_id) is a stored content hash and is NOT recomputed, so corrected rows
stay consistent with future re-scrapes, which still hash on the layoff date.

Usage::

    warn-v2 backfill-notice-dates --dry-run          # preview count
    warn-v2 backfill-notice-dates                    # commit all states
    warn-v2 backfill-notice-dates --state MI         # one state only
"""
from __future__ import annotations

import logging

from sqlalchemy import select

from warn_v2.db.models import Notice
from warn_v2.db.session import session_scope

log = logging.getLogger(__name__)


def backfill_notice_dates(
    *,
    dry_run: bool = True,
    state_filter: str | None = None,
) -> dict[str, int]:
    """Clamp future notice_date values to the scrape (first-seen) date.

    Targets notices where ``notice_date > scraped_at::date``.  Preserves the
    original forward-looking date in ``effective_date`` when that field is NULL.

    Returns ``{"updated": N}``.
    """
    stats: dict[str, int] = {"updated": 0}
    state = state_filter.upper() if state_filter else None

    with session_scope() as session:
        dialect = session.bind.dialect.name if session.bind is not None else ""

        if dialect == "postgresql":
            from sqlalchemy import text

            state_clause = "AND state = :state" if state else ""
            params: dict = {"state": state} if state else {}
            where = f"""
                WHERE notice_date IS NOT NULL
                  AND notice_date > scraped_at::date
                  {state_clause}
            """
            count: int = session.execute(
                text(f"SELECT count(*) FROM notices {where}"), params
            ).scalar_one()
            stats["updated"] = count
            _log_count(count, state)
            if count == 0 or dry_run:
                if dry_run and count:
                    log.info("Dry run — no changes written.")
                return stats

            # All RHS expressions reference the pre-update row, so COALESCE sees
            # the old notice_date before notice_date is reassigned.
            session.execute(
                text(f"""
                    UPDATE notices
                    SET    effective_date = COALESCE(effective_date, notice_date),
                           notice_date    = scraped_at::date
                    {where}
                """),
                params,
            )
            session.commit()
            log.info("Updated %d notice(s).", count)
            return stats

        # SQLite / test path: SQLite has no real DATE type, so a SQL cast of
        # scraped_at to DATE is unreliable.  Filter in Python instead.
        fetch_stmt = select(Notice).where(Notice.notice_date.is_not(None))
        if state:
            fetch_stmt = fetch_stmt.where(Notice.state == state)
        candidates = [
            n
            for n in session.execute(fetch_stmt).scalars().all()
            if n.notice_date > n.scraped_at.date()
        ]
        count = len(candidates)
        stats["updated"] = count
        _log_count(count, state)
        if count == 0 or dry_run:
            if dry_run and count:
                log.info("Dry run — no changes written.")
            return stats

        for notice in candidates:
            if notice.effective_date is None:
                notice.effective_date = notice.notice_date
            notice.notice_date = notice.scraped_at.date()

        session.commit()
        log.info("Updated %d notice(s).", count)

    return stats


def _log_count(count: int, state: str | None) -> None:
    log.info(
        "%d notice(s) have a future notice_date%s",
        count,
        f" for state {state}" if state else "",
    )
