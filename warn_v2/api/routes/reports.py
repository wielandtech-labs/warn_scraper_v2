"""Routes: /reports — economic sentiment markdown (states, national, industries).

Serves the files written by `warn-v2 sentiment-report` (weekly CronJob) from
the shared reports volume. Public, like /stats — the reports contain only
aggregated public WARN data.
"""
from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel

from warn_v2.companies.naics import SECTOR_NAME
from warn_v2.reports.aggregate import NATIONAL_CODE, NATIONAL_NAME
from warn_v2.reports.generate import INDUSTRIES_JSON
from warn_v2.states import STATE_NAMES

router = APIRouter(prefix="/reports", tags=["reports"])

_REPORTS_DIR = Path(os.getenv("REPORTS_DIR", "/var/reports"))

# The report surface is the state list plus the national roll-up. "US" stays
# out of STATE_NAMES itself — that dict feeds the sitemap/state pages.
_REPORT_NAMES: dict[str, str] = {NATIONAL_CODE: NATIONAL_NAME, **STATE_NAMES}


class ReportInfo(BaseModel):
    state: str
    state_name: str
    generated_at: datetime  # file mtime


class IndustryScorecard(BaseModel):
    sector: str
    sector_name: str
    score: int | None  # 0-100, higher = healthier; None below MIN_NOTICES
    grade: str  # A-F or "N/A"
    cur_layoffs: int
    prior_layoffs: int
    cur_notices: int
    delta_pct: float | None
    generated_at: datetime  # industries.json mtime


@router.get("", response_model=list[ReportInfo])
def list_reports() -> list[ReportInfo]:
    """Jurisdictions with an available report (states + US), newest content
    indicated by mtime."""
    if not _REPORTS_DIR.is_dir():
        return []
    out: list[ReportInfo] = []
    for path in sorted(_REPORTS_DIR.glob("*.md")):
        code = path.stem
        if code not in _REPORT_NAMES:
            continue
        out.append(
            ReportInfo(
                state=code,
                state_name=_REPORT_NAMES[code],
                generated_at=datetime.fromtimestamp(path.stat().st_mtime, tz=UTC),
            )
        )
    return out


# Declared before /{state}: FastAPI matches routes in declaration order, so
# "industries" must not be swallowed by the state path parameter.
@router.get("/industries", response_model=list[IndustryScorecard])
def list_industry_scorecards() -> list[IndustryScorecard]:
    """Scorecard summary for every NAICS sector, worst score first."""
    path = _REPORTS_DIR / INDUSTRIES_JSON
    if not path.is_file():
        return []
    generated_at = datetime.fromtimestamp(path.stat().st_mtime, tz=UTC)
    rows = json.loads(path.read_text(encoding="utf-8"))
    return [IndustryScorecard(**row, generated_at=generated_at) for row in rows]


@router.get("/industries/{sector}")
def get_industry_report(sector: str) -> Response:
    """The latest scorecard for one NAICS sector, as markdown."""
    if sector not in SECTOR_NAME:  # whitelist doubles as a path-traversal guard
        raise HTTPException(status_code=404, detail="Unknown sector")
    path = _REPORTS_DIR / f"industry_{sector}.md"
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Report not available")
    return Response(
        path.read_text(encoding="utf-8"), media_type="text/markdown; charset=utf-8"
    )


@router.get("/{state}")
def get_state_report(state: str) -> Response:
    """The latest sentiment report for one state (or US), as markdown."""
    code = state.upper()
    if code not in _REPORT_NAMES:  # whitelist doubles as a path-traversal guard
        raise HTTPException(status_code=404, detail="Unknown state")
    path = _REPORTS_DIR / f"{code}.md"
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Report not available")
    return Response(
        path.read_text(encoding="utf-8"), media_type="text/markdown; charset=utf-8"
    )
