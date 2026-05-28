"""Integration tests for the FastAPI read-only API."""
from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from warn_v2.db.models import Company, Notice, ScraperRun

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def api_client(db):
    """TestClient wired to the in-memory SQLite DB via dependency override."""
    from warn_v2.api import app
    from warn_v2.api.deps import get_db

    def _override():
        yield db

    app.dependency_overrides[get_db] = _override
    client = TestClient(app, raise_server_exceptions=True)
    yield client
    app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _company(db, name: str = "Acme Inc", **kw) -> Company:
    c = Company(name=name, **kw)
    db.add(c)
    db.flush()
    return c


def _notice(
    db,
    company: Company | None = None,
    state: str = "CA",
    employer: str = "Acme Inc",
    notice_date: date = date(2026, 1, 15),
    layoff_count: int = 100,
) -> Notice:
    nid = f"test_{state}_{notice_date}_{employer[:8]}"
    n = Notice(
        notice_id=nid,
        state=state,
        employer=employer,
        notice_date=notice_date,
        layoff_count=layoff_count,
        company_id=company.id if company else None,
    )
    db.add(n)
    db.flush()
    return n


def _run(db, state: str = "CA", status: str = "ok") -> ScraperRun:
    r = ScraperRun(
        state=state,
        started_at=datetime.now(UTC),
        status=status,
    )
    db.add(r)
    db.flush()
    return r


# ---------------------------------------------------------------------------
# /healthz
# ---------------------------------------------------------------------------

def test_healthz(api_client):
    resp = api_client.get("/healthz")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


# ---------------------------------------------------------------------------
# /notices
# ---------------------------------------------------------------------------

def test_notices_empty(api_client, db):
    db.commit()
    resp = api_client.get("/notices")
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 0
    assert body["items"] == []


def test_notices_returns_data(api_client, db):
    _notice(db, state="CA")
    _notice(db, state="TX", employer="Texas Co", notice_date=date(2026, 2, 1))
    db.commit()

    resp = api_client.get("/notices")
    assert resp.status_code == 200
    assert resp.json()["total"] == 2


def test_notices_state_filter(api_client, db):
    _notice(db, state="CA")
    _notice(db, state="TX", employer="Texas Co", notice_date=date(2026, 2, 1))
    db.commit()

    resp = api_client.get("/notices?state=CA")
    body = resp.json()
    assert body["total"] == 1
    assert body["items"][0]["state"] == "CA"


def test_notices_employer_filter_ilike(api_client, db):
    _notice(db, employer="Acme Robotics Inc")
    _notice(db, employer="Other Corp", notice_date=date(2026, 2, 1))
    db.commit()

    resp = api_client.get("/notices?employer=acme")
    body = resp.json()
    assert body["total"] == 1
    assert "Acme" in body["items"][0]["employer"]


def test_notices_pagination(api_client, db):
    for i in range(5):
        _notice(db, employer=f"Corp {i}", notice_date=date(2026, 1, i + 1))
    db.commit()

    resp = api_client.get("/notices?limit=2&offset=0")
    body = resp.json()
    assert body["total"] == 5
    assert len(body["items"]) == 2
    assert body["limit"] == 2
    assert body["offset"] == 0


def test_notices_date_filter(api_client, db):
    _notice(db, notice_date=date(2026, 1, 1))
    _notice(db, employer="Late Corp", notice_date=date(2026, 6, 1))
    db.commit()

    resp = api_client.get("/notices?after=2026-03-01")
    body = resp.json()
    assert body["total"] == 1
    assert body["items"][0]["employer"] == "Late Corp"


def test_notice_detail_found(api_client, db):
    c = _company(db)
    n = _notice(db, company=c)
    db.commit()

    resp = api_client.get(f"/notices/{n.notice_id}")
    assert resp.status_code == 200
    body = resp.json()
    assert body["notice_id"] == n.notice_id
    assert body["company"]["id"] == c.id


def test_notice_detail_not_found(api_client, db):
    db.commit()
    resp = api_client.get("/notices/does-not-exist")
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# /companies
# ---------------------------------------------------------------------------

def test_companies_empty(api_client, db):
    db.commit()
    resp = api_client.get("/companies")
    assert resp.status_code == 200
    assert resp.json()["total"] == 0


def test_companies_list(api_client, db):
    _company(db, name="Alpha Inc")
    _company(db, name="Beta Corp")
    db.commit()

    resp = api_client.get("/companies")
    assert resp.json()["total"] == 2


def test_companies_enriched_filter_false(api_client, db):
    _company(db, name="Unenriched")
    _company(
        db,
        name="Enriched",
        enriched_at=datetime.now(UTC),
        enrichment_confidence=Decimal("0.9"),
    )
    db.commit()

    resp = api_client.get("/companies?enriched=false")
    body = resp.json()
    assert body["total"] == 1
    assert body["items"][0]["name"] == "Unenriched"


def test_companies_enriched_filter_true(api_client, db):
    _company(db, name="Unenriched")
    _company(
        db,
        name="Enriched",
        enriched_at=datetime.now(UTC),
        enrichment_confidence=Decimal("0.9"),
    )
    db.commit()

    resp = api_client.get("/companies?enriched=true")
    body = resp.json()
    assert body["total"] == 1
    assert body["items"][0]["name"] == "Enriched"


def test_company_detail_found(api_client, db):
    c = _company(db)
    db.commit()

    resp = api_client.get(f"/companies/{c.id}")
    assert resp.status_code == 200
    assert resp.json()["name"] == c.name


def test_company_detail_not_found(api_client, db):
    db.commit()
    resp = api_client.get("/companies/99999")
    assert resp.status_code == 404


def test_company_notices(api_client, db):
    c = _company(db)
    _notice(db, company=c)
    _notice(db, company=c, notice_date=date(2026, 3, 1), employer="Acme Inc")
    db.commit()

    resp = api_client.get(f"/companies/{c.id}/notices")
    assert resp.status_code == 200
    assert resp.json()["total"] == 2


# ---------------------------------------------------------------------------
# /scraper-runs
# ---------------------------------------------------------------------------

def test_scraper_runs_empty(api_client, db):
    db.commit()
    resp = api_client.get("/scraper-runs")
    assert resp.status_code == 200
    assert resp.json()["total"] == 0


def test_scraper_runs_list(api_client, db):
    _run(db, state="CA", status="ok")
    _run(db, state="TX", status="parse_failed")
    db.commit()

    resp = api_client.get("/scraper-runs")
    assert resp.json()["total"] == 2


def test_scraper_runs_status_filter(api_client, db):
    _run(db, state="CA", status="ok")
    _run(db, state="TX", status="parse_failed")
    db.commit()

    resp = api_client.get("/scraper-runs?status=ok")
    body = resp.json()
    assert body["total"] == 1
    assert body["items"][0]["status"] == "ok"


def test_scraper_runs_state_filter(api_client, db):
    _run(db, state="CA", status="ok")
    _run(db, state="TX", status="ok")
    db.commit()

    resp = api_client.get("/scraper-runs?state=TX")
    body = resp.json()
    assert body["total"] == 1
    assert body["items"][0]["state"] == "TX"
