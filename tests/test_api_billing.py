"""Stripe billing: checkout/portal routes + webhook role transitions.

Webhook tests compute real Stripe-Signature headers (hmac-sha256 over
"<ts>.<payload>") so stripe.Webhook.construct_event's verification path is
exercised for real — only the outbound Stripe API calls are monkeypatched.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import time
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient

from warn_v2 import auth, billing
from warn_v2.db.models import User

PASSWORD = "correct-horse-battery"
WEBHOOK_SECRET = "whsec_test_secret"


@pytest.fixture()
def api_client(db, monkeypatch):
    from warn_v2.api import app
    from warn_v2.api.deps import get_db

    monkeypatch.setenv("STRIPE_WEBHOOK_SECRET", WEBHOOK_SECRET)

    def _override():
        yield db

    app.dependency_overrides[get_db] = _override
    client = TestClient(app, base_url="https://testserver", raise_server_exceptions=True)
    yield client
    app.dependency_overrides.clear()


def _user(db, email: str, role: str = "free", customer: str | None = None,
          verified: bool = True) -> User:
    u = User(
        email=email,
        password_hash=auth.hash_password(PASSWORD),
        role=role,
        stripe_customer_id=customer,
        email_verified_at=datetime.now(UTC) if verified else None,
    )
    db.add(u)
    db.flush()
    return u


def _login(api_client, email: str):
    assert api_client.post(
        "/api/auth/login", json={"email": email, "password": PASSWORD}
    ).status_code == 200


def _signed_post(api_client, event: dict, secret: str = WEBHOOK_SECRET):
    payload = json.dumps(event).encode()
    ts = int(time.time())
    sig = hmac.new(secret.encode(), b"%d." % ts + payload, hashlib.sha256).hexdigest()
    return api_client.post(
        "/api/billing/webhook",
        content=payload,
        headers={"stripe-signature": f"t={ts},v1={sig}",
                 "content-type": "application/json"},
    )


def _event(type_: str, obj: dict, event_id: str = "evt_test_1") -> dict:
    return {"id": event_id, "object": "event", "type": type_, "data": {"object": obj}}


# ---------------------------------------------------------------------------
# Webhook
# ---------------------------------------------------------------------------

def test_checkout_completed_promotes_and_stores_customer(api_client, db):
    user = _user(db, "a@example.com")
    db.commit()

    resp = _signed_post(api_client, _event(
        "checkout.session.completed",
        {"client_reference_id": str(user.id), "customer": "cus_123"},
    ))
    assert resp.status_code == 200
    db.expire_all()
    assert user.role == "paid"
    assert user.stripe_customer_id == "cus_123"

    # Replays are idempotent.
    assert _signed_post(api_client, _event(
        "checkout.session.completed",
        {"client_reference_id": str(user.id), "customer": "cus_123"},
    )).status_code == 200
    db.expire_all()
    assert user.role == "paid"


def test_subscription_updated_tracks_status(api_client, db):
    user = _user(db, "a@example.com", role="paid", customer="cus_123")
    db.commit()

    _signed_post(api_client, _event(
        "customer.subscription.updated", {"customer": "cus_123", "status": "past_due"}
    ))
    db.expire_all()
    assert user.role == "free"

    _signed_post(api_client, _event(
        "customer.subscription.updated", {"customer": "cus_123", "status": "active"}
    ))
    db.expire_all()
    assert user.role == "paid"


def test_subscription_deleted_demotes_paid(api_client, db):
    user = _user(db, "a@example.com", role="paid", customer="cus_123")
    db.commit()
    _signed_post(api_client, _event(
        "customer.subscription.deleted", {"customer": "cus_123"}
    ))
    db.expire_all()
    assert user.role == "free"


@pytest.mark.parametrize("role", ["admin", "enterprise"])
def test_webhook_never_demotes_manual_roles(api_client, db, role):
    user = _user(db, "vip@example.com", role=role, customer="cus_vip")
    db.commit()
    for event in (
        _event("customer.subscription.deleted", {"customer": "cus_vip"}),
        _event("customer.subscription.updated", {"customer": "cus_vip", "status": "canceled"}),
    ):
        assert _signed_post(api_client, event).status_code == 200
    db.expire_all()
    assert user.role == role


def test_webhook_unknown_customer_and_type_are_ok(api_client, db):
    assert _signed_post(api_client, _event(
        "customer.subscription.deleted", {"customer": "cus_ghost"}
    )).status_code == 200
    assert _signed_post(api_client, _event("invoice.paid", {})).status_code == 200


def test_webhook_bad_signature_rejected(api_client, db):
    user = _user(db, "a@example.com")
    db.commit()
    event = _event("checkout.session.completed",
                   {"client_reference_id": str(user.id), "customer": "cus_123"})
    resp = _signed_post(api_client, event, secret="whsec_wrong")
    assert resp.status_code == 400
    db.expire_all()
    assert user.role == "free"


def test_webhook_unconfigured_is_503(api_client, db, monkeypatch):
    monkeypatch.delenv("STRIPE_WEBHOOK_SECRET")
    resp = api_client.post("/api/billing/webhook", content=b"{}",
                           headers={"stripe-signature": "t=1,v1=abc"})
    assert resp.status_code == 503


# ---------------------------------------------------------------------------
# Checkout / portal routes
# ---------------------------------------------------------------------------

def test_checkout_route(api_client, db, monkeypatch):
    assert api_client.post("/api/billing/checkout").status_code == 401

    _user(db, "new@example.com", verified=False)
    _login(api_client, "new@example.com")
    assert api_client.post("/api/billing/checkout").status_code == 403

    _user(db, "free@example.com")
    _login(api_client, "free@example.com")
    monkeypatch.setattr(
        billing, "create_checkout_session",
        lambda user, success_url, cancel_url: "https://checkout.stripe.test/s/abc",
    )
    resp = api_client.post("/api/billing/checkout")
    assert resp.status_code == 200
    assert resp.json() == {"url": "https://checkout.stripe.test/s/abc"}

    _user(db, "paid@example.com", role="paid")
    _login(api_client, "paid@example.com")
    assert api_client.post("/api/billing/checkout").status_code == 400


def test_checkout_unconfigured_is_503(api_client, db):
    _user(db, "free@example.com")
    _login(api_client, "free@example.com")
    # No STRIPE_SECRET_KEY / STRIPE_PRICE_ID in the test env.
    assert api_client.post("/api/billing/checkout").status_code == 503


def test_portal_route(api_client, db, monkeypatch):
    _user(db, "nocust@example.com")
    _login(api_client, "nocust@example.com")
    assert api_client.post("/api/billing/portal").status_code == 400

    _user(db, "paid@example.com", role="paid", customer="cus_123")
    _login(api_client, "paid@example.com")
    monkeypatch.setattr(
        billing, "create_portal_session",
        lambda customer_id, return_url: f"https://portal.stripe.test/{customer_id}",
    )
    resp = api_client.post("/api/billing/portal")
    assert resp.status_code == 200
    assert resp.json()["url"].endswith("cus_123")
