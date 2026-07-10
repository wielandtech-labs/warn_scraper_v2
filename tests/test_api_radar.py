"""Tests for /api/radar and /api/notices/{id}/occupation-mix."""
from __future__ import annotations

from datetime import date

import pytest
from fastapi.testclient import TestClient

from warn_v2.db.models import Company, Location, Notice
from warn_v2.labor import oews

_TODAY = date(2026, 7, 1)


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


@pytest.fixture(autouse=True)
def _fixed_today(monkeypatch):
    """Pin the radar's "today" so tests don't depend on the wall clock."""
    from warn_v2.api.routes import radar

    monkeypatch.setattr(radar, "_today", lambda: _TODAY)


@pytest.fixture(autouse=True)
def staffing():
    """Seed OEWS staffing patterns with a small fake dataset."""
    oews.reload_for_testing(
        {
            "occupations": {
                "51-4041": "Machinists",
                "51-1011": "Supervisors",
                "53-7062": "Laborers",
                "17-2112": "Industrial Engineers",
            },
            "levels": {
                "sector": {
                    "31-33": {
                        "title": "Manufacturing",
                        "coverage": 10.0,
                        "occs": [["51-4041", 6.0], ["53-7062", 4.0]],
                    }
                },
                "naics3": {
                    "312": {
                        "title": "Beverage and Tobacco Product Manufacturing",
                        "coverage": 7.0,
                        "occs": [["53-7062", 7.0]],
                    }
                },
                "naics4": {
                    "3119": {
                        "title": "Other Food Manufacturing",
                        "coverage": 26.0,
                        "occs": [
                            ["51-4041", 12.0],
                            ["51-1011", 8.0],
                            ["53-7062", 4.0],
                            ["17-2112", 2.0],
                        ],
                    }
                },
            },
        },
        vintage="May 2025",
    )
    yield
    oews.reload_for_testing({}, vintage=None)


def _notice(
    db,
    *,
    effective_date: date | None,
    state: str = "KS",
    employer: str = "Acme",
    layoff_count: int | None = 100,
    naics: str | None = None,
    closure_category: str | None = None,
    county: str | None = None,
    city: str | None = None,
    notice_date: date = date(2026, 5, 1),
    is_superseded: bool = False,
) -> Notice:
    company_id = None
    if naics is not None:
        company = Company(name=f"{employer} Co", naics_code=naics)
        db.add(company)
        db.flush()
        company_id = company.id
    location_id = None
    if county or city:
        loc = Location(state=state, county=county, city=city)
        db.add(loc)
        db.flush()
        location_id = loc.id
    n = Notice(
        notice_id=f"test_{state}_{employer}_{effective_date}_{layoff_count}",
        state=state,
        employer=employer,
        notice_date=notice_date,
        effective_date=effective_date,
        layoff_count=layoff_count,
        closure_category=closure_category,
        company_id=company_id,
        location_id=location_id,
        is_superseded=is_superseded,
    )
    db.add(n)
    db.flush()
    return n


# ---------------------------------------------------------------------------
# /api/radar
# ---------------------------------------------------------------------------

def test_empty(api_client, db):
    db.commit()
    body = api_client.get("/api/radar").json()
    assert body == {"items": [], "total": 0, "limit": 50, "offset": 0}


def test_only_upcoming_sorted_soonest_first(api_client, db):
    _notice(db, effective_date=date(2026, 6, 30), employer="Past")
    _notice(db, effective_date=None, employer="Undated")
    _notice(db, effective_date=date(2026, 8, 15), employer="Later")
    _notice(db, effective_date=_TODAY, employer="Today")
    db.commit()

    body = api_client.get("/api/radar").json()
    assert [r["employer"] for r in body["items"]] == ["Today", "Later"]
    assert body["total"] == 2
    assert [r["days_until"] for r in body["items"]] == [0, 45]


