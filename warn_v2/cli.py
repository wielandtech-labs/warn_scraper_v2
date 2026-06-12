"""warn-v2 CLI."""
from __future__ import annotations

import logging
import sys
from pathlib import Path

import click

from warn_v2.pipeline.runner import run_state
from warn_v2.scrapers.registry import all_states, get_scraper


@click.group()
@click.option("--log-level", default="INFO")
def main(log_level: str) -> None:
    logging.basicConfig(
        level=log_level.upper(),
        format="%(asctime)s %(levelname)-5s %(name)s: %(message)s",
    )


@main.command()
@click.option("--state", required=True, help="State abbreviation, e.g. CA")
def scrape(state: str) -> None:
    """Run the scraper for one state against the live source and persist results."""
    scraper = get_scraper(state)
    run = run_state(scraper)
    click.echo(
        f"{run.state} status={run.status} rows={run.rows_scraped} new={run.rows_new}"
    )
    if run.status != "ok":
        sys.exit(1)


@main.command(name="scrape-all")
@click.option("--states", default=None, help="Comma-separated subset, e.g. CA,TX")
@click.option(
    "--tolerate",
    default=None,
    help=(
        "Comma-separated states whose failure should NOT fail the run "
        "(known-blocked or chronically-flaky sources, e.g. GA). They are still "
        "scraped and their ScraperRun row still records the failure; they just "
        "don't flip the job's exit code. Prevents one flaky state from marking "
        "every nightly Job as Failed (which churns CronJob history and pod logs)."
    ),
)
def scrape_all(states: str | None, tolerate: str | None) -> None:
    """Run all registered scrapers.

    Exits non-zero only if a *non-tolerated* state failed. Tolerated-state
    failures are reported on stderr but don't fail the run — sustained outages
    are caught by alerting off the scraper_runs table, not the job exit code.
    """
    targets = [s.strip().upper() for s in states.split(",")] if states else all_states()
    tolerated = {s.strip().upper() for s in tolerate.split(",")} if tolerate else set()
    failed: list[str] = []
    tolerated_failures: list[str] = []
    for state in targets:
        scraper = get_scraper(state)
        run = run_state(scraper)
        click.echo(
            f"{run.state} status={run.status} rows={run.rows_scraped} new={run.rows_new}"
        )
        if run.status != "ok":
            (tolerated_failures if run.state in tolerated else failed).append(run.state)
    if tolerated_failures:
        click.echo(
            f"tolerated failures (not failing run): {', '.join(tolerated_failures)}",
            err=True,
        )
    if failed:
        click.echo(f"failed: {', '.join(failed)}", err=True)
        sys.exit(1)


@main.command(name="list")
def list_states() -> None:
    """List registered state scrapers."""
    for s in all_states():
        click.echo(s)


