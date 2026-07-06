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
    closure_category: str | None = None,
) -> Notice:
    nid = f"test_{state}_{notice_date}_{employer[:10]}_{layoff_count}"
    n = Notice(
        notice_id=nid,
        state=state,
        employer=employer,
        notice_date=notice_date,
        layoff_count=layoff_count,
        company_id=company_id,
        closure_category=closure_category,
    )
    db.add(n)
    db.flush()
    return n


# ---------------------------------------------------------------------------
# /stats/by-state
# ---------------------------------------------------------------------------

def test_by_state_empty(api_client, db):
    db.commit()
    resp = api_client.get("/api/stats/by-state")
    assert resp.status_code == 200
    assert resp.json() == []


def test_by_state_aggregates(api_client, db):
    _notice(db, state="CA", employer="Acme", notice_date=date(2026, 1, 1), layoff_count=100)
    _notice(db, state="CA", employer="Beta", notice_date=date(2026, 2, 1), layoff_count=200)
    _notice(db, state="TX", employer="Lone Star", notice_date=date(2026, 1, 15), layoff_count=50)
    db.commit()

    resp = api_client.get("/api/stats/by-state")
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

    resp = api_client.get("/api/stats/by-state?after=2026-01-01")
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

    resp = api_client.get("/api/stats/by-month")
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

    resp = api_client.get("/api/stats/by-month?state=CA")
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

    resp = api_client.get("/api/stats/by-month")
    body = resp.json()
    assert all(r["month"] is not None for r in body)
    assert len(body) == 1


# ---------------------------------------------------------------------------
# /stats/over-time
# ---------------------------------------------------------------------------

def test_over_time_month_bucket(api_client, db):
    _notice(db, state="CA", employer="A", notice_date=date(2026, 1, 5), layoff_count=10)
    _notice(db, state="CA", employer="B", notice_date=date(2026, 1, 20), layoff_count=25)
    _notice(db, state="CA", employer="C", notice_date=date(2026, 2, 1), layoff_count=40)
    db.commit()

    body = api_client.get("/api/stats/over-time?bucket=month").json()
    periods = {r["period"]: r for r in body}
    assert periods["2026-01"]["notice_count"] == 2
    assert periods["2026-01"]["layoff_total"] == 35
    assert periods["2026-02"]["notice_count"] == 1
    assert periods["2026-02"]["layoff_total"] == 40


def test_over_time_day_bucket(api_client, db):
    _notice(db, state="CA", employer="A", notice_date=date(2026, 1, 5), layoff_count=10)
    _notice(db, state="CA", employer="B", notice_date=date(2026, 1, 5), layoff_count=25)
    _notice(db, state="CA", employer="C", notice_date=date(2026, 1, 6), layoff_count=40)
    db.commit()

    body = api_client.get("/api/stats/over-time?bucket=day").json()
    periods = {r["period"]: r for r in body}
    assert periods["2026-01-05"]["notice_count"] == 2
    assert periods["2026-01-05"]["layoff_total"] == 35
    assert periods["2026-01-06"]["notice_count"] == 1
    assert periods["2026-01-06"]["layoff_total"] == 40


def test_over_time_year_bucket(api_client, db):
    _notice(db, state="CA", employer="A", notice_date=date(2024, 3, 1), layoff_count=10)
    _notice(db, state="CA", employer="B", notice_date=date(2024, 9, 1), layoff_count=25)
    _notice(db, state="CA", employer="C", notice_date=date(2025, 2, 1), layoff_count=40)
    db.commit()

    body = api_client.get("/api/stats/over-time?bucket=year").json()
    periods = {r["period"]: r for r in body}
    assert periods["2024"]["notice_count"] == 2
    assert periods["2024"]["layoff_total"] == 35
    assert periods["2025"]["notice_count"] == 1
    assert periods["2025"]["layoff_total"] == 40


def test_over_time_defaults_to_month(api_client, db):
    _notice(db, state="CA", employer="A", notice_date=date(2026, 1, 5), layoff_count=10)
    db.commit()

    body = api_client.get("/api/stats/over-time").json()
    assert body[0]["period"] == "2026-01"


