"""Tests for the deterministic sentiment-report aggregation."""
from __future__ import annotations

from datetime import date

from warn_v2.db.models import Company, Location, Notice
from warn_v2.reports.aggregate import (
    MIN_NOTICES,
    compute_national_aggregates,
    compute_state_aggregates,
)

# Fixed clock for every test. Windows (90d, inclusive):
#   current: 2026-04-03 .. 2026-07-01
#   prior:   2026-01-03 .. 2026-04-02
AS_OF = date(2026, 7, 1)
CUR_START = date(2026, 4, 3)
PRIOR_END = date(2026, 4, 2)
PRIOR_START = date(2026, 1, 3)

_seq = 0


def _notice(
    db,
    *,
    state: str = "CA",
    notice_date: date,
    layoff_count: int | None = 10,
    county: str | None = None,
    naics: str | None = None,
    is_superseded: bool = False,
    closure_category: str | None = None,
) -> Notice:
    global _seq
    _seq += 1
    location_id = None
    if county is not None:
        loc = Location(state=state, county=county, city=f"City{_seq}")
        db.add(loc)
        db.flush()
        location_id = loc.id
    company_id = None
    if naics is not None:
        comp = Company(name=f"Co {_seq}", naics_code=naics)
        db.add(comp)
        db.flush()
        company_id = comp.id
    n = Notice(
        notice_id=f"agg_{_seq}",
        state=state,
        employer=f"Employer {_seq}",
        notice_date=notice_date,
        layoff_count=layoff_count,
        location_id=location_id,
        company_id=company_id,
        is_superseded=is_superseded,
        closure_category=closure_category,
    )
    db.add(n)
    db.flush()
    return n


def test_window_boundaries_inclusive(db):
    _notice(db, notice_date=CUR_START, layoff_count=1)  # first day of current
    _notice(db, notice_date=AS_OF, layoff_count=2)  # last day of current
    _notice(db, notice_date=PRIOR_END, layoff_count=4)  # last day of prior
    _notice(db, notice_date=PRIOR_START, layoff_count=8)  # first day of prior
    _notice(db, notice_date=date(2026, 1, 2), layoff_count=16)  # before prior
    db.commit()

    agg = compute_state_aggregates(db, "CA", as_of=AS_OF)
    assert (agg.cur_notices, agg.cur_layoffs) == (2, 3)
    assert (agg.prior_notices, agg.prior_layoffs) == (2, 12)
    # The 2026-01-03 notice still counts toward the trailing-12mo figures.
    assert agg.yoy_cur_layoffs == 31


def test_superseded_and_other_state_excluded(db):
    _notice(db, notice_date=date(2026, 5, 1), layoff_count=100)
    _notice(db, notice_date=date(2026, 5, 2), layoff_count=999, is_superseded=True)
    _notice(db, state="TX", notice_date=date(2026, 5, 3), layoff_count=999)
    db.commit()

    agg = compute_state_aggregates(db, "CA", as_of=AS_OF)
    assert (agg.cur_notices, agg.cur_layoffs) == (1, 100)


def test_county_deltas_and_unknown_bucket(db):
    _notice(db, notice_date=date(2026, 5, 1), layoff_count=50, county="Alameda")
    _notice(db, notice_date=date(2026, 2, 1), layoff_count=20, county="Alameda")
    _notice(db, notice_date=date(2026, 5, 2), layoff_count=30)  # no location
    db.commit()

    agg = compute_state_aggregates(db, "CA", as_of=AS_OF)
    by_key = {r.key: r for r in agg.counties}
    alameda = by_key["Alameda"]
    assert (alameda.cur_layoffs, alameda.prior_layoffs) == (50, 20)
    assert alameda.delta_layoffs == 30
    assert alameda.pct_change == 150.0
    unknown = by_key["Unknown"]
    assert unknown.cur_layoffs == 30
    assert unknown.pct_change is None  # prior was 0 → rendered as "new"


def test_sector_rollup_31_33(db):
    # 311xxx and 332xxx both roll up to the Manufacturing sector "31-33".
    _notice(db, notice_date=date(2026, 5, 1), layoff_count=40, naics="311999")
    _notice(db, notice_date=date(2026, 5, 2), layoff_count=60, naics="332000")
    _notice(db, notice_date=date(2026, 5, 3), layoff_count=10, naics="541511")
    _notice(db, notice_date=date(2026, 5, 4), layoff_count=5)  # unenriched
    db.commit()

    agg = compute_state_aggregates(db, "CA", as_of=AS_OF)
    by_key = {r.key: r for r in agg.sectors}
    assert by_key["31-33"].cur_layoffs == 100
    assert by_key["31-33"].cur_notices == 2
    assert by_key["31-33"].name == "Manufacturing"
    assert by_key["54"].cur_layoffs == 10
    # 3 of 4 current-window notices carry a NAICS code.
    assert agg.naics_coverage_pct == 75.0


