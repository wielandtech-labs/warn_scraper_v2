"""Per-NAICS-sector aggregates and the deterministic scorecard score.

A sector scorecard mirrors a state report but pivots the axes: geography is
per-state (not county) and industry detail is the 3-digit subsector. Every
query joins Company and filters on the sector's NAICS prefixes, so figures
cover only NAICS-enriched notices — a partial, unevenly-distributed subset.
Scores are therefore normalized against each sector's OWN baseline, never
compared across sectors on absolute counts, and every scorecard carries a
coverage caveat.

Score formula (0-100, higher = healthier):
  For each component, pressure ratio r = clamp((cur - prior) / prior, -1, +1)
  mapped to 100 * (1 - r) / 2 — layoffs doubled → 0, flat → 50, gone to
  zero → 100. When prior == 0: no signal (cur == 0) → 50; all-new activity
  (cur > 0) → 0.
  score = 0.5 * layoff momentum (90d vs prior 90d layoffs)
        + 0.3 * YoY trend (trailing 12mo vs prior 12mo layoffs)
        + 0.2 * notice momentum (90d vs prior 90d notice counts)
  Grades: A >= 80 (easing sharply) · B 60-79 (easing) · C 40-59 (stable)
        · D 20-39 (elevated) · F < 20 (surging). Below MIN_NOTICES combined
  90-day notices the deltas are noise: score/grade are None / "N/A".
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

from sqlalchemy import String, cast, func, select
from sqlalchemy.orm import Session

from warn_v2.companies.naics import SECTOR_NAME, naics_filter, subsector_name
from warn_v2.db.models import Company, Notice
from warn_v2.reports.aggregate import (
    MIN_NOTICES,
    DeltaRow,
    _in_window,
    _int,
    _merge_deltas,
    _month_start_back,
)
from warn_v2.states import STATE_NAMES

SCORE_WEIGHTS = {"layoffs": 0.5, "yoy": 0.3, "notices": 0.2}

GRADE_BANDS = [(80, "A"), (60, "B"), (40, "C"), (20, "D"), (0, "F")]
GRADE_LABEL = {
    "A": "easing sharply",
    "B": "easing",
    "C": "stable",
    "D": "elevated",
    "F": "surging",
}


def _component(cur: int, prior: int) -> float:
    """One score component: 0 (pressure doubled or all-new) .. 100 (to zero)."""
    if prior == 0:
        return 50.0 if cur == 0 else 0.0
    r = (cur - prior) / prior
    r = max(-1.0, min(1.0, r))
    return 100.0 * (1.0 - r) / 2.0


def compute_score(
    *,
    cur_layoffs: int,
    prior_layoffs: int,
    yoy_cur_layoffs: int,
    yoy_prior_layoffs: int,
    cur_notices: int,
    prior_notices: int,
) -> int:
    return round(
        SCORE_WEIGHTS["layoffs"] * _component(cur_layoffs, prior_layoffs)
        + SCORE_WEIGHTS["yoy"] * _component(yoy_cur_layoffs, yoy_prior_layoffs)
        + SCORE_WEIGHTS["notices"] * _component(cur_notices, prior_notices)
    )


def grade_for(score: int | None) -> str:
    if score is None:
        return "N/A"
    for floor, grade in GRADE_BANDS:
        if score >= floor:
            return grade
    return "F"


@dataclass(slots=True)
class SectorAggregates:
    sector: str  # sector id, e.g. "31-33"
    sector_name: str
    as_of: date
    cur_start: date
    cur_end: date
    prior_start: date
    prior_end: date
    cur_notices: int
    cur_layoffs: int
    prior_notices: int
    prior_layoffs: int
    yoy_cur_notices: int
    yoy_cur_layoffs: int
    yoy_prior_notices: int
    yoy_prior_layoffs: int
    states: list[DeltaRow]  # sorted by cur_layoffs desc
    subsectors: list[DeltaRow]  # 3-digit NAICS, sorted by cur_layoffs desc
    monthly: list[tuple[str, int, int]]  # ("YYYY-MM", notices, layoffs), oldest first
    total_cur_notices: int  # ALL current-window notices nationally (coverage caveat)

    @property
    def sufficient(self) -> bool:
        return self.cur_notices + self.prior_notices >= MIN_NOTICES

    @property
    def score(self) -> int | None:
        if not self.sufficient:
            return None
        return compute_score(
            cur_layoffs=self.cur_layoffs,
            prior_layoffs=self.prior_layoffs,
            yoy_cur_layoffs=self.yoy_cur_layoffs,
            yoy_prior_layoffs=self.yoy_prior_layoffs,
            cur_notices=self.cur_notices,
            prior_notices=self.prior_notices,
        )

    @property
    def grade(self) -> str:
        return grade_for(self.score)

    def to_prompt_payload(self) -> dict:
        """Compact JSON-ready dict for the LLM: top rows only, no DB objects."""

        def rows(items: list[DeltaRow]) -> list[dict]:
            return [
                {
                    "name": r.name,
                    "notices_current": r.cur_notices,
                    "layoffs_current": r.cur_layoffs,
                    "notices_prior": r.prior_notices,
                    "layoffs_prior": r.prior_layoffs,
                    "delta_layoffs": r.delta_layoffs,
                }
                for r in items[:10]
            ]

        return {
            "sector": self.sector,
            "sector_name": self.sector_name,
            "current_window": {
                "start": self.cur_start.isoformat(),
                "end": self.cur_end.isoformat(),
            },
            "prior_window": {
                "start": self.prior_start.isoformat(),
                "end": self.prior_end.isoformat(),
            },
            "totals": {
                "notices_current": self.cur_notices,
                "layoffs_current": self.cur_layoffs,
                "notices_prior": self.prior_notices,
                "layoffs_prior": self.prior_layoffs,
            },
            "year_over_year": {
                "notices_trailing_12mo": self.yoy_cur_notices,
                "layoffs_trailing_12mo": self.yoy_cur_layoffs,
                "notices_prior_12mo": self.yoy_prior_notices,
                "layoffs_prior_12mo": self.yoy_prior_layoffs,
            },
            "score": self.score,
            "grade": self.grade,
            "top_states": rows(self.states),
            "top_subsectors": rows(self.subsectors),
            "monthly": [
                {"month": m, "notices": n, "layoffs": lt} for m, n, lt in self.monthly
            ],
            "coverage_note": (
                "Figures cover only notices whose company has an enriched NAICS "
                "code — a partial, unevenly-distributed subset of all WARN notices."
            ),
        }


def _sector_stmt(stmt, sector: str):
    """Join Company and restrict to the sector's NAICS prefixes."""
    return (
        stmt.select_from(Notice)
        .join(Company, Notice.company_id == Company.id)
        .where(naics_filter(Company.naics_code, sector, None))
    )


