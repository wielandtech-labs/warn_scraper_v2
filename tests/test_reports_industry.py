"""Tests for the industry scorecard score formula and sector aggregation."""
from __future__ import annotations

from datetime import date

import pytest

from warn_v2.db.models import Company, Notice
from warn_v2.reports.industry import (
    _component,
    compute_score,
    compute_sector_aggregates,
    grade_for,
    scorecard_summary,
)

# Same fixed clock as test_reports_aggregate. Windows (90d, inclusive):
#   current: 2026-04-03 .. 2026-07-01
#   prior:   2026-01-03 .. 2026-04-02
AS_OF = date(2026, 7, 1)

_seq = 0


def _notice(
    db,
    *,
    state: str = "CA",
    notice_date: date,
    layoff_count: int | None = 10,
    naics: str | None = None,
    is_superseded: bool = False,
) -> Notice:
    global _seq
    _seq += 1
    company_id = None
    if naics is not None:
        comp = Company(name=f"IndCo {_seq}", naics_code=naics)
        db.add(comp)
        db.flush()
        company_id = comp.id
    n = Notice(
        notice_id=f"ind_{_seq}",
        state=state,
        employer=f"Employer {_seq}",
        notice_date=notice_date,
        layoff_count=layoff_count,
        company_id=company_id,
        is_superseded=is_superseded,
    )
    db.add(n)
    db.flush()
    return n


# --- score formula -----------------------------------------------------------


def test_component_flat_is_50():
    assert _component(100, 100) == 50.0


def test_component_doubled_is_0():
    assert _component(200, 100) == 0.0


def test_component_to_zero_is_100():
    assert _component(0, 100) == 100.0


def test_component_clamps_beyond_double():
    assert _component(1000, 100) == 0.0  # 10x is clamped to the same floor as 2x


def test_component_prior_zero_branches():
    assert _component(0, 0) == 50.0  # no signal
    assert _component(5, 0) == 0.0  # all-new activity


def test_compute_score_flat_everywhere_is_50_grade_c():
    score = compute_score(
        cur_layoffs=100,
        prior_layoffs=100,
        yoy_cur_layoffs=400,
        yoy_prior_layoffs=400,
        cur_notices=10,
        prior_notices=10,
    )
    assert score == 50
    assert grade_for(score) == "C"


def test_compute_score_surging_is_0_grade_f():
    score = compute_score(
        cur_layoffs=200,
        prior_layoffs=100,
        yoy_cur_layoffs=800,
        yoy_prior_layoffs=400,
        cur_notices=20,
        prior_notices=10,
    )
    assert score == 0
    assert grade_for(score) == "F"


def test_compute_score_easing_is_100_grade_a():
    score = compute_score(
        cur_layoffs=0,
        prior_layoffs=100,
        yoy_cur_layoffs=0,
        yoy_prior_layoffs=400,
        cur_notices=0,
        prior_notices=10,
    )
    assert score == 100
    assert grade_for(score) == "A"


def test_compute_score_weight_arithmetic():
    # layoffs flat (50) * 0.5 + yoy doubled (0) * 0.3 + notices to zero (100) * 0.2
    score = compute_score(
        cur_layoffs=100,
        prior_layoffs=100,
        yoy_cur_layoffs=800,
        yoy_prior_layoffs=400,
        cur_notices=0,
        prior_notices=10,
    )
    assert score == 45
    assert grade_for(score) == "C"


def test_grade_bands():
    assert grade_for(80) == "A"
    assert grade_for(79) == "B"
    assert grade_for(60) == "B"
    assert grade_for(59) == "C"
    assert grade_for(40) == "C"
    assert grade_for(39) == "D"
    assert grade_for(20) == "D"
    assert grade_for(19) == "F"
    assert grade_for(0) == "F"
    assert grade_for(None) == "N/A"


# --- sector aggregation ------------------------------------------------------


def test_sector_rollup_and_exclusions(db):
    # 311xxx and 332xxx both belong to Manufacturing ("31-33").
    _notice(db, notice_date=date(2026, 5, 1), layoff_count=40, naics="311999")
    _notice(db, state="TX", notice_date=date(2026, 5, 2), layoff_count=60, naics="332000")
    _notice(db, notice_date=date(2026, 5, 3), layoff_count=10, naics="541511")  # other sector
    _notice(db, notice_date=date(2026, 5, 4), layoff_count=5)  # un-enriched
    _notice(db, notice_date=date(2026, 5, 5), layoff_count=99, naics="311111", is_superseded=True)
    db.commit()

    agg = compute_sector_aggregates(db, "31-33", as_of=AS_OF)
    assert agg.sector_name == "Manufacturing"
    assert (agg.cur_notices, agg.cur_layoffs) == (2, 100)
    # total_cur_notices counts every national notice, enriched or not.
    assert agg.total_cur_notices == 4


