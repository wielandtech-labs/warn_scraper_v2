"""Repeat-layoff dataset: employer events, labels, and point-in-time features.

The question: an employer files a WARN notice today — will it file another
one 1-12 months from now?

Unit of prediction is an *event*, not a notice. One reduction in force is
routinely filed as many notices (one per site, per state, plus amendments),
and counting those as "repeats" would make the task trivial and the score
useless. So per company, an event opens at its first notice (t0); notices in
the next EVENT_GAP_DAYS belong to it and are ignored; the next notice after
that opens the next event.

- Prediction time is t0. Every feature reads only notices dated <= t0
  (same-day multi-site filings are known at t0; anything later is not).
- Label: the company files again in (t0 + EVENT_GAP_DAYS, t0 + HORIZON_DAYS],
  i.e. the next event starts within the horizon.
- Censoring: an event is labelled only once its whole horizon is in the past
  AND its state's coverage is real data for every month of that horizon
  (warn_v2.outlook.coverage) — a scraper hole would read as "never filed
  again" and plant false negatives.

Caveat the model card repeats: notice dates are not arrival dates. Historical
backfills were scraped years later, so "dated <= t0" is the best available
point-in-time proxy, not a replay of what the site knew on t0.
"""
from __future__ import annotations

import json
import math
from collections.abc import Iterable
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
from sqlalchemy import select
from sqlalchemy.orm import Session

from warn_v2.companies.normalize import canonical_name
from warn_v2.db.models import Company, Notice
from warn_v2.outlook.coverage import usable_months
from warn_v2.outlook.panel import month_range

EVENT_GAP_DAYS = 30
HORIZON_DAYS = 365
MIN_DATE = date(1988, 1, 1)
MAX_COUNT = 50_000  # the audit's sanity ceiling; larger counts are typos
DEFAULT_LEAD_DAYS = 60  # effective_date imputed as notice_date + 60 when missing
# SC published only the year for 2013-2021 (notice_date = Jan 1), which would
# fuse a year of filings into one fake event.
PLACEHOLDER_DATES = {"SC": (2013, 2021)}

NOTICE_COLUMNS = [
    "notice_id", "state", "employer", "notice_date", "effective_date",
    "layoff_count", "closure_category", "company_key",
]

# The model's inputs, in order. Kept WARN-derived on purpose: enrichment fields
# (NAICS, employee count) are present-day snapshots — a company's current
# headcount already reflects the layoffs we'd be predicting — and partly
# provider-licensed.
NUMERIC_FEATURES = [
    "day_notices",          # notices filed on t0 (multi-site breadth)
    "day_states",           # distinct states on t0
    "day_layoffs_log",      # log1p(known affected workers on t0)
    "day_count_missing",    # no notice on t0 reported a count
    "day_closure_frac",     # share of t0 notices that are closures
    "lead_days",            # median effective - notice gap on t0
    "lead_is_default",      # that gap is exactly the imputed 60-day default
    "prior_notices_1y",
    "prior_notices_3y",
    "prior_events",         # events before this one, all history
    "days_since_prev_log",  # log1p days since the previous notice (0 if none)
    "has_prior",
    "prior_layoffs_log",
    "prior_states",
    "state_cov_years",      # how long the state has been covered at t0
    "state_notices_90d",    # the state's filing pace, trailing 90 days
    "us_notices_90d_log",   # national filing pace, trailing 90 days
    "month",
]
CATEGORICAL_FEATURES = ["state"]
FEATURES = NUMERIC_FEATURES + CATEGORICAL_FEATURES


