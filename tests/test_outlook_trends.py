"""Statistical properties of warn_v2.outlook.trends on synthetic series with a
known truth: planted effects are found, null series are not (at about the
nominal rate), and the pooling/FDR helpers match their textbook definitions."""
from __future__ import annotations

import math

import numpy as np
import pytest

from warn_v2.outlook.panel import month_range
from warn_v2.outlook.trends import ar1_inflation, bh_qvalues, fit_trend, shrink

MONTHS = month_range("2023-01", "2025-12")  # 36


def _nb(rng, lam, k=5.0):
    """Overdispersed counts (negative binomial, mean lam, shape k)."""
    lam = np.asarray(lam, dtype=float)
    return rng.negative_binomial(k, k / (k + lam)).tolist()


def _seasonal_level(months, base=30.0):
    return np.array([base * (1.6 if m.endswith(("-01", "-07")) else 1.0) for m in months])


class TestFitTrend:
    def test_planted_rise_is_found_with_the_right_size(self):
        rng = np.random.default_rng(1)
        years = np.arange(36) / 12
        y = _nb(rng, _seasonal_level(MONTHS) * np.exp(np.log(1.5) * years))
        fit = fit_trend(y, MONTHS)
        assert fit is not None
        assert fit.t > 2.5
        lo, hi = fit.ci_pct()
        assert lo < 50 < hi  # +50%/yr inside the 95% interval

    def test_planted_fall_has_negative_t(self):
        rng = np.random.default_rng(2)
        years = np.arange(36) / 12
        fit = fit_trend(_nb(rng, _seasonal_level(MONTHS) * np.exp(-0.5 * years)), MONTHS)
        assert fit is not None and fit.t < -2.5 and fit.pct < 0

    def test_seasonality_alone_is_not_a_trend(self):
        # A window starting in a spike month and ending before one would bias
        # a trend fit without month dummies; with them, no effect.
        rng = np.random.default_rng(3)
        fit = fit_trend(_nb(rng, _seasonal_level(MONTHS), k=200), MONTHS)
        assert fit is not None and abs(fit.t) < 2

    def test_null_false_positive_rate_near_nominal(self):
        hits = 0
        trials = 200
        for seed in range(trials):
            y = _nb(np.random.default_rng(seed), np.full(36, 20.0))
            fit = fit_trend(y, MONTHS)
            hits += fit is not None and fit.p < 0.05
        assert hits / trials <= 0.09

    def test_thin_series_returns_none(self):
        assert fit_trend([0] * 30 + [1] * 6, MONTHS) is None
        assert fit_trend([5] * 12, MONTHS[:12]) is None

    def test_offset_measures_share_not_volume(self):
        # Exposure doubles over the window and the sector keeps a constant
        # 20% share: its count doubles, its share trend is flat.
        rng = np.random.default_rng(4)
        exposure = np.linspace(100, 200, 36)
        y = rng.poisson(0.2 * exposure).tolist()
        count_fit = fit_trend(y, MONTHS)
        share_fit = fit_trend(y, MONTHS, offset=exposure.tolist())
        assert count_fit is not None and count_fit.t > 2
        assert share_fit is not None and abs(share_fit.t) < 2.5

    def test_covariate_effect_recovered_controlling_for_trend(self):
        rng = np.random.default_rng(5)
        months = month_range("2016-01", "2025-12")
        x = np.sin(np.arange(120) / 9.0) * 2  # a unemployment-change-like cycle
        y = _nb(rng, 20 * np.exp(0.15 * x), k=20)
        fit = fit_trend(y, months, covariate=x.tolist())
        assert fit is not None
        assert fit.t > 3
        assert fit.ci_pct()[0] < 100 * math.expm1(0.15) < fit.ci_pct()[1]

    def test_months_with_gaps_use_calendar_time(self):
        # Dropping a block of months must not compress the time axis: a
        # steady +30%/yr rise stays ~+30%/yr with the middle year removed.
        rng = np.random.default_rng(6)
        months = month_range("2020-01", "2025-12")
        years = np.arange(72) / 12
        y = _nb(rng, 40 * np.exp(np.log(1.3) * years), k=50)
        keep = [i for i, m in enumerate(months) if not m.startswith("2022")]
        fit = fit_trend([y[i] for i in keep], [months[i] for i in keep])
        assert fit is not None
        assert 20 < fit.pct < 40


class TestAr1Inflation:
    def test_independent_residuals_barely_inflate(self):
        rng = np.random.default_rng(7)
        assert ar1_inflation(rng.normal(size=500).tolist()) < 1.1

    def test_persistent_residuals_inflate(self):
        rng = np.random.default_rng(8)
        e = [0.0]
        for _ in range(299):
            e.append(0.7 * e[-1] + rng.normal())
        assert ar1_inflation(e) > 4

    def test_constant_residuals(self):
        assert ar1_inflation([1.0] * 10) == 1.0


def test_bh_qvalues_matches_statsmodels():
    from statsmodels.stats.multitest import multipletests

    p = [0.001, 0.2, 0.04, 0.03, 0.9, 0.012, 0.5]
    expected = multipletests(p, method="fdr_bh")[1]
    assert bh_qvalues(p) == pytest.approx(list(expected))


class TestShrink:
    def test_homogeneous_estimates_pool_to_their_mean(self):
        pooled = shrink([(0.1, 0.05), (0.1, 0.1), (0.1, 0.2)])
        assert pooled is not None
        assert pooled.tau2 == 0
        assert pooled.mu == pytest.approx(0.1)
        for post, _sd in pooled.posteriors:
            assert post == pytest.approx(0.1)

    def test_noisy_estimates_shrink_more(self):
        est = [(0.5, 0.05), (0.5, 0.5), (-0.2, 0.05), (0.1, 0.05), (0.0, 0.05)]
        pooled = shrink(est)
        assert pooled is not None and pooled.tau2 > 0
        precise, noisy = pooled.posteriors[0][0], pooled.posteriors[1][0]
        # Same raw estimate; the noisy one is pulled much closer to mu.
        assert abs(noisy - pooled.mu) < abs(precise - pooled.mu)

    def test_needs_three(self):
        assert shrink([(0.1, 0.1), (0.2, 0.1)]) is None