def test_over_time_state_and_date_filters(api_client, db):
    _notice(db, state="CA", employer="A", notice_date=date(2026, 1, 5), layoff_count=10)
    _notice(db, state="TX", employer="B", notice_date=date(2026, 1, 6), layoff_count=20)
    _notice(db, state="CA", employer="Old", notice_date=date(2025, 1, 1), layoff_count=99)
    db.commit()

    body = api_client.get(
        "/api/stats/over-time?bucket=day&state=CA&after=2026-01-01"
    ).json()
    assert len(body) == 1
    assert body[0]["period"] == "2026-01-05"
    assert body[0]["layoff_total"] == 10


# ---------------------------------------------------------------------------
# Pace projection for the current, incomplete period
# ---------------------------------------------------------------------------

def _freeze_today(monkeypatch: pytest.MonkeyPatch, d: date) -> None:
    from warn_v2.api.routes import stats as stats_routes

    monkeypatch.setattr(stats_routes, "_today", lambda: d)


def test_over_time_month_bucket_projects_current_month(api_client, db, monkeypatch):
    _freeze_today(monkeypatch, date(2026, 7, 15))  # July: 31 days, scale 31/15
    _notice(db, state="CA", employer="A", notice_date=date(2026, 6, 10), layoff_count=100)
    _notice(db, state="CA", employer="B", notice_date=date(2026, 7, 5), layoff_count=60)
    _notice(db, state="CA", employer="C", notice_date=date(2026, 7, 10), layoff_count=90)
    db.commit()

    body = api_client.get("/api/stats/over-time?bucket=month").json()
    periods = {r["period"]: r for r in body}
    cur = periods["2026-07"]
    assert cur["notice_count"] == 2  # actuals unchanged
    assert cur["layoff_total"] == 150
    assert cur["projected_notice_count"] == 4  # round(2 * 31/15)
    assert cur["projected_layoff_total"] == 310  # 150 * 31/15
    assert periods["2026-06"]["projected_notice_count"] is None
    assert periods["2026-06"]["projected_layoff_total"] is None


def test_over_time_year_bucket_projects_current_year(api_client, db, monkeypatch):
    _freeze_today(monkeypatch, date(2026, 3, 14))  # yday 73; 365/73 = 5.0
    _notice(db, state="CA", employer="Old", notice_date=date(2025, 6, 1), layoff_count=10)
    _notice(db, state="CA", employer="A", notice_date=date(2026, 1, 15), layoff_count=100)
    _notice(db, state="CA", employer="B", notice_date=date(2026, 2, 20), layoff_count=100)
    db.commit()

    body = api_client.get("/api/stats/over-time?bucket=year").json()
    periods = {r["period"]: r for r in body}
    assert periods["2026"]["projected_notice_count"] == 10  # 2 * 5
    assert periods["2026"]["projected_layoff_total"] == 1000  # 200 * 5
    assert periods["2025"]["projected_notice_count"] is None


def test_by_month_projects_current_month(api_client, db, monkeypatch):
    _freeze_today(monkeypatch, date(2026, 7, 15))
    _notice(db, state="CA", employer="A", notice_date=date(2026, 6, 10), layoff_count=100)
    _notice(db, state="CA", employer="B", notice_date=date(2026, 7, 5), layoff_count=60)
    _notice(db, state="CA", employer="C", notice_date=date(2026, 7, 10), layoff_count=90)
    db.commit()

    body = api_client.get("/api/stats/by-month").json()
    months = {r["month"]: r for r in body}
    assert months["2026-07"]["projected_notice_count"] == 4
    assert months["2026-07"]["projected_layoff_total"] == 310
    assert months["2026-06"]["projected_notice_count"] is None


