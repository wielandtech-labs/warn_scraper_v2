"""Admin company merge/unmerge endpoints + the public /members listing."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from warn_v2 import auth
from warn_v2.db.models import Company, CompanyMergeOverride, Notice, User

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


def _login_as(db, api_client, role: str) -> User:
    u = User(email=f"{role}@example.com", password_hash=auth.hash_password(PASSWORD), role=role)
    db.add(u)
    db.commit()
    resp = api_client.post("/api/auth/login", json={"email": u.email, "password": PASSWORD})
    assert resp.status_code == 200
    return u


@pytest.fixture()
def kmart(db):
    """Clean-named row auto-merged under a store-numbered survivor, plus strays."""
    store = Company(name="KMART CORPORATION # 7435")
    db.add(store)
    db.flush()
    clean = Company(name="Kmart Corporation", canonical_company_id=store.id)
    stray = Company(name="Kmart -- Store # 3461 -- Winter Haven")
    other = Company(name="KMART CORPORATION STORE #7362")
    db.add_all([clean, stray, other])
    db.flush()
    for i, (c, n) in enumerate([(store, 300), (clean, 50), (stray, 100), (other, 2000)]):
        db.add(Notice(notice_id=f"k{i}", state="FL", employer=c.name, company_id=c.id,
                      layoff_count=n))
    db.commit()
    return {"store": store, "clean": clean, "stray": stray, "other": other}


def test_requires_admin(db, api_client, kmart):
    body = {"target_id": kmart["clean"].id, "source_ids": [kmart["stray"].id]}
    assert api_client.post("/api/admin/companies/merge", json=body).status_code == 401
    _login_as(db, api_client, "paid")
    assert api_client.post("/api/admin/companies/merge", json=body).status_code == 403
    assert api_client.post(
        f"/api/admin/companies/{kmart['stray'].id}/unmerge"
    ).status_code == 403


def test_merge_relabels_and_rolls_up_top_employers(db, api_client, kmart):
    admin = _login_as(db, api_client, "admin")
    k = kmart
    resp = api_client.post("/api/admin/companies/merge", json={
        "target_id": k["clean"].id,
        "source_ids": [k["store"].id, k["stray"].id, k["other"].id],
        "note": "Kmart chain",
    })
    assert resp.status_code == 200, resp.text
    assert resp.json()["canonical_id"] == k["clean"].id

    db.expire_all()
    for key in ("store", "stray", "other"):
        assert db.get(Company, k[key].id).canonical_company_id == k["clean"].id
    assert db.get(Company, k["clean"].id).canonical_company_id is None
    ov = db.get(CompanyMergeOverride, k["store"].id)
    assert ov.decided_by == admin.id and ov.note == "Kmart chain"

    top = api_client.get("/api/stats/top-employers?limit=5").json()
    assert top[0]["employer"] == "Kmart Corporation"
    assert top[0]["layoff_total"] == 2450
    assert len(top) == 1

    members = api_client.get(f"/api/companies/{k['clean'].id}/members").json()
    assert [m["company_id"] for m in members] == [k["other"].id, k["store"].id, k["stray"].id]


def test_unmerge_restores_row(db, api_client, kmart):
    _login_as(db, api_client, "admin")
    k = kmart
    api_client.post("/api/admin/companies/merge", json={
        "target_id": k["clean"].id, "source_ids": [k["store"].id, k["stray"].id],
    })
    resp = api_client.post(f"/api/admin/companies/{k['stray'].id}/unmerge")
    assert resp.status_code == 200
    db.expire_all()
    assert db.get(Company, k["stray"].id).canonical_company_id is None
    assert db.get(Company, k["store"].id).canonical_company_id == k["clean"].id


def test_merge_validation(db, api_client, kmart):
    _login_as(db, api_client, "admin")
    k = kmart
    same = {"target_id": k["clean"].id, "source_ids": [k["clean"].id]}
    assert api_client.post("/api/admin/companies/merge", json=same).status_code == 400
    missing = {"target_id": k["clean"].id, "source_ids": [999999]}
    assert api_client.post("/api/admin/companies/merge", json=missing).status_code == 404
    empty = {"target_id": k["clean"].id, "source_ids": []}
    assert api_client.post("/api/admin/companies/merge", json=empty).status_code == 422
