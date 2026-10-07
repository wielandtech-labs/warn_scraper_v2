"""Claim gates and wording (warn_v2.outlook.claims)."""
from __future__ import annotations

import re

import pytest

from warn_v2.outlook.claims import national_claim, trend_claims, unemployment_claim

# README "Layoffs are job losses": rising layoffs are never growth.
BANNED = re.compile(r"\b(add|added|adds|grow|grew|grows|growing|gain|gained|gains)\b", re.I)


def _row(code, q, pct):
    return {
        "code": code,
        "name": f"Name {code}",
        "pct_per_year": pct,
        "ci_lo_pct": pct - 10,
        "ci_hi_pct": pct + 10,
        "q": q,
    }


def _pooled(pct, z, lo=None, hi=None):
    return {
        "pct": pct,
        "ci_lo_pct": pct - 5 if lo is None else lo,
        "ci_hi_pct": pct + 5 if hi is None else hi,
        "z": z,
        "n_states": 40,
    }


class TestTrendClaims:
    def test_gates_and_tiers(self):
        rows = [
            _row("AA", 0.001, 30),
            _row("BB", 0.03, -20),
            _row("CC", 0.15, 25),
            _row("DD", 0.4, 50),
        ]
        claims = {c.subject: c for c in trend_claims(rows, kind="state_trend", window_months=36)}
        assert set(claims) == {"AA", "BB", "CC"}
        assert claims["AA"].confidence == "high"
        assert claims["BB"].confidence == "medium"
        assert claims["CC"].confidence == "watch"
        assert claims["CC"].statement.startswith("Watch:")
        assert "not yet statistically established" in claims["CC"].statement
        assert "eased" in claims["BB"].statement and "rose" in claims["AA"].statement

    def test_ordered_by_strength(self):
        rows = [_row("AA", 0.04, 10), _row("BB", 0.001, 5)]
        assert [c.subject for c in trend_claims(rows, kind="sector_share", window_months=36)] == [
            "BB",
            "AA",
        ]


class TestNationalClaim:
    @pytest.mark.parametrize(
        ("z", "tier"), [(3.0, "high"), (2.0, "medium"), (1.8, "watch"), (1.0, None)]
    )
    def test_tiers(self, z, tier):
        claim = national_claim(_pooled(6, z), window_months=36)
        assert (claim.confidence if claim else None) == tier

    def test_missing(self):
        assert national_claim(None, window_months=36) is None


class TestUnemploymentClaim:
    def _link(self, full, robust):
        return {"pooled": full, "pooled_ex_2020": robust}

    def test_needs_both_fits_to_agree(self):
        assert unemployment_claim(self._link(_pooled(16, 14), _pooled(21, 8))).confidence == "high"
        # The ex-2020 interval spans zero: the pandemic alone carried it.
        assert unemployment_claim(self._link(_pooled(16, 14), _pooled(3, 1, -2, 8))) is None
        assert unemployment_claim(self._link(_pooled(16, 14), None)) is None
        assert unemployment_claim(None) is None


def test_no_banned_growth_words_in_any_template():
    statements = []
    for q in (0.001, 0.03, 0.15):
        for pct in (40, -40):
            for kind in ("state_trend", "sector_share"):
                claims = trend_claims([_row("AA", q, pct)], kind=kind, window_months=36)
                statements += [c.statement for c in claims]
    for z in (3.0, 1.8):
        for pct in (6, -6):
            statements.append(national_claim(_pooled(pct, z), window_months=36).statement)
    for pct in (16, -16):
        link = {"pooled": _pooled(pct, 9), "pooled_ex_2020": _pooled(pct, 9)}
        statements.append(unemployment_claim(link).statement)
    assert len(statements) == 18
    for s in statements:
        assert not BANNED.search(s), s
