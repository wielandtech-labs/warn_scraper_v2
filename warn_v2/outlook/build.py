"""Assemble outlook.json: trend tests, the unemployment link, and claims.

Called by the weekly sentiment-report CronJob, fail-open like
build_forecasts. Every section degrades to empty or null on thin data or an
empty bls_series table rather than raising.

Each state's months are masked by warn_v2.outlook.coverage (holes and its
data frontier are missing data, not zeros), and every fit uses only
that state's usable months. There is deliberately no fit on a summed national
series: states publish on different lags, so the sum's last months would mix
complete and incomplete states. The national headline is instead the
random-effects pool of the per-state trends.
"""
from __future__ import annotations

import math
from datetime import date, timedelta
from typing import Any

from sqlalchemy.orm import Session

from warn_v2.companies.naics import SECTOR_NAME
from warn_v2.outlook import claims as claims_mod
from warn_v2.outlook import indicators
from warn_v2.outlook.coverage import exclusion_reason, usable_months
from warn_v2.outlook.panel import Panel, build_panel, shift_month
from warn_v2.outlook.trends import CI_Z, Fit, bh_qvalues, fit_trend, shrink
from warn_v2.states import STATE_NAMES

OUTLOOK_JSON = "outlook.json"
SCHEMA = 1

TREND_MONTHS = 36
# Late filings keep arriving for weeks (prod: 90% of notices are scraped
# within 19 days of their notice date, 99% within 56). A month counts only
# once it ended at least this long ago; longer per-state publication lags are
# caught by the coverage mask.
SETTLE_DAYS = 30
# The pandemic shock, dropped in the robustness refit of the unemployment link.
SHOCK_MONTHS = ("2020-03", "2021-06")


def settled_months(months: list[str], as_of: date) -> list[str]:
    out = []
    for m in months:
        nxt = shift_month(m, 1)
        month_end = date(int(nxt[:4]), int(nxt[5:7]), 1)
        if month_end + timedelta(days=SETTLE_DAYS) <= as_of:
            out.append(m)
    return out


def _r(x: float, nd: int = 2) -> float:
    return round(x, nd)


def _pct(log: float) -> float:
    return _r(100 * math.expm1(log), 1)


def _pick(values: list, mask: list[bool]) -> list:
    return [v for v, ok in zip(values, mask, strict=True) if ok]


class _Masked:
    """One state's (notices, layoffs) series over a month list, with its mask."""

    def __init__(self, panel: Panel, state: str, months: list[str]):
        index = {m: i for i, m in enumerate(panel.months)}
        series = panel.series(states={state})
        self.months = months
        self.notices = [series[index[m]][0] for m in months]
        self.layoffs = [series[index[m]][1] for m in months]
        self.mask = usable_months(self.notices, months, first_seen=panel.first_seen.get(state))


def _fit_row(code: str, name: str, fit: Fit, notices: list[int], layoffs: Fit | None) -> dict:
    lo, hi = fit.ci_pct()
    return {
        "code": code,
        "name": name,
        "pct_per_year": _r(fit.pct, 1),
        "ci_lo_pct": _r(lo, 1),
        "ci_hi_pct": _r(hi, 1),
        "t": _r(fit.t),
        "p": _r(fit.p, 4),
        "months": fit.n_months,
        "notices": sum(notices),
        "layoffs_pct_per_year": _r(layoffs.pct, 1) if layoffs else None,
        "layoffs_t": _r(layoffs.t) if layoffs else None,
    }


def _add_q(rows: list[dict]) -> None:
    for row, q in zip(rows, bh_qvalues([r["p"] for r in rows]), strict=True):
        row["q"] = _r(q, 4)


def _pool(fits: list[Fit], rows: list[dict] | None = None) -> dict[str, Any] | None:
    """Random-effects pooled estimate; with `rows`, also writes each row's
    empirical-Bayes posterior (shrunk_pct, shrunk_z)."""
    pooled = shrink([(f.coef, f.se) for f in fits])
    if pooled is None:
        return None
    if rows is not None:
        for row, (post, sd) in zip(rows, pooled.posteriors, strict=True):
            row["shrunk_pct"] = _pct(post)
            row["shrunk_z"] = _r(post / sd)
    return {
        "pct": _pct(pooled.mu),
        "ci_lo_pct": _pct(pooled.mu - CI_Z * pooled.mu_se),
        "ci_hi_pct": _pct(pooled.mu + CI_Z * pooled.mu_se),
        "z": _r(pooled.mu / pooled.mu_se),
        "tau_pct": _pct(math.sqrt(pooled.tau2)),
        "n_states": len(fits),
    }


def _state_trends(panel: Panel, window: list[str]) -> tuple[dict[str, Any], dict[str, list[bool]]]:
    rows, fits, excluded, masks = [], [], {}, {}
    for st in panel.states:
        if st not in STATE_NAMES:
            continue
        s = _Masked(panel, st, window)
        reason = exclusion_reason(s.mask)
        fit = None if reason else fit_trend(_pick(s.notices, s.mask), _pick(window, s.mask))
        if fit is None:
            excluded[st] = reason or "too few notices"
            continue
        masks[st] = s.mask
        layoffs = fit_trend(_pick(s.layoffs, s.mask), _pick(window, s.mask))
        row = _fit_row(st, STATE_NAMES[st], fit, _pick(s.notices, s.mask), layoffs)
        row["last_month"] = _pick(window, s.mask)[-1]
        rows.append(row)
        fits.append(fit)
    _add_q(rows)
    pooled = _pool(fits, rows)
    return (
        {
            "states": sorted(rows, key=lambda r: -r["t"]),
            "excluded": dict(sorted(excluded.items())),
            "pooled": pooled,
        },
        masks,
    )


