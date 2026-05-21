"""Open a pull request with a heal patch via the `gh` CLI.

`gh` is preinstalled on the user's homelab and in the CI image. We shell out
rather than depend on PyGithub so authentication just reuses whatever credential
helper gh already has (gh auth login on the user's box, GITHUB_TOKEN env in CI).
"""
from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path

from warn_v2.heal.tools import state_module_path


@dataclass(slots=True)
class PROpened:
    branch: str
    url: str


@dataclass(slots=True)
class PRPlan:
    state: str
    new_module_src: str
    summary: str
    error: str
    snapshot_path: Path
    rows_before: int = 0
    rows_after: int = 0


def open_pr(
    plan: PRPlan,
    *,
    repo_root: Path | None = None,
    dry_run: bool = False,
) -> PROpened:
    """Create a branch, commit the patched module, open a PR. Returns branch+url."""
    root = repo_root or _repo_root()
    branch = f"heal/{plan.state.lower()}-{plan.snapshot_path.stem}"

    target = state_module_path(plan.state)
    if not target.is_absolute():
        target = root / target
    target.write_text(plan.new_module_src, encoding="utf-8")

    body = _pr_body(plan)

    if dry_run:
        return PROpened(branch=branch, url="(dry-run)")

    _run("git", "checkout", "-B", branch, cwd=root)
    _run("git", "add", str(target.relative_to(root)), cwd=root)
    _run(
        "git",
        "commit",
        "-m",
        f"heal({plan.state.lower()}): {plan.summary}",
        cwd=root,
    )
    _run("git", "push", "--set-upstream", "origin", branch, cwd=root)

    proc = _run(
        "gh",
        "pr",
        "create",
        "--title",
        f"heal({plan.state.lower()}): {plan.summary}",
        "--body",
        body,
        "--head",
        branch,
        cwd=root,
        capture=True,
    )
    return PROpened(branch=branch, url=(proc.stdout or "").strip())


def _pr_body(plan: PRPlan) -> str:
    return (
        f"## Self-heal patch for {plan.state}\n\n"
        f"**Summary:** {plan.summary}\n\n"
        f"### Failure context\n"
        f"```\n{plan.error.strip()[:4000]}\n```\n\n"
        f"### Row counts\n"
        f"- Before patch: **{plan.rows_before}**\n"
        f"- After patch (against the failing snapshot): **{plan.rows_after}**\n\n"
        f"### Snapshot\n"
        f"`{plan.snapshot_path}`\n\n"
        f"---\n"
        f"_Opened automatically by the warn-v2 self-heal agent._"
    )


def _repo_root() -> Path:
    proc = _run("git", "rev-parse", "--show-toplevel", capture=True)
    return Path((proc.stdout or "").strip())


def _run(*cmd: str, cwd: Path | None = None, capture: bool = False):
    return subprocess.run(
        cmd,
        cwd=str(cwd) if cwd else None,
        check=True,
        capture_output=capture,
        text=True,
    )
