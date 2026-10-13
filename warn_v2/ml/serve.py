"""Read side of the repeat-layoff model: one company's current risk.

Shown only for an employer's latest event whose 12-month horizon is still
open, scored by the champion of the latest weekly run. First-time filers get
no number: the backtest puts the model near chance for them (PR-AUC 0.11 vs a
0.08 base rate), so the honest answer is "not enough history".
"""
from __future__ import annotations

import json
import os
from datetime import UTC, date, datetime, timedelta
from typing import Literal

from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from warn_v2.db.models import Company, MlModelRun, RepeatRiskScore
from warn_v2.ml import HORIZON_DAYS, MODEL

# Tiers by calibrated probability; the base rate is ~0.20.
TIERS: list[tuple[float, str]] = [(0.35, "high"), (0.15, "moderate"), (0.0, "low")]


def public_enabled() -> bool:
    return os.getenv("REPEAT_RISK_PUBLIC", "0") == "1"


class RepeatRiskOut(BaseModel):
    status: Literal["scored", "insufficient_history", "no_open_event", "unavailable"]
    tier: Literal["low", "moderate", "high"] | None = None
    probability: float | None = None
    base_rate: float | None = None
    event_start: date | None = None
    horizon_end: date | None = None
    model_version: str | None = None
    scored_at: datetime | None = None


def tier_for(p: float) -> Literal["low", "moderate", "high"]:
    for floor, name in TIERS:
        if p >= floor:
            return name  # type: ignore[return-value]
    return "low"


def company_risk(db: Session, company: Company) -> RepeatRiskOut:
    run = db.scalars(
        select(MlModelRun).where(MlModelRun.model == MODEL)
        .order_by(MlModelRun.created_at.desc(), MlModelRun.id.desc()).limit(1)
    ).first()
    metrics = json.loads(run.metrics) if run is not None else {}
    version = metrics.get("scorer_version")
    if not version:
        return RepeatRiskOut(status="unavailable")
    base_rate = (metrics.get("pooled") or {}).get("prevalence")

    # Scores carry the canonical id from scoring time; matching the whole
    # group keeps a company merged since the last weekly run findable.
    canonical = company.canonical_company_id or company.id
    group = select(Company.id).where(
        (Company.id == canonical) | (Company.canonical_company_id == canonical)
    )
    # Same open-horizon rule (UTC, inclusive) as train.open_events.
    horizon_open = datetime.now(UTC).date() - timedelta(days=HORIZON_DAYS)
    score = db.scalars(
        select(RepeatRiskScore)
        .where(RepeatRiskScore.model_version == version,
               RepeatRiskScore.company_id.in_(group),
               RepeatRiskScore.event_start >= horizon_open)
        .order_by(RepeatRiskScore.event_start.desc()).limit(1)
    ).first()
    if score is None:
        return RepeatRiskOut(status="no_open_event", base_rate=base_rate)

    common = dict(
        base_rate=base_rate, event_start=score.event_start,
        horizon_end=score.event_start + timedelta(days=HORIZON_DAYS),
        model_version=version, scored_at=score.scored_at,
    )
    # The model's own view of the history, so the card and the model agree.
    if score.prior_events == 0:
        return RepeatRiskOut(status="insufficient_history", **common)
    return RepeatRiskOut(
        status="scored", tier=tier_for(score.score),
        probability=round(score.score, 2), **common,
    )
