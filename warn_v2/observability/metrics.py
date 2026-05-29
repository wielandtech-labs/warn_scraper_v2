"""Prometheus metrics. Imported by the API and the runner CLI."""
from __future__ import annotations

from prometheus_client import Counter, Gauge, Histogram

scrape_attempts = Counter(
    "warn_scrape_attempts_total",
    "Number of scrape runs attempted.",
    ["state", "status"],
)

scrape_rows = Histogram(
    "warn_scrape_rows",
    "Distribution of row counts produced by a scrape.",
    ["state"],
    buckets=(0, 1, 10, 50, 100, 250, 500, 1000, 2500, 5000, 10000),
)

scrape_duration = Histogram(
    "warn_scrape_duration_seconds",
    "Wall-clock duration of one scrape.",
    ["state"],
    buckets=(0.1, 0.5, 1, 2, 5, 10, 30, 60, 120, 300),
)

scrape_new_rows = Counter(
    "warn_scrape_new_rows_total",
    "Number of net-new notices persisted.",
    ["state"],
)

heal_jobs = Counter(
    "warn_heal_jobs_total",
    "Number of self-heal jobs spawned.",
    ["state", "outcome"],
)

# NOTE: enrichment_backlog is intentionally NOT defined here.
# It is computed from the DB by WarnCollector (warn_v2.observability.collector)
# registered in the API at startup. Defining it here as a Gauge would cause a
# duplicate-registration conflict with the collector.
