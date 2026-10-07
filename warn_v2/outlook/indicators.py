"""BLS series from `bls_series`, aligned to the outlook panel's months.

`fetch-bls` keeps the table current (see warn_v2.labor); catalog.series_id is
the only place ids are built. An empty table (the job hasn't run, or BLS was
down) yields empty series — every consumer treats that as "skip", never as
an error.
"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from warn_v2.db.models import BlsSeries
from warn_v2.labor import catalog
from warn_v2.outlook.panel import shift_month

# 12-month change in the unemployment rate, lagged one month: the
# percentage-point rise from t-13 to t-1. Year-over-year differencing removes
# seasonality and level differences between states; the one-month lag keeps
# the regressor strictly in the past, which a forecast can actually use.
YOY = 12
LAG = 1


def load(session: Session, series_ids: list[str]) -> dict[str, dict[str, float]]:
    """series_id -> {"YYYY-MM": value} for the requested ids."""
    out: dict[str, dict[str, float]] = {sid: {} for sid in series_ids}
    if not series_ids:
        return out
    stmt = select(BlsSeries.series_id, BlsSeries.period, BlsSeries.value).where(
        BlsSeries.series_id.in_(series_ids)
    )
    for sid, period, value in session.execute(stmt).all():
        out[sid][period] = value
    return out


def state_u3_ids(states: list[str]) -> dict[str, str]:
    """state -> LAUS unemployment-rate series id, for states BLS publishes."""
    ids = {}
    for st in states:
        sid = catalog.series_id("unemployment", area=st, measure="u3")
        if sid:
            ids[st] = sid
    return ids


def lagged_yoy_change(series: dict[str, float], months: list[str]) -> list[float | None]:
    """The lagged 12-month change aligned to `months`; None for a month that
    lacks either observation. BLS does skip months — the October 2025
    government shutdown cancelled that month's CPS and LAUS releases — so a
    gap must cost only the affected months, never the whole series."""
    out: list[float | None] = []
    for m in months:
        cur = series.get(shift_month(m, -LAG))
        prior = series.get(shift_month(m, -LAG - YOY))
        out.append(None if cur is None or prior is None else cur - prior)
    return out
