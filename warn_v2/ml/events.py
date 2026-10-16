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
from warn_v2.ml import HORIZON_DAYS as HORIZON_DAYS
from warn_v2.outlook.coverage import usable_months
from warn_v2.outlook.panel import month_range

EVENT_GAP_DAYS = 30
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
    "day_layoffs_log",      # log1p(known affected workers on t0); 0 = no count given
    "day_closure_frac",     # share of t0 notices that are closures
    "lead_days",            # median effective - notice gap on t0
    "lead_is_default",      # that gap is exactly the imputed 60-day default
    "prior_notices_1y",
    "prior_notices_3y",
    "prior_events",         # events before this one, all history
    "days_since_prev_log",  # log1p days since the previous notice (0 if none)
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


def _linked_key(company_id: int | None, canonical_id: int | None) -> str | None:
    return f"c{canonical_id or company_id}" if company_id is not None else None


def _resolve_keys(df: pd.DataFrame) -> pd.DataFrame:
    """Fill company_key for notices with no linked company.

    Enrichment links notices to companies days to weeks after they're scraped,
    so one employer's history is often part linked, part not. Keying the
    unlinked part by name alone would split it in two (a fake first-time filer,
    and a fake "never filed again"), so an unlinked notice joins the linked
    company whose employer names normalize to the same key — when exactly one
    does. Otherwise it is keyed by the normalized name.
    """
    names = df["employer"].map(lambda e: canonical_name(e) or str(e).lower())
    linked = df["company_key"].notna()
    owners = (
        pd.DataFrame({"name": names[linked], "key": df.loc[linked, "company_key"]})
        .drop_duplicates()
        .groupby("name")["key"]
    )
    unique_owner = owners.first()[owners.nunique() == 1]
    fallback = names.map(unique_owner).fillna("n" + names)
    df = df.copy()
    df["company_key"] = df["company_key"].where(linked, fallback)
    return df


def load_notices(session: Session, key_map: dict[int, str] | None = None) -> pd.DataFrame:
    """Every live, dated, statutory notice with its company key.

    key_map: raw company_id -> company key, overriding the canonical grouping
    (the entity-resolution rerun, warn_v2/ml/er/remap.py). Unmapped
    companies keep their usual key."""
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
        (*r[:7], (key_map.get(r[7]) if key_map and r[7] is not None else None)
         or _linked_key(r[7], r[8]))
        for r in session.execute(stmt).all()
    ]
    return _clean(_resolve_keys(pd.DataFrame(rows, columns=NOTICE_COLUMNS)))


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
                _linked_key(co.get("id"), co.get("canonical_company_id")),
            ))
    return _clean(_resolve_keys(pd.DataFrame(rows, columns=NOTICE_COLUMNS)))


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


def _month_index(days: np.ndarray) -> np.ndarray:
    """Days since the epoch -> months since 1970-01."""
    months: np.ndarray = days.astype("datetime64[D]").astype("datetime64[M]").astype(np.int64)
    return months


def _coverage(masks: dict[str, dict[str, bool]], states: np.ndarray,
              m_lo: int, m_hi: int) -> tuple[np.ndarray, np.ndarray]:
    """For each event's state, over months m_lo..m_hi: running count of
    uncovered months (prefix sums, one leading 0) and the first uncovered
    month at or after each month (m_hi + 1 when none). Months missing from a
    state's mask are uncovered, as are all months of a state with no mask."""
    span = m_hi - m_lo + 1
    names, inv = np.unique(states, return_inverse=True)
    uncov = np.ones((len(names), span), dtype=bool)
    for j, st in enumerate(names):
        for month, ok in masks.get(str(st), {}).items():
            k = int(month[:4]) * 12 + int(month[5:7]) - 1 - 1970 * 12 - m_lo
            if ok and 0 <= k < span:
                uncov[j, k] = False
    prefix = np.zeros((len(names), span + 1), dtype=np.int64)
    np.cumsum(uncov, axis=1, out=prefix[:, 1:])
    pos = np.where(uncov, np.arange(span), span)
    first_after = np.minimum.accumulate(pos[:, ::-1], axis=1)[:, ::-1] + m_lo
    return prefix[inv], first_after[inv]


def _log1p_each(x: np.ndarray) -> np.ndarray:
    # math.log1p per value, not np.log1p: numpy's need not match libm to the
    # last bit, and these features feed a trained model.
    return np.array([_log1p(v) for v in x.tolist()], dtype=float)


def _log1p(x: float) -> float:
    return math.log1p(max(x, 0.0))