def test_sufficient_threshold(db):
    for i in range(MIN_NOTICES - 1):
        _notice(db, notice_date=date(2026, 5, 1 + i))
    db.commit()
    assert not compute_state_aggregates(db, "CA", as_of=AS_OF).sufficient

    _notice(db, notice_date=date(2026, 2, 1))  # prior window counts too
    db.commit()
    assert compute_state_aggregates(db, "CA", as_of=AS_OF).sufficient


def test_zero_notice_state_returns_empty_aggregates(db):
    db.commit()
    agg = compute_state_aggregates(db, "WY", as_of=AS_OF)
    assert agg.state == "WY"
    assert agg.state_name == "Wyoming"
    assert agg.cur_notices == 0
    assert agg.counties == []
    assert agg.sectors == []
    assert agg.monthly == []
    assert agg.naics_coverage_pct == 0.0
    assert not agg.sufficient


def test_monthly_series_and_closure_split(db):
    _notice(db, notice_date=date(2026, 5, 1), layoff_count=10, closure_category="Layoff")
    _notice(db, notice_date=date(2026, 5, 20), layoff_count=20, closure_category="Closure")
    _notice(db, notice_date=date(2026, 6, 2), layoff_count=30)
    _notice(db, notice_date=date(2025, 6, 1), layoff_count=99)  # before 12mo cutoff
    db.commit()

    agg = compute_state_aggregates(db, "CA", as_of=AS_OF)
    assert ("2026-05", 2, 30) in agg.monthly
    assert ("2026-06", 1, 30) in agg.monthly
    assert all(m >= "2025-08" for m, _, _ in agg.monthly)  # 12-month lookback
    assert agg.closure_split == {"Layoff": 1, "Closure": 1, "Unspecified": 1}


def test_prompt_payload_shape(db):
    for i in range(12):
        _notice(db, notice_date=date(2026, 5, 1), layoff_count=10, county=f"County{i:02d}")
    db.commit()

    agg = compute_state_aggregates(db, "CA", as_of=AS_OF)
    payload = agg.to_prompt_payload()
    assert payload["state"] == "CA"
    assert payload["state_name"] == "California"
    assert len(payload["top_counties"]) == 10  # capped
    assert payload["totals"]["layoffs_current"] == 120
    assert payload["current_window"] == {"start": "2026-04-03", "end": "2026-07-01"}
    row = payload["top_counties"][0]
    assert set(row) == {
        "name",
        "notices_current",
        "layoffs_current",
        "notices_prior",
        "layoffs_prior",
        "delta_layoffs",
    }
    assert "top_states" not in payload  # national-only key


def test_national_totals_sum_across_states(db):
    _notice(db, state="CA", notice_date=date(2026, 5, 1), layoff_count=100)
    _notice(db, state="TX", notice_date=date(2026, 5, 2), layoff_count=50)
    _notice(db, state="TX", notice_date=date(2026, 5, 3), layoff_count=999, is_superseded=True)
    _notice(db, state="NY", notice_date=date(2026, 2, 1), layoff_count=30)  # prior window
    db.commit()

    agg = compute_national_aggregates(db, as_of=AS_OF)
    assert agg.state == "US"
    assert agg.state_name == "United States"
    assert (agg.cur_notices, agg.cur_layoffs) == (2, 150)
    assert (agg.prior_notices, agg.prior_layoffs) == (1, 30)
    assert agg.counties == []


def test_national_states_table_merges_windows(db):
    _notice(db, state="CA", notice_date=date(2026, 5, 1), layoff_count=100)
    _notice(db, state="NY", notice_date=date(2026, 2, 1), layoff_count=30)  # prior only
    db.commit()

    agg = compute_national_aggregates(db, as_of=AS_OF)
    by_key = {r.key: r for r in agg.states}
    assert by_key["CA"].name == "California"
    assert (by_key["CA"].cur_layoffs, by_key["CA"].prior_layoffs) == (100, 0)
    # A state active only in the prior window still gets a row.
    assert (by_key["NY"].cur_layoffs, by_key["NY"].prior_layoffs) == (0, 30)


def test_national_payload_includes_top_states(db):
    _notice(db, state="CA", notice_date=date(2026, 5, 1), layoff_count=100)
    db.commit()

    payload = compute_national_aggregates(db, as_of=AS_OF).to_prompt_payload()
    assert payload["state"] == "US"
    assert payload["top_states"][0]["name"] == "California"
    assert payload["top_states"][0]["layoffs_current"] == 100
