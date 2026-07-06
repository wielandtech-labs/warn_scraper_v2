"""Self-signup, email verification, and password reset (/api/auth/*)."""
from __future__ import annotations

import re

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from warn_v2 import auth
from warn_v2.api.routes import auth as auth_routes
from warn_v2.db.models import AuthToken, User, UserSession

PASSWORD = "correct-horse-battery"


@pytest.fixture()
def sent(monkeypatch):
    outbox: list[dict] = []

    def _fake(to, subject, text_body, html_body=None, **kwargs):
        outbox.append({"to": to, "subject": subject, "text": text_body})

    monkeypatch.setattr("warn_v2.api.routes.auth.send_email", _fake)
    return outbox


@pytest.fixture()
def api_client(db, monkeypatch, sent):
    from warn_v2.api import app
    from warn_v2.api.deps import get_db

    monkeypatch.setenv("SIGNUP_ENABLED", "1")
    # Fresh per-test limiter: the signup limiter is module state keyed on the
    # shared TestClient IP.
    monkeypatch.setattr(
        auth_routes, "_email_limiter", auth_routes.SlidingWindowLimiter(window=3600)
    )

    def _override():
        yield db

    app.dependency_overrides[get_db] = _override
    client = TestClient(app, base_url="https://testserver", raise_server_exceptions=True)
    yield client
    app.dependency_overrides.clear()


def _extract_token(text: str) -> str:
    m = re.search(r"token=([A-Za-z0-9_-]+)", text)
    assert m, text
    return m.group(1)


# ---------------------------------------------------------------------------
# Signup + verification
# ---------------------------------------------------------------------------

def test_signup_flow_end_to_end(api_client, db, sent):
    resp = api_client.post(
        "/api/auth/signup", json={"email": "New@Example.com ", "password": PASSWORD}
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "pending"

    user = db.scalar(select(User).where(User.email == "new@example.com"))
    assert user is not None
    assert user.role == "free"
    assert user.email_verified_at is None

    # Unverified: login works but key creation is blocked.
    assert api_client.post(
        "/api/auth/login", json={"email": "new@example.com", "password": PASSWORD}
    ).status_code == 200
    assert api_client.post("/api/keys", json={}).status_code == 403

    # Click the emailed link.
    token = _extract_token(sent[0]["text"])
    verify = api_client.get(f"/api/auth/verify?token={token}")
    assert verify.status_code == 200
    assert "verified" in verify.text.lower()
    db.expire_all()
    assert user.email_verified_at is not None
    assert api_client.post("/api/keys", json={}).status_code == 201

    # Token is single-use.
    assert "not valid" in api_client.get(f"/api/auth/verify?token={token}").text.lower()


def test_signup_existing_email_same_response_no_email(api_client, db, sent):
    api_client.post("/api/auth/signup", json={"email": "a@example.com", "password": PASSWORD})
    assert len(sent) == 1

    dup = api_client.post(
        "/api/auth/signup", json={"email": "a@example.com", "password": "different-password-1"}
    )
    assert dup.status_code == 200
    assert dup.json() == {
        "status": "pending",
        "message": auth_routes._PENDING_MSG,
    }  # byte-identical to the fresh-signup response
    assert len(sent) == 1  # no second email
    assert db.scalar(select(User).where(User.email == "a@example.com")) is not None


def test_signup_validation(api_client, db, sent):
    assert api_client.post(
        "/api/auth/signup", json={"email": "not-an-email", "password": PASSWORD}
    ).status_code == 422
    assert api_client.post(
        "/api/auth/signup", json={"email": "a@example.com", "password": "short"}
    ).status_code == 422
    assert sent == []


def test_signup_disabled_by_default(api_client, db, monkeypatch):
    monkeypatch.delenv("SIGNUP_ENABLED")
    assert api_client.post(
        "/api/auth/signup", json={"email": "a@example.com", "password": PASSWORD}
    ).status_code == 503
    assert api_client.post(
        "/api/auth/forgot", json={"email": "a@example.com"}
    ).status_code == 503


def test_signup_ip_rate_limit(api_client, db, sent):
    for i in range(auth_routes._EMAIL_ENDPOINT_LIMIT):
        assert api_client.post(
            "/api/auth/signup", json={"email": f"u{i}@example.com", "password": PASSWORD}
        ).status_code == 200
    resp = api_client.post(
        "/api/auth/signup", json={"email": "over@example.com", "password": PASSWORD}
    )
    assert resp.status_code == 429
    assert "Retry-After" in resp.headers


# ---------------------------------------------------------------------------
# Password reset
# ---------------------------------------------------------------------------

def _signed_up_user(api_client, db, sent) -> User:
    api_client.post("/api/auth/signup", json={"email": "a@example.com", "password": PASSWORD})
    token = _extract_token(sent[-1]["text"])
    api_client.get(f"/api/auth/verify?token={token}")
    return db.scalar(select(User).where(User.email == "a@example.com"))


def test_password_reset_flow(api_client, db, sent):
    user = _signed_up_user(api_client, db, sent)
    api_client.post("/api/auth/login", json={"email": user.email, "password": PASSWORD})
    assert db.scalar(select(UserSession)) is not None

    assert api_client.post("/api/auth/forgot", json={"email": user.email}).status_code == 200
    token = _extract_token(sent[-1]["text"])

    # The emailed link renders a self-contained form.
    page = api_client.get(f"/api/auth/reset-page?token={token}")
    assert page.status_code == 200
    assert token in page.text

    new_password = "brand-new-password-42"
    assert api_client.post(
        "/api/auth/reset", json={"token": token, "password": new_password}
    ).status_code == 200

    # All sessions revoked; old password dead; new one works.
    assert db.scalar(select(UserSession)) is None
    assert api_client.post(
        "/api/auth/login", json={"email": user.email, "password": PASSWORD}
    ).status_code == 401
    assert api_client.post(
        "/api/auth/login", json={"email": user.email, "password": new_password}
    ).status_code == 200

    # Token is single-use.
    assert api_client.post(
        "/api/auth/reset", json={"token": token, "password": new_password}
    ).status_code == 400


def test_forgot_unknown_email_same_response_no_email(api_client, db, sent):
    resp = api_client.post("/api/auth/forgot", json={"email": "ghost@example.com"})
    assert resp.status_code == 200
    assert resp.json()["message"] == auth_routes._RESET_MSG
    assert sent == []


def test_expired_token_rejected_and_consumed(api_client, db, sent):
    _signed_up_user(api_client, db, sent)
    api_client.post("/api/auth/forgot", json={"email": "a@example.com"})
    token = _extract_token(sent[-1]["text"])

    row = db.scalar(select(AuthToken).where(AuthToken.purpose == "reset"))
    row.expires_at = row.expires_at - auth.RESET_TTL * 2
    db.commit()

    assert api_client.post(
        "/api/auth/reset", json={"token": token, "password": "whatever-password-9"}
    ).status_code == 400
    assert db.scalar(select(AuthToken).where(AuthToken.purpose == "reset")) is None
