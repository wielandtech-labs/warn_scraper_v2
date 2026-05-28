"""Batch processor: find unenriched companies, run the agent, persist results."""
from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from warn_v2.db.models import Company, Notice
from warn_v2.enrichment.agent import (
    EnrichmentContext,
    EnrichmentResult,
    LLMClient,
    result_to_confidence_decimal,
    run_enrichment,
)

log = logging.getLogger(__name__)


def find_pending(
    session: Session,
    *,
    limit: int = 50,
    state_filter: str | None = None,
    rerun_below: float | None = None,
) -> list[Company]:
    """Return companies that need enrichment.

    Selects companies with `enriched_at IS NULL`.  If `rerun_below` is set,
    also includes companies whose `enrichment_confidence < rerun_below`.
    If `state_filter` is given, only companies that have at least one notice
    for that state are returned.
    """
    stmt = select(Company)

    if rerun_below is not None:
        from sqlalchemy import or_

        stmt = stmt.where(
            or_(
                Company.enriched_at.is_(None),
                Company.enrichment_confidence < Decimal(str(rerun_below)),
            )
        )
    else:
        stmt = stmt.where(Company.enriched_at.is_(None))

    if state_filter:
        state_upper = state_filter.upper()
        stmt = stmt.where(
            Company.id.in_(
                select(Notice.company_id).where(
                    Notice.state == state_upper,
                    Notice.company_id.is_not(None),
                )
            )
        )

    stmt = stmt.limit(limit)
    return list(session.scalars(stmt))


def _load_notice_context(session: Session, company_id: int) -> list[dict]:
    """Return up to 5 recent notices for a company, for disambiguation."""
    rows = session.execute(
        select(
            Notice.state,
            Notice.company_id,
            Notice.layoff_count,
            Notice.notice_date,
        )
        .where(Notice.company_id == company_id)
        .order_by(Notice.notice_date.desc())
        .limit(5)
    ).all()

    result = []
    for row in rows:
        entry: dict = {"state": row.state}
        if row.layoff_count is not None:
            entry["layoff_count"] = row.layoff_count
        if row.notice_date is not None:
            entry["notice_date"] = row.notice_date.isoformat()
        result.append(entry)
    return result


def _persist_result(session: Session, company: Company, result: EnrichmentResult) -> None:
    """Write enrichment findings back to the Company row and commit."""
    company.website = result.website
    company.sic_code = result.sic_code
    company.sic_desc = result.sic_desc
    company.duns = result.duns
    company.enrichment_confidence = result_to_confidence_decimal(result)
    company.enrichment_sources = json.dumps(result.sources) if result.sources else None
    company.enriched_at = datetime.now(UTC)
    session.add(company)
    session.commit()


def enrich_batch(
    session: Session,
    client: LLMClient,
    *,
    limit: int = 50,
    state_filter: str | None = None,
    rerun_below: float | None = None,
    dry_run: bool = False,
) -> dict:
    """Enrich a batch of companies. Returns summary stats.

    Commits after each company so partial runs are safe.
    In dry_run mode the agent still runs but nothing is written to the DB.
    """
    companies = find_pending(
        session,
        limit=limit,
        state_filter=state_filter,
        rerun_below=rerun_below,
    )
    if not companies:
        log.info("enrich_batch: no pending companies found")
        return {"total": 0, "enriched": 0, "skipped": 0}

    log.info("enrich_batch: found %d company/companies to enrich", len(companies))
    enriched = 0
    skipped = 0

    for company in companies:
        notice_ctx = _load_notice_context(session, company.id)
        ctx = EnrichmentContext(
            company_id=company.id,
            company_name=company.name,
            notices=notice_ctx,
        )

        try:
            result = run_enrichment(ctx, client)
        except Exception:
            log.exception("enrichment failed for company_id=%d name=%r", company.id, company.name)
            skipped += 1
            continue

        if not result.proposed:
            log.warning(
                "company_id=%d name=%r: agent did not finalize (%d turns, msg=%r)",
                company.id,
                company.name,
                result.turns,
                result.last_message,
            )
            skipped += 1
            continue

        log.info(
            "company_id=%d name=%r: confidence=%.2f website=%r sic=%r",
            company.id,
            company.name,
            result.confidence,
            result.website,
            result.sic_code,
        )

        if not dry_run:
            _persist_result(session, company, result)
        enriched += 1

    return {"total": len(companies), "enriched": enriched, "skipped": skipped}
