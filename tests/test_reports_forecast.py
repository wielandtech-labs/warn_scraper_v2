"""Tests for the 6-month trend forecast (warn_v2.reports.forecast)."""
from __future__ import annotations

from datetime import date
from unittest import mock

from warn_v2.db.models import Notice
from warn_v2.reports import forecast as forecast_mod
from warn_v2.reports.aggregate import NATIONAL_CODE
from warn_v2.reports.forecast import (
    Forecast,
    ForecastPoint,
    build_forecasts,
    compute_forecast,
)

AS_OF = date(2026, 7, 1)  # first day of the (partial) current month


def _months(n: int, *, start_year: int = 2021, start_month: int = 7) -> list[str]:
    out = []
    y, m = start_year, start_month
    for _ in range(n):
        out.append(f"{y:04d}-{m:02d}")
        m += 1
        if m == 13:
            m = 1
            y += 1
    return out


def _seasonal_series(n: int = 60) -> list[tuple[str, int, int]]:
    """60 months of trending, Jan/Jul-spiking synthetic data ending 2026-06."""
    months = _months(n)
    series = []
    for i, m in enumerate(months):
        spike = 40 if m.endswith(("-01", "-07")) else 0
        notices = 10 + i // 10 + spike // 10
        layoffs = 80 + i * 2 + spike
        series.append((m, notices, layoffs))
    return series


def _flat_series(
    n: int, *, notices: int = 10, layoffs: int = 100, **kwargs
) -> list[tuple[str, int, int]]:
    return [(m, notices, layoffs) for m in _months(n, **kwargs)]


def _seq_notice(
    db, *, seq: list[int], state: str = "CA", notice_date: date, layoff_count: int
) -> Notice:
    seq[0] += 1
    n = Notice(
        notice_id=f"fc_{seq[0]}",
        state=state,
        employer=f"Employer {seq[0]}",
        notice_date=notice_date,
        layoff_count=layoff_count,
    )
    db.add(n)
    db.flush()
    return n


class TestComputeForecast:
    def test_seasonal_series_picks_seasonal_model(self):
        series = _seasonal_series(60)
        assert series[-1][0] == "2026-06"
        f = compute_forecast(series, as_of=AS_OF)
        assert f is not None
        assert f.model == "ets-seasonal"
        assert f.history_months == 60
        assert f.last_history_month == "2026-06"
        assert len(f.points) == 6
        assert [p.month for p in f.points] == [
            "2026-07", "2026-08", "2026-09", "2026-10", "2026-11", "2026-12",
        ]
        for p in f.points:
            assert p.notices_lo <= p.notices <= p.notices_hi
            assert p.layoffs_lo <= p.layoffs <= p.layoffs_hi
            assert p.notices_lo >= 0 and p.layoffs_lo >= 0

    def test_partial_current_month_excluded(self):
        series = _flat_series(60)
        as_of = date(2026, 7, 1)
        f_without = compute_forecast(series, as_of=as_of)
        series_with_partial = [*series, ("2026-07", 99999, 999999)]
        f_with = compute_forecast(series_with_partial, as_of=as_of)
        assert f_without is not None and f_with is not None
        assert f_without.points == f_with.points
        assert f_without.last_history_month == f_with.last_history_month == "2026-06"

    def test_ladder_trend_tier_at_20_months(self):
        series = _flat_series(20)
        as_of = date(2023, 3, 1)  # one month after the last synthetic month
        f = compute_forecast(series, as_of=as_of)
        assert f is not None
        assert f.model == "ets-trend"

    def test_ladder_level_tier_at_13_months(self):
        series = _flat_series(13)
        as_of = date(2022, 8, 1)
        f = compute_forecast(series, as_of=as_of)
        assert f is not None
        assert f.model == "ets-level"

    def test_ladder_below_minimum_returns_none(self):
        series = _flat_series(8)
        as_of = date(2022, 3, 1)
        assert compute_forecast(series, as_of=as_of) is None

    def test_all_zero_series_returns_none(self):
        series = [(m, 0, 0) for m in _months(12)]
        as_of = date(2022, 7, 1)
        assert compute_forecast(series, as_of=as_of) is None

    def test_sparse_nonzero_below_trend_threshold_returns_none(self):
        # 40 months but only 5 nonzero: fails ets-trend's nonzero>=12 and
        # ets-level's nonzero>=6 too.
        months = _months(40)
        series = [(m, 1 if i < 5 else 0, 10 if i < 5 else 0) for i, m in enumerate(months)]
        as_of = date(2024, 11, 1)
        assert compute_forecast(series, as_of=as_of) is None

    def test_interior_gap_month_is_zero_filled(self):
        months = _months(20)
        series = [(m, 10, 100) for m in months if m != months[10]]  # drop one interior month
        as_of = date(2023, 3, 1)
        f = compute_forecast(series, as_of=as_of)
        assert f is not None
        assert f.history_months == 20  # the gap counts as a zero month, not a shorter series

    def test_declining_series_never_goes_negative(self):
        months = _months(30)
        series = [(m, max(0, 30 - i), max(0, 300 - i * 10)) for i, m in enumerate(months)]
        as_of = date(2024, 1, 1)
        f = compute_forecast(series, as_of=as_of)
        assert f is not None
        assert all(p.notices_lo >= 0 and p.layoffs_lo >= 0 for p in f.points)

    def test_fit_failure_falls_open_to_none(self):
        series = _flat_series(60)
        as_of = date(2026, 7, 1)
        with mock.patch.object(forecast_mod, "_fit_tier", side_effect=RuntimeError("boom")):
            assert compute_forecast(series, as_of=as_of) is None

    def test_sanity_guard_falls_back_to_next_tier(self):
        series = _flat_series(60)
        as_of = date(2026, 7, 1)
        real_fit = forecast_mod._fit_tier
        calls = {"n": 0}

        def fake_fit(values, kwargs, horizon):
            calls["n"] += 1
            if calls["n"] <= 2:  # the top (seasonal) tier's two metric calls
                huge = [1_000_000.0] * horizon
                return huge, huge, huge
            return real_fit(values, kwargs, horizon)

        with mock.patch.object(forecast_mod, "_fit_tier", side_effect=fake_fit):
            f = compute_forecast(series, as_of=as_of)
        assert f is not None
        assert f.model == "ets-trend"

    def test_to_payload_round_trips_shape(self):
        f = Forecast(
            model="ets-level",
            history_months=12,
            last_history_month="2026-06",
            points=[
                ForecastPoint(
                    month="2026-07",
                    notices=5, notices_lo=2, notices_hi=8,
                    layoffs=50, layoffs_lo=20, layoffs_hi=80,
                )
            ],
        )
        payload = f.to_payload()
        assert payload == {
            "model": "ets-level",
            "history_months": 12,
            "last_history_month": "2026-06",
            "points": [
                {
                    "month": "2026-07",
                    "notices": 5, "notices_lo": 2, "notices_hi": 8,
                    "layoffs": 50, "layoffs_lo": 20, "layoffs_hi": 80,
                }
            ],
        }


