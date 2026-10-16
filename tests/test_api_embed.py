"""/embed/* — the iframe notice card and the state badge."""
from __future__ import annotations

from datetime import date

import pytest
from fastapi.testclient import TestClient

from warn_v2.api.routes import embed as embed_route
from warn_v2.db.models import Company, Location, Notice

NID = "0123456789abcdef0123456789abcdef"


@pytest.fixture()
def api_client(db, monkeypatch):
    from warn_v2.api import app
    from warn_v2.api.deps import get_db

    def _override():
        yield db

    monkeypatch.setenv("SITE_BASE_URL", "https://warnindex.test")
    app.dependency_overrides[get_db] = _override
    embed_route._badge_cache.clear()
    client = TestClient(app, raise_server_exceptions=True)
    yield client
    app.dependency_overrides.clear()
    embed_route._badge_cache.clear()


def _notice(nid: str, state: str, d: date, count: int | None, **kw) -> Notice:
    return Notice(
        notice_id=nid,
        state=state,
        employer=kw.pop("employer", "Acme"),
        notice_date=d,
        layoff_count=count,
        source_url="https://example.com",
        **kw,
    )


# ----- notice card -----

def test_notice_card_renders_with_frame_headers(api_client, db):
    loc = Location(city="Fresno", state="CA")
    db.add(loc)
    db.flush()
    db.add(
        _notice(
            NID,
            "CA",
            date(2026, 9, 1),
            1420,
            effective_date=date(2026, 11, 1),
            closure_category="Closure",
            location_id=loc.id,
        )
    )
    db.commit()

    r = api_client.get(f"/embed/notices/{NID}")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/html")
    assert r.headers["content-security-policy"] == "frame-ancestors *"
    assert r.headers["x-robots-tag"] == "noindex"
    assert "max-age=3600" in r.headers["cache-control"]
    assert "x-frame-options" not in r.headers
    body = r.text
    assert "Acme" in body and "Fresno, California" in body
    assert "1,420" in body and "Closure" in body
    assert "Sep 1, 2026" in body and "Nov 1, 2026" in body
    assert f"https://warnindex.test/notices/{NID}" in body
    assert "<script" not in body
    assert "Superseded" not in body


def test_notice_card_escapes_employer(api_client, db):
    db.add(_notice(NID, "TX", date(2026, 9, 1), 5, employer="<script>alert(1)</script>"))
    db.commit()
    body = api_client.get(f"/embed/notices/{NID}").text
    assert "<script>" not in body
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in body


def test_notice_card_uses_canonical_company_and_logo(api_client, db):
    canon = Company(name="Acme Corporation", logo_url="https://cdn.example/acme.png")
    db.add(canon)
    db.flush()
    dup = Company(name="ACME CORP INC", canonical_company_id=canon.id)
    db.add(dup)
    db.flush()
    db.add(_notice(NID, "TX", date(2026, 9, 1), 5, company_id=dup.id, is_superseded=True))
    db.commit()
    body = api_client.get(f"/embed/notices/{NID}").text
    assert "Acme Corporation" in body and "ACME CORP INC" not in body
    # Through the site's logo proxy, never the raw third-party URL.
    assert f"https://warnindex.test/api/logos/{canon.id}" in body
    assert "cdn.example" not in body
    assert "Superseded" in body


def test_unknown_notice_is_404_card(api_client):
    r = api_client.get("/embed/notices/ffffffffffffffffffffffffffffffff")
    assert r.status_code == 404
    assert r.headers["content-type"].startswith("text/html")
    assert r.headers["content-security-policy"] == "frame-ancestors *"
    assert "max-age=300" in r.headers["cache-control"]
    assert "Notice not found" in r.text


# ----- state badge -----

def test_badge_sums_recent_non_superseded(api_client, db, monkeypatch):
    monkeypatch.setattr(embed_route, "_today", lambda: date(2026, 10, 16))
    db.add_all(
        [
            _notice("CA-1", "CA", date(2026, 10, 1), 1000),
            _notice("CA-2", "CA", date(2026, 9, 16), 420),  # exactly 30 days back: in
            _notice("CA-3", "CA", date(2026, 9, 15), 9000),  # 31 days back: out
            _notice("CA-4", "CA", date(2026, 10, 2), 7000, is_superseded=True),
            _notice("CA-5", "CA", date(2026, 10, 3), None),
            _notice("CA-7", "CA", date(2026, 10, 4), 300, closure_category="Non-WARN"),
            _notice("CA-8", "CA", date(2027, 10, 4), 800),  # mis-parsed future date
            _notice("TX-1", "TX", date(2026, 10, 3), 50),
        ]
    )
    db.commit()

    r = api_client.get("/embed/badge/state/ca.svg")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("image/svg+xml")
    assert "max-age=86400" in r.headers["cache-control"]
    assert "California layoffs (30d)" in r.text
    assert "1,420 workers" in r.text

    db.add(_notice("CA-6", "CA", date(2026, 10, 10), 1))
    db.commit()
    assert "1,420 workers" in api_client.get("/embed/badge/state/CA.svg").text  # cached


def test_badge_state_with_no_notices_is_zero(api_client):
    assert "0 workers" in api_client.get("/embed/badge/state/WY.svg").text


def test_badge_unknown_state_404(api_client):
    assert api_client.get("/embed/badge/state/ZZ.svg").status_code == 404
