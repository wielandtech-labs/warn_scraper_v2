"""Jobs that write to the reports volume check it first (see warn_v2/reports/writable.py)."""
from __future__ import annotations

import os
from pathlib import Path

import click
import pytest
from click.testing import CliRunner

from warn_v2.reports import writable
from warn_v2.reports.writable import require_writable, unwritable_dirs


def _deny(monkeypatch, *denied: Path) -> None:
    """Simulate directories this uid can't write (the suite may run as root,
    where real permission bits don't stop anything)."""
    real = writable._can_write
    blocked = {str(p) for p in denied}
    monkeypatch.setattr(writable, "_can_write",
                        lambda p: False if str(p) in blocked else real(p))


def test_writable_tree_passes_and_missing_root_is_created(tmp_path):
    root = tmp_path / "reports"
    assert unwritable_dirs(root) == [] and root.is_dir()
    require_writable(root)


def test_lists_every_unwritable_subdirectory_with_its_owner(tmp_path, monkeypatch):
    model_dir = tmp_path / "models" / "repeat_risk"
    model_dir.mkdir(parents=True)
    _deny(monkeypatch, tmp_path / "models", model_dir)
    assert set(unwritable_dirs(tmp_path)) == {tmp_path / "models", model_dir}
    with pytest.raises(click.ClickException) as exc:
        require_writable(tmp_path)
    msg = exc.value.message
    assert str(model_dir) in msg and "owner uid" in msg and "chown -R" in msg


def test_failed_probe_counts_even_when_access_says_yes(tmp_path, monkeypatch):
    def refuse(*a, **k):
        raise PermissionError("root-squashed")

    monkeypatch.setattr(writable.tempfile, "NamedTemporaryFile", refuse)
    assert unwritable_dirs(tmp_path) == [tmp_path]


@pytest.mark.skipif(os.name != "posix" or os.geteuid() == 0,
                    reason="root ignores permission bits")
def test_real_permission_bits(tmp_path):
    locked = tmp_path / "locked"
    locked.mkdir()
    locked.chmod(0o555)
    try:
        assert locked in unwritable_dirs(tmp_path)
    finally:
        locked.chmod(0o755)


def test_ml_train_fails_before_touching_the_database(tmp_path, monkeypatch):
    from warn_v2 import cli

    _deny(monkeypatch, tmp_path)

    def boom():
        raise AssertionError("train_and_score must not run")

    monkeypatch.setattr("warn_v2.db.session.session_scope", boom)
    res = CliRunner().invoke(cli.main, ["ml-train", "--reports-dir", str(tmp_path)])
    assert res.exit_code != 0 and "not writable" in res.output
