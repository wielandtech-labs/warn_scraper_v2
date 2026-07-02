"""Routes: /reports — per-state economic sentiment markdown.

Serves the files written by `warn-v2 sentiment-report` (weekly CronJob) from
the shared reports volume. Public, like /stats — the reports contain only
aggregated public WARN data.
"""
from __future__ import annotations

import os
from datetime import UTC, datetime
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel

from warn_v2.states import STATE_NAMES

router = APIRouter(prefix="/reports", tags=["reports"])

_REPORTS_DIR = Path(os.getenv("REPORTS_DIR", "/var/reports"))


class ReportInfo(BaseModel):
    state: str
    state_name: str
    generated_at: datetime  # file mtime


@router.get("", response_model=list[ReportInfo])
def list_reports() -> list[ReportInfo]:
    """States with an available report, newest content indicated by mtime."""
    if not _REPORTS_DIR.is_dir():
        return []
    out: list[ReportInfo] = []
    for path in sorted(_REPORTS_DIR.glob("*.md")):
        code = path.stem
        if code not in STATE_NAMES:
            continue
        out.append(
            ReportInfo(
                state=code,
                state_name=STATE_NAMES[code],
                generated_at=datetime.fromtimestamp(path.stat().st_mtime, tz=UTC),
            )
        )
    return out


@router.get("/{state}")
def get_state_report(state: str) -> Response:
    """The latest sentiment report for one state, as markdown."""
    code = state.upper()
    if code not in STATE_NAMES:  # whitelist doubles as a path-traversal guard
        raise HTTPException(status_code=404, detail="Unknown state")
    path = _REPORTS_DIR / f"{code}.md"
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Report not available")
    return Response(
        path.read_text(encoding="utf-8"), media_type="text/markdown; charset=utf-8"
    )
