"""6-month trend forecasts for the sentiment reports and stats charts.

Every number here is computed once a week by the sentiment-report CronJob
(see build_forecasts) and written to forecasts.json — statsmodels never runs
in the API request path (see warn_v2.api.routes.reports). Fail-open by
design: a fit failure for one jurisdiction (short history, non-convergence,
a runaway prediction) drops that jurisdiction from the file rather than
breaking the weekly run, mirroring warn_v2.reports.bls.

statsmodels/numpy are imported lazily inside _fit_tier only — this module is
imported by warn_v2.reports.generate, which the API pod also imports, and
neither scipy nor statsmodels should load in that process.
"""
from __future__ import annotations

import logging
import warnings
from dataclasses import dataclass
from datetime import date
from typing import Any

from sqlalchemy import String, cast, func, select
from sqlalchemy.orm import Session

from warn_v2.db.models import Notice
from warn_v2.reports.aggregate import NATIONAL_CODE, _int, _month_start_back

log = logging.getLogger(__name__)

HORIZON = 6
LOOKBACK_MONTHS = 72
FORECASTS_JSON = "forecasts.json"

# (model id, min complete months, min nonzero months, ETSModel kwargs)
_LADDER: tuple[tuple[str, int, int, dict[str, Any]], ...] = (
    (
        "ets-seasonal",
        36,
        24,
        {"trend": "add", "damped_trend": True, "seasonal": "add", "seasonal_periods": 12},
    ),
    ("ets-trend", 18, 12, {"trend": "add", "damped_trend": True, "seasonal": None}),
    ("ets-level", 12, 6, {"trend": None, "seasonal": None}),
)

# A forecast point more than this multiple of the historical max is treated
# as a blown-up fit rather than a real projection.
_SANITY_MULTIPLE = 10


@dataclass(slots=True)
class ForecastPoint:
    month: str  # "YYYY-MM"
    notices: int
    notices_lo: int
    notices_hi: int
    layoffs: int
    layoffs_lo: int
    layoffs_hi: int

    def to_payload(self) -> dict[str, Any]:
        return {
            "month": self.month,
            "notices": self.notices,
            "notices_lo": self.notices_lo,
            "notices_hi": self.notices_hi,
            "layoffs": self.layoffs,
            "layoffs_lo": self.layoffs_lo,
            "layoffs_hi": self.layoffs_hi,
        }


@dataclass(slots=True)
class Forecast:
    model: str  # "ets-seasonal" | "ets-trend" | "ets-level"
    history_months: int
    last_history_month: str
    points: list[ForecastPoint]  # exactly HORIZON entries, oldest first

    def to_payload(self) -> dict[str, Any]:
        return {
            "model": self.model,
            "history_months": self.history_months,
            "last_history_month": self.last_history_month,
            "points": [p.to_payload() for p in self.points],
        }


def _forecast_months(as_of: date, horizon: int) -> list[str]:
    """The `horizon` calendar months starting with as_of's month."""
    start = as_of.year * 12 + (as_of.month - 1)
    months = []
    for i in range(horizon):
        total = start + i
        months.append(f"{total // 12:04d}-{total % 12 + 1:02d}")
    return months


def _prep_series(
    monthly: list[tuple[str, int, int]], as_of: date
) -> tuple[list[str], list[float], list[float]]:
    """Drop the partial current month, zero-fill interior gaps. Returns
    (months, notices, layoffs) aligned, oldest first, complete months only.
    A month absent from `monthly` contributed no notices — same sum-over-no-
    rows semantics as warn_v2.reports.aggregate._zip_year_earlier."""
    cutoff = as_of.isoformat()[:7]
    complete = sorted((m, n, lt) for m, n, lt in monthly if m < cutoff)
    if not complete:
        return [], [], []
    by_month = {m: (n, lt) for m, n, lt in complete}
    first_y, first_mo = int(complete[0][0][:4]), int(complete[0][0][5:7])
    last_y, last_mo = int(complete[-1][0][:4]), int(complete[-1][0][5:7])

    months: list[str] = []
    notices: list[float] = []
    layoffs: list[float] = []
    y, mo = first_y, first_mo
    while (y, mo) <= (last_y, last_mo):
        key = f"{y:04d}-{mo:02d}"
        n, lt = by_month.get(key, (0, 0))
        months.append(key)
        notices.append(float(n))
        layoffs.append(float(lt))
        mo += 1
        if mo == 13:
            mo = 1
            y += 1
    return months, notices, layoffs


def _fit_tier(
    values: list[float], kwargs: dict[str, Any], horizon: int
) -> tuple[list[float], list[float], list[float]]:
    """Fit one ETS model on `values` and return (mean, lo, hi) for `horizon`
    steps ahead at an 80% prediction interval. Raises on any fitting failure
    — callers are expected to catch and fall back to the next ladder tier.

    ETSModel.get_prediction needs a pandas-indexed endog (it reads
    predicted_mean.index internally) — a bare numpy array raises
    AttributeError, so values are wrapped in a plain-RangeIndex Series."""
    import pandas as pd
    from statsmodels.tsa.exponential_smoothing.ets import ETSModel

    y = pd.Series(values, dtype=float)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        model = ETSModel(y, error="add", **kwargs)
        res = model.fit(disp=False)
        n = len(y)
        pred = res.get_prediction(start=n, end=n + horizon - 1)
        frame = pred.summary_frame(alpha=0.2)
    return (
        frame["mean"].tolist(),
        frame["pi_lower"].tolist(),
        frame["pi_upper"].tolist(),
    )


