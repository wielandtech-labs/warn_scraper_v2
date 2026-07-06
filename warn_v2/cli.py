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
    from warn_v2.db.models import SCRAPER_SUCCESS_STATUSES

    scraper = get_scraper(state)
    run = run_state(scraper)
    click.echo(
        f"{run.state} status={run.status} rows={run.rows_scraped} new={run.rows_new}"
    )
    if run.status not in SCRAPER_SUCCESS_STATUSES:
        sys.exit(1)


@main.command(name="scrape-all")
@click.option("--states", default=None, help="Comma-separated subset, e.g. CA,TX")
@click.option(
    "--skip",
    default=None,
    help=(
        "Comma-separated states to exclude from the run (slow publishers "
        "scraped on their own less-frequent schedule; see the Helm "
        "scraper.skipStates / slowStates values)."
    ),
)
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
def scrape_all(states: str | None, skip: str | None, tolerate: str | None) -> None:
    """Run all registered scrapers.

    Exits non-zero only if a *non-tolerated* state failed. Tolerated-state
    failures are reported on stderr but don't fail the run — sustained outages
    are caught by alerting off the scraper_runs table, not the job exit code.
    """
    from warn_v2.db.models import SCRAPER_SUCCESS_STATUSES

    targets = [s.strip().upper() for s in states.split(",")] if states else all_states()
    if skip:
        skip_set = {s.strip().upper() for s in skip.split(",")}
        targets = [t for t in targets if t not in skip_set]
    tolerated = {s.strip().upper() for s in tolerate.split(",")} if tolerate else set()
    failed: list[str] = []
    tolerated_failures: list[str] = []
    for state in targets:
        scraper = get_scraper(state)
        run = run_state(scraper)
        click.echo(
            f"{run.state} status={run.status} rows={run.rows_scraped} new={run.rows_new}"
        )
        if run.status not in SCRAPER_SUCCESS_STATUSES:
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
@click.option("--limit", default=10, show_default=True, help="Max companies to enrich per run")
@click.option(
    "--recent-limit",
    type=click.IntRange(min=0),
    default=0,
    show_default=True,
    metavar="N",
    help=(
        "Additionally enrich up to N companies ordered by most-recent notice "
        "date (deduped against the impact-ordered --limit batch) — works the "
        "queue from both ends."
    ),
)
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
    recent_limit: int,
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
      warn-v2 enrich --limit 25 --recent-limit 25  # 25 biggest + 25 most recent
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
                recent_limit=recent_limit,
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
        f"provider_rejected={stats.get('provider_rejected', 0)} "
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


@main.command("purge-impossible-dates")
@click.option("--dry-run", is_flag=True, help="Preview matches without deleting")
@click.option("--state", default=None, help="Limit to one state abbreviation, e.g. CO")
def purge_impossible_dates_cmd(dry_run: bool, state: str | None) -> None:
    """Delete notices dated before the WARN Act (1988) or far in the future.

    \b
    One-shot cleanup for rows ingested before validate.filter_bad_dates
    existed (e.g. CO's junk 1957 form submission). The scrape-time guard
    keeps purged rows from coming back.

    Always run with --dry-run first and review the output before committing.
    """
    from warn_v2.scripts.purge_impossible_dates import purge_impossible_dates

    stats = purge_impossible_dates(dry_run=dry_run, state_filter=state)
    suffix = " (dry run — nothing deleted)" if dry_run else ""
    click.echo(f"matched={stats['matched']} deleted={stats['deleted']}{suffix}")


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
@click.option(
    "--fix-out-of-state",
    is_flag=True,
    help=(
        "Instead of filling NULLs: re-geocode locations whose coordinates fall "
        "outside their own state (HQ address/ZIP pins); clears coords when no "
        "in-state result exists"
    ),
)
def backfill_geo(
    dry_run: bool, rerun_address: bool, state: str | None, fix_out_of_state: bool
) -> None:
    """Populate locations.lat/lon using address geocoding + ZIP centroid fallback.

    By default only targets locations where coordinates are NULL.
    Use --rerun-address to upgrade existing ZIP/city-centroid coordinates to
    Census street-level accuracy wherever a street address is now available.

    \b
    Examples:
      warn-v2 backfill-geo                     # fill NULLs only
      warn-v2 backfill-geo --rerun-address     # also upgrade existing centroids
      warn-v2 backfill-geo --fix-out-of-state  # repair wrong-state pins
      warn-v2 backfill-geo --dry-run           # preview without writing
    """
    if fix_out_of_state and rerun_address:
        raise click.UsageError("--fix-out-of-state and --rerun-address are mutually exclusive")

    if fix_out_of_state:
        from warn_v2.scripts.backfill_geo import fix_out_of_state as fix_oos

        stats = fix_oos(dry_run=dry_run, state_filter=state)
        suffix = " (dry run — nothing written)" if dry_run else ""
        click.echo(
            f"considered={stats['considered']} fixed={stats['fixed']} "
            f"cleared={stats['cleared']}{suffix}"
        )
        return

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


