"""Batch processor: find unenriched companies, run the enrichment cascade, persist results.

Cascade (cheapest first):
  1. External provider plugin (ENRICHMENT_PROVIDER_MODULE env var) — richest data
  2. SEC EDGAR lookup — free, SIC code for public companies
  3. Claude Haiku — cheap fallback for website + any remaining gaps
"""
from __future__ import annotations

import json
import logging
import time
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from warn_v2.companies.normalize import (
    is_unsearchable,
    match_is_consistent,
    search_name,
)
from warn_v2.db.models import Company, Notice
from warn_v2.enrichment.agent import (
    EnrichmentContext,
    EnrichmentResult,
    LLMClient,
    result_to_confidence_decimal,
    run_enrichment,
)
from warn_v2.enrichment.provider import (
    EnrichmentProvider,
    ProviderResult,
    ProviderUnavailable,
)

log = logging.getLogger(__name__)


def find_pending(
    session: Session,
    *,
    limit: int = 50,
    state_filter: str | None = None,
    rerun_below: float | None = None,
    recent_years: int | None = None,
    provider_attempted: bool | None = None,
) -> list[Company]:
    """Return companies that need enrichment, highest-impact first.

    Selects companies with ``enriched_at IS NULL``.  If ``rerun_below`` is set,
    also includes companies whose ``enrichment_confidence < rerun_below``.
    If ``state_filter`` is given, only companies that have at least one notice
    for that state are returned.
    If ``recent_years`` is set, only companies that have at least one notice
    within the last N years are returned (focuses the backlog on active companies).
    ``provider_attempted`` filters on the D&B attempt stamp: ``False`` = only
    companies the provider hasn't tried yet (provider-only main flow), ``True``
    = only already-attempted ones (backup-tier runs), ``None`` = no filter.

    Companies are ordered by total **workers affected** across their
    (non-superseded) WARN notices, descending — so the scarce DUNS/provider
    lookups are spent on the biggest layoffs first.
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

    if provider_attempted is True:
        stmt = stmt.where(Company.provider_attempted_at.is_not(None))
    elif provider_attempted is False:
        stmt = stmt.where(Company.provider_attempted_at.is_(None))

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

    if recent_years is not None:
        cutoff = (datetime.now(UTC) - timedelta(days=recent_years * 365)).date()
        stmt = stmt.where(
            Company.id.in_(
                select(Notice.company_id).where(
                    Notice.company_id.is_not(None),
                    Notice.notice_date >= cutoff,
                )
            )
        )

    # Rank by total workers affected across the company's own (non-superseded)
    # notices. coalesce -> 0 sorts companies with no/blank layoff counts last.
    # Tie-break on id for a deterministic order across runs.
    affected = (
        select(func.coalesce(func.sum(Notice.layoff_count), 0))
        .where(
            Notice.company_id == Company.id,
            Notice.is_superseded.is_(False),
        )
        .correlate(Company)
        .scalar_subquery()
    )
    stmt = stmt.order_by(affected.desc(), Company.id)

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
    """Write Claude enrichment findings back to the Company row and commit."""
    company.website = result.website
    company.sic_code = result.sic_code
    company.sic_desc = result.sic_desc
    company.duns = result.duns
    company.enrichment_confidence = result_to_confidence_decimal(result)
    company.enrichment_sources = json.dumps(result.sources) if result.sources else None
    company.enrichment_source = "claude"
    company.enriched_at = datetime.now(UTC)
    session.add(company)
    session.commit()


def _persist_provider_result(
    session: Session, company: Company, result: ProviderResult
) -> None:
    """Write external provider findings back to the Company row and commit."""
    company.website = result.website
    company.sic_code = result.sic_code
    company.sic_desc = result.sic_desc
    company.duns = result.duns
    company.naics_code = result.naics_code
    company.naics_desc = result.naics_desc
    company.employee_count = result.employee_count
    company.parent_company_name = result.parent_company_name
    company.parent_duns = result.parent_duns
    company.global_ultimate_name = result.global_ultimate_name
    company.global_ultimate_duns = result.global_ultimate_duns
    company.global_ultimate_id = result.global_ultimate_id
    company.hq_address = result.hq_address
    company.enrichment_confidence = Decimal(str(round(result.confidence, 2)))
    company.enrichment_sources = json.dumps(result.sources) if result.sources else None
    company.enrichment_source = "provider"
    company.enriched_at = datetime.now(UTC)
    session.add(company)
    session.commit()


def _persist_lookup_result(
    session: Session, company: Company, sic_code: str, sic_desc: str | None,
    naics_code: str | None, naics_desc: str | None, confidence: float, sources: list[str],
) -> None:
    """Write EDGAR lookup findings back to the Company row and commit."""
    company.sic_code = sic_code
    company.sic_desc = sic_desc
    company.naics_code = naics_code
    company.naics_desc = naics_desc
    company.enrichment_confidence = Decimal(str(round(confidence, 2)))
    company.enrichment_sources = json.dumps(sources) if sources else None
    company.enrichment_source = "edgar"
    company.enriched_at = datetime.now(UTC)
    session.add(company)
    session.commit()


ALL_TIERS = frozenset({"provider", "edgar", "claude"})


def enrich_batch(
    session: Session,
    client: LLMClient,
    *,
    limit: int = 50,
    state_filter: str | None = None,
    rerun_below: float | None = None,
    dry_run: bool = False,
    inter_delay_s: float = 30.0,
    provider: EnrichmentProvider | None = None,
    recent_years: int | None = None,
    tiers: frozenset[str] | set[str] = ALL_TIERS,
) -> dict:
    """Enrich a batch of companies. Returns summary stats.

    Tiers (subset of {"provider", "edgar", "claude"}):
      1. ``provider.lookup()`` if a provider is configured — DUNS linkage,
         the main value. A provider MISS stamps ``provider_attempted_at`` and
         leaves the company unenriched (still queued, skipped on future
         provider-only runs) instead of falling through.
      2. EDGAR free lookup (SIC + approximate NAICS)
      3. Claude Haiku fallback (website + remaining gaps)

    Tier selection drives which companies are picked: a provider-only run
    takes companies the provider hasn't attempted; a run WITHOUT the provider
    tier (backup mode) takes only already-attempted ones, so the cheap tiers
    never preempt a company's one D&B shot.

    Commits after each company so partial runs are safe.
    In dry_run mode the agents still run but nothing is written to the DB.

    ``inter_delay_s`` (default 30 s) is the sleep inserted *between* companies
    to respect Anthropic token-per-minute limits.  Set to 0 in tests.
    """
    from warn_v2.enrichment.lookup import edgar_lookup

    tiers = frozenset(tiers)
    if tiers == {"provider"}:
        provider_attempted = False
    elif "provider" not in tiers:
        provider_attempted = True
    else:
        provider_attempted = None

    companies = find_pending(
        session,
        limit=limit,
        state_filter=state_filter,
        rerun_below=rerun_below,
        recent_years=recent_years,
        provider_attempted=provider_attempted,
    )
    if not companies:
        log.info("enrich_batch: no pending companies found")
        return {"total": 0, "enriched": 0, "skipped": 0, "provider": 0,
                "provider_miss": 0, "provider_rejected": 0, "edgar": 0, "claude": 0}

    log.info("enrich_batch: found %d company/companies to enrich", len(companies))
    enriched = 0
    skipped = 0
    stats_provider = 0
    stats_provider_miss = 0
    stats_provider_rejected = 0
    stats_edgar = 0
    stats_claude = 0
    # Once the provider signals it can't search (session trip, cap, cooldown),
    # every later company in this run would trip too — stop calling it.
    provider_ok = True

    for i, company in enumerate(companies):
        # Only apply the inter-company delay before Claude calls (free tiers are fast).
        notice_ctx = _load_notice_context(session, company.id)
        state = notice_ctx[0]["state"] if notice_ctx else None
        # Search with site designators stripped ("Google - Bordeaux" -> "Google");
        # exact-ish search tiers miss the raw WARN spelling entirely otherwise.
        query = search_name(company.name)
        if query != company.name:
            log.info("company_id=%d: search query %r (from %r)", company.id, query, company.name)

        # ------------------------------------------------------------------ #
        # Tier 1: external provider plugin
        # ------------------------------------------------------------------ #
        if "provider" in tiers and provider is not None and provider_ok:
            attempted = True
            if is_unsearchable(query):
                # Aggressive cleaning collapsed the name to a lone generic token
                # ("Alliance"); a lookup would only match by luck — treat as a miss.
                log.info(
                    "company_id=%d name=%r: query %r too generic to search; skipping provider",
                    company.id, company.name, query,
                )
                pr = None
            else:
                try:
                    pr = provider.lookup(query, state)
                except ProviderUnavailable as e:
                    # The provider could not actually search this company (session
                    # trip, cap, cooldown, transport error). Don't burn its one
                    # shot: leave it un-attempted so a healthy run retries it, and
                    # stop calling the provider for the rest of this run.
                    log.warning(
                        "company_id=%d name=%r: provider unavailable (%s); "
                        "pausing provider tier for this run",
                        company.id, company.name, e,
                    )
                    provider_ok = False
                    attempted = False
                    pr = None
                except Exception:
                    # An unexpected error is not evidence the company is absent —
                    # treat it like unavailability so we never burn the one shot.
                    log.exception(
                        "provider.lookup failed for company_id=%d name=%r; "
                        "pausing provider tier for this run",
                        company.id, company.name,
                    )
                    provider_ok = False
                    attempted = False
                    pr = None

            if attempted:
                if not dry_run:
                    # Stamp only a real attempt (hit or genuine miss) so
                    # provider-only runs drain the queue without retrying the
                    # same misses — but an unavailable provider above never
                    # reaches here, so a trip can't poison the queue.
                    company.provider_attempted_at = datetime.now(UTC)

                # Certainty guard: a heavily-stripped query can resolve to an
                # unrelated company. Only accept a hit that shares a distinctive
                # token with the ORIGINAL WARN name; otherwise reject (no DUNS).
                rejected = pr is not None and not match_is_consistent(
                    company.name, pr.entity_name
                )
                if rejected:
                    log.warning(
                        "company_id=%d name=%r: rejected provider match entity=%r conf=%.2f "
                        "(shares no distinctive token with original)",
                        company.id, company.name, pr.entity_name, pr.confidence,
                    )
                    pr = None

                if pr is not None:
                    log.info(
                        "company_id=%d name=%r: provider hit duns=%r sic=%r naics=%r conf=%.2f",
                        company.id, company.name, pr.duns, pr.sic_code, pr.naics_code, pr.confidence,
                    )
                    if not dry_run:
                        _persist_provider_result(session, company, pr)
                    enriched += 1
                    stats_provider += 1
                    continue

                if rejected:
                    stats_provider_rejected += 1
                else:
                    stats_provider_miss += 1
                if not dry_run:
                    session.commit()  # persist the miss stamp

            if not (tiers & {"edgar", "claude"}):
                # Provider-only main flow: leave unenriched for a later
                # backup-tier run rather than degrading to thin data. (Also the
                # path for an unavailable provider — the company stays queued.)
                continue

        # ------------------------------------------------------------------ #
        # Tier 2: EDGAR free lookup (SIC + approximate NAICS)
        # ------------------------------------------------------------------ #
        if "edgar" not in tiers:
            lr = None
        else:
            try:
                lr = edgar_lookup(query, state)
            except Exception:
                log.exception("edgar_lookup failed for company_id=%d name=%r",
                              company.id, company.name)
                lr = None

        if lr is not None:
            log.info(
                "company_id=%d name=%r: EDGAR hit entity=%r sic=%r naics=%r conf=%.2f",
                company.id, company.name, lr.entity_name, lr.sic_code, lr.naics_code, lr.confidence,
            )
            if not dry_run:
                _persist_lookup_result(
                    session, company,
                    sic_code=lr.sic_code,
                    sic_desc=lr.sic_desc,
                    naics_code=lr.naics_code,
                    naics_desc=lr.naics_desc,
                    confidence=lr.confidence,
                    sources=lr.sources,
                )
            enriched += 1
            stats_edgar += 1
            continue

        # ------------------------------------------------------------------ #
        # Tier 3: Claude Haiku fallback
        # ------------------------------------------------------------------ #
        if "claude" not in tiers:
            continue  # leave unenriched; claude is an explicit backup tier
        if i > 0 and inter_delay_s > 0:
            log.debug("enrich_batch: sleeping %.0fs before Claude call", inter_delay_s)
            time.sleep(inter_delay_s)

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
                company.id, company.name, result.turns, result.last_message,
            )
            skipped += 1
            continue

        log.info(
            "company_id=%d name=%r: claude conf=%.2f website=%r sic=%r",
            company.id, company.name, result.confidence, result.website, result.sic_code,
        )

        if not dry_run:
            _persist_result(session, company, result)
        enriched += 1
        stats_claude += 1

    return {
        "total": len(companies),
        "enriched": enriched,
        "skipped": skipped,
        "provider": stats_provider,
        "provider_miss": stats_provider_miss,
        "provider_rejected": stats_provider_rejected,
        "edgar": stats_edgar,
        "claude": stats_claude,
    }