def build_events(notices: pd.DataFrame, *, as_of: date) -> pd.DataFrame:
    """One row per (company, event) with features at t0 and, where the
    horizon is observable, the label.

    Columns: company_key, t0, state, FEATURES..., next_gap_days (days to
    the next event, NaN if none yet), followup_days (days observed, capped at
    the horizon and cut at the first coverage hole), label (1/0, NaN when
    censored), labelled (bool).

    Vectorized over all notices at once (dates as integer days); every
    per-company window is a slice of one array sorted by (company, date).
    """
    as_of_ts = pd.Timestamp(as_of)
    notices = notices[notices["notice_date"] <= as_of_ts]
    masks = coverage_masks(notices, as_of)
    columns = ["company_key", "t0", "state", *NUMERIC_FEATURES,
               "next_gap_days", "followup_days", "label", "labelled"]

    def days_of(s: pd.Series) -> np.ndarray:
        out: np.ndarray = s.to_numpy(dtype="datetime64[D]").astype(np.int64)
        return out

    state_dates = {st: np.sort(days_of(g)) for st, g in notices.groupby("state")["notice_date"]}
    us_dates = np.sort(days_of(notices["notice_date"]))

    codes, keys = pd.factorize(notices["company_key"])
    keep = codes >= 0  # groupby drops notices without a company key
    code = codes[keep]
    day = days_of(notices["notice_date"])[keep]
    order = np.lexsort((day, code))  # stable: same-day notices keep their order
    code, day = code[order], day[order]
    counts = notices["layoff_count"].to_numpy(dtype=float)[keep][order]
    states = notices["state"].to_numpy()[keep][order]
    closure = (notices["closure_category"] == "Closure").to_numpy()[keep][order]
    leads = (notices["effective_date"] - notices["notice_date"]).dt.days.to_numpy(
        dtype=float)[keep][order]
    n = len(day)

    # Group boundaries, and event starts: an event opens at a company's first
    # notice and at each notice more than EVENT_GAP_DAYS after the current
    # event's t0 (chained from t0, not from the previous notice).
    first = np.r_[True, code[1:] != code[:-1]] if n else np.zeros(0, dtype=bool)
    gstart = np.maximum.accumulate(np.where(first, np.arange(n), 0))
    starts: list[int] = []
    anchor = 0
    for i, (d, f) in enumerate(zip(day.tolist(), first.tolist(), strict=True)):
        if f or d > anchor + EVENT_GAP_DAYS:
            starts.append(i)
            anchor = d
    if not starts:
        events = pd.DataFrame.from_records([], columns=columns)
        events = events.astype({"labelled": bool, "t0": "datetime64[ns]"})
        return events.sort_values(["t0", "company_key"]).reset_index(drop=True)

    s = np.array(starts)
    t0 = day[s]
    n_ev = len(s)
    ev_first = first[s]
    ev_idx = np.arange(n_ev)
    prior_events = ev_idx - np.maximum.accumulate(np.where(ev_first, ev_idx, 0))
    has_next = np.r_[~ev_first[1:], False]
    next_gap = np.where(has_next, np.r_[t0[1:], 0] - t0, np.nan).astype(float)
    g0 = gstart[s]
    has_prior = s > g0  # i: dates are sorted, so prior = [group start, s) is < t0

    # One sorted search key for "this company, this day": a window of days
    # ending at t0 never reaches into the previous company's range.
    pad = 4 * 365
    rel = day - day.min() + pad
    ckey = code.astype(np.int64) * (int(rel.max()) + pad) + rel
    day_end = np.searchsorted(ckey, ckey[s], side="right")
    day_n = day_end - s

    def trailing_prior(days: int) -> np.ndarray:
        count: np.ndarray = s - np.searchsorted(ckey, ckey[s] - days, side="right")
        return count

    # Per-event aggregates over the t0 notices [s, day_end).
    ev_rep = np.repeat(ev_idx, day_n)
    pos = np.arange(int(day_n.sum())) - np.repeat(np.cumsum(day_n) - day_n, day_n) \
        + np.repeat(s, day_n)
    by_state = (
        pd.DataFrame({"ev": ev_rep, "state": states[pos]})
        .groupby(["ev", "state"]).size().rename("k").reset_index()
    )
    day_states = by_state.groupby("ev").size().to_numpy()
    # The event's state: where most t0 notices were filed (ties -> first by name).
    mode = by_state.sort_values(["ev", "k", "state"], ascending=[True, False, True],
                                kind="stable").drop_duplicates("ev")
    ev_state = mode["state"].to_numpy()
    if len(ev_state) != n_ev:  # a null state would shift every later event's state
        raise ValueError("notices with no state")
    lead_med = (
        pd.Series(leads[pos]).groupby(ev_rep).median()
        .reindex(ev_idx).fillna(float(DEFAULT_LEAD_DAYS)).to_numpy()
    )
    csum = np.r_[0.0, np.cumsum(np.nan_to_num(counts))]  # integer counts: exact
    cclosure = np.r_[0, np.cumsum(closure)]
    seen = ~pd.DataFrame({"c": code, "s": states}).duplicated().to_numpy()
    cseen = np.r_[0, np.cumsum(seen)]

    prev_gap = np.where(has_prior, t0 - day[np.maximum(s - 1, 0)], 0)
    state_first = np.array([state_dates[st][0] for st in ev_state])
    state_90d = np.empty(n_ev, dtype=np.int64)
    for st in np.unique(ev_state):
        sel = ev_state == st
        d = state_dates[st]
        state_90d[sel] = (np.searchsorted(d, t0[sel], side="right")
                          - np.searchsorted(d, t0[sel] - 90, side="right"))
    us_90d = (np.searchsorted(us_dates, t0, side="right")
              - np.searchsorted(us_dates, t0 - 90, side="right"))

    # Censoring against the state's coverage mask, month by month.
    as_of_day = int(np.datetime64(as_of, "D").astype(np.int64))
    horizon_end = t0 + HORIZON_DAYS
    follow_end = np.minimum(as_of_day, horizon_end)
    m0, m1, m_end = _month_index(t0), _month_index(horizon_end), _month_index(follow_end)
    m_lo = int(m0.min())
    prefix, first_after = _coverage(masks, ev_state, m_lo, int(m1.max()))
    row = np.arange(n_ev)
    covered = prefix[row, m1 - m_lo + 1] == prefix[row, m0 - m_lo]
    labelled = (horizon_end < as_of_day) & covered
    label = np.where(labelled, ((~np.isnan(next_gap)) & (next_gap <= HORIZON_DAYS))
                     .astype(float), np.nan)
    followup = (follow_end - t0).astype(float)
    hole = first_after[row, m0 - m_lo]
    cut = hole <= m_end
    hole_day = hole[cut].astype("datetime64[M]").astype("datetime64[D]").astype(np.int64)
    followup[cut] = np.maximum(0, np.minimum(followup[cut], hole_day - t0[cut]))

    t0_ts = t0.astype("datetime64[D]").astype("datetime64[ns]")
    data = {
        "company_key": np.asarray(keys, dtype=object)[code[s]],
        "t0": t0_ts,
        "state": np.array([str(v) for v in ev_state], dtype=object),
        "day_notices": day_n.astype(np.int64),
        "day_states": day_states.astype(np.int64),
        "day_layoffs_log": _log1p_each(csum[day_end] - csum[s]),
        "day_closure_frac": (cclosure[day_end] - cclosure[s]) / day_n,
        "lead_days": np.clip(lead_med, -30, 365),
        "lead_is_default": (lead_med == DEFAULT_LEAD_DAYS).astype(float),
        "prior_notices_1y": trailing_prior(365).astype(np.int64),
        "prior_notices_3y": trailing_prior(3 * 365).astype(np.int64),
        "prior_events": prior_events.astype(np.int64),
        "days_since_prev_log": np.where(has_prior, _log1p_each(prev_gap.astype(float)), 0.0),
        "prior_layoffs_log": np.where(has_prior, _log1p_each(csum[s] - csum[g0]), 0.0),
        "prior_states": (cseen[s] - cseen[g0]).astype(np.int64),
        "state_cov_years": (t0 - state_first).astype(float) / 365.25,
        "state_notices_90d": state_90d,
        "us_notices_90d_log": _log1p_each(us_90d),
        "month": pd.DatetimeIndex(t0_ts).month.to_numpy().astype(np.int64),
        "next_gap_days": next_gap,
        "followup_days": followup,
        "label": label,
        "labelled": labelled,
    }
    events = pd.DataFrame(data, columns=columns)
    events = events.astype({"labelled": bool, "t0": "datetime64[ns]"})
    return events.sort_values(["t0", "company_key"]).reset_index(drop=True)


def km_repeat_curve(events: pd.DataFrame, days: Iterable[int], *, as_of: date) -> dict[int, float]:
    """Kaplan-Meier P(next event within d days), using every event — the
    ones whose horizon is still open contribute until they're censored.
    A sanity check on the labelled-only base rate, which drops recent events."""
    from statsmodels.duration.survfunc import SurvfuncRight

    observed = events["next_gap_days"].notna()
    follow = (pd.Timestamp(as_of) - events["t0"]).dt.days.astype(float)
    duration = events["next_gap_days"].where(observed, follow)
    sf = SurvfuncRight(duration.to_numpy(), observed.to_numpy(int))
    out = {}
    for d in days:
        k = int(np.searchsorted(sf.surv_times, d, side="right"))
        out[d] = float(1 - sf.surv_prob[k - 1]) if k else 0.0
    return out