def test_day_bucket_never_projected(api_client, db, monkeypatch):
    _freeze_today(monkeypatch, date(2026, 7, 15))
    _notice(db, state="CA", employer="A", notice_date=date(2026, 7, 15), layoff_count=50)
    db.commit()

    body = api_client.get("/api/stats/over-time?bucket=day").json()
    assert body[-1]["period"] == "2026-07-15"
    assert body[-1]["projected_notice_count"] is None
    assert body[-1]["projected_layoff_total"] is None


def test_no_projection_when_current_period_absent(api_client, db, monkeypatch):
    _freeze_today(monkeypatch, date(2026, 7, 15))
    _notice(db, state="CA", employer="A", notice_date=date(2026, 5, 10), layoff_count=10)
    _notice(db, state="CA", employer="B", notice_date=date(2026, 6, 10), layoff_count=20)
    db.commit()

    body = api_client.get("/api/stats/over-time?bucket=month").json()
    assert {r["period"] for r in body} == {"2026-05", "2026-06"}  # no synthetic row
    assert body[-1]["projected_notice_count"] is None


def test_no_projection_on_last_day_of_period(api_client, db, monkeypatch):
    _freeze_today(monkeypatch, date(2026, 7, 31))
    _notice(db, state="CA", employer="A", notice_date=date(2026, 7, 5), layoff_count=50)
    db.commit()

    body = api_client.get("/api/stats/over-time?bucket=month").json()
    assert body[-1]["period"] == "2026-07"
    assert body[-1]["projected_notice_count"] is None


def test_no_projection_early_in_month(api_client, db, monkeypatch):
    _notice(db, state="CA", employer="A", notice_date=date(2026, 7, 1), layoff_count=500)
    db.commit()

    # Day 2 of July: <10% elapsed, the 15.5x pace would blow out the y-axis.
    _freeze_today(monkeypatch, date(2026, 7, 2))
    body = api_client.get("/api/stats/over-time?bucket=month").json()
    assert body[-1]["projected_notice_count"] is None
    # Day 4: >=10% elapsed, projection kicks in.
    _freeze_today(monkeypatch, date(2026, 7, 4))
    body = api_client.get("/api/stats/over-time?bucket=month").json()
    assert body[-1]["projected_notice_count"] is not None


def test_no_projection_early_in_year(api_client, db, monkeypatch):
    _freeze_today(monkeypatch, date(2026, 1, 20))  # yday 20: <10% of 365
    _notice(db, state="CA", employer="A", notice_date=date(2026, 1, 5), layoff_count=500)
    db.commit()

    body = api_client.get("/api/stats/over-time?bucket=year").json()
    assert body[-1]["period"] == "2026"
    assert body[-1]["projected_notice_count"] is None


def test_projection_floor_at_actual(api_client, db, monkeypatch):
    _freeze_today(monkeypatch, date(2026, 7, 30))  # scale 31/30: rounds back to actual
    _notice(db, state="CA", employer="A", notice_date=date(2026, 7, 5), layoff_count=1)
    db.commit()

    body = api_client.get("/api/stats/over-time?bucket=month").json()
    assert body[-1]["projected_notice_count"] == 1  # never below the actual count
    assert body[-1]["projected_layoff_total"] == 1


def test_before_filter_suppresses_projection(api_client, db, monkeypatch):
    _freeze_today(monkeypatch, date(2026, 7, 15))
    _notice(db, state="CA", employer="A", notice_date=date(2026, 7, 5), layoff_count=60)
    db.commit()

    # before < today truncates the current period mid-way: no projection.
    body = api_client.get("/api/stats/over-time?bucket=month&before=2026-07-10").json()
    assert body[-1]["projected_notice_count"] is None
    # before >= today doesn't truncate: projection present.
    body = api_client.get("/api/stats/over-time?bucket=month&before=2026-08-01").json()
    assert body[-1]["projected_notice_count"] is not None