@main.command()
@click.option("--state", default=None, help="State abbreviation to heal (e.g. CA)")
@click.option(
    "--all",
    "heal_all",
    is_flag=True,
    help="Heal every state that has a recent unhealed failure in the DB.",
)
@click.option(
    "--snapshot",
    "snapshot_path",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    help="Path to the failing snapshot. Defaults to looking up the latest failed run in the DB.",
)
@click.option("--error", default="", help="Error message to brief the agent with")
@click.option("--dry-run", is_flag=True, help="Run the agent but don't open a PR")
@click.option(
    "--max-turns",
    type=int,
    default=12,
    help="Max LLM turns before giving up",
)
def heal(
    state: str | None,
    heal_all: bool,
    snapshot_path: Path | None,
    error: str,
    dry_run: bool,
    max_turns: int,
) -> None:
    """Run the self-heal agent for one broken state scraper, or all candidates.

    \b
    Examples:
      warn-v2 heal --state IA           # heal IA using latest DB failure
      warn-v2 heal --state IA --snapshot ./snapshots/IA/snap.bin
      warn-v2 heal --all                # heal every state with a recent failure
      warn-v2 heal --all --dry-run      # rehearse without opening PRs
    """
    from warn_v2.db.session import session_scope
    from warn_v2.heal.agent import build_anthropic_client, run_heal
    from warn_v2.heal.detector import find_candidates
    from warn_v2.heal.github import PRPlan, open_pr
    from warn_v2.heal.tools import HealContext

    if not heal_all and not state:
        raise click.UsageError("Provide --state STATE or --all")
    if heal_all and state:
        raise click.UsageError("--all and --state are mutually exclusive")
    if heal_all and snapshot_path:
        raise click.UsageError("--snapshot cannot be combined with --all")

    client = build_anthropic_client()

    def _run_one(
        state_code: str, snap: Path, err: str
    ) -> bool:
        """Shared logic for healing a single state. Returns True if a PR was proposed."""
        scraper = get_scraper(state_code)
        ctx = HealContext(
            state=state_code.upper(),
            snapshot_path=snap,
            error=err or "(no error message supplied)",
            expected_row_range=scraper.expected_row_range,
            required_fields=scraper.required_fields,
        )
        result = run_heal(ctx, client, max_turns=max_turns)
        if not result.proposed:
            click.echo(f"[{state_code}] agent did not propose a patch ({result.turns} turns)")
            if result.last_message:
                click.echo(f"[{state_code}] final: {result.last_message}")
            return False
        plan = PRPlan(
            state=state_code.upper(),
            new_module_src=result.code or "",
            summary=result.summary or "self-heal patch",
            error=err,
            snapshot_path=snap,
            rows_after=result.rows_after,
        )
        pr = open_pr(plan, dry_run=dry_run)
        click.echo(f"[{state_code}] branch: {pr.branch}")
        click.echo(f"[{state_code}] pr:     {pr.url}")
        return True

    if heal_all:
        with session_scope() as session:
            candidates = find_candidates(session)
        if not candidates:
            click.echo("no recent failed runs found — nothing to heal")
            return
        click.echo(
            f"found {len(candidates)} candidate(s): "
            f"{', '.join(c.state for c in candidates)}"
        )
        failed: list[str] = []
        for cand in candidates:
            if not _run_one(cand.state, cand.snapshot_path, cand.error or ""):
                failed.append(cand.state)
        if failed:
            click.echo(f"no patch proposed for: {', '.join(failed)}", err=True)
            sys.exit(3)
        return

    # ---- single-state path ----
    assert state is not None  # guarded above
    if snapshot_path is None:
        with session_scope() as session:
            candidates = [c for c in find_candidates(session) if c.state == state.upper()]
        if not candidates:
            click.echo(f"no recent failed run found for {state}", err=True)
            sys.exit(2)
        snapshot_path = candidates[0].snapshot_path
        error = error or candidates[0].error

    if not _run_one(state, snapshot_path, error):
        sys.exit(3)


@main.command()
@click.option("--limit", default=10, show_default=True, help="Max companies to enrich per run")
@click.option("--state", default=None, help="Only enrich companies from this state's notices")
@click.option(
    "--rerun-below",
    type=float,
    default=None,
    metavar="CONFIDENCE",
    help="Also re-enrich companies whose confidence is below this threshold (e.g. 0.7)",
)
@click.option("--dry-run", is_flag=True, help="Run agents but do not write results to the DB")
@click.option(
    "--sleep-between",
    type=float,
    default=30.0,
    show_default=True,
    metavar="SECONDS",
    help="Seconds to sleep between Claude API calls (throttles TPM usage)",
)
@click.option(
    "--recent-years",
    type=int,
    default=None,
    metavar="N",
    help="Only enrich companies with notices in the last N years (e.g. 2)",
)
@click.option(
    "--tiers",
    default="provider",
    show_default=True,
    help=(
        "Comma-separated tiers to run: provider, edgar, claude. The default "
        "provider-only flow stamps misses and leaves them queued; run the "
        "cheap tiers explicitly as a backup pass (--tiers edgar,claude)."
    ),
)
def enrich(
    limit: int,
    state: str | None,
    rerun_below: float | None,
    dry_run: bool,
    sleep_between: float,
    recent_years: int | None,
    tiers: str,
) -> None:
    """Enrich company records — provider (D&B) first, DUNS linkage is the value.

    \b
    Main flow (default, what the CronJob runs):
      provider only. A miss stamps provider_attempted_at and leaves the
      company unenriched (still queued), so thin web data never blocks a
      future D&B match.
    Backup flow (explicit, run eventually for the leftovers):
      warn-v2 enrich --tiers edgar,claude — only touches companies the
      provider has already attempted.

    \b
    Examples:
      warn-v2 enrich                        # D&B-only on untried companies
      warn-v2 enrich --limit 200            # larger batch
      warn-v2 enrich --tiers edgar,claude   # backup pass over D&B misses
      warn-v2 enrich --tiers provider,edgar,claude  # old full cascade
      warn-v2 enrich --recent-years 2       # only companies with recent notices
      warn-v2 enrich --state CA             # only companies from CA notices
      warn-v2 enrich --dry-run              # test without writing to DB
    """
    from warn_v2.db.session import session_scope
    from warn_v2.enrichment.agent import build_anthropic_client
    from warn_v2.enrichment.provider import load_provider
    from warn_v2.enrichment.worker import ALL_TIERS, enrich_batch

    tier_set = frozenset(t.strip().lower() for t in tiers.split(",") if t.strip())
    invalid = tier_set - ALL_TIERS
    if invalid or not tier_set:
        click.echo(f"invalid --tiers (choose from {sorted(ALL_TIERS)}): {tiers!r}", err=True)
        sys.exit(1)

    provider = load_provider()
    if provider:
        click.echo("External enrichment provider loaded.")
    elif tier_set == {"provider"}:
        click.echo(
            "provider-only run but no ENRICHMENT_PROVIDER_MODULE configured — nothing to do",
            err=True,
        )
        sys.exit(1)
    else:
        click.echo("No external provider configured.")

    client = build_anthropic_client()
    try:
        with session_scope() as session:
            stats = enrich_batch(
                session,
                client,
                limit=limit,
                state_filter=state,
                rerun_below=rerun_below,
                dry_run=dry_run,
                inter_delay_s=sleep_between,
                provider=provider,
                recent_years=recent_years,
                tiers=tier_set,
            )
    finally:
        if provider:
            try:
                provider.close()
            except Exception:
                pass

    suffix = " (dry run — nothing written)" if dry_run else ""
    click.echo(
        f"enriched={stats['enriched']} "
        f"(provider={stats['provider']} edgar={stats['edgar']} claude={stats['claude']}) "
        f"provider_miss={stats['provider_miss']} "
        f"skipped={stats['skipped']} total={stats['total']}{suffix}"
    )
    # Provider misses are EXPECTED outcomes (stamped + left queued), not
    # failures — only genuine agent errors flip the exit code.
    if stats["skipped"] and not dry_run:
        sys.exit(1)