class TestBuildForecasts:
    def test_national_and_state_jurisdictions_present(self, db):
        seq = [0]
        as_of = date(2026, 7, 1)
        for m in _months(40, start_year=2023, start_month=3):
            y, mo = int(m[:4]), int(m[5:7])
            _seq_notice(db, seq=seq, state="CA", notice_date=date(y, mo, 5), layoff_count=100)
        payload = build_forecasts(db, as_of=as_of)
        assert payload["schema"] == 1
        assert payload["as_of"] == as_of.isoformat()
        assert NATIONAL_CODE in payload["jurisdictions"]
        assert "CA" in payload["jurisdictions"]
        ca_layoffs = sum(p["layoffs"] for p in payload["jurisdictions"]["CA"]["points"])
        us_layoffs = sum(p["layoffs"] for p in payload["jurisdictions"][NATIONAL_CODE]["points"])
        assert us_layoffs >= ca_layoffs

    def test_thin_jurisdiction_absent(self, db):
        seq = [0]
        as_of = date(2026, 7, 1)
        # Only 3 months of TX data -- below even the lowest ladder tier.
        for m in ("2026-03", "2026-04", "2026-05"):
            y, mo = int(m[:4]), int(m[5:7])
            _seq_notice(db, seq=seq, state="TX", notice_date=date(y, mo, 5), layoff_count=50)
        payload = build_forecasts(db, as_of=as_of)
        assert "TX" not in payload["jurisdictions"]

    def test_superseded_and_non_warn_excluded(self, db):
        seq = [0]
        as_of = date(2026, 7, 1)
        for m in _months(40, start_year=2023, start_month=3):
            y, mo = int(m[:4]), int(m[5:7])
            _seq_notice(db, seq=seq, state="CA", notice_date=date(y, mo, 5), layoff_count=100)
        # Add a superseded and a Non-WARN notice in the last complete month --
        # both must be excluded from the fitted series.
        db.add(
            Notice(
                notice_id="fc_superseded",
                state="CA",
                employer="Superseded Co",
                notice_date=date(2026, 6, 10),
                layoff_count=99999,
                is_superseded=True,
            )
        )
        db.add(
            Notice(
                notice_id="fc_nonwarn",
                state="CA",
                employer="Non-WARN Co",
                notice_date=date(2026, 6, 11),
                layoff_count=99999,
                closure_category="Non-WARN",
            )
        )
        db.flush()
        payload = build_forecasts(db, as_of=as_of)
        # A forecast fit off a series containing a 99999-layoff outlier would
        # trip the sanity guard on every tier; the fact CA still forecasts
        # confirms both extra rows were excluded from aggregation.
        assert "CA" in payload["jurisdictions"]