def test_after_inside_current_period_suppresses_projection(api_client, db, monkeypatch):
    _freeze_today(monkeypatch, date(2026, 7, 15))
    _notice(db, state="CA", employer="A", notice_date=date(2026, 7, 5), layoff_count=60)
    _notice(db, state="CA", employer="B", notice_date=date(2026, 7, 10), layoff_count=90)
    db.commit()

    # after inside the month covers only part of the elapsed window: no projection.
    body = api_client.get("/api/stats/over-time?bucket=month&after=2026-07-03").json()
    assert body[-1]["projected_notice_count"] is None
    # after == period start covers the full elapsed window: projection present.
    body = api_client.get("/api/stats/over-time?bucket=month&after=2026-07-01").json()
    assert body[-1]["projected_notice_count"] == 4  # round(2 * 31/15)


def test_leap_year_projection(api_client, db, monkeypatch):
    _freeze_today(monkeypatch, date(2028, 3, 1))  # leap year, yday 61; 366/61 = 6.0
    _notice(db, state="CA", employer="A", notice_date=date(2028, 1, 10), layoff_count=61)
    db.commit()

    body = api_client.get("/api/stats/over-time?bucket=year").json()
    assert body[-1]["period"] == "2028"
    assert body[-1]["projected_notice_count"] == 6
    assert body[-1]["projected_layoff_total"] == 366


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

    resp = api_client.get("/api/stats/top-employers")
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

    resp = api_client.get("/api/stats/top-employers?limit=3")
    body = resp.json()
    assert len(body) == 3


def test_top_employers_state_filter(api_client, db):
    _notice(db, state="CA", employer="Cali", notice_date=date(2026, 1, 1), layoff_count=100)
    _notice(db, state="TX", employer="Tex", notice_date=date(2026, 1, 1), layoff_count=200)
    db.commit()

    resp = api_client.get("/api/stats/top-employers?state=CA")
    body = resp.json()
    assert len(body) == 1
    assert body[0]["employer"] == "Cali"


# ---------------------------------------------------------------------------
# is_superseded filtering
# ---------------------------------------------------------------------------

def test_superseded_notices_excluded_from_all_endpoints(api_client, db):
    """Superseded notices must not count toward any stats aggregate."""
    _notice(db, state="CA", employer="Active", notice_date=date(2026, 1, 1), layoff_count=100)
    sup = _notice(db, state="CA", employer="Superseded", notice_date=date(2026, 1, 1),
                  layoff_count=50)
    sup.is_superseded = True
    db.commit()

    # by-state: only Active's count should appear
    body = api_client.get("/api/stats/by-state").json()
    ca = next(r for r in body if r["state"] == "CA")
    assert ca["notice_count"] == 1
    assert ca["layoff_total"] == 100

    # by-month: same
    body = api_client.get("/api/stats/by-month").json()
    assert len(body) == 1
    assert body[0]["notice_count"] == 1
    assert body[0]["layoff_total"] == 100

    # top-employers: only Active appears
    body = api_client.get("/api/stats/top-employers").json()
    assert len(body) == 1
    assert body[0]["employer"] == "Active"


# ---------------------------------------------------------------------------
# /stats/by-parent-group
# ---------------------------------------------------------------------------

def _company(db, name: str, **kw) -> Company:
    c = Company(name=name, **kw)
    db.add(c)
    db.flush()
    return c


def test_by_parent_group_ranks_families_by_layoffs(api_client, db):
    # Two families; Disney (sum 400) should outrank Comcast (sum 150).
    pix = _company(db, name="Pixar", parent_group_key="ult:disney")
    mar = _company(db, name="Marvel Studios", parent_group_key="ult:disney")
    dwm = _company(db, name="DreamWorks", parent_group_key="ult:comcast")
    foc = _company(db, name="Focus Features", parent_group_key="ult:comcast")
    _notice(db, state="CA", employer="Pixar", notice_date=date(2026, 1, 1),
            layoff_count=100, company_id=pix.id)
    _notice(db, state="CA", employer="Marvel", notice_date=date(2026, 1, 2),
            layoff_count=300, company_id=mar.id)
    _notice(db, state="CA", employer="DreamWorks", notice_date=date(2026, 1, 3),
            layoff_count=100, company_id=dwm.id)
    _notice(db, state="CA", employer="Focus", notice_date=date(2026, 1, 4),
            layoff_count=50, company_id=foc.id)
    db.commit()

    body = api_client.get("/api/stats/by-parent-group").json()
    assert len(body) == 2
    assert body[0]["layoff_total"] == 400
    assert body[0]["member_count"] == 2
    # Representative = largest member (Marvel, 300).
    assert body[0]["representative_company_name"] == "Marvel Studios"
    assert body[0]["representative_company_id"] == mar.id
    assert body[0]["notice_count"] == 2
    assert body[1]["layoff_total"] == 150


