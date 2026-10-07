"""Turn tested results into plain-language claims — only the ones that pass.

A claim is emitted only when its evidence clears a gate: a Benjamini-Hochberg
q-value below Q_GATE for a family of tests (states, sectors), or a 95%
interval excluding zero for a single pooled estimate. Every claim carries its
evidence so the page can show "how we know".

Weaker evidence (q below Q_WATCH, or a pooled estimate past the one-sided 5%
line) becomes a "watch" item instead: worded as not yet established, and kept
visually apart from claims on the page. Thirty-six months of state data is
short, and a signal the reader can watch develop is worth more than silence
— as long as it is never dressed up as a finding.

Wording follows the site's framing rule (README, "Layoffs are job losses"):
a rise in layoff filings is bad news. Statements say rose / climbed / worsened
or eased / declined / fell, never added / grew / gained — test_outlook_claims
enforces it on every template.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

Q_GATE = 0.05
Q_STRONG = 0.01
Q_WATCH = 0.20
Z_GATE = 1.96
Z_STRONG = 2.576  # two-sided 1%, the single-estimate analogue of Q_STRONG
Z_WATCH = 1.645


@dataclass(slots=True)
class Claim:
    id: str
    horizon: str  # "near" | "mid" | "long"
    kind: str  # "state_trend" | "sector_share" | "national_trend" | "unemployment_link"
    subject: str  # state code, sector id, or "US"
    statement: str
    effect_pct: float
    ci_lo_pct: float
    ci_hi_pct: float
    q: float | None
    confidence: str  # "high" | "medium" | "watch"

    def to_payload(self) -> dict[str, Any]:
        out = asdict(self)
        for k in ("effect_pct", "ci_lo_pct", "ci_hi_pct"):
            out[k] = round(out[k], 1)
        if out["q"] is not None:
            out["q"] = round(out["q"], 4)
        return out


def _direction(pct: float) -> tuple[str, str]:
    """(verb, adjective) for a rise or a fall in layoff activity."""
    return ("rose", "worsening") if pct > 0 else ("eased", "improving")


def _confidence(q: float) -> str:
    return "high" if q < Q_STRONG else "medium" if q < Q_GATE else "watch"


def _z_confidence(z: float) -> str | None:
    z = abs(z)
    return "high" if z > Z_STRONG else "medium" if z > Z_GATE else "watch" if z > Z_WATCH else None


def _ci(lo: float, hi: float) -> str:
    return f"95% CI {lo:+.0f}% to {hi:+.0f}%"


def trend_claims(rows: list[dict[str, Any]], *, kind: str, window_months: int) -> list[Claim]:
    """Claims for the state or sector trend rows that clear the q gate."""
    years = window_months // 12
    out = []
    for r in rows:
        q = r.get("q")
        if q is None or q >= Q_WATCH:
            continue
        pct, lo, hi = r["pct_per_year"], r["ci_lo_pct"], r["ci_hi_pct"]
        verb, adj = _direction(pct)
        subject = (
            f"WARN layoff filings in {r['name']}"
            if kind == "state_trend"
            else f"{r['name']}'s share of WARN layoff filings"
        )
        if q >= Q_GATE:
            text = (
                f"Watch: {subject} {verb} about {abs(pct):.0f}% a year over the past {years} "
                f"years ({_ci(lo, hi)}), but across this many tests that is not yet "
                f"statistically established (q = {q:.2f})."
            )
        elif kind == "state_trend":
            text = (
                f"{subject} {verb} about {abs(pct):.0f}% a year over the past {years} years "
                f"({_ci(lo, hi)}), a {adj} trend that, if it holds, carries into the next "
                f"12 months."
            )
        else:
            text = (
                f"{subject} {verb} about {abs(pct):.0f}% a year over the past {years} years "
                f"({_ci(lo, hi)})."
            )
        out.append(
            Claim(
                id=f"{kind}:{r['code']}",
                horizon="mid",
                kind=kind,
                subject=r["code"],
                statement=text,
                effect_pct=pct,
                ci_lo_pct=lo,
                ci_hi_pct=hi,
                q=q,
                confidence=_confidence(q),
            )
        )
    out.sort(key=lambda c: (c.q, -abs(c.effect_pct)))
    return out


def national_claim(pooled: dict[str, Any] | None, *, window_months: int) -> Claim | None:
    """The random-effects pooled state trend, gated on its 95% interval."""
    confidence = _z_confidence(pooled["z"]) if pooled else None
    if confidence is None:
        return None
    pct = pooled["pct"]
    verb, adj = _direction(pct)
    lead = "Watch: pooled" if confidence == "watch" else "Pooled"
    tail = (
        "; the interval still includes no change, so this is not yet established."
        if confidence == "watch"
        else f", a {adj} national trend."
    )
    return Claim(
        id="national_trend:US",
        horizon="mid",
        kind="national_trend",
        subject="US",
        statement=(
            f"{lead} across {pooled['n_states']} states, WARN layoff filings in a typical state "
            f"{verb} about {abs(pct):.0f}% a year over the past {window_months // 12} years "
            f"({_ci(pooled['ci_lo_pct'], pooled['ci_hi_pct'])}){tail}"
        ),
        effect_pct=pct,
        ci_lo_pct=pooled["ci_lo_pct"],
        ci_hi_pct=pooled["ci_hi_pct"],
        q=None,
        confidence=confidence,
    )


def unemployment_claim(sensitivity: dict[str, Any] | None) -> Claim | None:
    """The pooled unemployment link, gated on BOTH the full-sample and the
    ex-2020 interval excluding zero, so the pandemic shock alone can't carry
    it."""
    if not sensitivity:
        return None
    full, robust = sensitivity.get("pooled"), sensitivity.get("pooled_ex_2020")
    if not full or not robust:
        return None
    for est in (full, robust):
        if est["ci_lo_pct"] * est["ci_hi_pct"] <= 0:
            return None
    if (full["pct"] > 0) != (robust["pct"] > 0):
        return None
    pct = full["pct"]
    direction = "more" if pct > 0 else "fewer"
    follow = " If unemployment rises, expect filings to follow." if pct > 0 else ""
    return Claim(
        id="unemployment_link:US",
        horizon="long",
        kind="unemployment_link",
        subject="US",
        statement=(
            f"Across {full['n_states']} states, each 1-point rise in a state's unemployment rate "
            f"over the prior year has come with about {abs(pct):.0f}% {direction} WARN layoff "
            f"filings the following month ({_ci(full['ci_lo_pct'], full['ci_hi_pct'])}; "
            f"{robust['pct']:+.0f}% excluding 2020-21).{follow}"
        ),
        effect_pct=pct,
        ci_lo_pct=full["ci_lo_pct"],
        ci_hi_pct=full["ci_hi_pct"],
        q=None,
        confidence="high" if min(abs(full["z"]), abs(robust["z"])) > Z_STRONG else "medium",
    )
