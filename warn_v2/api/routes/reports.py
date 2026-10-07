"""Routes: /reports — economic sentiment markdown (states, national, industries).

Two sources:
- The markdown reports are written by the /layoff-sentiment Claude Code skill
  and committed to warn_v2/reports/published/, so they ship inside the image.
- The JSON files (industries.json, forecasts.json, payloads.json) are written
  by `warn-v2 sentiment-report` (weekly CronJob) to the shared reports volume.

Public, like /stats — everything here is aggregated public WARN data.
"""
from __future__ import annotations

import json
import logging
import os
import re
from datetime import UTC, datetime
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel, ValidationError

from warn_v2.companies.naics import SECTOR_NAME
from warn_v2.reports.aggregate import NATIONAL_CODE, NATIONAL_NAME
from warn_v2.reports.forecast import FORECASTS_JSON
from warn_v2.reports.generate import INDUSTRIES_JSON, PAYLOADS_JSON
from warn_v2.states import STATE_NAMES

log = logging.getLogger(__name__)

router = APIRouter(prefix="/reports", tags=["reports"])

_REPORTS_DIR = Path(os.getenv("REPORTS_DIR", "/var/reports"))
_PUBLISHED_DIR = Path(__file__).resolve().parents[2] / "reports" / "published"

# Every report opens with an italic "_Generated YYYY-MM-DD ..." line. File
# mtimes inside the image are checkout time, not report time.
_GENERATED_RE = re.compile(r"^_Generated (\d{4}-\d{2}-\d{2})", re.MULTILINE)

# The report surface is the state list plus the national roll-up. "US" stays
# out of STATE_NAMES itself — that dict feeds the sitemap/state pages.
_REPORT_NAMES: dict[str, str] = {NATIONAL_CODE: NATIONAL_NAME, **STATE_NAMES}


class ReportInfo(BaseModel):
    state: str
    state_name: str
    generated_at: datetime  # the report's "_Generated" date


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


class ForecastPointOut(BaseModel):
    month: str
    notice_count: int
    notice_count_lo: int
    notice_count_hi: int
    layoff_total: int
    layoff_total_lo: int
    layoff_total_hi: int


class ForecastOut(BaseModel):
    state: str
    model: str  # "ets-seasonal" | "ets-trend" | "ets-level"
    history_months: int
    last_history_month: str
    generated_at: datetime  # forecasts.json mtime
    points: list[ForecastPointOut]


def _generated_at(path: Path) -> datetime:
    """The date in the report's "_Generated" line; mtime if it has none."""
    match = _GENERATED_RE.search(path.read_text(encoding="utf-8"))
    if match:
        try:
            return datetime.fromisoformat(match.group(1)).replace(tzinfo=UTC)
        except ValueError:
            pass
    return datetime.fromtimestamp(path.stat().st_mtime, tz=UTC)


def _markdown(path: Path) -> Response:
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Report not available")
    return Response(
        path.read_text(encoding="utf-8"), media_type="text/markdown; charset=utf-8"
    )


@router.get("", response_model=list[ReportInfo])
def list_reports() -> list[ReportInfo]:
    """Jurisdictions with an available report (states + US)."""
    if not _PUBLISHED_DIR.is_dir():
        return []
    out: list[ReportInfo] = []
    for path in sorted(_PUBLISHED_DIR.glob("*.md")):
        code = path.stem
        if code not in _REPORT_NAMES:
            continue
        out.append(
            ReportInfo(
                state=code,
                state_name=_REPORT_NAMES[code],
                generated_at=_generated_at(path),
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
    # The file on the PVC can be up to a week older than the running code, so
    # tolerate schema drift: skip rows the current model can't parse instead
    # of 500ing the endpoint until the next weekly CronJob rewrites the file.
    try:
        rows = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        log.warning("unreadable %s: %s", INDUSTRIES_JSON, exc)
        return []
    out: list[IndustryScorecard] = []
    for row in rows:
        try:
            out.append(IndustryScorecard(**row, generated_at=generated_at))
        except (ValidationError, TypeError) as exc:
            log.warning("skipping stale %s row: %s", INDUSTRIES_JSON, exc)
    return out


@router.get("/industries/{sector}")
def get_industry_report(sector: str) -> Response:
    """The published scorecard for one NAICS sector, as markdown."""
    if sector not in SECTOR_NAME:  # whitelist doubles as a path-traversal guard
        raise HTTPException(status_code=404, detail="Unknown sector")
    return _markdown(_PUBLISHED_DIR / f"industry_{sector}.md")


def _forecast_point_out(row: dict) -> ForecastPointOut:
    return ForecastPointOut(
        month=row["month"],
        notice_count=row["notices"],
        notice_count_lo=row["notices_lo"],
        notice_count_hi=row["notices_hi"],
        layoff_total=row["layoffs"],
        layoff_total_lo=row["layoffs_lo"],
        layoff_total_hi=row["layoffs_hi"],
    )


# Declared before /{state}: same route-order requirement as /industries.
@router.get("/forecasts/{state}", response_model=ForecastOut)
def get_forecast(state: str) -> ForecastOut:
    """The latest 6-month forecast for one state (or US), built weekly
    alongside the sentiment reports. 404 when the file, or this
    jurisdiction within it, isn't available -- including a jurisdiction
    whose history never cleared the lowest forecast ladder tier."""
    code = state.upper()
    if code not in _REPORT_NAMES:  # whitelist doubles as a path-traversal guard
        raise HTTPException(status_code=404, detail="Unknown state")
    path = _REPORTS_DIR / FORECASTS_JSON
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Forecast not available")
    generated_at = datetime.fromtimestamp(path.stat().st_mtime, tz=UTC)
    # The file on the PVC can be up to a week older than the running code, so
    # tolerate schema drift rather than 500ing until the next weekly run.
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        row = payload["jurisdictions"][code]
        return ForecastOut(
            state=code,
            model=row["model"],
            history_months=row["history_months"],
            last_history_month=row["last_history_month"],
            generated_at=generated_at,
            points=[_forecast_point_out(p) for p in row["points"]],
        )
    except KeyError:
        raise HTTPException(status_code=404, detail="Forecast not available") from None
    except (OSError, json.JSONDecodeError, ValidationError, TypeError) as exc:
        log.warning("unreadable %s: %s", FORECASTS_JSON, exc)
        raise HTTPException(status_code=404, detail="Forecast not available") from None


# Declared before /{state}: same route-order requirement as /industries.
@router.get("/payloads")
def get_payloads() -> Response:
    """Every report's pre-computed figures (payloads.json, written by the
    weekly CronJob) -- the input the /layoff-sentiment skill writes its
    analysis from. Served raw: it is already JSON and only aggregated data."""
    path = _REPORTS_DIR / PAYLOADS_JSON
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Payloads not available")
    return Response(path.read_bytes(), media_type="application/json")


@router.get("/{state}")
def get_state_report(state: str) -> Response:
    """The published report for one state (or US), as markdown."""
    code = state.upper()
    if code not in _REPORT_NAMES:  # whitelist doubles as a path-traversal guard
        raise HTTPException(status_code=404, detail="Unknown state")
    return _markdown(_PUBLISHED_DIR / f"{code}.md")
