"""Which notices are worth announcing, and haven't been yet on a platform."""
from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from warn_v2.db.models import Notice, NoticeSocialPost

# Discovered recently: the scrape that found it ran within this window.
SCRAPED_WITHIN = timedelta(hours=48)
# ...and filed recently. Backfills (backfill-historical, ingest-file) insert
# years-old notices with scraped_at=now, so scraped_at alone would announce a
# decade of history the first time a backfill lands.
FILED_WITHIN = timedelta(days=30)


def select_candidates(
    db: Session,
    *,
    now: datetime,
    platform: str,
    min_layoffs: int,
    limit: int,
) -> list[Notice]:
    """Largest-first notices with at least `min_layoffs` workers, discovered and
    filed recently, not superseded, not Non-WARN, and not yet posted on
    `platform`."""
    already = select(NoticeSocialPost.notice_id).where(NoticeSocialPost.platform == platform)
    stmt = (
        select(Notice)
        .options(selectinload(Notice.location))
        .where(
            Notice.layoff_count >= min_layoffs,
            Notice.is_superseded.is_(False),
            Notice.closure_category.is_distinct_from("Non-WARN"),
            Notice.scraped_at >= now - SCRAPED_WITHIN,
            Notice.notice_date >= (now - FILED_WITHIN).date(),
            Notice.notice_id.not_in(already),
        )
        .order_by(Notice.layoff_count.desc(), Notice.notice_id)
        .limit(limit)
    )
    return list(db.scalars(stmt))