def _sector_totals(
    session: Session, sector: str, start: date, end: date
) -> tuple[int, int]:
    stmt = _sector_stmt(
        select(
            func.count(Notice.notice_id), func.coalesce(func.sum(Notice.layoff_count), 0)
        ),
        sector,
    )
    row = session.execute(_in_window(stmt, None, start, end)).one()
    return _int(row[0]), _int(row[1])


def _sector_state_window(
    session: Session, sector: str, start: date, end: date
) -> dict[str, tuple[int, int]]:
    stmt = _sector_stmt(
        select(
            Notice.state,
            func.count(Notice.notice_id),
            func.coalesce(func.sum(Notice.layoff_count), 0),
        ),
        sector,
    ).group_by(Notice.state)
    rows = session.execute(_in_window(stmt, None, start, end)).all()
    return {r[0]: (_int(r[1]), _int(r[2])) for r in rows}


def _sector_subsector_window(
    session: Session, sector: str, start: date, end: date
) -> dict[str, tuple[int, int]]:
    prefix3 = func.substr(Company.naics_code, 1, 3)
    stmt = _sector_stmt(
        select(
            prefix3,
            func.count(Notice.notice_id),
            func.coalesce(func.sum(Notice.layoff_count), 0),
        ),
        sector,
    ).group_by(prefix3)
    rows = session.execute(_in_window(stmt, None, start, end)).all()
    return {r[0]: (_int(r[1]), _int(r[2])) for r in rows}


