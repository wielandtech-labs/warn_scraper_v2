"""Tests for the /metrics Prometheus endpoint and the WarnCollector wiring."""
from __future__ import annotations

from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient

from warn_v2.db.models import Company

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def metrics_client(db):
    """TestClient with the WarnCollector registered (and cleaned up after).

    The collector opens its own session via the module-level factory, which
    the ``db`` fixture already points at the in-memory SQLite engine — no
    dependency override needed. Registered here instead of via the app
    lifespan so repeated tests don't stack duplicate collectors in the
    process-global REGISTRY.
    """
    from prometheus_client import REGISTRY

    from warn_v2.api import app
    from warn_v2.observability.collector import WarnCollector

    collector = WarnCollector()
    REGISTRY.register(collector)
    client = TestClient(app, raise_server_exceptions=True)
    yield client
    REGISTRY.unregister(collector)


# ---------------------------------------------------------------------------
# Routing
# ---------------------------------------------------------------------------

def test_metrics_exact_path_serves_prometheus_text(metrics_client):
    resp = metrics_client.get("/metrics")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/plain")
    assert "warn_enrichment_backlog" in resp.text


def test_metrics_not_shadowed_by_spa_mount(tmp_path):
    """Regression: app.mount('/metrics', ...) only matched /metrics/..., so the
    SPA catch-all at '/' swallowed the exact path and served index.html —
    Prometheus scraped HTML and the target was down since day one."""
    from warn_v2.api import create_app

    (tmp_path / "index.html").write_text(
        "<html><head><title>dev</title></head><body>SPA</body></html>",
        encoding="utf-8",
    )
    client = TestClient(create_app(static_dir=tmp_path), raise_server_exceptions=True)

    resp = client.get("/metrics")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/plain")
    assert "<html" not in resp.text

    # The SPA fallback still owns unknown non-API paths.
    spa = client.get("/notices")
    assert spa.status_code == 200
    assert spa.headers["content-type"].startswith("text/html")


def test_metrics_blocked_through_ingress(metrics_client):
    """Requests that traversed the ingress carry X-Forwarded-For and get 404."""
    resp = metrics_client.get("/metrics", headers={"X-Forwarded-For": "203.0.113.9"})
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Collector values
# ---------------------------------------------------------------------------

def test_collector_enrichment_metrics(db, metrics_client):
    now = datetime.now(UTC)
    db.add_all(
        [
            # provider hit
            Company(
                name="Enriched Co",
                enriched_at=now,
                enrichment_source="provider",
                provider_attempted_at=now,
            ),
            # untried
            Company(name="Untried Co"),
            # provider miss — queued for the backup tiers
            Company(name="Missed Co", provider_attempted_at=now),
        ]
    )
    db.flush()

    text = metrics_client.get("/metrics").text
    assert "warn_companies 3.0" in text
    assert "warn_enrichment_backlog 2.0" in text
    assert "warn_enrichment_provider_attempts_total 2.0" in text
    assert "warn_enrichment_provider_misses 1.0" in text
    assert 'warn_enrichment_total{source="provider"} 1.0' in text
