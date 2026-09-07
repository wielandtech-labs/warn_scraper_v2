"""Alert management: the /manage endpoints, their two auth paths, and signup guards."""
from __future__ import annotations

from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from warn_v2 import auth
from warn_v2.api.routes.subscriptions import MAX_PER_EMAIL
from warn_v2.db.models import Subscription, User

PASSWORD = "correct-horse-battery"
EMAIL = "me@example.com"


@pytest.fixture()
def sent(monkeypatch):
    """Capture outbound emails instead of sending. Returns the captured list."""
    box: list[dict] = []

    def _fake(to, subject, text_body, html_body=None, **kwargs):
        box.append({"to": to, "subject": subject, "text": text_body, "html": html_body})

    monkeypatch.setattr("warn_v2.api.routes.subscriptions.send_email", _fake)
    return box


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


def _subscribe(api_client, db, **filters) -> Subscription:
    """Sign up through the API and return the stored row."""
    body = {"email": filters.pop("email", EMAIL), **filters}
    resp = api_client.post("/api/subscriptions", json=body)
    assert resp.status_code == 200, resp.text
    db.commit()
    return db.scalars(
        select(Subscription).order_by(Subscription.id.desc())
    ).first()


def _user(db, email: str, verified: bool = True) -> User:
    u = User(
        email=email,
        password_hash=auth.hash_password(PASSWORD),
        role="free",
        email_verified_at=datetime.now(UTC) if verified else None,
    )
    db.add(u)
    db.flush()
    db.commit()
    return u


def _login(api_client, email: str) -> None:
    assert (
        api_client.post("/api/auth/login", json={"email": email, "password": PASSWORD}).status_code
        == 200
    )


# --- signup with the new filters -------------------------------------------

def test_signup_stores_every_filter(api_client, db, sent):
    sub = _subscribe(
        api_client,
        db,
        state="ca",
        subsector="311",
        employer_query="  Acme  ",
        min_layoffs=100,
        closure_category="Closure",
        frequency="weekly",
    )
    assert (sub.state, sub.subsector, sub.employer_query) == ("CA", "311", "Acme")
    assert (sub.min_layoffs, sub.closure_category, sub.frequency) == (100, "Closure", "weekly")
    # The subsector implies its sector, so the stored row and the digest's deep
    # link agree instead of carrying a half-set industry filter.
    assert sub.industry == "31-33"


@pytest.mark.parametrize(
    "payload",
    [
        {"state": "ZZ"},
        {"industry": "99"},
        {"subsector": "999"},
        {"closure_category": "Shutdown"},
        {"frequency": "hourly"},
        {"min_layoffs": 0},
        {"min_layoffs": 10_000_000},
    ],
)
def test_signup_rejects_bad_filters(api_client, db, sent, payload):
    resp = api_client.post("/api/subscriptions", json={"email": EMAIL, **payload})
    assert resp.status_code == 422
    assert sent == []


def test_duplicate_signup_does_not_stack(api_client, db, sent):
    _subscribe(api_client, db, state="CA")
    _subscribe(api_client, db, state="CA")
    assert db.scalar(select(func.count()).select_from(Subscription)) == 1
    # Same answer both times — a stranger can't learn the address is subscribed.
    assert len(sent) == 2  # a re-sent confirmation, not a second alert
    assert "confirm" in sent[1]["subject"].lower()


def test_duplicate_signup_after_confirm_sends_manage_link(api_client, db, sent):
    sub = _subscribe(api_client, db, state="CA")
    api_client.get(f"/api/subscriptions/confirm?token={sub.confirm_token}")
    db.commit()

    resp = api_client.post("/api/subscriptions", json={"email": EMAIL, "state": "CA"})
    assert resp.json()["status"] == "pending"
    assert db.scalar(select(func.count()).select_from(Subscription)) == 1
    assert sub.manage_token in sent[-1]["text"]


def test_signup_caps_alerts_per_email(api_client, db, sent):
    for i in range(MAX_PER_EMAIL):
        _subscribe(api_client, db, min_layoffs=i + 1)
    resp = api_client.post("/api/subscriptions", json={"email": EMAIL, "min_layoffs": 999})
    assert resp.status_code == 400
    assert db.scalar(select(func.count()).select_from(Subscription)) == MAX_PER_EMAIL


# --- manage link ------------------------------------------------------------

def test_manage_link_emails_the_token(api_client, db, sent):
    sub = _subscribe(api_client, db, state="CA")
    sent.clear()

    resp = api_client.post("/api/subscriptions/manage-link", json={"email": EMAIL.upper()})
    assert resp.status_code == 200
    assert len(sent) == 1
    assert sub.manage_token in sent[0]["text"]


def test_manage_link_for_unknown_email_is_silent(api_client, db, sent):
    db.commit()
    resp = api_client.post(
        "/api/subscriptions/manage-link", json={"email": "nobody@example.com"}
    )
    # Same 200 as a known address, and no mail: the response must not reveal
    # whether someone is subscribed.
    assert resp.status_code == 200
    assert sent == []


# --- managing with a token --------------------------------------------------