@main.command()
@click.option("--host", default="0.0.0.0", show_default=True, help="Bind host")
@click.option("--port", default=8000, show_default=True, help="Bind port")
@click.option("--reload", is_flag=True, help="Enable auto-reload (dev only)")
def serve(host: str, port: int, reload: bool) -> None:
    """Start the FastAPI HTTP server.

    This is the command run by the K8s api pod (args: [serve]).

    \b
    Examples:
      warn-v2 serve                       # production mode
      warn-v2 serve --reload              # dev mode with auto-reload
      warn-v2 serve --port 9000           # custom port
    """
    import uvicorn

    uvicorn.run("warn_v2.api:app", host=host, port=port, reload=reload)


@main.command("mark-superseded")
@click.option("--dry-run", is_flag=True, help="Preview matches without writing")
@click.option("--state", default=None, help="Limit to one state abbreviation, e.g. IA")
@click.option("--force", is_flag=True, help="Bypass the 20%% guardrail")
def mark_superseded_cmd(dry_run: bool, state: str | None, force: bool) -> None:
    """Flag duplicate/amended notices as superseded so totals are accurate.

    \b
    Detects two patterns:
      ZIP-variance: same notice, scraped with different ZIP → keep the one with address
      Amendment:    same employer/date/location, updated count → keep the newer one

    Always run with --dry-run first and review the output before committing.

    \b
    Examples:
      warn-v2 mark-superseded --dry-run           # preview all states
      warn-v2 mark-superseded --dry-run --state IA
      warn-v2 mark-superseded --state IA          # commit IA only
      warn-v2 mark-superseded --state IA --force  # override 20%% guardrail
    """
    from warn_v2.scripts.mark_superseded import mark_superseded

    stats = mark_superseded(dry_run=dry_run, state_filter=state, force=force)
    suffix = " (dry run — nothing written)" if dry_run else ""
    click.echo(f"marked={stats['marked']} skipped={stats['skipped']}{suffix}")


@main.command("consolidate-companies")
@click.option("--dry-run", is_flag=True, help="Preview merges without writing")
@click.option("--force", is_flag=True, help="Bypass the 50%% guardrail")
def consolidate_companies_cmd(dry_run: bool, force: bool) -> None:
    """Merge duplicate Company rows (DUNS-first, name-normalization fallback).

    \b
    Non-destructive: sets canonical_company_id on duplicates (never touches
    Notice.company_id or deletes rows), so it's fully reversible. Survivors also
    get a parent_group_key for sibling-under-parent rollup. Re-run safely as
    enrichment fills in more DUNS over time.

    Always run with --dry-run first and review the counts.
    """
    from warn_v2.scripts.consolidate_companies import consolidate_companies

    stats = consolidate_companies(dry_run=dry_run, force=force)
    suffix = " (dry run — nothing written)" if dry_run else ""
    if stats.get("aborted"):
        suffix = " (ABORTED by guardrail — re-run with --force)"
    click.echo(
        f"merged={stats['merged']} duns_groups={stats['duns_groups']} "
        f"name_groups={stats['name_groups']} total={stats['total']}{suffix}"
    )


