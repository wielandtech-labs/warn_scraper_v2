"""Trend tests: is layoff activity really rising or easing, and how sure are we?

fit_trend fits log E[y_t] = a + b * years_t + seasonal(month_t) [+ log offset_t]
as a quasi-Poisson GLM, with the slope's variance inflated for AR(1)
autocorrelation in the Pearson residuals:

- Poisson QMLE gives a consistent trend estimate for counts even when they are
  overdispersed, which WARN counts always are; the Pearson-chi2 scale makes
  the standard error honest about that overdispersion.
- Month-to-month persistence shrinks the effective sample size. The slope's
  variance is multiplied by (1 + rho) / (1 - rho), with rho the lag-1
  residual autocorrelation after Marriott-Pope small-sample bias correction.
  Newey-West (HAC) errors were tried first and rejected: simulated on 36-month
  null series they rejected 19-25% of the time at a nominal 5%. This test
  holds ~4-5% on independent data and ~8% at rho = 0.5; measured on prod
  data, residual rho has median 0.04 and 90th percentile 0.32.
- Month-of-year dummies absorb seasonality (January and July filings spike),
  so the slope isn't fooled by where in the year the window starts and ends.
- `offset` turns a count trend into a rate trend: a sector's notices against
  all NAICS-classified notices measures the sector's SHARE, which is immune to
  enrichment coverage changing over time.
- Inference uses t(df_resid) rather than z: with 36 months and 13 parameters,
  the normal approximation is visibly anti-conservative.

`bh_qvalues` controls the false discovery rate across the ~50 states and ~20
sectors tested at once; `shrink` is a DerSimonian-Laird random-effects model
whose empirical-Bayes posteriors pull noisy small-state slopes toward the
pooled slope.
"""
from __future__ import annotations

import itertools
import math
import warnings
from collections.abc import Sequence
from dataclasses import dataclass

MIN_MONTHS = 24
MIN_NONZERO = 12
MIN_TOTAL = 30
CI_Z = 1.96


@dataclass(slots=True)
class Fit:
    """One tested coefficient on the log scale: the trend (per year) or a
    covariate's effect (per unit of the covariate)."""

    coef: float
    se: float
    t: float
    p: float
    n_months: int
    total: int

    @property
    def pct(self) -> float:
        """The coefficient as a percent change in the expected count."""
        return 100.0 * math.expm1(self.coef)

    def ci_pct(self, z: float = CI_Z) -> tuple[float, float]:
        return (
            100.0 * math.expm1(self.coef - z * self.se),
            100.0 * math.expm1(self.coef + z * self.se),
        )


def ar1_inflation(resid: Sequence[float]) -> float:
    """Variance inflation (1 + rho) / (1 - rho) for a trend slope under AR(1)
    errors. rho is bias-corrected (Marriott-Pope: + (1 + 3 rho) / n), floored at
    0 so negative autocorrelation never narrows the interval, and capped."""
    n = len(resid)
    mean = sum(resid) / n
    dev = [r - mean for r in resid]
    var = sum(d * d for d in dev)
    if var <= 0:
        return 1.0
    rho = sum(a * b for a, b in itertools.pairwise(dev)) / var
    rho = max(0.0, rho)
    rho = min(0.9, rho + (1 + 3 * rho) / n)
    return (1 + rho) / (1 - rho)


def fit_trend(
    counts: Sequence[float],
    months: Sequence[str],
    *,
    offset: Sequence[float] | None = None,
    covariate: Sequence[float] | None = None,
) -> Fit | None:
    """Fit the seasonal Poisson trend and return the tested coefficient: the
    yearly trend, or — when `covariate` is given — the covariate's effect with
    the trend kept as a control (so two series that merely drift together over
    the years don't look related). None when the series is too thin to say
    anything or the fit fails. Never raises."""
    n = len(counts)
    total = int(sum(counts))
    nonzero = sum(1 for c in counts if c > 0)
    if n < MIN_MONTHS or nonzero < MIN_NONZERO or total < MIN_TOTAL:
        return None
    if offset is not None and any(o <= 0 for o in offset):
        return None
    try:
        return _fit(counts, months, offset, covariate)
    except Exception:
        return None


