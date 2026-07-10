"""Deterministic per-state and national aggregates behind the sentiment reports.

Every number in a report comes from here — the LLM narrative layer only turns
these figures into prose and never computes anything itself. Query idioms
mirror warn_v2.api.routes.stats so they stay portable across SQLite (tests)
and Postgres (prod): filter is_superseded=False, bucket on notice_date, month
buckets via substr(cast(date as text), 1, 7).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import String, cast, func, select
from sqlalchemy.orm import Session

from warn_v2.companies.naics import SECTOR_NAME, sector_for_code
from warn_v2.db.models import Company, Location, Notice
from warn_v2.states import STATE_NAMES

# Below this many notices across both 90-day windows the deltas are noise, so
# the narrative is skipped (the deterministic tables still render).
MIN_NOTICES = 5

# Pseudo-jurisdiction for the national roll-up. Deliberately NOT in
# STATE_NAMES — that dict feeds the sitemap/state pages, where "US" would be a
# bogus entry. The reports API whitelists it separately.
NATIONAL_CODE = "US"
NATIONAL_NAME = "United States"


@dataclass(slots=True)
class DeltaRow:
    """Current-vs-prior-window totals for one county or NAICS sector."""

    key: str  # county string or sector id ("31-33")
    name: str  # display name
    cur_notices: int
    cur_layoffs: int
    prior_notices: int
    prior_layoffs: int

    @property
    def delta_layoffs(self) -> int:
        return self.cur_layoffs - self.prior_layoffs

    @property
    def pct_change(self) -> float | None:
        """Percent change in layoffs vs the prior window; None when prior is 0
        (rendered as "new" — a percentage against zero is meaningless)."""
        if self.prior_layoffs == 0:
            return None
        return (self.cur_layoffs - self.prior_layoffs) / self.prior_layoffs * 100.0


@dataclass(slots=True)
class StateAggregates:
    state: str
    state_name: str
    as_of: date
    cur_start: date
    cur_end: date
    prior_start: date
    prior_end: date
    season_start: date  # same window one year earlier (seasonal baseline)
    season_end: date
    cur_notices: int
    cur_layoffs: int
    prior_notices: int
    prior_layoffs: int
    season_notices: int
    season_layoffs: int
    yoy_cur_notices: int
    yoy_cur_layoffs: int
    yoy_prior_notices: int
    yoy_prior_layoffs: int
    closure_split: dict[str, int]  # current-window notice counts by closure_category
    counties: list[DeltaRow]  # sorted by cur_layoffs desc (empty for national)
    sectors: list[DeltaRow]  # sorted by cur_layoffs desc
    # ("YYYY-MM", notices, layoffs, layoffs same month a year earlier), oldest first
    monthly: list[tuple[str, int, int, int]]
    naics_coverage_pct: float  # % of current-window notices with an enriched NAICS
    states: list[DeltaRow] = field(default_factory=list)  # national only: per-state deltas

    @property
    def sufficient(self) -> bool:
        """Enough recent activity to support a trend narrative."""
        return self.cur_notices + self.prior_notices >= MIN_NOTICES

    def to_prompt_payload(self) -> dict:
        """Compact JSON-ready dict for the LLM: top rows only, no DB objects."""

        def rows(items: list[DeltaRow]) -> list[dict]:
            return [
                {
                    "name": r.name,
                    "notices_current": r.cur_notices,
                    "layoffs_current": r.cur_layoffs,
                    "notices_prior": r.prior_notices,
                    "layoffs_prior": r.prior_layoffs,
                    "delta_layoffs": r.delta_layoffs,
                    "pct_change": (
                        round(r.pct_change, 1) if r.pct_change is not None else None
                    ),
                }
                for r in items[:10]
            ]

        return {
            "state": self.state,
            "state_name": self.state_name,
            "current_window": {
                "start": self.cur_start.isoformat(),
                "end": self.cur_end.isoformat(),
            },
            "prior_window": {
                "start": self.prior_start.isoformat(),
                "end": self.prior_end.isoformat(),
            },
            "same_window_last_year": {
                "start": self.season_start.isoformat(),
                "end": self.season_end.isoformat(),
                "notices": self.season_notices,
                "layoffs": self.season_layoffs,
            },
            "totals": {
                "notices_current": self.cur_notices,
                "layoffs_current": self.cur_layoffs,
                "notices_prior": self.prior_notices,
                "layoffs_prior": self.prior_layoffs,
            },
            "year_over_year": {
                "notices_trailing_12mo": self.yoy_cur_notices,
                "layoffs_trailing_12mo": self.yoy_cur_layoffs,
                "notices_prior_12mo": self.yoy_prior_notices,
                "layoffs_prior_12mo": self.yoy_prior_layoffs,
            },
            "pct_change": {
                "layoffs_vs_prior_window": _pct(self.cur_layoffs, self.prior_layoffs),
                "layoffs_vs_same_window_last_year": _pct(
                    self.cur_layoffs, self.season_layoffs
                ),
                "layoffs_trailing_12mo_vs_prior_12mo": _pct(
                    self.yoy_cur_layoffs, self.yoy_prior_layoffs
                ),
                "note": (
                    "null means the earlier figure was 0, so no percentage is defined"
                ),
            },
            "top_counties": rows(self.counties),
            "top_sectors": rows(self.sectors),
            **({"top_states": rows(self.states)} if self.states else {}),
            "monthly": [
                {"month": m, "notices": n, "layoffs": lt, "layoffs_year_earlier": ly}
                for m, n, lt, ly in self.monthly
            ],
            "naics_coverage_pct": round(self.naics_coverage_pct, 1),
        }


def _int(value) -> int:
    if value is None:
        return 0
    if isinstance(value, Decimal):
        return int(value)
    return int(value)


def _pct(cur: int, earlier: int) -> float | None:
    """Percent change vs an earlier figure, rounded to 1dp; None when the
    earlier figure is 0 (a percentage against zero is meaningless)."""
    if earlier == 0:
        return None
    return round((cur - earlier) / earlier * 100.0, 1)


def _in_window(stmt, state: str | None, start: date, end: date):
    """state=None means national: no per-state filter."""
    stmt = stmt.where(
        Notice.is_superseded.is_(False),
        # Non-WARN Rapid Response events (MS) would skew YoY comparisons —
        # reports count statutory WARN notices only.
        Notice.closure_category.is_distinct_from("Non-WARN"),
        Notice.notice_date.is_not(None),
        Notice.notice_date >= start,
        Notice.notice_date <= end,
    )
    if state is not None:
        stmt = stmt.where(Notice.state == state)
    return stmt


def _window_totals(
    session: Session, state: str | None, start: date, end: date
) -> tuple[int, int]:
    stmt = select(
        func.count(Notice.notice_id), func.coalesce(func.sum(Notice.layoff_count), 0)
    )
    row = session.execute(_in_window(stmt, state, start, end)).one()
    return _int(row[0]), _int(row[1])


def _closure_split(
    session: Session, state: str | None, start: date, end: date
) -> dict[str, int]:
    stmt = select(Notice.closure_category, func.count(Notice.notice_id)).group_by(
        Notice.closure_category
    )
    rows = session.execute(_in_window(stmt, state, start, end)).all()
    return {(cat or "Unspecified"): _int(n) for cat, n in rows}


def _county_window(
    session: Session, state: str | None, start: date, end: date
) -> dict[str, tuple[int, int]]:
    """(notices, layoffs) per county; unlocated notices land in "Unknown"."""
    county = func.coalesce(Location.county, "Unknown")
    stmt = (
        select(
            county,
            func.count(Notice.notice_id),
            func.coalesce(func.sum(Notice.layoff_count), 0),
        )
        .select_from(Notice)
        .join(Location, Notice.location_id == Location.id, isouter=True)
        .group_by(county)
    )
    rows = session.execute(_in_window(stmt, state, start, end)).all()
    return {r[0]: (_int(r[1]), _int(r[2])) for r in rows}


def _sector_window(
    session: Session, state: str | None, start: date, end: date
) -> dict[str, tuple[int, int]]:
    """(notices, layoffs) per NAICS sector id. Inner join to Company: an
    un-enriched notice has no NAICS, so it appears only in county/total figures
    (the gap is surfaced as naics_coverage_pct)."""
    prefix2 = func.substr(Company.naics_code, 1, 2)
    stmt = (
        select(
            prefix2,
            func.count(Notice.notice_id),
            func.coalesce(func.sum(Notice.layoff_count), 0),
        )
        .select_from(Notice)
        .join(Company, Notice.company_id == Company.id)
        .where(Company.naics_code.is_not(None))
        .group_by(prefix2)
    )
    out: dict[str, tuple[int, int]] = {}
    for prefix, n, lt in session.execute(_in_window(stmt, state, start, end)).all():
        sector = sector_for_code(prefix)  # rolls 31/32/33 → "31-33" etc.
        if not sector:
            continue
        prev = out.get(sector, (0, 0))
        out[sector] = (prev[0] + _int(n), prev[1] + _int(lt))
    return out


def _naics_covered(session: Session, state: str | None, start: date, end: date) -> int:
    stmt = (
        select(func.count(Notice.notice_id))
        .select_from(Notice)
        .join(Company, Notice.company_id == Company.id)
        .where(Company.naics_code.is_not(None))
    )
    return _int(session.execute(_in_window(stmt, state, start, end)).scalar())


def _monthly_series(
    session: Session, state: str | None, start: date
) -> list[tuple[str, int, int]]:
    period = func.substr(cast(Notice.notice_date, String), 1, 7).label("period")
    stmt = (
        select(
            period,
            func.count(Notice.notice_id),
            func.coalesce(func.sum(Notice.layoff_count), 0),
        )
        .where(
            Notice.is_superseded.is_(False),
            Notice.closure_category.is_distinct_from("Non-WARN"),
            Notice.notice_date.is_not(None),
            Notice.notice_date >= start,
        )
        .group_by(period)
        .order_by(period)
    )
    if state is not None:
        stmt = stmt.where(Notice.state == state)
    return [(r[0], _int(r[1]), _int(r[2])) for r in session.execute(stmt).all()]


def _state_window(session: Session, start: date, end: date) -> dict[str, tuple[int, int]]:
    """(notices, layoffs) per state — the national report's geographic axis."""
    stmt = select(
        Notice.state,
        func.count(Notice.notice_id),
        func.coalesce(func.sum(Notice.layoff_count), 0),
    ).group_by(Notice.state)
    rows = session.execute(_in_window(stmt, None, start, end)).all()
    return {r[0]: (_int(r[1]), _int(r[2])) for r in rows}