def _sector_trends(panel: Panel, window: list[str], masks: dict[str, list[bool]]) -> list[dict]:
    """Each sector's SHARE of NAICS-classified notices, summed over the fitted
    states' usable months only. Share, not count: enrichment coverage changes
    over time, and a count trend would mostly measure that."""
    if not masks:
        return []
    index = {m: i for i, m in enumerate(panel.months)}
    cols = [index[m] for m in window]
    by_sector: dict[str, list[int]] = {}
    exposure = [0] * len(window)
    for (st, sec), series in panel.cells.items():
        mask = masks.get(st)
        if mask is None or sec is None:
            continue
        counts = [series[c][0] if ok else 0 for c, ok in zip(cols, mask, strict=True)]
        acc = by_sector.setdefault(sec, [0] * len(window))
        for i, v in enumerate(counts):
            acc[i] += v
            exposure[i] += v
    keep = [e > 0 for e in exposure]
    months, offset = _pick(window, keep), _pick(exposure, keep)
    rows, fits = [], []
    for sector, counts in sorted(by_sector.items()):
        counts = _pick(counts, keep)
        fit = fit_trend(counts, months, offset=offset)
        if fit is None:
            continue
        rows.append(_fit_row(sector, SECTOR_NAME.get(sector, sector), fit, counts, None))
        fits.append(fit)
    _add_q(rows)
    _pool(fits, rows)
    return sorted(rows, key=lambda r: -r["t"])


def _unemployment_link(session: Session, panel: Panel, months: list[str]) -> dict | None:
    """Per-state effect of the lagged 12-month change in the state
    unemployment rate on monthly notices (trend + seasonality controlled),
    pooled by random effects; refit without the pandemic shock months."""
    ids = indicators.state_u3_ids([s for s in panel.states if s in STATE_NAMES])
    u3 = indicators.load(session, list(ids.values()))
    lo, hi = SHOCK_MONTHS
    rows, full, robust = [], [], []
    for st, sid in sorted(ids.items()):
        x = indicators.lagged_yoy_change(u3[sid], months)
        s = _Masked(panel, st, months)
        mask = [ok and v is not None for ok, v in zip(s.mask, x, strict=True)]
        if exclusion_reason(mask, min_share=0):
            continue
        calm = [ok and not lo <= m <= hi for m, ok in zip(months, mask, strict=True)]
        fit = fit_trend(_pick(s.notices, mask), _pick(months, mask), covariate=_pick(x, mask))
        fit_calm = fit_trend(_pick(s.notices, calm), _pick(months, calm), covariate=_pick(x, calm))
        if fit is None or fit_calm is None:
            continue
        ci_lo, ci_hi = fit.ci_pct()
        rows.append(
            {
                "code": st,
                "name": STATE_NAMES[st],
                "pct": _r(fit.pct, 1),
                "ci_lo_pct": _r(ci_lo, 1),
                "ci_hi_pct": _r(ci_hi, 1),
                "t": _r(fit.t),
                "p": _r(fit.p, 4),
                "months": fit.n_months,
            }
        )
        full.append(fit)
        robust.append(fit_calm)
    if not rows:
        return None
    _add_q(rows)
    return {
        "regressor": "12-month change in the state unemployment rate (points), lagged 1 month",
        "first_month": months[0],
        "last_month": months[-1],
        "states": sorted(rows, key=lambda r: -r["t"]),
        "pooled": _pool(full),
        "pooled_ex_2020": _pool(robust),
    }


def build_outlook(session: Session, *, as_of: date | None = None) -> dict[str, Any]:
    as_of = as_of or date.today()
    panel = build_panel(session, as_of=as_of)
    settled = settled_months(panel.months, as_of)
    window = settled[-TREND_MONTHS:]

    if window:
        trends, masks = _state_trends(panel, window)
    else:
        trends, masks = {"states": [], "excluded": {}, "pooled": None}, {}
    sectors = _sector_trends(panel, window, masks)
    link = _unemployment_link(session, panel, settled) if settled else None

    claims = [
        c
        for c in (
            claims_mod.national_claim(trends["pooled"], window_months=len(window)),
            claims_mod.unemployment_claim(link),
        )
        if c is not None
    ]
    n = len(window)
    claims += claims_mod.trend_claims(trends["states"], kind="state_trend", window_months=n)
    claims += claims_mod.trend_claims(sectors, kind="sector_share", window_months=n)

    return {
        "schema": SCHEMA,
        "as_of": as_of.isoformat(),
        "window": {
            "first_month": window[0] if window else None,
            "last_month": window[-1] if window else None,
            "months": len(window),
        },
        "method": {
            "trend": "quasi-Poisson GLM with month-of-year dummies; AR(1)-inflated SE; t(df) test",
            "coverage": "per-state masks drop pre-coverage months, holes and an incomplete trailing edge",
            "multiple_testing": "Benjamini-Hochberg q-values within each family",
            "pooling": "DerSimonian-Laird random effects; empirical-Bayes shrinkage",
            "settle_days": SETTLE_DAYS,
        },
        "trends": trends,
        "sectors": sectors,
        "unemployment_link": link,
        "claims": [c.to_payload() for c in claims],
    }