@main.command("backfill-ny-layoff-counts")
@click.option("--dry-run", is_flag=True, help="Preview counts without writing")
@click.option("--limit", type=int, default=None, help="Max notices to process")
@click.option(
    "--pdf-dir",
    default="/var/pdfs",
    show_default=True,
    type=click.Path(file_okay=False, path_type=Path),
    help="Root directory for stored PDFs (read-only here)",
)
def backfill_ny_layoff_counts_cmd(dry_run: bool, limit: int | None, pdf_dir: Path) -> None:
    """Fill NULL layoff_count on pre-Tableau NY notices from their WARN UNIT PDFs.

    NY notices from the old dol.ny.gov HTML listing (pre-April 2025) have no
    layoff_count and the current Tableau CSV doesn't cover them. Their
    raw_notice_url redirects to the NY DOL WARN UNIT summary PDF, which
    publishes "Total Number of Affected Workers". Fill-only: never overwrites
    an existing count. One-shot — safe to re-run (already-filled rows drop out
    of the candidate set).

    \b
    Examples:
      warn-v2 backfill-ny-layoff-counts --dry-run    # preview
      warn-v2 backfill-ny-layoff-counts              # commit
    """
    from warn_v2.scripts.backfill_ny_layoff_counts import backfill_ny_layoff_counts

    stats = backfill_ny_layoff_counts(dry_run=dry_run, limit=limit, pdf_dir=pdf_dir)
    suffix = " (dry run — nothing written)" if dry_run else ""
    click.echo(
        f"considered={stats['considered']} filled={stats['filled']} "
        f"no_count={stats['no_count']} errors={stats['errors']}{suffix}"
    )
    if stats["errors"] and not stats["filled"]:
        sys.exit(1)


@main.command("backfill-layoff-counts")
@click.option("--dry-run", is_flag=True, help="Preview counts without writing")
@click.option(
    "--state", default=None,
    help="Limit to one state abbreviation (default: CT, HI, WV)",
)
@click.option("--limit", type=int, default=None, help="Max notices to process")
@click.option(
    "--pdf-dir",
    default="/var/pdfs",
    show_default=True,
    type=click.Path(file_okay=False, path_type=Path),
    help="Root directory of stored PDFs",
)
def backfill_layoff_counts_cmd(
    dry_run: bool, state: str | None, limit: int | None, pdf_dir: Path
) -> None:
    """Fill NULL layoff_count from stored per-notice PDFs (CT/HI/WV).

    These states publish no worker counts on their listing pages; the count
    exists only inside the letter PDFs already stored by download-pdfs. Text
    is read via pdfplumber with OCR fallback for scanned letters (HI/WV), and
    the count extracted conservatively: explicit totals preferred, NULL kept
    when ambiguous, existing counts never overwritten (fill-only).

    \b
    Examples:
      warn-v2 backfill-layoff-counts --dry-run       # preview impact
      warn-v2 backfill-layoff-counts                 # CT+HI+WV
      warn-v2 backfill-layoff-counts --state CT      # one state only
    """
    from warn_v2.scripts.backfill_layoff_counts import backfill_layoff_counts

    stats = backfill_layoff_counts(
        state, limit=limit, dry_run=dry_run, pdf_dir=pdf_dir
    )
    suffix = " (dry run — nothing written)" if dry_run else ""
    click.echo(
        f"considered={stats['considered']} filled={stats['filled']} "
        f"no_count={stats['no_count']} no_text={stats['no_text']} "
        f"missing={stats['missing']} errors={stats['errors']}{suffix}"
    )


