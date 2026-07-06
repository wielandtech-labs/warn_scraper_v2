"""Rate limiting (per-minute window + daily quota) and /api/usage."""
from __future__ import annotations

from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient

from warn_v2 import api_keys, auth
from warn_v2.api import ratelimit
from warn_v2.db.models import User

PASSWORD = "correct-horse-battery"


class FakeClock:
    def __init__(self, start: float = 1_000.0) -> None:
        self.now = start

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


@pytest.fixture()
def clock(monkeypatch):
    """Fresh limiter with a controllable clock; module state never leaks.

    Also re-enables limiting (conftest's autouse fixture turns it off for the
    rest of the suite).
    """
    fake = FakeClock()
    monkeypatch.setattr(ratelimit, "ENABLED", True)
    monkeypatch.setattr(ratelimit, "_minute_limiter", ratelimit.SlidingWindowLimiter(clock=fake))
    return fake


@pytest.fixture()
def api_client(db, clock):
    from warn_v2.api import app
    from warn_v2.api.deps import get_db

    def _override():
        yield db

    app.dependency_overrides[get_db] = _override
    client = TestClient(app, base_url="https://testserver", raise_server_exceptions=True)
    yield client
    app.dependency_overrides.clear()


def _user(db, email: str, role: str = "free") -> User:
    u = User(
        email=email,
        password_hash=auth.hash_password(PASSWORD),
        role=role,
        email_verified_at=datetime.now(UTC),  # key creation requires verification
    )
    db.add(u)
    db.flush()
    return u


def _login(api_client, email: str):
    resp = api_client.post("/api/auth/login", json={"email": email, "password": PASSWORD})
    assert resp.status_code == 200


def _keyed(db, role: str = "free") -> dict[str, str]:
    user = _user(db, f"{role}-key@example.com", role=role)
    _key, raw = api_keys.create_key(db, user)
    db.commit()
    return {"X-API-Key": raw}


# ---------------------------------------------------------------------------
# SlidingWindowLimiter unit behavior
# ---------------------------------------------------------------------------

def test_sliding_window_slides_and_prunes():
    fake = FakeClock()
    limiter = ratelimit.SlidingWindowLimiter(clock=fake)

    assert limiter.hit("a", 2) == (True, 1, 0.0)
    assert limiter.hit("a", 2)[0] is True
    allowed, remaining, retry_after = limiter.hit("a", 2)
    assert allowed is False
    assert remaining == 0
    assert retry_after == pytest.approx(60.0)

    fake.advance(61)
    assert limiter.hit("a", 2)[0] is True  # window slid

    fake.advance(400)  # past prune interval; idle identities dropped
    limiter.hit("b", 2)
    assert "a" not in limiter._hits


# ---------------------------------------------------------------------------
# Per-minute burst limiting
# ---------------------------------------------------------------------------

def test_anonymous_burst_limit_and_retry_after(api_client, db, clock, monkeypatch):
    monkeypatch.setitem(ratelimit.PER_MINUTE, "anon", 3)
    for _ in range(3):
        assert api_client.get("/api/notices").status_code == 200

    resp = api_client.get("/api/notices")
    assert resp.status_code == 429
    assert int(resp.headers["Retry-After"]) >= 1

    clock.advance(61)
    assert api_client.get("/api/notices").status_code == 200


def test_paid_session_gets_higher_burst_than_anon(api_client, db, clock, monkeypatch):
    monkeypatch.setitem(ratelimit.PER_MINUTE, "anon", 1)
    monkeypatch.setitem(ratelimit.PER_MINUTE, "paid", 5)
    _user(db, "p@example.com", role="paid")
    _login(api_client, "p@example.com")

    for _ in range(5):
        assert api_client.get("/api/notices").status_code == 200
    assert api_client.get("/api/notices").status_code == 429


def test_admin_is_exempt(api_client, db, clock, monkeypatch):
    monkeypatch.setitem(ratelimit.PER_MINUTE, "anon", 1)
    _user(db, "a@example.com", role="admin")
    _login(api_client, "a@example.com")
    for _ in range(10):
        assert api_client.get("/api/notices").status_code == 200


def test_auth_keys_usage_routes_are_not_limited(api_client, db, clock, monkeypatch):
    monkeypatch.setitem(ratelimit.PER_MINUTE, "anon", 1)
    assert api_client.get("/api/notices").status_code == 200
    assert api_client.get("/api/notices").status_code == 429  # limiter active
    # ...but the excluded routers still answer.
    for _ in range(3):
        assert api_client.get("/api/auth/me").status_code == 401  # not 429
        assert api_client.get("/api/keys").status_code == 401
        assert api_client.get("/api/usage").status_code == 401


def test_disabled_flag_bypasses_everything(api_client, db, clock, monkeypatch):
    monkeypatch.setitem(ratelimit.PER_MINUTE, "anon", 1)
    monkeypatch.setattr(ratelimit, "ENABLED", False)
    for _ in range(5):
        assert api_client.get("/api/notices").status_code == 200


# ---------------------------------------------------------------------------
# Keyed requests: daily quota + headers
# ---------------------------------------------------------------------------

def test_keyed_request_headers_and_daily_quota(api_client, db, clock, monkeypatch):
    monkeypatch.setitem(ratelimit.PER_DAY, "free", 2)
    headers = _keyed(db, role="free")

    resp = api_client.get("/api/notices", headers=headers)
    assert resp.status_code == 200
    assert resp.headers["X-RateLimit-Limit"] == str(ratelimit.PER_MINUTE["free"])
    assert resp.headers["X-RateLimit-Daily-Limit"] == "2"
    assert resp.headers["X-RateLimit-Daily-Remaining"] == "1"

    assert api_client.get("/api/notices", headers=headers).status_code == 200
    over = api_client.get("/api/notices", headers=headers)
    assert over.status_code == 429
    assert "usage" in over.json()["detail"]


def test_anonymous_requests_carry_no_quota_headers(api_client, db, clock):
    resp = api_client.get("/api/notices")
    assert resp.status_code == 200
    assert "X-RateLimit-Limit" not in resp.headers


# ---------------------------------------------------------------------------
# /api/usage
# ---------------------------------------------------------------------------

def test_usage_endpoint(api_client, db, clock):
    headers = _keyed(db, role="free")
    for _ in range(3):
        assert api_client.get("/api/notices", headers=headers).status_code == 200

    body = api_client.get("/api/usage", headers=headers).json()
    assert body["tier"] == "free"
    assert body["per_minute_limit"] == ratelimit.PER_MINUTE["free"]
    assert body["daily_limit"] == ratelimit.PER_DAY["free"]
    assert body["today"] == 3
    assert len(body["keys"]) == 1
    assert body["keys"][0]["today"] == 3


def test_usage_shows_unused_keys_with_zero(api_client, db, clock):
    _user(db, "s@example.com", role="paid")
    _login(api_client, "s@example.com")
    assert api_client.post("/api/keys", json={"name": "fresh"}).status_code == 201

    body = api_client.get("/api/usage").json()
    assert body["today"] == 0
    assert body["keys"][0]["name"] == "fresh"
    assert body["keys"][0]["today"] == 0
