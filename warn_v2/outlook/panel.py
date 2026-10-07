"""The monthly WARN panel the outlook models fit on.

One query groups notices by (state, 2-digit NAICS prefix, month) over the
lookback window into (state, sector) cells; state and sector totals are rolled
up in Python, so a sector total can be restricted to the states with
consistent coverage. Same filters as warn_v2.reports.forecast: superseded and Non-WARN
notices are excluded, months are keyed on notice_date, and the partial current
month is dropped.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from sqlalchemy import String, cast, func, select
from sqlalchemy.orm import Session

from warn_v2.companies.naics import sector_for_code
from warn_v2.db.models import Company, Notice
from warn_v2.reports.aggregate import _int, _month_start_back

LOOKBACK_MONTHS = 120


def month_range(first: str, last: str) -> list[str]:
    """Every "YYYY-MM" from first to last inclusive."""
    y, m = int(first[:4]), int(first[5:7])
    ly, lm = int(last[:4]), int(last[5:7])
    out = []
    while (y, m) <= (ly, lm):
        out.append(f"{y:04d}-{m:02d}")
        m += 1
        if m == 13:
            m, y = 1, y + 1
    return out


def shift_month(month: str, delta: int) -> str:
    total = int(month[:4]) * 12 + int(month[5:7]) - 1 + delta
    return f"{total // 12:04d}-{total % 12 + 1:02d}"


@dataclass(slots=True)
class Panel:
    """Monthly counts aligned to `months` (complete months, oldest first).

    `cells[(state, sector)]` is a list of (notices, layoffs) per month; sector
    is None for notices without a recognised NAICS code. `first_seen` is
    each state's earliest notice month over ALL history (not just the window)
    — the coverage mask needs it.
    """

    months: list[str]
    cells: dict[tuple[str, str | None], list[tuple[int, int]]] = field(default_factory=dict)
    first_seen: dict[str, str] = field(default_factory=dict)

    @property
    def states(self) -> list[str]:
        return sorted({st for st, _ in self.cells})

    @property
    def sectors(self) -> list[str]:
        return sorted({sec for _, sec in self.cells if sec is not None})

    def series(
        self,
        *,
        states: set[str] | None = None,
        sector: str | None = None,
        classified_only: bool = False,
    ) -> list[tuple[int, int]]:
        """Summed (notices, layoffs) per month over the matching cells: all
        sectors unless `sector` is given (or only NAICS-classified notices with
        `classified_only` — the exposure for a sector-share trend)."""
        out = [(0, 0)] * len(self.months)
        for (st, sec), rows in self.cells.items():
            if states is not None and st not in states:
                continue
            if sector is not None and sec != sector:
                continue
            if classified_only and sec is None:
                continue
            out = [(a + c, b + d) for (a, b), (c, d) in zip(out, rows, strict=True)]
        return out


def _filters(stmt):
    return stmt.where(
        Notice.is_superseded.is_(False),
        Notice.closure_category.is_distinct_from("Non-WARN"),
        Notice.notice_date.is_not(None),
    )


def build_panel(
    session: Session, *, as_of: date, lookback: int = LOOKBACK_MONTHS
) -> Panel:
    start = _month_start_back(as_of, lookback)
    months = month_range(start.isoformat()[:7], shift_month(as_of.isoformat()[:7], -1))
    index = {m: i for i, m in enumerate(months)}
    zero = [(0, 0)] * len(months)

    period = func.substr(cast(Notice.notice_date, String), 1, 7).label("period")
    prefix = func.substr(Company.naics_code, 1, 2).label("prefix")
    stmt = _filters(
        select(
            Notice.state,
            prefix,
            period,
            func.count(Notice.notice_id),
            func.coalesce(func.sum(Notice.layoff_count), 0),
        ).outerjoin(Company, Notice.company_id == Company.id)
    ).where(Notice.notice_date >= start, Notice.notice_date < as_of.replace(day=1))
    stmt = stmt.group_by(Notice.state, prefix, period)

    panel = Panel(months=months)
    for state, pre, m, n, lt in session.execute(stmt).all():
        i = index.get(m)
        if i is None:
            continue
        rows = panel.cells.setdefault((state, sector_for_code(pre)), list(zero))
        rows[i] = (rows[i][0] + _int(n), rows[i][1] + _int(lt))

    span = _filters(select(Notice.state, func.min(Notice.notice_date))).group_by(Notice.state)
    for state, first in session.execute(span).all():
        panel.first_seen[state] = str(first)[:7]
    return panel