def test_by_parent_group_excludes_singletons_and_self_keys(api_client, db):
    # A real 2-member family, a singleton real family, and a self-keyed company.
    a = _company(db, name="Pixar", parent_group_key="ult:disney")
    b = _company(db, name="Marvel Studios", parent_group_key="ult:disney")
    solo = _company(db, name="Lonely Sub", parent_group_key="ult:lonelyparent")
    selfc = _company(db, name="Independent Co", parent_group_key="self:independent co")
    _notice(db, state="CA", employer="Pixar", notice_date=date(2026, 1, 1),
            layoff_count=10, company_id=a.id)
    _notice(db, state="CA", employer="Marvel", notice_date=date(2026, 1, 2),
            layoff_count=20, company_id=b.id)
    _notice(db, state="CA", employer="Lonely", notice_date=date(2026, 1, 3),
            layoff_count=999, company_id=solo.id)
    _notice(db, state="CA", employer="Indie", notice_date=date(2026, 1, 4),
            layoff_count=999, company_id=selfc.id)
    db.commit()

    body = api_client.get("/api/stats/by-parent-group").json()
    assert len(body) == 1  # only the 2-member Disney family
    assert body[0]["representative_company_name"] == "Marvel Studios"


def test_by_parent_group_rolls_up_merged_dupes(api_client, db):
    canon = _company(db, name="Pixar", parent_group_key="ult:disney")
    mar = _company(db, name="Marvel Studios", parent_group_key="ult:disney")
    dupe = _company(db, name="Pixar Animation")
    dupe.canonical_company_id = canon.id
    db.flush()
    _notice(db, state="CA", employer="Pixar", notice_date=date(2026, 1, 1),
            layoff_count=100, company_id=canon.id)
    _notice(db, state="CA", employer="PixarAnim", notice_date=date(2026, 1, 2),
            layoff_count=40, company_id=dupe.id)
    _notice(db, state="CA", employer="Marvel", notice_date=date(2026, 1, 3),
            layoff_count=10, company_id=mar.id)
    db.commit()

    body = api_client.get("/api/stats/by-parent-group").json()
    assert len(body) == 1
    # Pixar canonical = 140 (own + dupe), Marvel = 10, family total 150, 2 members.
    assert body[0]["layoff_total"] == 150
    assert body[0]["member_count"] == 2
    assert body[0]["representative_company_name"] == "Pixar"


def test_by_parent_group_excludes_superseded(api_client, db):
    a = _company(db, name="Pixar", parent_group_key="ult:disney")
    b = _company(db, name="Marvel Studios", parent_group_key="ult:disney")
    _notice(db, state="CA", employer="Pixar", notice_date=date(2026, 1, 1),
            layoff_count=100, company_id=a.id)
    sup = _notice(db, state="CA", employer="Pixar", notice_date=date(2026, 1, 2),
                  layoff_count=999, company_id=a.id)
    sup.is_superseded = True
    _notice(db, state="CA", employer="Marvel", notice_date=date(2026, 1, 3),
            layoff_count=50, company_id=b.id)
    db.commit()

    body = api_client.get("/api/stats/by-parent-group").json()
    assert len(body) == 1
    assert body[0]["layoff_total"] == 150  # superseded 999 excluded


