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


if __name__ == "__main__":
    main()