@main.command("backfill-geo")
@click.option("--dry-run", is_flag=True, help="Preview impact without writing")
@click.option(
    "--rerun-address",
    is_flag=True,
    help=(
        "Also upgrade locations that already have coordinates but have a "
        "linked notice with a street address (ZIP/city centroid → Census accuracy)"
    ),
)
@click.option("--state", default=None, help="Limit to one state abbreviation, e.g. AZ")
def backfill_geo(dry_run: bool, rerun_address: bool, state: str | None) -> None:
    """Populate locations.lat/lon using address geocoding + ZIP centroid fallback.

    By default only targets locations where coordinates are NULL.
    Use --rerun-address to upgrade existing ZIP/city-centroid coordinates to
    Census street-level accuracy wherever a street address is now available.

    \b
    Examples:
      warn-v2 backfill-geo                   # fill NULLs only
      warn-v2 backfill-geo --rerun-address   # also upgrade existing centroids
      warn-v2 backfill-geo --dry-run         # preview without writing
    """
    from warn_v2.scripts.backfill_geo import backfill

    stats = backfill(dry_run=dry_run, rerun_address=rerun_address, state_filter=state)
    suffix = " (dry run — nothing written)" if dry_run else ""
    click.echo(
        f"considered={stats['considered']} "
        f"upgraded={stats['upgraded_address']} "
        f"filled_address={stats['filled_address']} filled_zip={stats['filled_zip']} "
        f"no_coords={stats['no_coords']}{suffix}"
    )


@main.command("backfill-effective-dates")
@click.option("--dry-run", is_flag=True, help="Preview count without writing")
@click.option("--state", default=None, help="Limit to one state abbreviation, e.g. KY")
def backfill_effective_dates_cmd(dry_run: bool, state: str | None) -> None:
    """Fill in missing effective_date as notice_date + 60 days (WARN Act minimum).

    Targets notices that have a notice_date but a NULL effective_date — typically
    from state sources that omit the layoff/closure start date.  Safe to re-run:
    notices that already have an effective_date are untouched.

    \b
    Examples:
      warn-v2 backfill-effective-dates --dry-run     # preview count
      warn-v2 backfill-effective-dates               # commit all states
      warn-v2 backfill-effective-dates --state KY    # one state only
    """
    from warn_v2.scripts.backfill_effective_dates import backfill_effective_dates

    stats = backfill_effective_dates(dry_run=dry_run, state_filter=state)
    suffix = " (dry run — nothing written)" if dry_run else ""
    click.echo(f"updated={stats['updated']}{suffix}")


@main.command("backfill-notice-dates")
@click.option("--dry-run", is_flag=True, help="Preview count without writing")
@click.option("--state", default=None, help="Limit to one state abbreviation, e.g. MI")
def backfill_notice_dates_cmd(dry_run: bool, state: str | None) -> None:
    """Clamp future notice_date values to the scrape (first-seen) date.

    A WARN notice can't be filed in the future. Some sources (e.g. MI) publish
    only the layoff/effective date, which gets stored as notice_date. This
    rewrites those rows: the forward-looking date is preserved in effective_date
    (when it's NULL) and notice_date is set to scraped_at::date. New inserts are
    already corrected at storage time; this fixes pre-existing rows.

    \b
    Examples:
      warn-v2 backfill-notice-dates --dry-run        # preview count
      warn-v2 backfill-notice-dates                  # commit all states
      warn-v2 backfill-notice-dates --state MI       # one state only
    """
    from warn_v2.scripts.backfill_notice_dates import backfill_notice_dates

    stats = backfill_notice_dates(dry_run=dry_run, state_filter=state)
    suffix = " (dry run — nothing written)" if dry_run else ""
    click.echo(f"updated={stats['updated']}{suffix}")


@main.command("backfill-historical")
@click.option(
    "--state", required=True,
    help="State to backfill: AZ, CA, DC, DE, FL, HI, IL, KS, KY, MD, ME, MN, "
         "MS, NM, OH, TX, VT, WI (CO is already cumulative)",
)
@click.option("--year-start", type=int, default=None,
              help="First year to fetch (default: per-state earliest; "
                   "see docs/historical-sources.md)")
@click.option("--year-end", type=int, default=None,
              help="Last year to fetch (default: current year)")
