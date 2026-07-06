"""API-key auth: /api/keys management + header resolution in get_current_user."""
from __future__ import annotations

from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from warn_v2 import api_keys, auth
from warn_v2.db.models import ApiKey, Company, User

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


def _user(db, email: str, role: str = "free", verified: bool = True) -> User:
    u = User(
        email=email,
        password_hash=auth.hash_password(PASSWORD),
        role=role,
        email_verified_at=datetime.now(UTC) if verified else None,
    )
    db.add(u)
    db.flush()
    return u


def _login(api_client, email: str):
    resp = api_client.post("/api/auth/login", json={"email": email, "password": PASSWORD})
    assert resp.status_code == 200


def _fresh_client(db):
    """A client with no cookie jar — key-only requests."""
    from warn_v2.api import app

    return TestClient(app, base_url="https://testserver", raise_server_exceptions=True)


# ---------------------------------------------------------------------------
# Key management endpoints
# ---------------------------------------------------------------------------

def test_key_management_requires_session(api_client, db):
    assert api_client.post("/api/keys", json={}).status_code == 401
    assert api_client.get("/api/keys").status_code == 401
    assert api_client.delete("/api/keys/1").status_code == 401


def test_create_key_returns_raw_once_and_lists_prefix_only(api_client, db):
    _user(db, "a@example.com")
    _login(api_client, "a@example.com")

    resp = api_client.post("/api/keys", json={"name": "ci"})
    assert resp.status_code == 201
    body = resp.json()
    assert body["key"].startswith(api_keys.KEY_PREFIX)
    assert body["prefix"] == body["key"][: api_keys.PREFIX_DISPLAY_LEN]
    assert body["name"] == "ci"

    listing = api_client.get("/api/keys").json()
    assert len(listing) == 1
    assert listing[0]["prefix"] == body["prefix"]
    assert "key" not in listing[0]  # raw key never shown again


def test_unverified_user_cannot_create_keys(api_client, db):
    _user(db, "new@example.com", verified=False)
    _login(api_client, "new@example.com")
    resp = api_client.post("/api/keys", json={})
    assert resp.status_code == 403
    assert "Verify" in resp.json()["detail"]
    # Listing/revoking existing keys is still allowed — only minting is gated.
    assert api_client.get("/api/keys").status_code == 200


def test_active_key_cap(api_client, db):
    _user(db, "a@example.com")
    _login(api_client, "a@example.com")
    for _ in range(api_keys.MAX_ACTIVE_KEYS):
        assert api_client.post("/api/keys", json={}).status_code == 201
    assert api_client.post("/api/keys", json={}).status_code == 400

    # Revoking one frees a slot.
    key_id = api_client.get("/api/keys").json()[0]["id"]
    assert api_client.delete(f"/api/keys/{key_id}").status_code == 200
    assert api_client.post("/api/keys", json={}).status_code == 201


def test_revoke_other_users_key_is_404(api_client, db):
    owner = _user(db, "owner@example.com")
    key, _raw = api_keys.create_key(db, owner)
    db.commit()

    _user(db, "other@example.com")
    _login(api_client, "other@example.com")
    assert api_client.delete(f"/api/keys/{key.id}").status_code == 404
    assert db.get(ApiKey, key.id).revoked_at is None


# ---------------------------------------------------------------------------
# Header resolution
# ---------------------------------------------------------------------------

def test_key_authenticates_via_x_api_key_and_bearer(api_client, db):
    user = _user(db, "a@example.com", role="paid")
    _key, raw = api_keys.create_key(db, user)
    db.commit()

    client = _fresh_client(db)
    assert client.get("/api/auth/me").status_code == 401  # no cookie, no key

    me = client.get("/api/auth/me", headers={"X-API-Key": raw})
    assert me.status_code == 200
    assert me.json() == {"email": "a@example.com", "role": "paid"}

    me = client.get("/api/auth/me", headers={"Authorization": f"Bearer {raw}"})
    assert me.status_code == 200


def test_key_gets_role_gated_fields(api_client, db):
    c = Company(name="Acme Inc", duns="123456789", parent_company_name="Acme Holdings")
    db.add(c)
    db.flush()
    paid = _user(db, "p@example.com", role="paid")
    ent = _user(db, "e@example.com", role="enterprise")
    _key, paid_raw = api_keys.create_key(db, paid)
    _key, ent_raw = api_keys.create_key(db, ent)
    db.commit()

    client = _fresh_client(db)
    anon = client.get(f"/api/companies/{c.id}").json()
    assert "parent_company_name" not in anon

    as_paid = client.get(f"/api/companies/{c.id}", headers={"X-API-Key": paid_raw}).json()
    assert as_paid["parent_company_name"] == "Acme Holdings"
    assert "duns" not in as_paid

    as_ent = client.get(f"/api/companies/{c.id}", headers={"X-API-Key": ent_raw}).json()
    assert as_ent["duns"] == "123456789"


def test_revoked_and_garbage_keys_are_anonymous(api_client, db):
    user = _user(db, "a@example.com")
    key, raw = api_keys.create_key(db, user)
    db.commit()

    client = _fresh_client(db)
    assert client.get("/api/auth/me", headers={"X-API-Key": raw}).status_code == 200

    api_keys.revoke_key(db, key)
    db.commit()
    assert client.get("/api/auth/me", headers={"X-API-Key": raw}).status_code == 401
    assert client.get(
        "/api/auth/me", headers={"X-API-Key": "warn_not-a-real-key"}
    ).status_code == 401
    assert client.get(
        "/api/auth/me", headers={"Authorization": "Bearer something-else"}
    ).status_code == 401


def test_key_cannot_manage_keys(api_client, db):
    user = _user(db, "a@example.com")
    key, raw = api_keys.create_key(db, user)
    db.commit()

    client = _fresh_client(db)
    headers = {"X-API-Key": raw}
    assert client.post("/api/keys", json={}, headers=headers).status_code == 401
    assert client.get("/api/keys", headers=headers).status_code == 401
    assert client.delete(f"/api/keys/{key.id}", headers=headers).status_code == 401


def test_key_use_bumps_last_used_at(api_client, db):
    user = _user(db, "a@example.com")
    key, raw = api_keys.create_key(db, user)
    db.commit()
    assert key.last_used_at is None

    client = _fresh_client(db)
    assert client.get("/api/auth/me", headers={"X-API-Key": raw}).status_code == 200
    db.expire_all()
    assert db.scalar(select(ApiKey.last_used_at).where(ApiKey.id == key.id)) is not None


def test_cookie_wins_over_key(api_client, db):
    """A logged-in browser session isn't reassigned by a stray key header."""
    _user(db, "cookie@example.com", role="admin")
    key_user = _user(db, "key@example.com", role="free")
    _key, raw = api_keys.create_key(db, key_user)
    db.commit()

    _login(api_client, "cookie@example.com")
    me = api_client.get("/api/auth/me", headers={"X-API-Key": raw})
    assert me.json()["email"] == "cookie@example.com"