def _clamp(mean: float, lo: float, hi: float) -> tuple[int, int, int]:
    """Counts can never be negative and the band must always contain the
    point estimate, even after independently rounding each bound."""
    lo_i = max(0, round(lo))
    point_i = max(lo_i, max(0, round(mean)))
    hi_i = max(point_i, round(hi))
    return point_i, lo_i, hi_i


def _compute_forecast(
    monthly: list[tuple[str, int, int]], *, as_of: date, horizon: int
) -> Forecast | None:
    months, notices, layoffs = _prep_series(monthly, as_of)
    n = len(months)
    if n == 0:
        return None
    nonzero = min(sum(1 for v in notices if v > 0), sum(1 for v in layoffs if v > 0))
    notices_max = max(notices, default=0.0)
    layoffs_max = max(layoffs, default=0.0)
    forecast_months = _forecast_months(as_of, horizon)

    for model_id, min_n, min_nonzero, kwargs in _LADDER:
        if n < min_n or nonzero < min_nonzero:
            continue
        try:
            n_mean, n_lo, n_hi = _fit_tier(notices, kwargs, horizon)
            l_mean, l_lo, l_hi = _fit_tier(layoffs, kwargs, horizon)
        except Exception as exc:
            log.warning("forecast fit failed (%s): %s", model_id, exc)
            continue

        points: list[ForecastPoint] = []
        sane = True
        for i, month in enumerate(forecast_months):
            n_point, n_lo_i, n_hi_i = _clamp(n_mean[i], n_lo[i], n_hi[i])
            l_point, l_lo_i, l_hi_i = _clamp(l_mean[i], l_lo[i], l_hi[i])
            if (
                n_point > _SANITY_MULTIPLE * max(notices_max, 1.0)
                or l_point > _SANITY_MULTIPLE * max(layoffs_max, 1.0)
            ):
                sane = False
                break
            points.append(
                ForecastPoint(
                    month=month,
                    notices=n_point,
                    notices_lo=n_lo_i,
                    notices_hi=n_hi_i,
                    layoffs=l_point,
                    layoffs_lo=l_lo_i,
                    layoffs_hi=l_hi_i,
                )
            )
        if not sane:
            log.warning("forecast sanity check failed (%s)", model_id)
            continue
        return Forecast(
            model=model_id,
            history_months=n,
            last_history_month=months[-1],
            points=points,
        )
    return None


def compute_forecast(
    monthly: list[tuple[str, int, int]], *, as_of: date, horizon: int = HORIZON
) -> Forecast | None:
    """Fit a 6-month-ahead forecast from a monthly (month, notices, layoffs)
    series, oldest first. Tries a ladder of ETS models from most to least
    data-hungry (seasonal -> trend -> level-only) and returns the richest
    one the history supports; None when even the simplest tier is
    ineligible or every tier fails. Never raises."""
    try:
        return _compute_forecast(monthly, as_of=as_of, horizon=horizon)
    except Exception as exc:  # fail-open, matches warn_v2.reports.bls
        log.warning("forecast computation failed: %s", exc)
        return None


def _monthly_series_by_state(
    session: Session, start: date
) -> dict[str, list[tuple[str, int, int]]]:
    """Same filters as aggregate._monthly_series, grouped by state too."""
    period = func.substr(cast(Notice.notice_date, String), 1, 7).label("period")
    stmt = (
        select(
            Notice.state,
            period,
            func.count(Notice.notice_id),
            func.coalesce(func.sum(Notice.layoff_count), 0),
        )
        .where(
            Notice.is_superseded.is_(False),
            Notice.closure_category.is_distinct_from("Non-WARN"),
            Notice.notice_date.is_not(None),
            Notice.notice_date >= start,
        )
        .group_by(Notice.state, period)
        .order_by(Notice.state, period)
    )
    out: dict[str, list[tuple[str, int, int]]] = {}
    for state, m, n, lt in session.execute(stmt).all():
        out.setdefault(state, []).append((m, _int(n), _int(lt)))
    return out


def build_forecasts(session: Session, *, as_of: date | None = None) -> dict[str, Any]:
    """Fit a forecast for every jurisdiction with enough history: the
    national roll-up plus each state. Returns the forecasts.json payload;
    jurisdictions whose history doesn't clear even the lowest ladder tier
    are simply absent."""
    as_of = as_of or date.today()
    by_state = _monthly_series_by_state(session, _month_start_back(as_of, LOOKBACK_MONTHS - 1))

    national_totals: dict[str, list[int]] = {}
    for rows in by_state.values():
        for m, n, lt in rows:
            totals = national_totals.setdefault(m, [0, 0])
            totals[0] += n
            totals[1] += lt
    national_series = sorted((m, n, lt) for m, (n, lt) in national_totals.items())

    jurisdictions: dict[str, dict[str, Any]] = {}
    national_forecast = compute_forecast(national_series, as_of=as_of)
    if national_forecast is not None:
        jurisdictions[NATIONAL_CODE] = national_forecast.to_payload()

    for state, rows in sorted(by_state.items()):
        forecast = compute_forecast(rows, as_of=as_of)
        if forecast is not None:
            jurisdictions[state] = forecast.to_payload()

    return {"schema": 1, "as_of": as_of.isoformat(), "jurisdictions": jurisdictions}