@click.option("--dry-run", is_flag=True, help="Fetch and parse but do not write to DB")
def backfill_historical_cmd(
    state: str,
    year_start: int | None,
    year_end: int | None,
    dry_run: bool,
) -> None:
    """Ingest historical WARN data for states where the regular scraper only fetches
    the current year.

    \b
    Supported states: AZ, CA, DC, DE, FL, HI, IL, KS, KY, MD, ME, MN, MS, NM,
    OH, TX, VT, WI.
    CO is excluded — its Google Sheets export is cumulative since 2019.
    Per-state earliest years and the dedup protocol: docs/historical-sources.md.
    Dry runs print a duplicate preview (already_exists / near_miss counts).

    \b
    Examples:
      warn-v2 backfill-historical --state CA
      warn-v2 backfill-historical --state DC --dry-run
      warn-v2 backfill-historical --state VT --year-start 2003 --year-end 2010
    """
    from warn_v2.scripts.backfill_historical import backfill_historical

    stats = backfill_historical(
        state,
        year_start=year_start,
        year_end=year_end,
        dry_run=dry_run,
    )
    suffix = " (dry run — nothing written)" if dry_run else ""
    click.echo(
        f"years_attempted={stats['years_attempted']} "
        f"years_ok={stats['years_ok']} "
        f"rows_seen={stats['rows_seen']} "
        f"rows_new={stats['rows_new']}"
        f"{suffix}"
    )


@main.command("ingest-file")
@click.option("--state", required=True, help="State the file's notices belong to")
@click.option(
    "--file", "path", required=True,
    type=click.Path(exists=True, dir_okay=False),
    help="Local CSV/XLSX/PDF file to ingest (e.g. a records-request response)",
)
@click.option(
    "--parser", "parser_name", default="scraper", show_default=True,
    help="'scraper' (state's regular parser), 'tabular' (generic CSV/XLSX), "
         "or a registered per-state FOIA parser",
)
@click.option("--source-url", default=None,
              help="source_url to store on the rows (default: file://<name>)")
@click.option("--dry-run", is_flag=True, help="Parse and preview but do not write to DB")
def ingest_file_cmd(
    state: str,
    path: str,
    parser_name: str,
    source_url: str | None,
    dry_run: bool,
) -> None:
    """Ingest a local WARN-notice file (e.g. a public-records response).

    \b
    Runs the same upsert path as the scrapers; dry runs print a duplicate
    preview (already_exists / near_miss counts). Request drafts and per-state
    notes live in docs/foia/.

    \b
    Examples:
      warn-v2 ingest-file --state IA --file response.xlsx --dry-run
      warn-v2 ingest-file --state SC --file notices.csv --parser tabular
    """
    from warn_v2.scripts.ingest_file import ingest_file

    stats = ingest_file(
        state,
        path,
        parser=parser_name,
        source_url=source_url,
        dry_run=dry_run,
    )
    suffix = " (dry run — nothing written)" if dry_run else ""
    click.echo(
        f"rows_seen={stats['rows_seen']} rows_new={stats['rows_new']}{suffix}"
    )


@main.command("enrich-ga")
@click.option("--limit", type=int, default=None, help="Max notices to process per run")
@click.option(
    "--pdf-dir",
    default="/var/pdfs",
    show_default=True,
    type=click.Path(file_okay=False, path_type=Path),
    help="Root directory for PDF storage",
)
@click.option("--dry-run", is_flag=True, help="Fetch and parse but do not write to DB or disk")
def enrich_ga_cmd(limit: int | None, pdf_dir: Path, dry_run: bool) -> None:
    """Enrich GA notices from TCSG entry detail pages.

    Fetches each notice's raw_notice_url and extracts: closure_type,
    effective_date, company address, zip, and the attached PDF (if any).
    Only processes notices that are still missing at least one of those fields.

    \b
    Examples:
      warn-v2 enrich-ga                    # all GA notices missing data
      warn-v2 enrich-ga --limit 20         # first 20
      warn-v2 enrich-ga --dry-run          # preview without writing
    """
    from warn_v2.scripts.enrich_ga import enrich_ga

    stats = enrich_ga(limit=limit, dry_run=dry_run, pdf_dir=pdf_dir)
    suffix = " (dry run — nothing written)" if dry_run else ""
    click.echo(
        f"considered={stats['considered']} enriched={stats['enriched']} "
        f"pdf_fetched={stats['pdf_fetched']} skipped={stats['skipped']} "
        f"errors={stats['errors']}{suffix}"
    )
    if stats["errors"]:
        sys.exit(1)


