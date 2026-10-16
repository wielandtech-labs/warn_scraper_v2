"""Admin logo-search endpoints: queue, probe, and the validated override PUT."""
from __future__ import annotations

import struct
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from warn_v2 import auth
from warn_v2.api import logo_fetch
from warn_v2.db.models import Company, Notice, User

PASSWORD = "correct-horse-battery"


def _png(width: int) -> bytes:
    ihdr = b"\x00\x00\x00\x0dIHDR" + struct.pack(">II", width, width)
    return b"\x89PNG\r\n\x1a\n" + ihdr + b"\x00" * 8


@pytest.fixture(autouse=True)
def _fresh_cache():
    logo_fetch.cache.clear()
    yield
    logo_fetch.cache.clear()


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


def _login_as(db, api_client, role: str) -> None:
    u = User(email=f"{role}@example.com", password_hash=auth.hash_password(PASSWORD), role=role)
    db.add(u)
    db.commit()
    resp = api_client.post("/api/auth/login", json={"email": u.email, "password": PASSWORD})
    assert resp.status_code == 200


@pytest.fixture()
def admin(db, api_client):
    _login_as(db, api_client, "admin")


@pytest.fixture()
def images(monkeypatch):
    """URL -> image bytes for fetch_image; anything else is unfetchable."""
    table: dict[str, bytes] = {}

    def fake_fetch(url):
        data = table.get(url)
        return (data, logo_fetch.sniff_type(data)) if data else None

    monkeypatch.setattr(logo_fetch, "fetch_image", fake_fetch)
    return table


def _company(db, name, layoffs, *, state="CA", **kw) -> Company:
    c = Company(name=name, **kw)
    db.add(c)
    db.flush()
    db.add(Notice(notice_id=f"n-{name}", state=state, employer=name, company_id=c.id,
                  layoff_count=layoffs, notice_date=datetime(2008, 11, 3).date()))
    db.commit()
    return c


def test_requires_admin(db, api_client):
    c = _company(db, "Kmart", 100)
    for method, path in (("get", "/api/admin/logo-queue"),
                         ("get", f"/api/admin/companies/{c.id}/logo-probe"),
                         ("put", f"/api/admin/companies/{c.id}/logo")):
        assert api_client.request(method, path, json={}).status_code == 401
    _login_as(db, api_client, "paid")
    assert api_client.get("/api/admin/logo-queue").status_code == 403


def test_queue_order_and_exclusions(db, api_client, admin):
    big = _company(db, "Circuit City", 5000, website=None)
    small = _company(db, "Corner Shop", 10, state="NY")
    _company(db, "Has Override", 9000, logo_url="https://x.example/a.png")
    _company(db, "Checked Recently", 8000, logo_checked_at=datetime.now(UTC))
    stale = _company(db, "Checked Long Ago", 7000,
                     logo_checked_at=datetime.now(UTC) - timedelta(days=200))
    dupe = _company(db, "Circuit City Stores", 300, state="VA",
                    canonical_company_id=big.id)

    items = api_client.get("/api/admin/logo-queue").json()
    assert [i["id"] for i in items] == [stale.id, big.id, small.id]
    cc = items[1]
    # The merged dupe's notices roll up to the canonical; the dupe itself is not queued.
    assert cc["layoff_total"] == 5300
    assert cc["states"] == ["CA", "VA"]
    assert cc["last_notice_year"] == 2008
    assert dupe.id not in [i["id"] for i in items]
    assert len(api_client.get("/api/admin/logo-queue?limit=1").json()) == 1


def test_put_validates_and_stamps(db, api_client, admin, images):
    c = _company(db, "Kmart", 100)
    images["https://up.example/tiny.png"] = _png(16)
    images["https://up.example/kmart.png"] = _png(256)
    path = f"/api/admin/companies/{c.id}/logo"

    r = api_client.put(path, json={"logo_url": "https://up.example/missing.svg"})
    assert r.status_code == 422
    r = api_client.put(path, json={"logo_url": "https://up.example/tiny.png"})
    assert r.status_code == 422 and "too small" in r.json()["detail"]
    db.refresh(c)
    assert c.logo_url is None and c.logo_checked_at is None  # rejections stamp nothing

    r = api_client.put(path, json={"logo_url": "https://up.example/kmart.png"})
    assert r.status_code == 200
    assert r.json() == {"source": "override", "media": "image/png", "width": 256}
    db.refresh(c)
    assert c.logo_url == "https://up.example/kmart.png"
    assert c.logo_checked_at is not None
    assert c.has_logo
    # Validated bytes are cached, so the public route serves them at once.
    assert logo_fetch.cache.get(logo_fetch.override_key(c.logo_url)) == (
        True, (_png(256), "image/png"))


def test_put_null_clears_and_evicts(db, api_client, admin, images):
    c = _company(db, "Kmart", 100, logo_url="https://up.example/old.png")
    key = logo_fetch.override_key("https://up.example/old.png")
    logo_fetch.cache.put(key, (_png(256), "image/png"))

    r = api_client.put(f"/api/admin/companies/{c.id}/logo", json={"logo_url": None})
    assert r.status_code == 200 and r.json()["source"] is None
    db.refresh(c)
    assert c.logo_url is None and c.logo_checked_at is not None
    assert logo_fetch.cache.get(key) == (False, None)
    assert api_client.put("/api/admin/companies/999999/logo", json={}).status_code == 404


def test_probe_reports_source_and_width(db, api_client, admin, monkeypatch):
    c = _company(db, "Acme", 100, website="acme.com")

    def fake_logo_for(website, logo_url=None):
        if logo_url:
            return None
        return (_png(32), "image/png") if website else None

    monkeypatch.setattr(logo_fetch, "logo_for", fake_logo_for)
    r = api_client.get(f"/api/admin/companies/{c.id}/logo-probe")
    assert r.json() == {"source": "favicon", "media": "image/png", "width": 32}

    c.website = None
    db.commit()
    r = api_client.get(f"/api/admin/companies/{c.id}/logo-probe")
    assert r.json() == {"source": None, "media": None, "width": None}
