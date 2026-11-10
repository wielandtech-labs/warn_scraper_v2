"""Which notices are worth announcing, and haven't been yet on a platform."""
from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session, aliased, contains_eager, selectinload

from warn_v2.db.models import Company, Notice, NoticeSocialPost
from warn_v2.social.format import MIN_INDUSTRY_CONFIDENCE

# Discovered recently: the scrape that found it ran within this window.
SCRAPED_WITHIN = timedelta(hours=48)
# ...and filed recently. Backfills (backfill-historical, ingest-file) insert
# years-old notices with scraped_at=now, so scraped_at alone would announce a
# decade of history the first time a backfill lands.
FILED_WITHIN = timedelta(days=30)
# A notice waits until its company has had a first enrichment attempt, so the
# post can carry the industry. The enricher runs every 6h; past this window
# the notice is posted without it, so a stalled enricher never silences alerts.
# Must stay well under SCRAPED_WITHIN or held notices would never post.
ENRICHMENT_WAIT = timedelta(hours=12)


def select_candidates(
    db: Session,
    *,
    now: datetime,
    platform: str,
    min_layoffs: int,
    limit: int,
) -> list[Notice]:
    """Largest-first notices with at least `min_layoffs` workers, discovered and
    filed recently, not superseded, not Non-WARN, not yet posted on `platform`,
    and past their company's first enrichment attempt (or ENRICHMENT_WAIT)."""
    canonical = aliased(Company)
    already = select(NoticeSocialPost.notice_id).where(NoticeSocialPost.platform == platform)
    stmt = (
        select(Notice)
        .outerjoin(Company, Notice.company_id == Company.id)
        .outerjoin(canonical, Company.canonical_company_id == canonical.id)
        .options(
            selectinload(Notice.location),
            contains_eager(Notice.company).selectinload(Company.canonical),
        )
        .where(
            Notice.layoff_count >= min_layoffs,
            Notice.is_superseded.is_(False),
            Notice.closure_category.is_distinct_from("Non-WARN"),
            Notice.scraped_at >= now - SCRAPED_WITHIN,
            Notice.notice_date >= (now - FILED_WITHIN).date(),
            Notice.notice_id.not_in(already),
            or_(
                Notice.company_id.is_(None),
                Company.naics_code.is_not(None),  # e.g. from the filing itself
                Company.enriched_at.is_not(None),
                # A merged dupe's canonical, when its label is one we'd post
                # (format._trusted_label; the "99" unclassified case aside).
                and_(
                    canonical.naics_code.is_not(None),
                    or_(
                        canonical.enrichment_confidence.is_(None),
                        canonical.enrichment_confidence >= MIN_INDUSTRY_CONFIDENCE,
                    ),
                ),
                Company.provider_attempted_at.is_not(None),
                Notice.scraped_at <= now - ENRICHMENT_WAIT,
            ),
        )
        .order_by(Notice.layoff_count.desc(), Notice.notice_id)
        .limit(limit)
    )
    return list(db.scalars(stmt))