@main.command("enrich-notices")
@click.option(
    "--state",
    default=None,
    help="Limit to one state (default: run every registered enricher)",
)
@click.option("--limit", type=int, default=None, help="Max notices per state per run")
@click.option(
    "--pdf-dir",
    default="/var/pdfs",
    show_default=True,
    type=click.Path(file_okay=False, path_type=Path),
    help="Root directory for PDF storage",
)
@click.option(
    "--request-delay",
    type=float,
    default=3.0,
    show_default=True,
    metavar="SECONDS",
    help="Base delay between detail-page requests; also seeds 429/503 backoff",
)
@click.option(
    "--dry-run", is_flag=True, help="Fetch and parse but do not write to DB or disk"
)
def enrich_notices_cmd(
    state: str | None,
    limit: int | None,
    pdf_dir: Path,
    request_delay: float,
    dry_run: bool,
) -> None:
    """Enrich notices from per-state detail pages / attachments.

    Some state sources publish only a thin list view (employer, date, count);
    this throttled second pass fills location, closure type, effective date and
    PDFs from each notice's detail page. Runs every registered state enricher, or
    just one with --state.

    \b
    Examples:
      warn-v2 enrich-notices                     # all registered states
      warn-v2 enrich-notices --state GA          # GA only
      warn-v2 enrich-notices --request-delay 5   # gentler on rate limits
      warn-v2 enrich-notices --dry-run           # preview without writing
    """
    from warn_v2.enrich_notices.base import STAT_KEYS
    from warn_v2.enrich_notices.registry import all_enrichers, get_enricher

    if state:
        try:
            enrichers = [get_enricher(state)]
        except KeyError as e:
            raise click.BadParameter(str(e), param_hint="--state") from e
    else:
        enrichers = all_enrichers()

    if not enrichers:
        click.echo("No notice enrichers registered.")
        return

    totals = dict.fromkeys(STAT_KEYS, 0)
    for enricher in enrichers:
        stats = enricher.run(
            limit=limit, dry_run=dry_run, pdf_dir=pdf_dir, request_delay=request_delay
        )
        for k in STAT_KEYS:
            totals[k] += stats.get(k, 0)
        click.echo(
            f"[{enricher.state}] "
            f"considered={stats.get('considered', 0)} "
            f"enriched={stats.get('enriched', 0)} "
            f"pdf_fetched={stats.get('pdf_fetched', 0)} "
            f"skipped={stats.get('skipped', 0)} "
            f"errors={stats.get('errors', 0)}"
        )

    suffix = " (dry run — nothing written)" if dry_run else ""
    click.echo(
        f"TOTAL considered={totals['considered']} enriched={totals['enriched']} "
        f"pdf_fetched={totals['pdf_fetched']} skipped={totals['skipped']} "
        f"errors={totals['errors']}{suffix}"
    )
    if totals["errors"]:
        sys.exit(1)


@main.command("download-pdfs")
@click.option("--state", default=None, help="State abbreviation (default: all PDF-bearing states)")
@click.option("--limit", type=int, default=None, help="Max PDFs to fetch per run")
@click.option(
    "--pdf-dir",
    default="/var/pdfs",
    show_default=True,
    type=click.Path(file_okay=False, path_type=Path),
    help="Root directory for PDF storage",
)
@click.option("--dry-run", is_flag=True, help="Fetch and parse but do not write to disk or DB")
@click.option(
    "--prune-non-pdf",
    is_flag=True,
    help="Instead of downloading: delete stored files that aren't PDFs and clear pdf_path",
)
def download_pdfs_cmd(
    state: str | None,
    limit: int | None,
    pdf_dir: Path,
    dry_run: bool,
    prune_non_pdf: bool,
) -> None:
    """Download per-notice PDFs and enrich notices with extracted fields.

    Targets notices that have a raw_notice_url but no stored pdf_path.
    PDFs are saved to PDF_DIR/{state}/{notice_id}.pdf and notices are updated
    with any fields extractable from the PDF content (layoff_count, effective_date,
    address, city, zip).

    \b
    Examples:
      warn-v2 download-pdfs --state AK              # Alaska only
      warn-v2 download-pdfs --state CT --limit 200  # first 200 CT PDFs
      warn-v2 download-pdfs --dry-run               # preview without writing
      warn-v2 download-pdfs --prune-non-pdf         # clean up stored non-PDF files
    """
    if prune_non_pdf:
        from warn_v2.scripts.download_pdfs import prune_non_pdf as prune

        stats = prune(state, dry_run=dry_run, pdf_dir=pdf_dir)
        suffix = " (dry run — nothing written)" if dry_run else ""
        click.echo(
            f"checked={stats['checked']} pruned={stats['pruned']} "
            f"missing={stats['missing']} kept={stats['kept']}{suffix}"
        )
        return

    from warn_v2.scripts.download_pdfs import download_pdfs

    stats = download_pdfs(state, limit=limit, dry_run=dry_run, pdf_dir=pdf_dir)
    suffix = " (dry run — nothing written)" if dry_run else ""
    click.echo(
        f"fetched={stats['fetched']} enriched={stats['enriched']} "
        f"skipped={stats['skipped']} errors={stats['errors']}{suffix}"
    )
    # Individual HTTP/storage errors (404s, bad URLs, stale links) are expected
    # and retryable — the notice keeps pdf_path=NULL and will be retried next run.
    # Exiting non-zero on any error would mark the CronJob Failed every time a
    # single URL is broken, the same pattern that plagued scrape-all with GA.
    # The error count is visible in the logs; alerting belongs on the DB side.