def _merge_deltas(
    cur: dict[str, tuple[int, int]],
    prior: dict[str, tuple[int, int]],
    name_for,
) -> list[DeltaRow]:
    rows = []
    for key in cur.keys() | prior.keys():
        c = cur.get(key, (0, 0))
        p = prior.get(key, (0, 0))
        rows.append(
            DeltaRow(
                key=key,
                name=name_for(key),
                cur_notices=c[0],
                cur_layoffs=c[1],
                prior_notices=p[0],
                prior_layoffs=p[1],
            )
        )
    rows.sort(key=lambda r: (-r.cur_layoffs, -r.cur_notices, r.name))
    return rows


def _month_start_back(as_of: date, months_back: int) -> date:
    """First day of the month `months_back` months before as_of's month."""
    total = as_of.year * 12 + (as_of.month - 1) - months_back
    return date(total // 12, total % 12 + 1, 1)


def _zip_year_earlier(
    raw: list[tuple[str, int, int]], cutoff_month: str
) -> list[tuple[str, int, int, int]]:
    """Pair each month at/after `cutoff_month` with the same calendar month one
    year earlier from `raw` (a series reaching back at least that far). A month
    absent from the series contributed no notices, so its year-earlier figure
    is 0 — same sum-over-no-rows semantics as the rest of the report."""
    layoffs_by_month = {m: lt for m, _, lt in raw}
    return [
        (m, n, lt, layoffs_by_month.get(f"{int(m[:4]) - 1}{m[4:]}", 0))
        for m, n, lt in raw
        if m >= cutoff_month
    ]


def compute_state_aggregates(
    session: Session,
    state: str,
    *,
    as_of: date | None = None,
    window_days: int = 90,
) -> StateAggregates:
    """Compute all report figures for one state.

    `as_of` is explicit (defaulting to today) so tests are deterministic.
    Windows are inclusive: current = [as_of-89d, as_of], prior = the 90 days
    before that, seasonal = the current window shifted back a fixed 365 days
    (drifts one calendar day across a Feb 29 — same convention as the YoY
    offsets); YoY compares the trailing 365 days with the 365 before.
    """
    return _compute_aggregates(session, state.upper(), as_of=as_of, window_days=window_days)


def compute_national_aggregates(
    session: Session,
    *,
    as_of: date | None = None,
    window_days: int = 90,
) -> StateAggregates:
    """National roll-up: same windows and figures as a state report across all
    non-superseded notices, with a per-state table instead of counties."""
    return _compute_aggregates(session, None, as_of=as_of, window_days=window_days)


def _compute_aggregates(
    session: Session,
    code: str | None,
    *,
    as_of: date | None,
    window_days: int,
) -> StateAggregates:
    as_of = as_of or date.today()
    cur_start = as_of - timedelta(days=window_days - 1)
    prior_start = as_of - timedelta(days=2 * window_days - 1)
    prior_end = as_of - timedelta(days=window_days)
    season_start = cur_start - timedelta(days=365)
    season_end = as_of - timedelta(days=365)
    yoy_cur_start = as_of - timedelta(days=364)
    yoy_prior_start = as_of - timedelta(days=729)
    yoy_prior_end = as_of - timedelta(days=365)

    cur_n, cur_l = _window_totals(session, code, cur_start, as_of)
    prior_n, prior_l = _window_totals(session, code, prior_start, prior_end)
    season_n, season_l = _window_totals(session, code, season_start, season_end)
    yoy_cur_n, yoy_cur_l = _window_totals(session, code, yoy_cur_start, as_of)
    yoy_prior_n, yoy_prior_l = _window_totals(session, code, yoy_prior_start, yoy_prior_end)

    if code is None:
        # National: a 51-state county table is noise — group by state instead.
        counties: list[DeltaRow] = []
        states = _merge_deltas(
            _state_window(session, cur_start, as_of),
            _state_window(session, prior_start, prior_end),
            lambda k: STATE_NAMES.get(k, k),
        )
    else:
        counties = _merge_deltas(
            _county_window(session, code, cur_start, as_of),
            _county_window(session, code, prior_start, prior_end),
            lambda k: k,
        )
        states = []
    sectors = _merge_deltas(
        _sector_window(session, code, cur_start, as_of),
        _sector_window(session, code, prior_start, prior_end),
        lambda k: SECTOR_NAME.get(k, k),
    )
    covered = _naics_covered(session, code, cur_start, as_of)

    return StateAggregates(
        state=code if code is not None else NATIONAL_CODE,
        state_name=STATE_NAMES.get(code, code) if code is not None else NATIONAL_NAME,
        as_of=as_of,
        cur_start=cur_start,
        cur_end=as_of,
        prior_start=prior_start,
        prior_end=prior_end,
        season_start=season_start,
        season_end=season_end,
        cur_notices=cur_n,
        cur_layoffs=cur_l,
        prior_notices=prior_n,
        prior_layoffs=prior_l,
        season_notices=season_n,
        season_layoffs=season_l,
        yoy_cur_notices=yoy_cur_n,
        yoy_cur_layoffs=yoy_cur_l,
        yoy_prior_notices=yoy_prior_n,
        yoy_prior_layoffs=yoy_prior_l,
        closure_split=_closure_split(session, code, cur_start, as_of),
        counties=counties,
        sectors=sectors,
        monthly=_zip_year_earlier(
            _monthly_series(session, code, _month_start_back(as_of, 23)),
            _month_start_back(as_of, 11).isoformat()[:7],
        ),
        naics_coverage_pct=(covered / cur_n * 100.0) if cur_n else 0.0,
        states=states,
    )