def _sector_monthly(
    session: Session, sector: str, start: date
) -> list[tuple[str, int, int]]:
    period = func.substr(cast(Notice.notice_date, String), 1, 7).label("period")
    stmt = (
        _sector_stmt(
            select(
                period,
                func.count(Notice.notice_id),
                func.coalesce(func.sum(Notice.layoff_count), 0),
            ),
            sector,
        )
        .where(
            Notice.is_superseded.is_(False),
            Notice.notice_date.is_not(None),
            Notice.notice_date >= start,
        )
        .group_by(period)
        .order_by(period)
    )
    return [(r[0], _int(r[1]), _int(r[2])) for r in session.execute(stmt).all()]


def _total_notices(session: Session, start: date, end: date) -> int:
    stmt = select(func.count(Notice.notice_id))
    return _int(session.execute(_in_window(stmt, None, start, end)).scalar())


def compute_sector_aggregates(
    session: Session,
    sector: str,
    *,
    as_of: date | None = None,
    window_days: int = 90,
) -> SectorAggregates:
    """Compute one sector's scorecard figures (national scope). Same inclusive
    windows as compute_state_aggregates. `sector` must be a NAICS_SECTORS id."""
    if sector not in SECTOR_NAME:
        raise ValueError(f"unknown NAICS sector: {sector}")
    as_of = as_of or date.today()
    cur_start = as_of - timedelta(days=window_days - 1)
    prior_start = as_of - timedelta(days=2 * window_days - 1)
    prior_end = as_of - timedelta(days=window_days)
    yoy_cur_start = as_of - timedelta(days=364)
    yoy_prior_start = as_of - timedelta(days=729)
    yoy_prior_end = as_of - timedelta(days=365)

    cur_n, cur_l = _sector_totals(session, sector, cur_start, as_of)
    prior_n, prior_l = _sector_totals(session, sector, prior_start, prior_end)
    yoy_cur_n, yoy_cur_l = _sector_totals(session, sector, yoy_cur_start, as_of)
    yoy_prior_n, yoy_prior_l = _sector_totals(
        session, sector, yoy_prior_start, yoy_prior_end
    )

    states = _merge_deltas(
        _sector_state_window(session, sector, cur_start, as_of),
        _sector_state_window(session, sector, prior_start, prior_end),
        lambda k: STATE_NAMES.get(k, k),
    )
    subsectors = _merge_deltas(
        _sector_subsector_window(session, sector, cur_start, as_of),
        _sector_subsector_window(session, sector, prior_start, prior_end),
        lambda k: subsector_name(k) or f"NAICS {k}",
    )

    return SectorAggregates(
        sector=sector,
        sector_name=SECTOR_NAME[sector],
        as_of=as_of,
        cur_start=cur_start,
        cur_end=as_of,
        prior_start=prior_start,
        prior_end=prior_end,
        cur_notices=cur_n,
        cur_layoffs=cur_l,
        prior_notices=prior_n,
        prior_layoffs=prior_l,
        yoy_cur_notices=yoy_cur_n,
        yoy_cur_layoffs=yoy_cur_l,
        yoy_prior_notices=yoy_prior_n,
        yoy_prior_layoffs=yoy_prior_l,
        states=states,
        subsectors=subsectors,
        monthly=_sector_monthly(session, sector, _month_start_back(as_of, 11)),
        total_cur_notices=_total_notices(session, cur_start, as_of),
    )


def scorecard_summary(aggs: list[SectorAggregates]) -> list[dict]:
    """JSON payload for industries.json: worst score first, N/A sectors last."""

    def sort_key(a: SectorAggregates):
        return (a.score is None, a.score if a.score is not None else 0, a.sector)

    return [
        {
            "sector": a.sector,
            "sector_name": a.sector_name,
            "score": a.score,
            "grade": a.grade,
            "cur_layoffs": a.cur_layoffs,
            "prior_layoffs": a.prior_layoffs,
            "cur_notices": a.cur_notices,
            "delta_pct": (
                round((a.cur_layoffs - a.prior_layoffs) / a.prior_layoffs * 100.0, 1)
                if a.prior_layoffs
                else None
            ),
        }
        for a in sorted(aggs, key=sort_key)
    ]
