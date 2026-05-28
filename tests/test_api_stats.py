"""Tests for /stats aggregation endpoints."""
from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from warn_v2.db.models import Company, Notice


@pytest.fixture()
def api_client(db):
    from warn_v2.api import app
    from warn_v2.api.deps import get_db

    def _override():
        yield db

    app.dependency_overrides[get_db] = _override
    client = TestClient(app, raise_server_exceptions=True)
    yield client
    app.dependency_overrides.clear()


def _notice(
    db,
    *,
    state: str,
    employer: str,
    notice_date: date,
    layoff_count: int,
    company_id: int | None = None,
) -> Notice:
    nid = f"test_{state}_{notice_date}_{employer[:10]}_{layoff_count}"
    n = Notice(
        notice_id=nid,
        state=state,
        employer=employer,
        notice_date=notice_date,
        layoff_count=layoff_count,
        company_id=company_id,
    )
    db.add(n)
    db.flush()
    return n


# ---------------------------------------------------------------------------
# /stats/by-state
# ---------------------------------------------------------------------------

def test_by_state_empty(api_client, db):
    db.commit()
    resp = api_client.get("/stats/by-state")
    assert resp.status_code == 200
    assert resp.json() == []


def test_by_state_aggregates(api_client, db):
    _notice(db, state="CA", employer="Acme", notice_date=date(2026, 1, 1), layoff_count=100)
    _notice(db, state="CA", employer="Beta", notice_date=date(2026, 2, 1), layoff_count=200)
    _notice(db, state="TX", employer="Lone Star", notice_date=date(2026, 1, 15), layoff_count=50)
    db.commit()

    resp = api_client.get("/stats/by-state")
    body = resp.json()
    assert len(body) == 2
    ca = next(r for r in body if r["state"] == "CA")
    tx = next(r for r in body if r["state"] == "TX")
    assert ca["notice_count"] == 2
    assert ca["layoff_total"] == 300
    assert tx["notice_count"] == 1
    assert tx["layoff_total"] == 50


def test_by_state_date_filter(api_client, db):
    _notice(db, state="CA", employer="Old", notice_date=date(2025, 1, 1), layoff_count=10)
    _notice(db, state="CA", employer="New", notice_date=date(2026, 6, 1), layoff_count=20)
    db.commit()

    resp = api_client.get("/stats/by-state?after=2026-01-01")
    body = resp.json()
    assert len(body) == 1
    assert body[0]["notice_count"] == 1
    assert body[0]["layoff_total"] == 20


# ---------------------------------------------------------------------------
# /stats/by-month
# ---------------------------------------------------------------------------

def test_by_month_aggregates(api_client, db):
    _notice(db, state="CA", employer="A", notice_date=date(2026, 1, 5), layoff_count=10)
    _notice(db, state="CA", employer="B", notice_date=date(2026, 1, 20), layoff_count=25)
    _notice(db, state="CA", employer="C", notice_date=date(2026, 2, 1), layoff_count=40)
    db.commit()

    resp = api_client.get("/stats/by-month")
    body = resp.json()
    months = {r["month"]: r for r in body}
    assert months["2026-01"]["notice_count"] == 2
    assert months["2026-01"]["layoff_total"] == 35
    assert months["2026-02"]["notice_count"] == 1
    assert months["2026-02"]["layoff_total"] == 40


def test_by_month_state_filter(api_client, db):
    _notice(db, state="CA", employer="A", notice_date=date(2026, 1, 5), layoff_count=10)
    _notice(db, state="TX", employer="B", notice_date=date(2026, 1, 6), layoff_count=20)
    db.commit()

    resp = api_client.get("/stats/by-month?state=CA")
    body = resp.json()
    assert len(body) == 1
    assert body[0]["layoff_total"] == 10


def test_by_month_skips_null_dates(api_client, db):
    _notice(db, state="CA", employer="Dated", notice_date=date(2026, 1, 5), layoff_count=10)
    n = Notice(
        notice_id="no_date_test",
        state="CA",
        employer="No Date",
        notice_date=None,
        layoff_count=5,
    )
    db.add(n)
    db.commit()

    resp = api_client.get("/stats/by-month")
    body = resp.json()
    assert all(r["month"] is not None for r in body)
    assert len(body) == 1


# ---------------------------------------------------------------------------
# /stats/top-employers
# ---------------------------------------------------------------------------

def test_top_employers_sorted_desc(api_client, db):
    c1 = Company(name="Big Co")
    db.add(c1)
    db.flush()
    c2 = Company(name="Small Co")
    db.add(c2)
    db.flush()
    _notice(db, state="CA", employer="Big Co", notice_date=date(2026, 1, 1),
            layoff_count=1000, company_id=c1.id)
    _notice(db, state="CA", employer="Big Co", notice_date=date(2026, 2, 1),
            layoff_count=500, company_id=c1.id)
    _notice(db, state="CA", employer="Small Co", notice_date=date(2026, 1, 1),
            layoff_count=20, company_id=c2.id)
    db.commit()

    resp = api_client.get("/stats/top-employers")
    body = resp.json()
    assert body[0]["employer"] == "Big Co"
    assert body[0]["layoff_total"] == 1500
    assert body[0]["notice_count"] == 2
    assert body[1]["employer"] == "Small Co"
    assert body[1]["layoff_total"] == 20


def test_top_employers_limit(api_client, db):
    for i in range(5):
        _notice(db, state="CA", employer=f"Emp {i}", notice_date=date(2026, 1, i + 1),
                layoff_count=10 * (i + 1))
    db.commit()

    resp = api_client.get("/stats/top-employers?limit=3")
    body = resp.json()
    assert len(body) == 3


def test_top_employers_state_filter(api_client, db):
    _notice(db, state="CA", employer="Cali", notice_date=date(2026, 1, 1), layoff_count=100)
    _notice(db, state="TX", employer="Tex", notice_date=date(2026, 1, 1), layoff_count=200)
    db.commit()

    resp = api_client.get("/stats/top-employers?state=CA")
    body = resp.json()
    assert len(body) == 1
    assert body[0]["employer"] == "Cali"


# Ensure unused imports don't break ruff
_ = (UTC, datetime, Decimal)
