"""DB-backed custom Prometheus collector for warn-v2.

All metrics are computed from the database on every Prometheus scrape so they
stay accurate without needing instrumentation in ephemeral CronJob pods (which
die before they can be scraped).

Registered in warn_v2.api at startup:
    from prometheus_client import REGISTRY
    from warn_v2.observability.collector import WarnCollector
    REGISTRY.register(WarnCollector())
"""
from __future__ import annotations

import logging

from prometheus_client.core import (
    CounterMetricFamily,
    GaugeMetricFamily,
    SummaryMetricFamily,
)
from prometheus_client.registry import Collector

log = logging.getLogger(__name__)


class WarnCollector(Collector):
    """Yields DB-derived metrics on each Prometheus scrape."""

    def describe(self) -> list:
        # Return empty list so prometheus_client doesn't pre-check for conflicts.
        return []

    def collect(self):
        try:
            yield from self._collect()
        except Exception:
            log.exception("WarnCollector.collect() failed — returning empty metric set")

    def _collect(self):
        from sqlalchemy import func, select

        from warn_v2.db.models import Company, ScraperRun
        from warn_v2.db.session import get_session_factory

        with get_session_factory()() as s:
            # ------------------------------------------------------------------
            # 1. Enrichment backlog — companies where enriched_at IS NULL
            # ------------------------------------------------------------------
            backlog = s.scalar(select(func.count()).where(Company.enriched_at.is_(None))) or 0
            yield GaugeMetricFamily(
                "warn_enrichment_backlog",
                "Number of companies awaiting enrichment (enriched_at IS NULL).",
                value=float(backlog),
            )

            # ------------------------------------------------------------------
            # 2. Total enriched companies by source tier
            #    CounterMetricFamily appends _total suffix automatically.
            # ------------------------------------------------------------------
            rows = s.execute(
                select(Company.enrichment_source, func.count())
                .where(Company.enriched_at.isnot(None))
                .group_by(Company.enrichment_source)
            ).all()
            c = CounterMetricFamily(
                "warn_enrichment",
                "Total companies enriched, by source tier (provider/edgar/claude).",
                labels=["source"],
            )
            for source, count in rows:
                c.add_metric([source or "unknown"], float(count))
            yield c

            # ------------------------------------------------------------------
            # 3. Scraper run outcomes by state + status (cumulative count)
            # ------------------------------------------------------------------
            rows = s.execute(
                select(ScraperRun.state, ScraperRun.status, func.count())
                .group_by(ScraperRun.state, ScraperRun.status)
            ).all()
            c = CounterMetricFamily(
                "warn_scrape_attempts",
                "Total scraper runs by state and outcome status.",
                labels=["state", "status"],
            )
            for state, status, count in rows:
                c.add_metric([state, status], float(count))
            yield c

            # ------------------------------------------------------------------
            # 4. Net-new notices persisted by state (cumulative sum of rows_new)
            # ------------------------------------------------------------------
            rows = s.execute(
                select(ScraperRun.state, func.sum(ScraperRun.rows_new))
                .group_by(ScraperRun.state)
            ).all()
            c = CounterMetricFamily(
                "warn_scrape_new_rows",
                "Total net-new notices persisted by state (cumulative).",
                labels=["state"],
            )
            for state, total in rows:
                c.add_metric([state], float(total or 0))
            yield c

            # ------------------------------------------------------------------
            # 5. Scraper duration summary by state (sum + count of seconds).
            #    Dashboard uses rate(sum[1h]) / rate(count[1h]) for avg duration.
            # ------------------------------------------------------------------
            rows = s.execute(
                select(
                    ScraperRun.state,
                    func.sum(
                        func.extract("epoch", ScraperRun.finished_at - ScraperRun.started_at)
                    ),
                    func.count(),
                )
                .where(ScraperRun.finished_at.isnot(None))
                .group_by(ScraperRun.state)
            ).all()
            c = SummaryMetricFamily(
                "warn_scrape_duration_seconds",
                "Wall-clock duration of scraper runs by state (sum + count).",
                labels=["state"],
            )
            for state, dur_sum, count in rows:
                # add_metric(labels, quantiles, sum_value, count_value)
                c.add_metric([state], {}, float(dur_sum or 0.0), float(count))
            yield c