def _fit(counts, months, offset, covariate) -> Fit | None:
    import numpy as np
    import statsmodels.api as sm
    from scipy import stats

    n = len(counts)
    # Time from the actual month, not the row index: robustness refits drop
    # months (e.g. the 2020 shock), and the trend must not close the gap.
    idx = np.array([int(m[:4]) * 12 + int(m[5:7]) for m in months], dtype=float)
    years = (idx - idx.mean()) / 12.0
    moy = np.array([int(m[5:7]) for m in months])
    dummies = np.column_stack([(moy == k).astype(float) for k in range(2, 13)])
    keep = dummies.any(axis=0)  # a window shorter than a year lacks some months
    cols = [np.ones(n), years, dummies[:, keep]]
    if covariate is not None:
        cols.insert(2, np.asarray(covariate, dtype=float))
    X = np.column_stack(cols)
    target = 1 if covariate is None else 2
    y = np.asarray(counts, dtype=float)
    kw = {"offset": np.log(np.asarray(offset, dtype=float))} if offset is not None else {}
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        res = sm.GLM(y, X, family=sm.families.Poisson(), **kw).fit(scale="X2")
    coef = float(res.params[target])
    se = float(res.bse[target]) * math.sqrt(ar1_inflation(list(res.resid_pearson)))
    if not (math.isfinite(coef) and math.isfinite(se)) or se <= 0:
        return None
    t = coef / se
    return Fit(
        coef=coef,
        se=se,
        t=t,
        p=float(2 * stats.t.sf(abs(t), res.df_resid)),
        n_months=n,
        total=int(y.sum()),
    )


def bh_qvalues(pvalues: Sequence[float]) -> list[float]:
    """Benjamini-Hochberg adjusted p-values (q-values), in input order."""
    m = len(pvalues)
    order = sorted(range(m), key=lambda i: pvalues[i])
    q = [0.0] * m
    running = 1.0
    for rank in range(m, 0, -1):
        i = order[rank - 1]
        running = min(running, pvalues[i] * m / rank)
        q[i] = running
    return q


@dataclass(slots=True)
class Pooled:
    mu: float  # pooled slope (log-rate per year)
    mu_se: float
    tau2: float  # between-jurisdiction variance of true slopes
    posteriors: list[tuple[float, float]]  # (slope, sd) per input, shrunk


def shrink(estimates: Sequence[tuple[float, float]]) -> Pooled | None:
    """DerSimonian-Laird random-effects pooling of (slope, se) pairs plus the
    empirical-Bayes posterior for each: slope_i* = (1-B_i) slope_i + B_i mu,
    B_i = se_i^2 / (se_i^2 + tau^2). None with fewer than 3 estimates."""
    k = len(estimates)
    if k < 3:
        return None
    w = [1.0 / se**2 for _, se in estimates]
    sw = sum(w)
    mu_fe = sum(wi * b for wi, (b, _) in zip(w, estimates, strict=True)) / sw
    q = sum(wi * (b - mu_fe) ** 2 for wi, (b, _) in zip(w, estimates, strict=True))
    denom = sw - sum(wi * wi for wi in w) / sw
    tau2 = max(0.0, (q - (k - 1)) / denom) if denom > 0 else 0.0
    w_re = [1.0 / (se**2 + tau2) for _, se in estimates]
    mu = sum(wi * b for wi, (b, _) in zip(w_re, estimates, strict=True)) / sum(w_re)
    mu_var = 1.0 / sum(w_re)
    posteriors = []
    for b, se in estimates:
        shrink_b = se**2 / (se**2 + tau2) if tau2 > 0 else 1.0
        post = (1 - shrink_b) * b + shrink_b * mu
        var = (1 - shrink_b) * se**2 + shrink_b**2 * mu_var
        posteriors.append((post, math.sqrt(var)))
    return Pooled(mu=mu, mu_se=math.sqrt(mu_var), tau2=tau2, posteriors=posteriors)