def test_sector_state_and_subsector_grouping(db):
    _notice(db, state="CA", notice_date=date(2026, 5, 1), layoff_count=40, naics="311999")
    _notice(db, state="TX", notice_date=date(2026, 5, 2), layoff_count=60, naics="332000")
    _notice(db, state="CA", notice_date=date(2026, 2, 1), layoff_count=20, naics="311000")
    db.commit()

    agg = compute_sector_aggregates(db, "31-33", as_of=AS_OF)
    states = {r.key: r for r in agg.states}
    assert states["CA"].name == "California"
    assert (states["CA"].cur_layoffs, states["CA"].prior_layoffs) == (40, 20)
    assert states["TX"].cur_layoffs == 60

    subs = {r.key: r for r in agg.subsectors}
    assert subs["311"].name == "Food Manufacturing"
    assert (subs["311"].cur_layoffs, subs["311"].prior_layoffs) == (40, 20)
    assert subs["332"].cur_layoffs == 60


def test_sector_unknown_subsector_gets_fallback_name(db):
    _notice(db, notice_date=date(2026, 5, 1), layoff_count=10, naics="319999")  # no 319 subsector
    db.commit()

    agg = compute_sector_aggregates(db, "31-33", as_of=AS_OF)
    assert agg.subsectors[0].name == "NAICS 319"


def test_sector_monthly_series(db):
    _notice(db, notice_date=date(2026, 5, 1), layoff_count=10, naics="311999")
    _notice(db, notice_date=date(2026, 6, 1), layoff_count=20, naics="332000")
    _notice(db, notice_date=date(2026, 6, 2), layoff_count=99)  # un-enriched: excluded
    db.commit()

    agg = compute_sector_aggregates(db, "31-33", as_of=AS_OF)
    assert ("2026-05", 1, 10) in agg.monthly
    assert ("2026-06", 1, 20) in agg.monthly


def test_sector_insufficient_data_has_no_score(db):
    _notice(db, notice_date=date(2026, 5, 1), layoff_count=10, naics="311999")
    db.commit()

    agg = compute_sector_aggregates(db, "31-33", as_of=AS_OF)
    assert not agg.sufficient
    assert agg.score is None
    assert agg.grade == "N/A"


def test_sector_payload_shape(db):
    for i in range(6):
        _notice(db, notice_date=date(2026, 5, 1 + i), layoff_count=10, naics="311999")
    db.commit()

    agg = compute_sector_aggregates(db, "31-33", as_of=AS_OF)
    payload = agg.to_prompt_payload()
    assert payload["sector"] == "31-33"
    assert payload["sector_name"] == "Manufacturing"
    assert payload["score"] == agg.score
    assert payload["grade"] == agg.grade
    assert payload["top_states"][0]["name"] == "California"
    assert payload["top_subsectors"][0]["name"] == "Food Manufacturing"
    assert "coverage_note" in payload


def test_unknown_sector_rejected(db):
    with pytest.raises(ValueError, match="unknown NAICS sector"):
        compute_sector_aggregates(db, "99", as_of=AS_OF)


def test_scorecard_summary_orders_worst_first(db):
    # Manufacturing surging (many current notices, none prior) → score 0.
    for i in range(6):
        _notice(db, notice_date=date(2026, 5, 1 + i), layoff_count=100, naics="311999")
    # Professional services easing (all activity in the prior window) → high score.
    for i in range(6):
        _notice(db, notice_date=date(2026, 2, 1 + i), layoff_count=100, naics="541511")
    # Retail: too little data → score None, sorted last.
    _notice(db, notice_date=date(2026, 5, 1), layoff_count=10, naics="445110")
    db.commit()

    aggs = [
        compute_sector_aggregates(db, sid, as_of=AS_OF) for sid in ("54", "31-33", "44-45")
    ]
    summary = scorecard_summary(aggs)
    assert [row["sector"] for row in summary] == ["31-33", "54", "44-45"]
    assert summary[0]["grade"] == "F"
    assert summary[-1]["score"] is None
    assert set(summary[0]) == {
        "sector",
        "sector_name",
        "score",
        "grade",
        "cur_layoffs",
        "prior_layoffs",
        "cur_notices",
        "delta_pct",
    }
    # delta_pct: prior 0 → None for the surging sector; -100.0 for the easing one.
    assert summary[0]["delta_pct"] is None
    assert summary[1]["delta_pct"] == -100.0