def test_token_lists_every_alert_for_that_address(api_client, db, sent):
    sub = _subscribe(api_client, db, state="CA")
    _subscribe(api_client, db, state="TX")
    _subscribe(api_client, db, email="other@example.com", state="NY")

    resp = api_client.get(f"/api/subscriptions/manage?token={sub.manage_token}")
    assert resp.status_code == 200
    rows = resp.json()
    assert {r["state"] for r in rows} == {"CA", "TX"}
    assert all(r["email"] == EMAIL for r in rows)
    assert {"confirm_token", "manage_token", "unsubscribe_token"}.isdisjoint(rows[0])


def test_unknown_token_is_404(api_client, db):
    db.commit()
    assert api_client.get("/api/subscriptions/manage?token=nope").status_code == 404


def test_anonymous_without_token_is_401(api_client, db):
    db.commit()
    assert api_client.get("/api/subscriptions/manage").status_code == 401


def test_update_replaces_the_filter_set(api_client, db, sent):
    sub = _subscribe(api_client, db, state="CA", employer_query="Acme")

    resp = api_client.put(
        f"/api/subscriptions/manage/{sub.id}?token={sub.manage_token}",
        json={"state": "TX", "min_layoffs": 250, "frequency": "weekly"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert (body["state"], body["min_layoffs"], body["frequency"]) == ("TX", 250, "weekly")
    assert body["employer_query"] is None  # omitted fields are cleared
    assert body["scope"] == "Texas, 250+ affected"
    db.refresh(sub)
    assert sub.state == "TX"


def test_update_rejects_bad_filters(api_client, db, sent):
    sub = _subscribe(api_client, db, state="CA")
    resp = api_client.put(
        f"/api/subscriptions/manage/{sub.id}?token={sub.manage_token}",
        json={"state": "ZZ"},
    )
    assert resp.status_code == 422
    db.refresh(sub)
    assert sub.state == "CA"


def test_delete_removes_one_alert(api_client, db, sent):
    sub = _subscribe(api_client, db, state="CA")
    other = _subscribe(api_client, db, state="TX")

    resp = api_client.delete(f"/api/subscriptions/manage/{other.id}?token={sub.manage_token}")
    assert resp.status_code == 200
    assert db.scalars(select(Subscription)).all() == [sub]


def test_token_cannot_touch_another_address(api_client, db, sent):
    mine = _subscribe(api_client, db, state="CA")
    theirs = _subscribe(api_client, db, email="other@example.com", state="NY")

    url = f"/api/subscriptions/manage/{theirs.id}?token={mine.manage_token}"
    assert api_client.put(url, json={"state": "TX"}).status_code == 404
    assert api_client.delete(url).status_code == 404
    db.refresh(theirs)
    assert theirs.state == "NY"


def test_resend_confirmation_only_while_pending(api_client, db, sent):
    sub = _subscribe(api_client, db, state="CA")
    sent.clear()

    url = f"/api/subscriptions/manage/{sub.id}/resend-confirmation?token={sub.manage_token}"
    assert api_client.post(url).json()["status"] == "sent"
    assert sub.confirm_token in sent[0]["text"]

    api_client.get(f"/api/subscriptions/confirm?token={sub.confirm_token}")
    db.commit()
    assert api_client.post(url).json()["status"] == "confirmed"
    assert len(sent) == 1  # nothing re-sent for a confirmed alert


# --- managing with a session ------------------------------------------------

def test_verified_user_sees_and_claims_their_alerts(api_client, db, sent):
    sub = _subscribe(api_client, db, state="CA")  # created anonymously
    assert sub.user_id is None
    user = _user(db, EMAIL)
    _login(api_client, EMAIL)

    rows = api_client.get("/api/subscriptions/manage").json()
    assert [r["id"] for r in rows] == [sub.id]
    db.refresh(sub)
    assert sub.user_id == user.id  # adopted, so /account keeps showing it


def test_unverified_user_cannot_list(api_client, db, sent):
    _subscribe(api_client, db, state="CA")
    _user(db, EMAIL, verified=False)
    _login(api_client, EMAIL)

    # An unverified account proves nothing about owning the address.
    assert api_client.get("/api/subscriptions/manage").status_code == 401


def test_session_user_cannot_touch_another_address(api_client, db, sent):
    theirs = _subscribe(api_client, db, email="other@example.com", state="NY")
    _user(db, EMAIL)
    _login(api_client, EMAIL)

    assert api_client.get("/api/subscriptions/manage").json() == []
    assert api_client.delete(f"/api/subscriptions/manage/{theirs.id}").status_code == 404


def test_signup_while_logged_in_links_the_account(api_client, db, sent):
    user = _user(db, EMAIL)
    _login(api_client, EMAIL)
    sub = _subscribe(api_client, db, state="CA")
    assert sub.user_id == user.id


def test_signup_for_another_address_does_not_link(api_client, db, sent):
    _user(db, EMAIL)
    _login(api_client, EMAIL)
    sub = _subscribe(api_client, db, email="someone-else@example.com", state="CA")
    assert sub.user_id is None