def test_by_parent_group_state_and_date_filters(api_client, db):
    a = _company(db, name="Pixar", parent_group_key="ult:disney")
    b = _company(db, name="Marvel Studios", parent_group_key="ult:disney")
    _notice(db, state="CA", employer="Pixar", notice_date=date(2026, 6, 1),
            layoff_count=100, company_id=a.id)
    _notice(db, state="TX", employer="Marvel", notice_date=date(2026, 6, 1),
            layoff_count=200, company_id=b.id)
    _notice(db, state="CA", employer="Marvel", notice_date=date(2020, 1, 1),
            layoff_count=999, company_id=b.id)
    db.commit()

    # State filter: only CA notices -> Pixar(100) + Marvel old(999) in CA; both
    # members present so the family survives, but TX notice is excluded.
    ca = api_client.get("/api/stats/by-parent-group?state=CA").json()
    assert len(ca) == 1
    assert ca[0]["layoff_total"] == 1099  # 100 + 999 (both CA), TX 200 excluded

    # Date filter drops the 2020 notice -> only Pixar(100) remains in CA -> the
    # family collapses to a singleton and is excluded.
    recent = api_client.get(
        "/api/stats/by-parent-group?state=CA&after=2026-01-01"
    ).json()
    assert recent == []


def test_industries_rolls_up_to_sectors(api_client, db):
    mfg = _company(db, name="Mfg", naics_code="311999")
    mfg2 = _company(db, name="Mfg2", naics_code="332000")
    ret = _company(db, name="Ret", naics_code="445110")
    noind = _company(db, name="NoInd")  # no naics_code -> omitted
    _notice(db, state="CA", employer="Mfg", notice_date=date(2026, 1, 1),
            layoff_count=1, company_id=mfg.id)
    _notice(db, state="CA", employer="Mfg2", notice_date=date(2026, 1, 2),
            layoff_count=1, company_id=mfg2.id)
    _notice(db, state="CA", employer="Ret", notice_date=date(2026, 1, 3),
            layoff_count=1, company_id=ret.id)
    _notice(db, state="CA", employer="NoInd", notice_date=date(2026, 1, 4),
            layoff_count=1, company_id=noind.id)
    db.commit()

    body = api_client.get("/api/stats/industries").json()
    sectors = {r["sector"]: r for r in body}
    assert sectors["31-33"]["notice_count"] == 2  # both manufacturing codes
    assert sectors["31-33"]["name"] == "Manufacturing"
    assert sectors["44-45"]["notice_count"] == 1
    # ordered by count desc; no sector for the un-enriched company
    assert body[0]["sector"] == "31-33"


def test_industries_excludes_superseded(api_client, db):
    mfg = _company(db, name="Mfg", naics_code="311999")
    _notice(db, state="CA", employer="Mfg", notice_date=date(2026, 1, 1),
            layoff_count=1, company_id=mfg.id)
    sup = _notice(db, state="CA", employer="Mfg", notice_date=date(2026, 1, 2),
                  layoff_count=1, company_id=mfg.id)
    sup.is_superseded = True
    db.commit()

    body = api_client.get("/api/stats/industries").json()
    assert {r["sector"]: r["notice_count"] for r in body} == {"31-33": 1}


def test_industries_nests_subsectors(api_client, db):
    food = _company(db, name="Food", naics_code="311999")
    food2 = _company(db, name="Food2", naics_code="311111")  # same subsector 311
    mach = _company(db, name="Mach", naics_code="333120")     # 333, same sector 31-33
    _notice(db, state="CA", employer="Food", notice_date=date(2026, 1, 1),
            layoff_count=1, company_id=food.id)
    _notice(db, state="CA", employer="Food2", notice_date=date(2026, 1, 2),
            layoff_count=1, company_id=food2.id)
    _notice(db, state="CA", employer="Mach", notice_date=date(2026, 1, 3),
            layoff_count=1, company_id=mach.id)
    db.commit()

    body = api_client.get("/api/stats/industries").json()
    mfg = next(r for r in body if r["sector"] == "31-33")
    assert mfg["notice_count"] == 3  # sector total = sum of subsectors
    subs = {s["code"]: s for s in mfg["subsectors"]}
    assert subs["311"]["notice_count"] == 2
    assert subs["311"]["name"] == "Food Manufacturing"
    assert subs["333"]["notice_count"] == 1
    # populated-only: a subsector with no notices is absent
    assert "312" not in subs


