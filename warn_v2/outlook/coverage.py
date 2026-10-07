"""Which months of a state's series are real data, and which are holes.

States joined the dataset in different years, several were backfilled
unevenly, states publish on different lags, and a scraper can go silently
stale — on 2026-10-07 California held 6 notices for July and none for August
against ~120 a month, and Illinois and Oregon were blank for their last two or
three months, because all three scrapers were reading a stale source (fixed in
#334). Either way a zero there means "missing", not "no layoffs", and fitting
it as a zero would manufacture a collapse. So each month is classified instead
of each state:

- months before the state's first-ever notice are missing (not yet covered);
- a trailing run whose joint Poisson probability under the state's typical
  level is below GAP_P is missing (publication lag or a stale feed);
- an interior run of empty months that improbable is missing (a coverage
  hole, e.g. a scraper outage later never backfilled).

The typical level is the median month, which the holes themselves can't drag
down the way they would a mean. A state is left out entirely only when fewer
than MIN_USABLE months, or less than MIN_USABLE_SHARE of the window, survive.
"""
from __future__ import annotations

import math

GAP_P = 1e-3
MIN_USABLE = 24
MIN_USABLE_SHARE = 2 / 3
MAX_TRAILING = 6  # never trim more than this many months off the end


def _poisson_cdf(k: int, lam: float) -> float:
    term = total = math.exp(-lam)
    for i in range(1, k + 1):
        term *= lam / i
        total += term
    return min(1.0, total)


def _median(values: list[int]) -> float:
    s = sorted(values)
    n = len(s)
    return float(s[n // 2]) if n % 2 else (s[n // 2 - 1] + s[n // 2]) / 2


def usable_months(counts: list[int], months: list[str], *, first_seen: str | None) -> list[bool]:
    """mask[i] is True when months[i] is real data rather than a hole."""
    n = len(counts)
    if first_seen is None or n == 0:
        return [False] * n
    mask = [m >= first_seen[:7] for m in months]
    level = _median([c for c, ok in zip(counts, mask, strict=True) if ok] or [0])

    if level > 0:
        # Data frontier: the longest improbably-low trailing run.
        joint, cut = 1.0, 0
        for k in range(1, min(MAX_TRAILING, n) + 1):
            c = counts[n - k]
            if c >= level:
                break
            joint *= _poisson_cdf(c, level)
            if joint < GAP_P:
                cut = k
        for i in range(n - cut, n):
            mask[i] = False

        # Interior holes: runs of zeros no Poisson month at this level produces.
        i = 0
        while i < n:
            if counts[i] != 0 or not mask[i]:
                i += 1
                continue
            j = i
            while j < n and counts[j] == 0 and mask[j]:
                j += 1
            if math.exp(-level * (j - i)) < GAP_P:
                for k in range(i, j):
                    mask[k] = False
            i = j

    return mask


def exclusion_reason(mask: list[bool], *, min_share: float = MIN_USABLE_SHARE) -> str | None:
    """None when enough of the window is usable to fit; else why not.
    `min_share` guards a fixed trend window against states that cover only a
    sliver of it; a long regression window passes 0 and needs only
    MIN_USABLE months."""
    usable, n = sum(mask), len(mask)
    if usable < MIN_USABLE or usable < min_share * n:
        return f"only {usable} of {n} months usable"
    return None