@main.command("audit")
@click.option("--state", default=None, help="Limit to one state abbreviation, e.g. CA")
@click.option("--json", "as_json", is_flag=True, help="Emit machine-readable JSON")
@click.option("--markdown", is_flag=True, help="Emit the STATE_AUDIT.md table body")
@click.option(
    "--check-links",
    is_flag=True,
    help="Also HEAD-sample each flagged state's raw_notice_url links (network)",
)
def audit_cmd(state: str | None, as_json: bool, markdown: bool, check_links: bool) -> None:
    """Audit data quality across all jurisdictions (or one).

    Runs a single pass over the DB and scores each state against the data-quality
    rubric: field fill-rates, PDF coverage, per-year completeness, geocoding,
    company enrichment, scraper health, and sanity checks.  Each row lists the
    rubric items that failed (flags) and, in markdown mode, the remediation
    command that addresses them.

    \b
    Examples:
      warn-v2 audit                  # table for all jurisdictions
      warn-v2 audit --state CA       # one state
      warn-v2 audit --json           # full structured output
      warn-v2 audit --markdown       # STATE_AUDIT.md table body
      warn-v2 audit --check-links    # also verify PDF source links resolve
    """
    from warn_v2.db.session import session_scope
    from warn_v2.scripts.audit import (
        audit_states,
        render_json,
        render_markdown,
        render_table,
    )
    from warn_v2.scripts.audit import (
        check_links as _check_links,
    )

    with session_scope() as session:
        audits = audit_states(session, state_filter=state)
        if check_links:
            for a in audits:
                if a.active and a.pdf_state and a.pdf_eligible:
                    checked, dead = _check_links(session, a.state)
                    a.link_sample, a.link_dead = checked, dead
                    a.finalize()

    if as_json:
        click.echo(render_json(audits))
    elif markdown:
        click.echo(render_markdown(audits))
    else:
        click.echo(render_table(audits))


@main.command("reset-enrichment")
@click.option(
    "--sources",
    default="claude,edgar",
    show_default=True,
    help="Comma-separated enrichment_source values to reset (provider is refused)",
)
@click.option("--dry-run", is_flag=True, help="Preview counts without writing")
def reset_enrichment_cmd(sources: str, dry_run: bool) -> None:
    """Re-queue weakly-enriched companies for the full cascade.

    \b
    Metadata-only: clears enriched_at/confidence/source so find_pending picks
    the companies up again (highest layoff impact first), but KEEPS any data
    fields already gathered (website, SIC, ...) until the re-run overwrites
    them. Use after improving the provider lookup so D&B gets another shot at
    rows that previously fell through to EDGAR/Claude.

    Always run with --dry-run first and review the counts.
    """
    from sqlalchemy import func, select, update

    from warn_v2.db.models import Company
    from warn_v2.db.session import session_scope

    wanted = {s.strip().lower() for s in sources.split(",") if s.strip()}
    if "provider" in wanted:
        click.echo("refusing to reset provider-enriched rows (full D&B data)", err=True)
        sys.exit(1)
    if not wanted:
        click.echo("no sources given", err=True)
        sys.exit(1)

    with session_scope() as session:
        rows = session.execute(
            select(Company.enrichment_source, func.count())
            .where(Company.enrichment_source.in_(wanted))
            .group_by(Company.enrichment_source)
        ).all()
        total = sum(r[1] for r in rows)
        for source, count in rows:
            click.echo(f"{source}: {count}")
        if dry_run or total == 0:
            click.echo(f"total={total} (dry run — nothing written)" if dry_run else "total=0")
            return
        session.execute(
            update(Company)
            .where(Company.enrichment_source.in_(wanted))
            .values(
                enriched_at=None,
                enrichment_confidence=None,
                enrichment_source=None,
                enrichment_sources=None,
                provider_attempted_at=None,  # grant another D&B attempt
            )
        )
    click.echo(f"reset {total} companies — re-queued for the enrichment cascade")


