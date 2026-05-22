"""Tests for heal/github.py — PR preparation in dry-run mode.

All tests use dry_run=True so no git commands are executed.  The repo_root
fixture points at a tmp_path so we never touch real source files.
"""
from __future__ import annotations

from pathlib import Path

from warn_v2.heal.github import PROpened, PRPlan, _pr_body, open_pr

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _plan(
    tmp_path: Path,
    *,
    state: str = "CA",
    src: str = "# patched\n",
    summary: str = "rename column in header detection",
    error: str = "ParseFailed: column 'Company' not found",
    rows_before: int = 0,
    rows_after: int = 7,
) -> PRPlan:
    snap = tmp_path / "20260522T120000_abc12345.bin"
    snap.write_bytes(b"raw snapshot bytes")
    return PRPlan(
        state=state,
        new_module_src=src,
        summary=summary,
        error=error,
        snapshot_path=snap,
        rows_before=rows_before,
        rows_after=rows_after,
    )


# ---------------------------------------------------------------------------
# open_pr (dry_run=True) tests
# ---------------------------------------------------------------------------


def test_dry_run_returns_preopened(tmp_path: Path) -> None:
    plan = _plan(tmp_path)
    result = open_pr(plan, repo_root=tmp_path, dry_run=True)
    assert isinstance(result, PROpened)
    assert result.url == "(dry-run)"


def test_dry_run_branch_contains_state_and_snapshot_stem(tmp_path: Path) -> None:
    plan = _plan(tmp_path, state="TX")
    result = open_pr(plan, repo_root=tmp_path, dry_run=True)
    assert "tx" in result.branch
    assert "20260522T120000_abc12345" in result.branch


def test_dry_run_writes_module_to_repo_root_relative_path(tmp_path: Path) -> None:
    src = "# replacement scraper\n"
    plan = _plan(tmp_path, state="CA", src=src)
    open_pr(plan, repo_root=tmp_path, dry_run=True)

    target = tmp_path / "warn_v2" / "scrapers" / "states" / "ca.py"
    assert target.exists(), "module was not written to the expected path"
    assert target.read_text(encoding="utf-8") == src


def test_dry_run_does_not_touch_real_scraper(tmp_path: Path) -> None:
    """When repo_root is provided the real ca.py must be untouched."""
    from warn_v2.heal.tools import state_module_path

    real_path = state_module_path("CA")
    original = real_path.read_text(encoding="utf-8")

    plan = _plan(tmp_path, src="# should not land in real file\n")
    open_pr(plan, repo_root=tmp_path, dry_run=True)

    assert real_path.read_text(encoding="utf-8") == original


# ---------------------------------------------------------------------------
# _pr_body tests
# ---------------------------------------------------------------------------


def test_pr_body_contains_summary(tmp_path: Path) -> None:
    plan = _plan(tmp_path, summary="fix column rename")
    body = _pr_body(plan)
    assert "fix column rename" in body


def test_pr_body_contains_error_context(tmp_path: Path) -> None:
    plan = _plan(tmp_path, error="ParseFailed: header row missing")
    body = _pr_body(plan)
    assert "ParseFailed: header row missing" in body


def test_pr_body_contains_row_counts(tmp_path: Path) -> None:
    plan = _plan(tmp_path, rows_before=0, rows_after=42)
    body = _pr_body(plan)
    assert "42" in body
