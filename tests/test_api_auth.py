"""Auth endpoints + role-gated D&B field visibility.

The client uses base_url="https://testserver" so httpx's cookie jar sends the
Secure session cookie back; everything else mirrors tests/test_api.py.
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import select

from warn_v2 import auth
from warn_v2.api.deps import require_admin
from warn_v2.db.models import Company, Notice, User, UserSession

PASSWORD = "correct-horse-battery"

# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------

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


def _user(db, email: str, role: str = "free") -> User:
    u = User(email=email, password_hash=auth.hash_password(PASSWORD), role=role)
    db.add(u)
    db.flush()
    return u


def _login(api_client, email: str):
    resp = api_client.post("/api/auth/login", json={"email": email, "password": PASSWORD})
    assert resp.status_code == 200
    return resp


def _enriched_company(db) -> Company:
    c = Company(
        name="Acme Inc",
        duns="123456789",
        parent_duns="987654321",
        parent_company_name="Acme Holdings",
        global_ultimate_name="Acme Global",
        hq_address="1 Acme Way, Coyote, AZ",
        employee_count=500,
        website="https://acme.example",
    )
    db.add(c)
    db.flush()
    return c


def _notice(db, company: Company) -> Notice:
    n = Notice(
        notice_id="test_CA_acme",
        state="CA",
        employer=company.name,
        company_id=company.id,
    )
    db.add(n)
    db.flush()
    return n


# Served to paid sessions and above.
ENRICHED_FIELDS = (
    "parent_company_name",
    "global_ultimate_name",
    "hq_address",
    "employee_count",
)
# Raw DUNS identifiers: enterprise/admin only.
DUNS_FIELDS = ("duns", "parent_duns")
DNB_FIELDS = DUNS_FIELDS + ENRICHED_FIELDS


# ---------------------------------------------------------------------------
# Login / logout / me
# ---------------------------------------------------------------------------

def test_login_wrong_password_and_unknown_email_identical(api_client, db):
    _user(db, "a@example.com")
    wrong = api_client.post(
        "/api/auth/login", json={"email": "a@example.com", "password": "nope-nope-nope"}
    )
    unknown = api_client.post(
        "/api/auth/login", json={"email": "ghost@example.com", "password": PASSWORD}
    )
    assert wrong.status_code == unknown.status_code == 401
    assert wrong.json() == unknown.json()


def test_login_sets_secure_httponly_cookie(api_client, db):
    _user(db, "a@example.com", role="paid")
    resp = _login(api_client, "a@example.com")
    assert resp.json() == {"email": "a@example.com", "role": "paid"}
    cookie = resp.headers["set-cookie"].lower()
    assert auth.COOKIE_NAME in cookie
    assert "httponly" in cookie
    assert "secure" in cookie
    assert "samesite=lax" in cookie


def test_login_normalizes_email_case(api_client, db):
    _user(db, "a@example.com")
    resp = api_client.post(
        "/api/auth/login", json={"email": "  A@Example.COM ", "password": PASSWORD}
    )
    assert resp.status_code == 200


def test_me_and_logout_flow(api_client, db):
    _user(db, "a@example.com", role="admin")
    assert api_client.get("/api/auth/me").status_code == 401

    _login(api_client, "a@example.com")
    me = api_client.get("/api/auth/me")
    assert me.status_code == 200
    assert me.json() == {"email": "a@example.com", "role": "admin"}
    assert db.scalar(select(UserSession)) is not None

    api_client.post("/api/auth/logout")
    assert api_client.get("/api/auth/me").status_code == 401
    assert db.scalar(select(UserSession)) is None  # row deleted, not just cookie


def test_expired_session_rejected(api_client, db):
    _user(db, "a@example.com")
    _login(api_client, "a@example.com")
    sess = db.scalar(select(UserSession))
    sess.expires_at = datetime.now(UTC) - timedelta(minutes=1)
    db.flush()
    assert api_client.get("/api/auth/me").status_code == 401


def test_garbage_cookie_is_anonymous(api_client, db):
    api_client.cookies.set(auth.COOKIE_NAME, "not-a-real-token")
    assert api_client.get("/api/auth/me").status_code == 401


# ---------------------------------------------------------------------------
# Role-gated D&B fields
# ---------------------------------------------------------------------------

def _company_bodies(api_client, company_id: int, notice_id: str) -> list[dict]:
    """The company payload from each of the 5 reshaped endpoints."""
    return [
        api_client.get(f"/api/companies/{company_id}").json(),
        api_client.get("/api/companies").json()["items"][0],
        api_client.get(f"/api/companies/{company_id}/notices").json()["items"][0]["company"],
        api_client.get("/api/notices").json()["items"][0]["company"],
        api_client.get(f"/api/notices/{notice_id}").json()["company"],
    ]


def test_anonymous_and_free_get_no_dnb_fields(api_client, db):
    c = _enriched_company(db)
    n = _notice(db, c)

    for body in _company_bodies(api_client, c.id, n.notice_id):  # anonymous
        for field in DNB_FIELDS:
            assert field not in body  # key absent, not null — exact public shape

    _user(db, "free@example.com", role="free")
    _login(api_client, "free@example.com")
    for body in _company_bodies(api_client, c.id, n.notice_id):
        for field in DNB_FIELDS:
            assert field not in body
        assert body["name"] == "Acme Inc"
        assert body["website"] == "https://acme.example"


def test_paid_gets_enriched_fields_but_no_duns(api_client, db):
    c = _enriched_company(db)
    n = _notice(db, c)
    _user(db, "paid@example.com", role="paid")
    _login(api_client, "paid@example.com")

    for body in _company_bodies(api_client, c.id, n.notice_id):
        assert body["parent_company_name"] == "Acme Holdings"
        assert body["global_ultimate_name"] == "Acme Global"
        assert body["hq_address"] == "1 Acme Way, Coyote, AZ"
        assert body["employee_count"] == 500
        for field in DUNS_FIELDS:
            assert field not in body  # key absent, not null


@pytest.mark.parametrize("role", ["enterprise", "admin"])
def test_enterprise_and_admin_get_all_dnb_fields(api_client, db, role):
    c = _enriched_company(db)
    n = _notice(db, c)
    _user(db, f"{role}@example.com", role=role)
    _login(api_client, f"{role}@example.com")

    for body in _company_bodies(api_client, c.id, n.notice_id):
        assert body["duns"] == "123456789"
        assert body["parent_duns"] == "987654321"
        assert body["parent_company_name"] == "Acme Holdings"
        assert body["global_ultimate_name"] == "Acme Global"
        assert body["hq_address"] == "1 Acme Way, Coyote, AZ"
        assert body["employee_count"] == 500


def test_logout_drops_back_to_public_shape(api_client, db):
    c = _enriched_company(db)
    _notice(db, c)
    _user(db, "e@example.com", role="enterprise")
    _login(api_client, "e@example.com")
    assert "duns" in api_client.get(f"/api/companies/{c.id}").json()

    api_client.post("/api/auth/logout")
    assert "duns" not in api_client.get(f"/api/companies/{c.id}").json()


def _assert_no_dnb_anywhere(payload) -> None:
    """Recursively assert no D&B field key appears anywhere in a JSON payload."""
    if isinstance(payload, dict):
        for field in DNB_FIELDS:
            assert field not in payload
        for v in payload.values():
            _assert_no_dnb_anywhere(v)
    elif isinstance(payload, list):
        for v in payload:
            _assert_no_dnb_anywhere(v)


@pytest.mark.parametrize("role", ["paid", "enterprise"])
def test_paid_session_gets_no_dnb_on_non_reshaped_endpoints(api_client, db, role):
    """Policy pin: only the 5 reshaped endpoints may serve D&B fields.

    family/stats/map-pins keep static response models and must stay
    public-shaped even for paid/enterprise sessions — this test fails if a
    future change widens the surface without deliberately updating the policy.
    """
    c = _enriched_company(db)
    _notice(db, c)
    _user(db, "p@example.com", role=role)
    _login(api_client, "p@example.com")

    for path in (
        f"/api/companies/{c.id}/family",
        "/api/stats/top-employers",
        "/api/stats/by-parent-group",
        "/api/stats/by-state",
        "/api/map-pins",
    ):
        resp = api_client.get(path)
        assert resp.status_code == 200, path
        _assert_no_dnb_anywhere(resp.json())


# ---------------------------------------------------------------------------
# require_admin (no admin-only routes yet; unit-test the dependency)
# ---------------------------------------------------------------------------

def test_require_admin(db):
    with pytest.raises(HTTPException) as exc:
        require_admin(None)
    assert exc.value.status_code == 401

    paid = _user(db, "p@example.com", role="paid")
    with pytest.raises(HTTPException) as exc:
        require_admin(paid)
    assert exc.value.status_code == 403

    admin = _user(db, "a@example.com", role="admin")
    assert require_admin(admin) is admin