def test_superseded_excluded(api_client, db):
    _notice(db, effective_date=date(2026, 8, 1), employer="Kept")
    _notice(db, effective_date=date(2026, 8, 1), employer="Old", is_superseded=True)
    db.commit()

    body = api_client.get("/api/radar").json()
    assert [r["employer"] for r in body["items"]] == ["Kept"]


def test_unknown_industry_included_until_industry_filter(api_client, db):
    # No linked company → industry unknown, but the notice must still appear.
    _notice(db, effective_date=date(2026, 8, 1), employer="Mystery")
    _notice(db, effective_date=date(2026, 9, 1), employer="Foods", naics="311999")
    db.commit()

    body = api_client.get("/api/radar").json()
    assert [r["employer"] for r in body["items"]] == ["Mystery", "Foods"]
    mystery, foods = body["items"]
    assert mystery["naics_code"] is None
    assert mystery["sector_name"] is None
    assert mystery["occupation_preview"] is None
    assert foods["naics_code"] == "311999"
    assert foods["sector"] == "31-33"
    assert foods["sector_name"] == "Manufacturing"

    # An industry filter is a positive NAICS match — unknowns drop out.
    body = api_client.get("/api/radar?industry=31-33").json()
    assert [r["employer"] for r in body["items"]] == ["Foods"]
    assert body["total"] == 1


def test_subsector_wins_over_sector(api_client, db):
    _notice(db, effective_date=date(2026, 8, 1), employer="Foods", naics="311999")
    _notice(db, effective_date=date(2026, 8, 1), employer="Gadgets", naics="339999")
    db.commit()

    body = api_client.get("/api/radar?industry=31-33&subsector=311").json()
    assert [r["employer"] for r in body["items"]] == ["Foods"]


def test_state_and_closure_filters(api_client, db):
    _notice(db, effective_date=date(2026, 8, 1), state="KS", closure_category="Closure")
    _notice(db, effective_date=date(2026, 8, 1), state="TX", employer="Beta",
            closure_category="Layoff")
    db.commit()

    body = api_client.get("/api/radar?state=ks").json()
    assert [r["state"] for r in body["items"]] == ["KS"]

    body = api_client.get("/api/radar?closure_category=Layoff").json()
    assert [r["employer"] for r in body["items"]] == ["Beta"]


def test_min_layoffs_drops_unknown_counts(api_client, db):
    _notice(db, effective_date=date(2026, 8, 1), employer="Big", layoff_count=500)
    _notice(db, effective_date=date(2026, 8, 1), employer="Small", layoff_count=20)
    _notice(db, effective_date=date(2026, 8, 1), employer="Unknown", layoff_count=None)
    db.commit()

    body = api_client.get("/api/radar").json()
    assert body["total"] == 3

    body = api_client.get("/api/radar?min_layoffs=100").json()
    assert [r["employer"] for r in body["items"]] == ["Big"]


def test_days_horizon_boundary_inclusive(api_client, db):
    _notice(db, effective_date=date(2026, 7, 31), employer="Inside")  # +30 days
    _notice(db, effective_date=date(2026, 8, 1), employer="Outside")  # +31 days
    db.commit()

    body = api_client.get("/api/radar?days=30").json()
    assert [r["employer"] for r in body["items"]] == ["Inside"]
    assert body["total"] == 1


def test_pagination(api_client, db):
    for i in range(3):
        _notice(db, effective_date=date(2026, 8, 1 + i), employer=f"Emp{i}")
    db.commit()

    body = api_client.get("/api/radar?limit=2").json()
    assert body["total"] == 3
    assert [r["employer"] for r in body["items"]] == ["Emp0", "Emp1"]

    body = api_client.get("/api/radar?limit=2&offset=2").json()
    assert [r["employer"] for r in body["items"]] == ["Emp2"]


