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


@main.command(name="list")
def list_states() -> None:
    """List registered state scrapers."""
    for s in all_states():
        click.echo(s)


@main.command()
@click.option("--state", required=True, help="State abbreviation to heal")
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
    state: str, snapshot_path: Path | None, error: str, dry_run: bool, max_turns: int
) -> None:
    """Run the self-heal agent for a broken state scraper."""
    from warn_v2.heal.agent import build_anthropic_client, run_heal
    from warn_v2.heal.detector import find_candidates
    from warn_v2.heal.github import PRPlan, open_pr
    from warn_v2.heal.tools import HealContext
    from warn_v2.db.session import session_scope

    scraper = get_scraper(state)

    if snapshot_path is None:
        with session_scope() as session:
            candidates = [c for c in find_candidates(session) if c.state == state.upper()]
        if not candidates:
            click.echo(f"no recent failed run found for {state}", err=True)
            sys.exit(2)
        snapshot_path = candidates[0].snapshot_path
        error = error or candidates[0].error

    ctx = HealContext(
        state=state.upper(),
        snapshot_path=snapshot_path,
        error=error or "(no error message supplied)",
        expected_row_range=scraper.expected_row_range,
        required_fields=scraper.required_fields,
    )

    client = build_anthropic_client()
    result = run_heal(ctx, client, max_turns=max_turns)

    if not result.proposed:
        click.echo(f"agent did not propose a patch after {result.turns} turns")
        if result.last_message:
            click.echo(f"final message: {result.last_message}")
        sys.exit(3)

    plan = PRPlan(
        state=state.upper(),
        new_module_src=result.code or "",
        summary=result.summary or "self-heal patch",
        error=error or ctx.error,
        snapshot_path=snapshot_path,
        rows_after=result.rows_after,
    )
    pr = open_pr(plan, dry_run=dry_run)
    click.echo(f"branch: {pr.branch}")
    click.echo(f"pr:     {pr.url}")


if __name__ == "__main__":
    main()
