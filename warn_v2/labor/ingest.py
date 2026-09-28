"""Refresh the `bls_series` table from the BLS public API.

Backs ``warn-v2 fetch-bls``. Unlike ``warn_v2.reports.bls``, which degrades
silently because the narrative can render without macro context, this raises:
fetching is the entire job, so a failure must mark the CronJob failed rather
than leave the charts quietly stale.

The one failure mode worth naming: a malformed series id does not error at the
API. It comes back inside ``Results.series`` with an empty ``data`` list, which
is indistinguishable from a real series that has no data in the requested span.
So `refresh_bls` reports which series returned nothing and the caller decides —
see `MIN_EXPECTED_COVERAGE`.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime

import httpx
from sqlalchemy.orm import Session

from warn_v2.db.models import BlsSeries
from warn_v2.labor.bls_api import fetch_series, year_windows
from warn_v2.labor.catalog import all_series

log = logging.getLogger(__name__)

# Fraction of requested series that must come back with data before a run is
# considered sound. Not 100%: state JOLTS lags the national series by months,
# so a narrow window legitimately leaves those empty. Well below this and
# something structural broke — an id layout changed, or BLS is serving stubs.
MIN_EXPECTED_COVERAGE = 0.5


@dataclass
class RefreshResult:
    requested: int = 0
    with_data: int = 0
    rows_written: int = 0
    empty_series: list[str] = field(default_factory=list)

    @property
    def coverage(self) -> float:
        return self.with_data / self.requested if self.requested else 0.0


def _upsert(db: Session, rows: list[dict]) -> int:
    """Insert or update (series_id, period) rows. Returns the row count."""
    if not rows:
        return 0
    if db.get_bind().dialect.name == "postgresql":
        from sqlalchemy.dialects.postgresql import insert
    else:  # tests run SQLite
        from sqlalchemy.dialects.sqlite import insert
    # Chunked so a full-history refresh doesn't build one enormous statement.
    written = 0
    for i in range(0, len(rows), 1000):
        chunk = rows[i : i + 1000]
        stmt = insert(BlsSeries).values(chunk)
        stmt = stmt.on_conflict_do_update(
            index_elements=["series_id", "period"],
            # BLS revises published figures; the latest fetch always wins.
            set_={"value": stmt.excluded.value},
        )
        db.execute(stmt)
        written += len(chunk)
    db.commit()
    return written


def refresh_bls(
    db: Session,
    *,
    start_year: int,
    end_year: int | None = None,
    timeout_s: float = 60.0,
) -> RefreshResult:
    """Fetch every catalogued series for the span and upsert it.

    Raises on any HTTP or API-level failure, and when coverage falls below
    `MIN_EXPECTED_COVERAGE` — which is how a silently-wrong series id layout
    surfaces as a failed job instead of an empty chart.
    """
    end_year = end_year or datetime.now(UTC).year
    if start_year > end_year:
        raise ValueError(f"start_year {start_year} is after end_year {end_year}")

    series_ids = all_series()
    result = RefreshResult(requested=len(series_ids))
    merged: dict[str, dict[str, float]] = {}

    with httpx.Client(timeout=timeout_s) as client:
        for window_start, window_end in year_windows(start_year, end_year):
            log.info(
                "Fetching %d BLS series for %d-%d",
                len(series_ids), window_start, window_end,
            )
            fetched = fetch_series(client, series_ids, window_start, window_end)
            for series_id, points in fetched.items():
                merged.setdefault(series_id, {}).update(points)

    rows: list[dict] = []
    for series_id in series_ids:
        points = merged.get(series_id) or {}
        if not points:
            result.empty_series.append(series_id)
            continue
        result.with_data += 1
        rows.extend(
            {"series_id": series_id, "period": period, "value": value}
            for period, value in points.items()
        )

    if result.coverage < MIN_EXPECTED_COVERAGE:
        raise RuntimeError(
            f"BLS refresh returned data for only {result.with_data}/"
            f"{result.requested} series ({result.coverage:.0%}); "
            f"first empty: {result.empty_series[:5]}"
        )

    result.rows_written = _upsert(db, rows)
    log.info(
        "BLS refresh: %d/%d series, %d rows, %d empty",
        result.with_data, result.requested, result.rows_written,
        len(result.empty_series),
    )
    if result.empty_series:
        log.info("Series with no data in span: %s", ", ".join(result.empty_series[:20]))
    return result
