"""Bundled multi-file snapshots (backfill Mode 3b).

Small-file historical sources are committed to the repo as one tar.gz per
state under ``warn_v2/scrapers/data/<st>_archive.tar.gz`` so prod backfill
Jobs never touch the Wayback Machine. Members are the raw source files as
captured (PDF/XLS/HTML), named so the state's ``parse_for_url`` can dispatch
on them.
"""
from __future__ import annotations

import tarfile
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent / "data"


def load_archive(path: Path) -> list[tuple[str, bytes]]:
    """Return (member_name, bytes) for every regular file in a tar.gz,
    sorted by member name for deterministic ingest order."""
    with tarfile.open(path, "r:gz") as tar:
        return sorted(
            (m.name, tar.extractfile(m).read())
            for m in tar.getmembers()
            if m.isfile()
        )
