"""Synthetic notice histories for the repeat-layoff model tests."""
from __future__ import annotations

from datetime import date, timedelta

import numpy as np
import pandas as pd

from warn_v2.ml.events import NOTICE_COLUMNS, _clean


def notices_frame(rows: list[dict]) -> pd.DataFrame:
    """Rows -> the cleaned frame load_notices() returns. Each row needs
    company_key, state, notice_date; the rest default."""
    out = []
    for i, r in enumerate(rows):
        out.append({
            "notice_id": r.get("notice_id", f"n{i}"),
            "state": r["state"],
            "employer": r.get("employer", r["company_key"]),
            "notice_date": r["notice_date"],
            "effective_date": r.get("effective_date"),
            "layoff_count": r.get("layoff_count", 50),
            "closure_category": r.get("closure_category", "Layoff"),
            "company_key": r["company_key"],
        })
    return _clean(pd.DataFrame(out, columns=NOTICE_COLUMNS))


def background(state: str, start: date, end: date, per_month: int = 12,
               skip_months: set[str] | None = None, seed: int = 0) -> list[dict]:
    """One-off filers at a steady pace, so the state's coverage mask is solid
    (minus `skip_months`, which become holes)."""
    rng = np.random.default_rng(seed)
    rows, d, k = [], start, 0
    while d <= end:
        if f"{d:%Y-%m}" not in (skip_months or set()):
            for day in sorted(rng.integers(0, 28, per_month)):
                rows.append({"company_key": f"bg-{state}-{k}", "state": state,
                             "notice_date": d + timedelta(days=int(day))})
                k += 1
        d = (d.replace(day=1) + timedelta(days=32)).replace(day=1)
    return rows


def population(seed: int = 0, n_companies: int = 3000,
               start: date = date(2004, 1, 1), end: date = date(2022, 12, 31)) -> pd.DataFrame:
    """Companies whose repeat propensity is visible in their history: a
    latent 'distressed' share files roughly every 4-8 months, everyone else
    once. Plus steady background volume in each state."""
    rng = np.random.default_rng(seed)
    states = ["AA", "BB", "CC"]
    rows: list[dict] = []
    span = (end - start).days
    for c in range(n_companies):
        st = states[c % 3]
        d = start + timedelta(days=int(rng.integers(0, span)))
        distressed = rng.random() < 0.3
        while d <= end:
            rows.append({"company_key": f"c{c}", "state": st, "notice_date": d,
                         "layoff_count": int(rng.integers(20, 400))})
            if not distressed and rng.random() < 0.9:
                break
            d += timedelta(days=int(rng.integers(120, 240) if distressed
                                    else rng.integers(400, 2000)))
    for i, st in enumerate(states):
        rows += background(st, start, end, seed=i)
    return notices_frame(rows)