def test_industries_includes_layoff_totals(api_client, db):
    food = _company(db, name="Food", naics_code="311999")
    food2 = _company(db, name="Food2", naics_code="311111")  # same subsector 311
    _notice(db, state="CA", employer="Food", notice_date=date(2026, 1, 1),
            layoff_count=100, company_id=food.id)
    _notice(db, state="CA", employer="Food2", notice_date=date(2026, 1, 2),
            layoff_count=40, company_id=food2.id)
    db.commit()

    body = api_client.get("/api/stats/industries").json()
    mfg = next(r for r in body if r["sector"] == "31-33")
    assert mfg["layoff_total"] == 140  # sector total = sum of subsectors
    sub311 = next(s for s in mfg["subsectors"] if s["code"] == "311")
    assert sub311["layoff_total"] == 140


def test_industries_date_and_state_filters(api_client, db):
    mfg = _company(db, name="Mfg", naics_code="311999")
    ret = _company(db, name="Ret", naics_code="445110")
    _notice(db, state="CA", employer="Mfg", notice_date=date(2026, 6, 1),
            layoff_count=100, company_id=mfg.id)
    _notice(db, state="CA", employer="MfgOld", notice_date=date(2020, 1, 1),
            layoff_count=999, company_id=mfg.id)
    _notice(db, state="TX", employer="Ret", notice_date=date(2026, 6, 1),
            layoff_count=50, company_id=ret.id)
    db.commit()

    # Date filter drops the 2020 notice; state filter drops the TX retail notice.
    body = api_client.get(
        "/api/stats/industries?after=2026-01-01&state=CA"
    ).json()
    assert [r["sector"] for r in body] == ["31-33"]
    assert body[0]["notice_count"] == 1
    assert body[0]["layoff_total"] == 100


def test_industries_omits_empty_sectors_and_subsectors(api_client, db):
    food = _company(db, name="Food", naics_code="311999")
    _notice(db, state="CA", employer="Food", notice_date=date(2026, 1, 1),
            layoff_count=1, company_id=food.id)
    db.commit()

    body = api_client.get("/api/stats/industries").json()
    # exactly the one populated sector, with exactly its one populated subsector
    assert [r["sector"] for r in body] == ["31-33"]
    assert [s["code"] for r in body for s in r["subsectors"]] == ["311"]


def test_by_parent_group_empty_when_no_families(api_client, db):
    c = _company(db, name="Independent Co", parent_group_key="self:independent co")
    _notice(db, state="CA", employer="Indie", notice_date=date(2026, 1, 1),
            layoff_count=10, company_id=c.id)
    db.commit()

    assert api_client.get("/api/stats/by-parent-group").json() == []


def test_top_employers_returns_canonical_company_id(api_client, db):
    """company_id must be the canonical id, and null for unlinked notices.

    Regression: company_id was selected un-aggregated, which raises a GROUP BY
    error on Postgres (SQLite tolerates it). The fix wraps it in min(); this
    asserts the value is still correct after that change.
    """
    c = _company(db, name="Acme Inc")
    _notice(db, state="CA", employer="Acme Inc", notice_date=date(2026, 1, 1),
            layoff_count=100, company_id=c.id)
    _notice(db, state="CA", employer="Unlinked", notice_date=date(2026, 1, 2),
            layoff_count=50)  # no company_id -> grouped by employer string
    db.commit()

    body = api_client.get("/api/stats/top-employers").json()
    by_emp = {r["employer"]: r for r in body}
    assert by_emp["Acme Inc"]["company_id"] == c.id
    assert by_emp["Unlinked"]["company_id"] is None


