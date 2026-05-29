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
def scrape_all(states: str | None) -> None:
    """Run all registered scrapers and exit non-zero if any failed."""
    targets = [s.strip().upper() for s in states.split(",")] if states else all_states()
    failed: list[str] = []
    for state in targets:
        scraper = get_scraper(state)
        run = run_state(scraper)
        click.echo(
            f"{run.state} status={run.status} rows={run.rows_scraped} new={run.rows_new}"
        )
        if run.status != "ok":
            failed.append(run.state)
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
def enrich(
    limit: int,
    state: str | None,
    rerun_below: float | None,
    dry_run: bool,
    sleep_between: float,
    recent_years: int | None,
) -> None:
    """Enrich company records using a cheapest-first cascade.

    \b
    Cascade order:
      1. External provider (ENRICHMENT_PROVIDER_MODULE env var) — richest data
      2. SEC EDGAR lookup — free, SIC for public companies
      3. Claude Haiku — cheap fallback for website + remaining gaps

    \b
    Examples:
      warn-v2 enrich                        # enrich up to 50 unenriched companies
      warn-v2 enrich --limit 200            # larger batch
      warn-v2 enrich --recent-years 2       # only companies with notices in last 2 years
      warn-v2 enrich --state CA             # only companies from CA notices
      warn-v2 enrich --rerun-below 0.7      # also re-enrich low-confidence rows
      warn-v2 enrich --dry-run              # test without writing to DB
      warn-v2 enrich --sleep-between 10     # faster (lower TPM headroom)
    """
    from warn_v2.db.session import session_scope
    from warn_v2.enrichment.agent import build_anthropic_client
    from warn_v2.enrichment.provider import load_provider
    from warn_v2.enrichment.worker import enrich_batch

    provider = load_provider()
    if provider:
        click.echo("External enrichment provider loaded.")
    else:
        click.echo("No external provider configured — using EDGAR + Claude cascade.")

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
        f"skipped={stats['skipped']} total={stats['total']}{suffix}"
    )
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


@main.command("backfill-geo")
@click.option("--dry-run", is_flag=True, help="Preview impact without writing")
def backfill_geo(dry_run: bool) -> None:
    """Populate locations.lat/lon using address geocoding + ZIP centroid fallback.

    Idempotent — re-running only updates rows still missing coordinates.
    """
    from warn_v2.scripts.backfill_geo import backfill

    stats = backfill(dry_run=dry_run)
    suffix = " (dry run — nothing written)" if dry_run else ""
    click.echo(
        f"considered={stats['considered']} "
        f"filled_address={stats['filled_address']} filled_zip={stats['filled_zip']} "
        f"no_coords={stats['no_coords']}{suffix}"
    )


if __name__ == "__main__":
    main()
