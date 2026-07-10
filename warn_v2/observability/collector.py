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
from datetime import UTC

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

        from warn_v2.db.models import (
            SCRAPER_SUCCESS_STATUSES,
            Company,
            Notice,
            ScraperRun,
            Subscription,
        )
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
            # 2. Total companies — denominator for enrichment coverage %.
            # ------------------------------------------------------------------
            companies = s.scalar(select(func.count()).select_from(Company)) or 0
            yield GaugeMetricFamily(
                "warn_companies",
                "Total company records in the database.",
                value=float(companies),
            )

            # ------------------------------------------------------------------
            # 2b. Notices tracked by state (total count) and workers affected
            #     (sum of layoff_count). These are point-in-time totals; graphed
            #     over time in Grafana they give the "notices/workers tracked"
            #     growth curve, and their sum() gives the current totals. Both
            #     are collector-only (NOT declared in metrics.py) — same as
            #     warn_companies — to avoid a duplicate-registration conflict.
            # ------------------------------------------------------------------
            rows = s.execute(
                select(Notice.state, func.count()).group_by(Notice.state)
            ).all()
            g = GaugeMetricFamily(
                "warn_notices",
                "Total WARN notices stored, by state.",
                labels=["state"],
            )
            for state, count in rows:
                g.add_metric([state], float(count))
            yield g

            rows = s.execute(
                select(Notice.state, func.coalesce(func.sum(Notice.layoff_count), 0))
                .group_by(Notice.state)
            ).all()
            g = GaugeMetricFamily(
                "warn_workers_affected",
                "Total workers affected across stored WARN notices, by state "
                "(sum of layoff_count; notices with an unknown count are excluded).",
                labels=["state"],
            )
            for state, total in rows:
                g.add_metric([state], float(total or 0))
            yield g

            # ------------------------------------------------------------------
            # 3. Provider (D&B) attempts and misses. A miss stamps
            #    provider_attempted_at but leaves enriched_at NULL — the company
            #    queues for the backup tiers (edgar/claude). Hit rate =
            #    1 - misses/attempts; untried pool = backlog - misses.
            # ------------------------------------------------------------------
            attempted = (
                s.scalar(
                    select(func.count()).where(Company.provider_attempted_at.isnot(None))
                )
                or 0
            )
            c = CounterMetricFamily(
                "warn_enrichment_provider_attempts",
                "Companies the D&B provider tier has attempted (hit or miss).",
            )
            c.add_metric([], float(attempted))
            yield c

            misses = (
                s.scalar(
                    select(func.count()).where(
                        Company.provider_attempted_at.isnot(None),
                        Company.enriched_at.is_(None),
                    )
                )
                or 0
            )
            yield GaugeMetricFamily(
                "warn_enrichment_provider_misses",
                "Provider-attempted companies still unenriched — the backup-tier "
                "(edgar/claude) queue depth.",
                value=float(misses),
            )

            # ------------------------------------------------------------------
            # 4. Total enriched companies by source tier
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
            # 5. Scraper run outcomes by state + status (cumulative count)
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
            # 6. Net-new notices persisted by state (cumulative sum of rows_new)
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
            # 7. Scraper duration summary by state (sum + count of seconds).
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
                # add_metric(labels, count_value, sum_value) — there is no
                # quantiles arg on SummaryMetricFamily.
                c.add_metric([state], float(count), float(dur_sum or 0.0))
            yield c

            # ------------------------------------------------------------------
            # 8. Last *successful* scrape timestamp per state (unix seconds).
            #    Emitted as an absolute timestamp so alerting can do
            #    `time() - warn_scrape_last_success_timestamp_seconds > N`,
            #    mirroring kube_cronjob_status_last_successful_time. A state with
            #    no ok run ever (blocked source) is simply absent — no false page.
            # ------------------------------------------------------------------
            rows = s.execute(
                select(ScraperRun.state, func.max(ScraperRun.started_at))
                .where(ScraperRun.status.in_(SCRAPER_SUCCESS_STATUSES))
                .group_by(ScraperRun.state)
            ).all()
            g = GaugeMetricFamily(
                "warn_scrape_last_success_timestamp_seconds",
                "Unix timestamp of the most recent successful "
                "(ok or not_modified) scrape, per state.",
                labels=["state"],
            )
            for state, ts in rows:
                if ts is not None:
                    # started_at is stored in UTC. Postgres returns it tz-aware;
                    # some drivers/SQLite return it naive — normalize so
                    # .timestamp() doesn't silently apply the host's local offset.
                    if ts.tzinfo is None:
                        ts = ts.replace(tzinfo=UTC)
                    g.add_metric([state], ts.timestamp())
            yield g

            # ------------------------------------------------------------------
            # 9. Email alert subscriptions, by state filter, frequency, and
            #    confirmation status. A live row is a current subscriber
            #    (unsubscribe deletes the row); confirmed_at IS NOT NULL means
            #    the double-opt-in was completed. state is nullable ("any").
            #    No email/PII in labels — cardinality is bounded (states x
            #    frequency x {confirmed,pending}). The per-subscriber list lives
            #    in Grafana's Postgres datasource, not here.
            # ------------------------------------------------------------------
            confirmed_expr = Subscription.confirmed_at.isnot(None)
            rows = s.execute(
                select(
                    Subscription.state,
                    Subscription.frequency,
                    confirmed_expr.label("confirmed"),
                    func.count(),
                ).group_by(Subscription.state, Subscription.frequency, confirmed_expr)
            ).all()
            g = GaugeMetricFamily(
                "warn_subscriptions",
                "Email alert subscriptions by state filter, frequency, and "
                "confirmation status (confirmed=true once double-opt-in completes).",
                labels=["state", "frequency", "confirmed"],
            )
            for state, frequency, confirmed, count in rows:
                g.add_metric(
                    [state or "any", frequency, "true" if confirmed else "false"],
                    float(count),
                )
            yield g