def test_top_employers_industry_filter(api_client, db):
    mfg = _company(db, name="Mfg Co", naics_code="311999")
    ret = _company(db, name="Ret Co", naics_code="445110")
    _notice(db, state="CA", employer="Mfg Co", notice_date=date(2026, 1, 1),
            layoff_count=100, company_id=mfg.id)
    _notice(db, state="CA", employer="Ret Co", notice_date=date(2026, 1, 2),
            layoff_count=200, company_id=ret.id)
    db.commit()

    assert [r["employer"] for r in
            api_client.get("/api/stats/top-employers?industry=31-33").json()] == ["Mfg Co"]
    # subsector narrows; and wins over a conflicting sector
    assert [r["employer"] for r in
            api_client.get("/api/stats/top-employers?subsector=311").json()] == ["Mfg Co"]
    assert [r["employer"] for r in api_client.get(
        "/api/stats/top-employers?industry=44-45&subsector=311").json()] == ["Mfg Co"]


def test_by_state_industry_filter(api_client, db):
    mfg = _company(db, name="Mfg Co", naics_code="311999")
    ret = _company(db, name="Ret Co", naics_code="445110")
    _notice(db, state="CA", employer="Mfg Co", notice_date=date(2026, 1, 1),
            layoff_count=100, company_id=mfg.id)
    _notice(db, state="TX", employer="Ret Co", notice_date=date(2026, 1, 2),
            layoff_count=200, company_id=ret.id)
    db.commit()

    body = api_client.get("/api/stats/by-state?industry=31-33").json()
    assert len(body) == 1
    assert body[0]["state"] == "CA"
    assert body[0]["layoff_total"] == 100


def test_by_month_industry_filter(api_client, db):
    mfg = _company(db, name="Mfg Co", naics_code="311999")
    ret = _company(db, name="Ret Co", naics_code="445110")
    _notice(db, state="CA", employer="Mfg Co", notice_date=date(2026, 1, 1),
            layoff_count=100, company_id=mfg.id)
    _notice(db, state="CA", employer="Ret Co", notice_date=date(2026, 1, 2),
            layoff_count=200, company_id=ret.id)
    db.commit()

    body = api_client.get("/api/stats/by-month?industry=44-45").json()
    assert len(body) == 1
    assert body[0]["layoff_total"] == 200


def test_by_state_closure_category_filter(api_client, db):
    _notice(db, state="CA", employer="Closing Co", notice_date=date(2026, 1, 1),
            layoff_count=100, closure_category="Closure")
    _notice(db, state="TX", employer="Layoff Co", notice_date=date(2026, 1, 2),
            layoff_count=200, closure_category="Layoff")
    _notice(db, state="NY", employer="Unknown Co", notice_date=date(2026, 1, 3),
            layoff_count=50)
    db.commit()

    body = api_client.get("/api/stats/by-state?closure_category=Closure").json()
    assert len(body) == 1
    assert body[0]["state"] == "CA"
    assert body[0]["layoff_total"] == 100


def test_by_month_closure_category_filter(api_client, db):
    _notice(db, state="CA", employer="Closing Co", notice_date=date(2026, 1, 1),
            layoff_count=100, closure_category="Closure")
    _notice(db, state="CA", employer="Layoff Co", notice_date=date(2026, 1, 2),
            layoff_count=200, closure_category="Layoff")
    db.commit()

    body = api_client.get("/api/stats/by-month?closure_category=Layoff").json()
    assert len(body) == 1
    assert body[0]["month"] == "2026-01"
    assert body[0]["layoff_total"] == 200


def test_top_employers_closure_category_filter(api_client, db):
    _notice(db, state="CA", employer="Closing Co", notice_date=date(2026, 1, 1),
            layoff_count=100, closure_category="Closure")
    _notice(db, state="CA", employer="Layoff Co", notice_date=date(2026, 1, 2),
            layoff_count=200, closure_category="Layoff")
    db.commit()

    assert [r["employer"] for r in
            api_client.get("/api/stats/top-employers?closure_category=Closure").json()
            ] == ["Closing Co"]


# Ensure unused imports don't break ruff
_ = (UTC, datetime, Decimal)