def test_occupation_preview_top3_and_estimates(api_client, db):
    _notice(db, effective_date=date(2026, 8, 1), employer="Foods", naics="311999",
            layoff_count=100, city="Wichita", county="Sedgwick")
    _notice(db, effective_date=date(2026, 8, 2), employer="Counts Unknown",
            naics="311999", layoff_count=None)
    _notice(db, effective_date=date(2026, 8, 3), employer="Brews", naics="312111")
    db.commit()

    body = api_client.get("/api/radar").json()
    foods, unknown, brews = body["items"]

    # Top 3 of the 4 seeded occupations, estimate = round(count * pct / 100).
    assert [o["soc_code"] for o in foods["occupation_preview"]] == [
        "51-4041", "51-1011", "53-7062",
    ]
    assert [o["estimate"] for o in foods["occupation_preview"]] == [12, 8, 4]
    assert foods["oews_vintage"] == "May 2025"
    assert foods["city"] == "Wichita"
    assert foods["county"] == "Sedgwick"

    # No layoff count → shares only, no absolute estimates.
    assert [o["estimate"] for o in unknown["occupation_preview"]] == [None, None, None]

    # "312111" has no 4-digit entry seeded → 3-digit pattern applies.
    assert [o["soc_code"] for o in brews["occupation_preview"]] == ["53-7062"]
    assert [o["estimate"] for o in brews["occupation_preview"]] == [7]


# ---------------------------------------------------------------------------
# /api/notices/{id}/occupation-mix
# ---------------------------------------------------------------------------

def test_occupation_mix_unknown_notice_404(api_client, db):
    db.commit()
    assert api_client.get("/api/notices/nope/occupation-mix").status_code == 404


def test_occupation_mix_no_naics(api_client, db):
    n = _notice(db, effective_date=date(2026, 8, 1))
    db.commit()

    body = api_client.get(f"/api/notices/{n.notice_id}/occupation-mix").json()
    assert body["available"] is False
    assert body["reason"] == "no_naics"
    assert body["occupations"] == []


def test_occupation_mix_no_pattern(api_client, db):
    # A NAICS code whose 4-digit/3-digit/sector levels all miss the data.
    n = _notice(db, effective_date=date(2026, 8, 1), naics="999999")
    db.commit()

    body = api_client.get(f"/api/notices/{n.notice_id}/occupation-mix").json()
    assert body["available"] is False
    assert body["reason"] == "no_pattern"
    assert body["naics_code"] == "999999"


def test_occupation_mix_full_pattern(api_client, db):
    n = _notice(db, effective_date=date(2026, 8, 1), naics="311999", layoff_count=200)
    db.commit()

    body = api_client.get(f"/api/notices/{n.notice_id}/occupation-mix").json()
    assert body["available"] is True
    assert body["reason"] is None
    assert body["matched_naics"] == "3119"
    assert body["match_level"] == "4-digit"
    assert body["industry_title"] == "Other Food Manufacturing"
    assert body["coverage_pct"] == 26.0
    assert body["oews_vintage"] == "May 2025"
    # The full pattern (not the top-3 radar preview), highest share first.
    assert [(o["soc_code"], o["estimate"]) for o in body["occupations"]] == [
        ("51-4041", 24), ("51-1011", 16), ("53-7062", 8), ("17-2112", 4),
    ]
    assert body["occupations"][0]["title"] == "Machinists"


def test_occupation_mix_shares_only_without_count(api_client, db):
    n = _notice(db, effective_date=date(2026, 8, 1), naics="311999", layoff_count=None)
    db.commit()

    body = api_client.get(f"/api/notices/{n.notice_id}/occupation-mix").json()
    assert body["available"] is True
    assert body["layoff_count"] is None
    assert all(o["estimate"] is None for o in body["occupations"])
    assert body["occupations"][0]["pct"] == 12.0


def test_occupation_mix_works_for_past_notices(api_client, db):
    # The mix endpoint is not radar-gated: a notice whose separation already
    # happened still has a meaningful occupation profile.
    n = _notice(db, effective_date=date(2020, 1, 1), naics="311999")
    db.commit()

    assert api_client.get(f"/api/notices/{n.notice_id}/occupation-mix").json()["available"] is True
