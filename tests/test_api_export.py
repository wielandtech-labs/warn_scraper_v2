"""Tests for /api/notices/export and /api/companies/export."""
from __future__ import annotations

import csv
import io
from datetime import date

import pytest
from fastapi.testclient import TestClient

from warn_v2 import auth
from warn_v2.api.routes import exports
from warn_v2.db.models import Company, Notice, User

PASSWORD = "correct-horse-battery"


@pytest.fixture()
def api_client(db):
    from warn_v2.api import app
    from warn_v2.api.deps import get_db

    def _override():
        yield db

    app.dependency_overrides[get_db] = _override
    client = TestClient(app, base_url="https://testserver", raise_server_exceptions=True)
    yield client
    app.dependency_overrides.clear()


def _user(db, email, role="free"):
    u = User(email=email, password_hash=auth.hash_password(PASSWORD), role=role)
    db.add(u)
    db.flush()
    return u


def _login(api_client, email):
    assert api_client.post(
        "/api/auth/login", json={"email": email, "password": PASSWORD}
    ).status_code == 200


def _notice(db, employer="Acme Inc", state="CA", notice_date=date(2026, 1, 1),
            company=None, **kw):
    n = Notice(
        notice_id=f"x_{state}_{employer[:8]}_{notice_date}",
        state=state, employer=employer, notice_date=notice_date,
        company_id=company.id if company else None, **kw,
    )
    db.add(n)
    db.flush()
    return n


def _rows(text):
    return list(csv.reader(io.StringIO(text)))


def test_notices_export_csv(api_client, db):
    _notice(db, employer="Acme Inc", state="CA", layoff_count=100)
    _notice(db, employer="Texas Co", state="TX", notice_date=date(2026, 2, 1))
    db.commit()

    resp = api_client.get("/api/notices/export")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/csv")
    assert "attachment" in resp.headers["content-disposition"]
    rows = _rows(resp.text)
    assert rows[0][:3] == ["notice_id", "state", "employer"]
    assert len(rows) == 3  # header + 2 notices
    assert "company_duns" not in rows[0]  # enriched columns hidden for anon


def test_notices_export_json_and_state_filter(api_client, db):
    _notice(db, employer="Acme Inc", state="CA")
    _notice(db, employer="Texas Co", state="TX", notice_date=date(2026, 2, 1))
    db.commit()

    body = api_client.get("/api/notices/export?format=json&state=TX").json()
    assert isinstance(body, list)
    assert len(body) == 1
    assert body[0]["employer"] == "Texas Co"
    assert "company_duns" not in body[0]


def test_notices_export_excludes_superseded(api_client, db):
    _notice(db, employer="Active Co")
    sup = _notice(db, employer="Old Co", notice_date=date(2026, 1, 2))
    sup.is_superseded = True
    db.commit()

    rows = _rows(api_client.get("/api/notices/export").text)
    employers = {r[2] for r in rows[1:]}
    assert employers == {"Active Co"}


def test_notices_export_paid_includes_enriched_columns_but_no_duns(api_client, db):
    c = Company(name="Acme Inc", duns="123456789", parent_company_name="Acme Holdings",
                employee_count=500)
    db.add(c)
    db.flush()
    _notice(db, employer="Acme Inc", company=c)
    _user(db, "p@example.com", role="paid")
    db.commit()
    _login(api_client, "p@example.com")

    body = api_client.get("/api/notices/export?format=json").json()
    assert body[0]["parent_company_name"] == "Acme Holdings"
    assert body[0]["employee_count"] == 500
    assert "company_duns" not in body[0]  # DUNS is enterprise-only


@pytest.mark.parametrize("role", ["enterprise", "admin"])
def test_notices_export_enterprise_includes_duns(api_client, db, role):
    c = Company(name="Acme Inc", duns="123456789", parent_company_name="Acme Holdings")
    db.add(c)
    db.flush()
    _notice(db, employer="Acme Inc", company=c)
    _user(db, "e@example.com", role=role)
    db.commit()
    _login(api_client, "e@example.com")

    body = api_client.get("/api/notices/export?format=json").json()
    assert body[0]["company_duns"] == "123456789"
    assert body[0]["parent_company_name"] == "Acme Holdings"


def test_notices_export_respects_free_cap(api_client, db, monkeypatch):
    monkeypatch.setattr(exports, "FREE_EXPORT_CAP", 1)
    _notice(db, employer="A Co", notice_date=date(2026, 1, 1))
    _notice(db, employer="B Co", notice_date=date(2026, 2, 1))
    db.commit()

    rows = _rows(api_client.get("/api/notices/export").text)
    assert len(rows) == 2  # header + 1 capped row


def test_companies_export_csv_with_layoff_total(api_client, db):
    c = Company(name="Acme Inc")
    db.add(c)
    db.flush()
    _notice(db, employer="Acme Inc", company=c, layoff_count=100)
    db.commit()

    rows = _rows(api_client.get("/api/companies/export").text)
    assert rows[0][0] == "id"
    assert "layoff_total" in rows[0]
    assert "duns" not in rows[0]  # enriched hidden for anon
    lt_idx = rows[0].index("layoff_total")
    assert rows[1][lt_idx] == "100"


def test_companies_export_enterprise_includes_duns_paid_does_not(api_client, db):
    db.add(Company(name="Acme Inc", duns="123456789", parent_duns="987654321",
                   hq_address="1 Acme Way"))
    _user(db, "p@example.com", role="paid")
    _user(db, "a@example.com", role="admin")
    db.commit()

    _login(api_client, "p@example.com")
    body = api_client.get("/api/companies/export?format=json").json()
    assert body[0]["hq_address"] == "1 Acme Way"
    assert "duns" not in body[0]
    assert "parent_duns" not in body[0]

    _login(api_client, "a@example.com")
    body = api_client.get("/api/companies/export?format=json").json()
    assert body[0]["duns"] == "123456789"
    assert body[0]["parent_duns"] == "987654321"


def test_notices_export_invalid_format_rejected(api_client, db):
    db.commit()
    assert api_client.get("/api/notices/export?format=xml").status_code == 422


def test_export_route_not_shadowed_by_notice_id(api_client, db):
    """/api/notices/export must hit the export route, not /notices/{id}='export'."""
    db.commit()
    assert api_client.get("/api/notices/export").status_code == 200