def _clean(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df["notice_date"] = pd.to_datetime(df["notice_date"], errors="coerce")
    df["effective_date"] = pd.to_datetime(df["effective_date"], errors="coerce")
    df = df[df["notice_date"].notna() & (df["notice_date"] >= pd.Timestamp(MIN_DATE))]
    df = df[df["closure_category"].fillna("") != "Non-WARN"]
    for st, (lo, hi) in PLACEHOLDER_DATES.items():
        yr = df["notice_date"].dt.year
        df = df[~((df["state"] == st) & yr.between(lo, hi))]
    cnt = pd.to_numeric(df["layoff_count"], errors="coerce")
    df["layoff_count"] = cnt.where((cnt > 0) & (cnt <= MAX_COUNT))
    df = df.drop_duplicates("notice_id")
    return df.sort_values(["company_key", "notice_date", "notice_id"]).reset_index(drop=True)


def _company_key(company_id: int | None, canonical_id: int | None, employer: str) -> str:
    if company_id is not None:
        return f"c{canonical_id or company_id}"
    return "n" + (canonical_name(employer) or employer.lower())


def load_notices(session: Session) -> pd.DataFrame:
    """Every live, dated, statutory notice with its company key."""
    stmt = (
        select(
            Notice.notice_id, Notice.state, Notice.employer, Notice.notice_date,
            Notice.effective_date, Notice.layoff_count, Notice.closure_category,
            Notice.company_id, Company.canonical_company_id,
        )
        .outerjoin(Company, Notice.company_id == Company.id)
        .where(Notice.is_superseded.is_(False), Notice.notice_date.is_not(None))
    )
    rows = [
        (*r[:7], _company_key(r[7], r[8], r[2]))
        for r in session.execute(stmt).all()
    ]
    return _clean(pd.DataFrame(rows, columns=NOTICE_COLUMNS))


def load_notices_jsonl(path: Path) -> pd.DataFrame:
    """The same frame from a snapshot of the public /api/notices payload
    (one notice object per line) — for offline study without DB access."""
    rows = []
    with path.open(encoding="utf-8") as fh:
        for line in fh:
            n = json.loads(line)
            co = n.get("company") or {}
            rows.append((
                n["notice_id"], n["state"], n["employer"], n["notice_date"],
                n["effective_date"], n["layoff_count"], n["closure_category"],
                _company_key(co.get("id"), co.get("canonical_company_id"), n["employer"]),
            ))
    return _clean(pd.DataFrame(rows, columns=NOTICE_COLUMNS))


def coverage_masks(notices: pd.DataFrame, as_of: date) -> dict[str, dict[str, bool]]:
    """Per state, month -> True when that month is real data (not a hole)."""
    last = (as_of.replace(day=1) - timedelta(days=1)).isoformat()[:7]
    out: dict[str, dict[str, bool]] = {}
    period = notices["notice_date"].dt.strftime("%Y-%m")
    for st, grp in period.groupby(notices["state"]):
        first = grp.min()
        if first > last:
            continue
        months = month_range(first, last)
        counts = grp.value_counts()
        series = [int(counts.get(m, 0)) for m in months]
        mask = usable_months(series, months, first_seen=first)
        out[str(st)] = dict(zip(months, mask, strict=True))
    return out


def _horizon_covered(mask: dict[str, bool], t0: pd.Timestamp) -> bool:
    end = t0 + pd.Timedelta(days=HORIZON_DAYS)
    months = month_range(t0.strftime("%Y-%m"), end.strftime("%Y-%m"))
    return all(mask.get(m, False) for m in months)


def _log1p(x: float) -> float:
    return math.log1p(max(x, 0.0))


def build_events(notices: pd.DataFrame, *, as_of: date) -> pd.DataFrame:
    """One row per (company, event) with features at t0 and, where the
    horizon is observable, the label.

    Columns: company_key, t0, state, FEATURES..., next_gap_days (days to
    the next event, NaN if none yet), label (1/0, NaN when censored),
    labelled (bool).
    """
    as_of_ts = pd.Timestamp(as_of)
    notices = notices[notices["notice_date"] <= as_of_ts]
    masks = coverage_masks(notices, as_of)

    state_dates = {
        st: np.sort(g.to_numpy(dtype="datetime64[D]"))
        for st, g in notices.groupby("state")["notice_date"]
    }
    state_first = {st: d[0] for st, d in state_dates.items()}
    us_dates = np.sort(notices["notice_date"].to_numpy(dtype="datetime64[D]"))

    def trailing(d: np.ndarray, t0: np.datetime64, days: int) -> int:
        lo = np.searchsorted(d, t0 - np.timedelta64(days, "D"), side="right")
        hi = np.searchsorted(d, t0, side="right")
        return int(hi - lo)

    records: list[dict[str, object]] = []
    for key, grp in notices.groupby("company_key", sort=False):
        dates = grp["notice_date"].to_numpy(dtype="datetime64[D]")
        counts = grp["layoff_count"].to_numpy(dtype=float)
        states = grp["state"].to_numpy()
        closure = (grp["closure_category"] == "Closure").to_numpy()
        leads = (grp["effective_date"] - grp["notice_date"]).dt.days.to_numpy(dtype=float)

        starts: list[int] = []  # index of each event's first notice
        for i, d in enumerate(dates):
            if not starts or d > dates[starts[-1]] + np.timedelta64(EVENT_GAP_DAYS, "D"):
                starts.append(i)

        for e, i in enumerate(starts):
            t0 = dates[i]
            day = slice(i, int(np.searchsorted(dates, t0, side="right")))
            prior = slice(0, i)  # strictly before t0: dates are sorted, i is t0's first
            day_counts = counts[day]
            day_states = states[day]
            # The event's state: where most t0 notices were filed (ties -> first).
            vals, freq = np.unique(day_states, return_counts=True)
            state = str(vals[int(np.argmax(freq))])
            lead = leads[day]
            lead = lead[~np.isnan(lead)]
            lead_med = float(np.median(lead)) if lead.size else float(DEFAULT_LEAD_DAYS)
            prior_counts = counts[prior]
            prev = dates[i - 1] if i else None

            next_gap = (
                float((dates[starts[e + 1]] - t0).astype(int)) if e + 1 < len(starts) else math.nan
            )
            t0_ts = pd.Timestamp(t0)
            horizon_end = t0_ts + pd.Timedelta(days=HORIZON_DAYS)
            labelled = horizon_end < as_of_ts and _horizon_covered(masks.get(state, {}), t0_ts)
            label = (
                float(not math.isnan(next_gap) and next_gap <= HORIZON_DAYS)
                if labelled else math.nan
            )

            records.append({
                "company_key": key,
                "t0": t0_ts,
                "state": state,
                "day_notices": day.stop - day.start,
                "day_states": len(vals),
                "day_layoffs_log": _log1p(float(np.nansum(day_counts))),
                "day_count_missing": float(np.isnan(day_counts).all()),
                "day_closure_frac": float(closure[day].mean()),
                "lead_days": float(np.clip(lead_med, -30, 365)),
                "lead_is_default": float(lead_med == DEFAULT_LEAD_DAYS),
                "prior_notices_1y": trailing(dates[prior], t0, 365) if i else 0,
                "prior_notices_3y": trailing(dates[prior], t0, 3 * 365) if i else 0,
                "prior_events": e,
                "days_since_prev_log": _log1p(float((t0 - prev).astype(int))) if i else 0.0,
                "has_prior": float(i > 0),
                "prior_layoffs_log": _log1p(float(np.nansum(prior_counts))) if i else 0.0,
                "prior_states": len(set(states[prior])),
                "state_cov_years": float((t0 - state_first[state]).astype(int)) / 365.25,
                "state_notices_90d": trailing(state_dates[state], t0, 90),
                "us_notices_90d_log": _log1p(trailing(us_dates, t0, 90)),
                "month": t0_ts.month,
                "next_gap_days": next_gap,
                "label": label,
                "labelled": labelled,
            })

    events = pd.DataFrame.from_records(records)
    return events.sort_values(["t0", "company_key"]).reset_index(drop=True)


def km_repeat_curve(events: pd.DataFrame, days: Iterable[int], *, as_of: date) -> dict[int, float]:
    """Kaplan-Meier P(next event within d days), using every event — the
    ones whose horizon is still open contribute until they're censored.
    A sanity check on the labelled-only base rate, which drops recent events."""
    as_of_ts = pd.Timestamp(as_of)
    observed = events["next_gap_days"].notna()
    follow = (as_of_ts - events["t0"]).dt.days.astype(float)
    duration = events["next_gap_days"].where(observed, follow).to_numpy()
    event = observed.to_numpy()
    order = np.argsort(duration, kind="stable")
    duration, event = duration[order], event[order]
    n = len(duration)
    surv, out, j = 1.0, {}, 0
    at_risk = n
    for d in sorted(days):
        while j < n and duration[j] <= d:
            k = j
            deaths = 0
            while k < n and duration[k] == duration[j]:
                deaths += int(event[k])
                k += 1
            if at_risk:
                surv *= 1 - deaths / at_risk
            at_risk -= k - j
            j = k
        out[d] = 1 - surv
    return out