@main.command("backfill-historical")
@click.option(
    "--state", required=True,
    help="State to backfill: AZ, CA, DC, DE, FL, HI, IL, KS, KY, MD, ME, MN, "
         "MS, NM, OH, PA, TX, VT, WI (CO is already cumulative)",
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
    Supported states: AZ, CA, CO, DC, DE, FL, HI, IL, KS, KY, MD, ME, MN, MS,
    NM, OH, TX, VT, WI.
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
    if _enrich_run_failed(stats):
        sys.exit(1)


def _enrich_run_failed(stats: dict) -> bool:
    """True when an enrichment run erred without accomplishing anything.

    Rate-limited sources (TCSG) block before the queue drains on most runs, so
    errors alongside banked progress are the designed success mode — and once
    the backlog drains, a healthy run is mostly skips. ``skipped`` counts as
    progress: it means pages were fetched and parsed, i.e. the source was
    reachable. Only errors with zero work of any kind is a real failure.
    """
    accomplished = (
        stats.get("enriched", 0) + stats.get("pdf_fetched", 0) + stats.get("skipped", 0)
    )
    return bool(stats.get("errors", 0)) and not accomplished


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
    failed_states: list[str] = []
    for enricher in enrichers:
        stats = enricher.run(
            limit=limit, dry_run=dry_run, pdf_dir=pdf_dir, request_delay=request_delay
        )
        for k in STAT_KEYS:
            totals[k] += stats.get(k, 0)
        # Judge each state on its own stats — aggregating first would let one
        # state's progress mask another state's total failure.
        if _enrich_run_failed(stats):
            failed_states.append(enricher.state)
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
    if failed_states:
        click.echo(f"states with errors and no progress: {', '.join(failed_states)}")
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
@click.option(
    "--re-extract",
    is_flag=True,
    help="Instead of downloading: re-run field extraction over already-stored PDFs",
)
def download_pdfs_cmd(
    state: str | None,
    limit: int | None,
    pdf_dir: Path,
    dry_run: bool,
    prune_non_pdf: bool,
    re_extract: bool,
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
      warn-v2 download-pdfs --re-extract            # re-read stored PDFs (no network)
    """
    if prune_non_pdf and re_extract:
        raise click.UsageError("--prune-non-pdf and --re-extract are mutually exclusive")

    if prune_non_pdf:
        from warn_v2.scripts.download_pdfs import prune_non_pdf as prune

        stats = prune(state, dry_run=dry_run, pdf_dir=pdf_dir)
        suffix = " (dry run — nothing written)" if dry_run else ""
        click.echo(
            f"checked={stats['checked']} pruned={stats['pruned']} "
            f"missing={stats['missing']} kept={stats['kept']}{suffix}"
        )
        return

    if re_extract:
        from warn_v2.scripts.download_pdfs import re_extract as reextract

        stats = reextract(state, limit=limit, dry_run=dry_run, pdf_dir=pdf_dir)
        suffix = " (dry run — nothing written)" if dry_run else ""
        click.echo(
            f"considered={stats['considered']} enriched={stats['enriched']} "
            f"missing={stats['missing']} errors={stats['errors']}{suffix}"
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


@main.command("cadence-report")
@click.option("--state", default=None, help="Limit to one state abbreviation, e.g. CA")
@click.option("--json", "as_json", is_flag=True, help="Emit machine-readable JSON")
@click.option("--markdown", is_flag=True, help="Emit a markdown table (with caveats)")
@click.option(
    "--since-days",
    type=int,
    default=None,
    metavar="N",
    help="Only consider runs from the last N days (default: all history)",
)
def cadence_report_cmd(
    state: str | None, as_json: bool, markdown: bool, since_days: int | None
) -> None:
    """Report how often each state's source actually publishes new notices.

    Aggregates scraper_runs history per state: how many runs found new rows,
    the median gap between new-row days, and a suggested schedule tier
    (hot/steady/slow/dormant). Sampling is once per day, so intra-day
    publication frequency is not detectable; backfill spikes inflate old
    history — prefer --since-days 90.

    \b
    Examples:
      warn-v2 cadence-report                       # table for all jurisdictions
      warn-v2 cadence-report --state CA            # one state
      warn-v2 cadence-report --json                # machine-readable
      warn-v2 cadence-report --markdown --since-days 180
    """
    from datetime import UTC, datetime, timedelta

    from warn_v2.db.session import session_scope
    from warn_v2.scripts.cadence import (
        cadence_states,
        render_json,
        render_markdown,
        render_table,
    )

    since = (
        datetime.now(UTC) - timedelta(days=since_days) if since_days else None
    )
    with session_scope() as session:
        rows = cadence_states(session, state_filter=state, since=since)

    if as_json:
        click.echo(render_json(rows))
    elif markdown:
        click.echo(render_markdown(rows))
    else:
        click.echo(render_table(rows))


@main.command("cross-check")
@click.option("--state", default=None, help="Limit to one state abbreviation, e.g. CA")
@click.option("--json", "as_json", is_flag=True, help="Emit machine-readable JSON")
@click.option("--no-store", is_flag=True, help="Don't persist results (read-only preview)")
@click.option(
    "--fail-on-drift",
    type=int,
    default=None,
    metavar="N",
    help=(
        "Exit non-zero if any state has more than N notices missing_from_db. "
        "Off by default: like scrape-all, per-source noise shouldn't churn the "
        "CronJob's status — alerting belongs on the cross_check_runs table."
    ),
)
def cross_check_cmd(
    state: str | None, as_json: bool, no_store: bool, fail_on_drift: int | None
) -> None:
    """Verify stored notices against each state's live WARN page.

    Re-fetches what each state currently publishes (network) and diffs it
    against the DB, recording drift in both directions to cross_check_runs:
    notices on the page we're missing (missing_from_db) and notices we hold
    that vanished from the page within its current date window (extra_in_db).
    Read-only against notices — it never writes a Notice row.

    \b
    Examples:
      warn-v2 cross-check                  # all non-blocked states
      warn-v2 cross-check --state DC       # one state
      warn-v2 cross-check --json           # machine-readable
      warn-v2 cross-check --no-store       # preview without writing
      warn-v2 cross-check --fail-on-drift 0  # exit 1 on any missing notice
    """
    from datetime import UTC, datetime

    from warn_v2.db.session import session_scope
    from warn_v2.scripts.cross_check import (
        cross_check_states,
        persist,
        render_json,
        render_table,
    )

    # cross_check_states does the network sweep, opening a short read session
    # per state — so we never hold one transaction across the whole run. Persist
    # the collected results in a single separate short transaction.
    results = cross_check_states(state_filter=state)
    if not no_store:
        with session_scope() as session:
            persist(session, results, checked_at=datetime.now(UTC))

    click.echo(render_json(results) if as_json else render_table(results))

    if fail_on_drift is not None:
        offenders = [cc for cc in results if cc.missing_count > fail_on_drift]
        if offenders:
            summary = ", ".join(f"{cc.state}({cc.missing_count})" for cc in offenders)
            click.echo(f"missing_from_db exceeds {fail_on_drift}: {summary}", err=True)
            sys.exit(1)


@main.command("reset-enrichment")
@click.option(
    "--sources",
    default="claude,edgar",
    show_default=True,
    help="Comma-separated enrichment_source values to reset (provider is refused)",
)
@click.option(
    "--include-null-source",
    is_flag=True,
    help=(
        "Also reset enriched rows with a NULL enrichment_source AND no DUNS "
        "(pre-source-field EDGAR/Claude-era rows the --sources filter can't "
        "target). Scoped to duns IS NULL so it never touches a real D&B hit."
    ),
)
@click.option("--dry-run", is_flag=True, help="Preview counts without writing")
def reset_enrichment_cmd(sources: str, include_null_source: bool, dry_run: bool) -> None:
    """Re-queue weakly-enriched companies for the full cascade.

    \b
    Metadata-only: clears enriched_at/confidence/source so find_pending picks
    the companies up again (highest layoff impact first), but KEEPS any data
    fields already gathered (website, SIC, ...) until the re-run overwrites
    them. Use after improving the provider lookup so D&B gets another shot at
    rows that previously fell through to EDGAR/Claude.

    Always run with --dry-run first and review the counts.
    """
    from sqlalchemy import and_, func, or_, select, update

    from warn_v2.db.models import Company
    from warn_v2.db.session import session_scope

    wanted = {s.strip().lower() for s in sources.split(",") if s.strip()}
    if "provider" in wanted:
        click.echo("refusing to reset provider-enriched rows (full D&B data)", err=True)
        sys.exit(1)
    if not wanted and not include_null_source:
        click.echo("no sources given", err=True)
        sys.exit(1)

    cond = Company.enrichment_source.in_(wanted) if wanted else None
    if include_null_source:
        # Enriched but source-less AND DUNS-less = legacy EDGAR/Claude rows; the
        # duns guard keeps any old source-less D&B hit out of scope.
        null_cond = and_(
            Company.enriched_at.is_not(None),
            Company.enrichment_source.is_(None),
            Company.duns.is_(None),
        )
        cond = null_cond if cond is None else or_(cond, null_cond)

    with session_scope() as session:
        rows = session.execute(
            select(Company.enrichment_source, func.count())
            .where(cond)
            .group_by(Company.enrichment_source)
        ).all()
        total = sum(r[1] for r in rows)
        for source, count in rows:
            click.echo(f"{source or 'null'}: {count}")
        if dry_run or total == 0:
            click.echo(f"total={total} (dry run — nothing written)" if dry_run else "total=0")
            return
        session.execute(
            update(Company)
            .where(cond)
            .values(
                enriched_at=None,
                enrichment_confidence=None,
                enrichment_source=None,
                enrichment_sources=None,
                provider_attempted_at=None,  # grant another D&B attempt
            )
        )
    click.echo(f"reset {total} companies — re-queued for the enrichment cascade")


_ROLES = click.Choice(["admin", "enterprise", "paid", "free"])
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
    """Change an existing user's role (admin | enterprise | paid | free)."""
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


@main.command("issue-key")
@click.option("--email", required=True)
@click.option("--name", default=None, help="Label shown in key listings")
def issue_key_cmd(email: str, name: str | None) -> None:
    """Mint an API key for a user and print the raw key (shown only once)."""
    from sqlalchemy import select

    from warn_v2 import api_keys
    from warn_v2.db.models import User
    from warn_v2.db.session import session_scope

    with session_scope() as session:
        user = session.scalar(select(User).where(User.email == email.strip().lower()))
        if user is None:
            click.echo(f"no such user: {email}", err=True)
            sys.exit(1)
        key, raw = api_keys.create_key(session, user, name)
        click.echo(f"created key {key.prefix}… for {email}")
        click.echo(raw)


@main.command("revoke-key")
@click.option("--email", required=True)
@click.option("--prefix", required=True, help="Key prefix as shown in listings")
def revoke_key_cmd(email: str, prefix: str) -> None:
    """Revoke a user's API key(s) matching a displayed prefix."""
    from sqlalchemy import select

    from warn_v2 import api_keys
    from warn_v2.db.models import ApiKey, User
    from warn_v2.db.session import session_scope

    with session_scope() as session:
        user = session.scalar(select(User).where(User.email == email.strip().lower()))
        if user is None:
            click.echo(f"no such user: {email}", err=True)
            sys.exit(1)
        matches = list(
            session.scalars(
                select(ApiKey).where(
                    ApiKey.user_id == user.id,
                    ApiKey.prefix == prefix,
                    ApiKey.revoked_at.is_(None),
                )
            )
        )
        if not matches:
            click.echo(f"no active key with prefix {prefix} for {email}", err=True)
            sys.exit(1)
        for key in matches:
            api_keys.revoke_key(session, key)
    click.echo(f"revoked {len(matches)} key(s) for {email}")


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


@main.command("send-alert-digest")
def send_alert_digest_cmd() -> None:
    """Email confirmed subscribers any new WARN notices matching their filters.

    Run on a schedule shortly after the daily scrape. Each subscription's
    watermark advances only on a successful send, so reruns are safe.
    """
    from datetime import UTC, datetime

    from warn_v2.db.session import session_scope
    from warn_v2.notifications.digest import run_digest

    with session_scope() as session:
        summary = run_digest(session, datetime.now(UTC))
    click.echo(
        f"subscriptions={summary['subscriptions']} emailed={summary['emailed']} "
        f"notices={summary['notices']} failed={summary['failed']}"
    )


@main.command("sentiment-report")
@click.option("--state", default=None, help="One state abbreviation, e.g. CA (default: all)")
@click.option(
    "--industry",
    default=None,
    metavar="SECTOR",
    help="One NAICS sector id, e.g. 31-33 (generates only that scorecard)",
)
@click.option(
    "--national",
    is_flag=True,
    help="Only the US-wide roll-up (US.md)",
)
@click.option(
    "--reports-dir",
    default="/var/reports",
    show_default=True,
    type=click.Path(file_okay=False, path_type=Path),
    help="Directory for the markdown reports",
)
@click.option("--skip-llm", is_flag=True, help="Write deterministic tables only (no Ollama call)")
@click.option("--dry-run", is_flag=True, help="Compute and render but write no files")
def sentiment_report_cmd(
    state: str | None,
    industry: str | None,
    national: bool,
    reports_dir: Path,
    skip_llm: bool,
    dry_run: bool,
) -> None:
    """Generate economic sentiment markdown reports.

    Deterministic layoff-trend figures (trailing 90 days vs the prior 90, plus
    a 12-month series) with a narrative written by the cluster's Ollama
    service (OLLAMA_BASE_URL / OLLAMA_MODEL). The default run covers every
    state, a national roll-up (US.md), and a scorecard per NAICS sector
    (industry_{sector}.md + industries.json). A failed narrative degrades that
    report to figures-only; the run exits non-zero only when every attempted
    narrative failed (systemic outage).

    \b
    Examples:
      warn-v2 sentiment-report                       # states + national + industries
      warn-v2 sentiment-report --state CA            # one state
      warn-v2 sentiment-report --industry 31-33      # one sector scorecard
      warn-v2 sentiment-report --national            # US roll-up only
      warn-v2 sentiment-report --skip-llm --dry-run  # offline smoke test
    """
    from warn_v2.companies.naics import SECTOR_NAME
    from warn_v2.db.session import session_scope
    from warn_v2.reports.aggregate import NATIONAL_CODE
    from warn_v2.reports.generate import (
        generate_industry_reports,
        generate_national_report,
        generate_reports,
        write_report,
    )
    from warn_v2.reports.ollama import build_ollama_client
    from warn_v2.states import is_valid_state

    if state and industry:
        click.echo("--state and --industry are mutually exclusive", err=True)
        sys.exit(1)
    if national and (state or industry):
        click.echo("--national is mutually exclusive with --state and --industry", err=True)
        sys.exit(1)
    if state and not is_valid_state(state):
        click.echo(f"unknown state: {state!r}", err=True)
        sys.exit(1)
    if industry and industry not in SECTOR_NAME:
        click.echo(f"unknown industry: {industry!r}", err=True)
        sys.exit(1)

    client = None if skip_llm else build_ollama_client()
    stats = {
        "generated": 0,
        "insufficient": 0,
        "narrative_ok": 0,
        "narrative_failed": 0,
        "total": 0,
    }

    def merge(group: dict[str, int]) -> None:
        for k in stats:
            stats[k] += group[k]

    with session_scope() as session:
        if industry is None and not national:
            merge(
                generate_reports(
                    session,
                    client,
                    reports_dir=reports_dir,
                    states=[state] if state else None,
                    dry_run=dry_run,
                    progress=click.echo,
                )
            )
        if state is None and industry is None:
            content, status = generate_national_report(session, client)
            if not dry_run:
                write_report(reports_dir, NATIONAL_CODE, content)
            key = {
                "ok": "narrative_ok",
                "llm_unavailable": "narrative_failed",
                "insufficient_data": "insufficient",
            }.get(status)
            if key:
                stats[key] += 1
            stats["generated"] += 1
            stats["total"] += 1
            click.echo(f"{NATIONAL_CODE} narrative={status} chars={len(content)}")
        if state is None and not national:
            merge(
                generate_industry_reports(
                    session,
                    client,
                    reports_dir=reports_dir,
                    sectors=[industry] if industry else None,
                    dry_run=dry_run,
                    progress=click.echo,
                )
            )

    suffix = " (dry run — nothing written)" if dry_run else ""
    click.echo(
        f"generated={stats['generated']} insufficient={stats['insufficient']} "
        f"narrative_ok={stats['narrative_ok']} narrative_failed={stats['narrative_failed']} "
        f"total={stats['total']}{suffix}"
    )
    # Partial narrative failures are degraded output, not job failures; all
    # attempted narratives failing means Ollama is down — surface that.
    if stats["narrative_failed"] and not stats["narrative_ok"]:
        sys.exit(1)


if __name__ == "__main__":
    main()