_ROLES = click.Choice(["admin", "paid", "free"])
_MIN_PASSWORD_LEN = 12


@main.command("create-user")
@click.option("--email", required=True)
@click.option("--role", type=_ROLES, default="free", show_default=True)
@click.option(
    "--password-stdin",
    is_flag=True,
    help="Read the password from stdin (for k8s Jobs); default prompts interactively",
)
def create_user_cmd(email: str, role: str, password_stdin: bool) -> None:
    """Create an account. Accounts are admin-provisioned only (no self-signup).

    \b
    Examples:
      warn-v2 create-user --email a@b.com --role paid
      printf '%s' "$PW" | warn-v2 create-user --email a@b.com --role admin --password-stdin
    """
    from sqlalchemy.exc import IntegrityError

    from warn_v2.auth import hash_password
    from warn_v2.db.models import User
    from warn_v2.db.session import session_scope

    if password_stdin:
        password = sys.stdin.readline().rstrip("\n")
    else:
        password = click.prompt("Password", hide_input=True, confirmation_prompt=True)
    if len(password) < _MIN_PASSWORD_LEN:
        click.echo(f"password must be at least {_MIN_PASSWORD_LEN} characters", err=True)
        sys.exit(1)

    email = email.strip().lower()
    try:
        with session_scope() as session:
            session.add(User(email=email, password_hash=hash_password(password), role=role))
    except IntegrityError:
        click.echo(f"user already exists: {email}", err=True)
        sys.exit(1)
    click.echo(f"created {email} role={role}")


@main.command("set-password")
@click.option("--email", required=True)
@click.option(
    "--password-stdin",
    is_flag=True,
    help="Read the password from stdin (for k8s Jobs); default prompts interactively",
)
def set_password_cmd(email: str, password_stdin: bool) -> None:
    """Change a user's password and revoke all their active sessions."""
    from sqlalchemy import delete, select

    from warn_v2.auth import hash_password
    from warn_v2.db.models import User, UserSession
    from warn_v2.db.session import session_scope

    if password_stdin:
        password = sys.stdin.readline().rstrip("\n")
    else:
        password = click.prompt("Password", hide_input=True, confirmation_prompt=True)
    if len(password) < _MIN_PASSWORD_LEN:
        click.echo(f"password must be at least {_MIN_PASSWORD_LEN} characters", err=True)
        sys.exit(1)

    with session_scope() as session:
        user = session.scalar(select(User).where(User.email == email.strip().lower()))
        if user is None:
            click.echo(f"no such user: {email}", err=True)
            sys.exit(1)
        user.password_hash = hash_password(password)
        # Compromise response: invalidate every outstanding session too.
        session.execute(delete(UserSession).where(UserSession.user_id == user.id))
    click.echo(f"password updated for {email}; active sessions revoked")


@main.command("set-role")
@click.option("--email", required=True)
@click.option("--role", type=_ROLES, required=True)
def set_role_cmd(email: str, role: str) -> None:
    """Change an existing user's role (admin | paid | free)."""
    from sqlalchemy import select

    from warn_v2.db.models import User
    from warn_v2.db.session import session_scope

    with session_scope() as session:
        user = session.scalar(select(User).where(User.email == email.strip().lower()))
        if user is None:
            click.echo(f"no such user: {email}", err=True)
            sys.exit(1)
        user.role = role
    click.echo(f"{email} role={role}")


@main.command("list-users")
def list_users_cmd() -> None:
    """List accounts (email, role, created_at)."""
    from sqlalchemy import select

    from warn_v2.db.models import User
    from warn_v2.db.session import session_scope

    with session_scope() as session:
        for u in session.scalars(select(User).order_by(User.email)):
            click.echo(f"{u.email}\t{u.role}\t{u.created_at:%Y-%m-%d}")


@main.command("delete-user")
@click.option("--email", required=True)
def delete_user_cmd(email: str) -> None:
    """Delete an account and its sessions."""
    from sqlalchemy import delete, select

    from warn_v2.db.models import User, UserSession
    from warn_v2.db.session import session_scope

    with session_scope() as session:
        user = session.scalar(select(User).where(User.email == email.strip().lower()))
        if user is None:
            click.echo(f"no such user: {email}", err=True)
            sys.exit(1)
        # Explicit session delete: SQLite (tests) doesn't enforce FK CASCADE
        # without the foreign_keys pragma; explicit works on both backends.
        session.execute(delete(UserSession).where(UserSession.user_id == user.id))
        session.delete(user)
    click.echo(f"deleted {email}")


if __name__ == "__main__":
    main()
