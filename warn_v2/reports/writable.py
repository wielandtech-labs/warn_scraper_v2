"""Fail fast when a job can't write to its output directory.

The reports and PDF PVCs are NFS, where the pod's fsGroup does not re-own existing
files. When #382 (2026-10-16) moved the containers from root to uid 1000,
everything earlier runs had written stayed root-owned. The weekly ml-train
then ran its whole backtest before failing on a mkdir, and the scores went
quietly stale for weeks. Jobs that write there check first, so a permission
problem fails the run in seconds with the paths, owners and the fix.
"""
from __future__ import annotations

import os
import tempfile
from pathlib import Path

import click

MAX_LISTED = 10


def _can_write(d: Path) -> bool:
    return os.access(d, os.W_OK | os.X_OK)


def unwritable_dirs(root: Path) -> list[Path]:
    """Directories under ``root`` (``root`` included) this process can't
    create files in. Creates ``root`` if missing; a root that can't be
    created counts as unwritable."""
    try:
        root.mkdir(parents=True, exist_ok=True)
    except OSError:
        return [root]
    bad = []
    for dirpath, _dirnames, _files in os.walk(root):
        d = Path(dirpath)
        if not _can_write(d):
            bad.append(d)
    if not bad:
        # os.access can be optimistic on NFS (squashed ids); one real probe.
        try:
            with tempfile.NamedTemporaryFile(dir=root, prefix=".write-probe-"):
                pass
        except OSError:
            bad.append(root)
    return bad


def require_writable(root: Path) -> None:
    """Raise a ClickException naming every unwritable directory under root."""
    bad = unwritable_dirs(root)
    if not bad:
        return
    # No getuid/getgid on Windows (local test runs).
    uid = os.getuid() if hasattr(os, "getuid") else "?"
    gid = os.getgid() if hasattr(os, "getgid") else "?"

    def owner(p: Path) -> str:
        try:
            return str(p.stat().st_uid)
        except OSError:
            return "?"

    listed = "\n".join(f"  {p} (owner uid {owner(p)})" for p in bad[:MAX_LISTED])
    more = f"\n  … and {len(bad) - MAX_LISTED} more" if len(bad) > MAX_LISTED else ""
    raise click.ClickException(
        f"{len(bad)} director{'y' if len(bad) == 1 else 'ies'} under {root} not writable "
        f"by uid {uid}:\n{listed}{more}\n"
        f"Re-own them once as root, e.g. `chown -R {uid}:{gid} {root}`."
    )
