"""Tests for /api/search (global autocomplete) and the companies name filter."""
from __future__ import annotations

from datetime import date

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


def _company(db, name, **kw):
    c = Company(name=name, **kw)
    db.add(c)
    db.flush()
    return c


def _notice(db, employer, state="CA", notice_date=date(2026, 1, 1), **kw):
    n = Notice(
        notice_id=f"s_{state}_{employer[:10]}_{notice_date}",
        state=state,
        employer=employer,
        notice_date=notice_date,
        **kw,
    )
    db.add(n)
    db.flush()
    return n


def test_search_matches_companies_and_notices(api_client, db):
    _company(db, "Acme Robotics Inc")
    _company(db, "Globex Corp")
    _notice(db, "Acme Robotics Inc")
    _notice(db, "Unrelated Co", notice_date=date(2026, 2, 1))
    db.commit()

    body = api_client.get("/api/search?q=acme").json()
    assert [c["name"] for c in body["companies"]] == ["Acme Robotics Inc"]
    assert [n["employer"] for n in body["notices"]] == ["Acme Robotics Inc"]
    assert body["notices"][0]["state"] == "CA"


def test_search_excludes_superseded_notices(api_client, db):
    _notice(db, "Acme Active")
    sup = _notice(db, "Acme Old", notice_date=date(2026, 1, 2))
    sup.is_superseded = True
    db.commit()

    employers = {n["employer"] for n in api_client.get("/api/search?q=acme").json()["notices"]}
    assert employers == {"Acme Active"}


def test_search_excludes_merged_companies(api_client, db):
    canon = _company(db, "Acme Inc")
    dupe = _company(db, "Acme LLC")
    dupe.canonical_company_id = canon.id
    db.commit()

    names = [c["name"] for c in api_client.get("/api/search?q=acme").json()["companies"]]
    assert names == ["Acme Inc"]  # the merged dupe is hidden


def test_search_respects_limit(api_client, db):
    for i in range(5):
        _company(db, f"Acme {i}")
    db.commit()

    body = api_client.get("/api/search?q=acme&limit=2").json()
    assert len(body["companies"]) == 2


def test_search_blank_query_rejected(api_client, db):
    db.commit()
    # min_length=1 → empty string is a validation error
    assert api_client.get("/api/search?q=").status_code == 422


def test_search_whitespace_query_returns_empty(api_client, db):
    _company(db, "Acme Inc")
    db.commit()
    body = api_client.get("/api/search?q=%20%20").json()
    assert body == {"companies": [], "notices": []}


def test_companies_name_filter(api_client, db):
    _company(db, "Acme Robotics")
    _company(db, "Globex Corp")
    db.commit()

    body = api_client.get("/api/companies?name=acme").json()
    assert body["total"] == 1
    assert body["items"][0]["name"] == "Acme Robotics"
