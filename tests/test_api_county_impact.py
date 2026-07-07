"""Tests for /stats/county-impact and the county employment reference data."""
from __future__ import annotations

from datetime import date

import pytest
from fastapi.testclient import TestClient

from warn_v2.db.models import Location, Notice
from warn_v2.geo import county_employment
from warn_v2.scripts.fetch_county_employment import _parse_cbp, _parse_gazetteer


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
    """Pin the default 12-month window so tests don't depend on the wall clock."""
    from warn_v2.api.routes import stats

    monkeypatch.setattr(stats, "_today", lambda: date(2026, 7, 1))


@pytest.fixture()
def cbp():
    """Seed the county employment table with a small fake CBP dataset."""
    county_employment.reload_for_testing(
        {
            "KS|sedgwick": 200_000,
            "KS|riley": 30_000,
            "TX|loving": 500,
        },
        year=2023,
    )
    yield
    county_employment.reload_for_testing({}, year=None)


def _notice(
    db,
    *,
    state: str,
    county: str | None,
    layoff_count: int | None,
    employer: str = "Acme",
    notice_date: date = date(2026, 3, 1),
    is_superseded: bool = False,
) -> Notice:
    loc = Location(state=state, county=county)
    db.add(loc)
    db.flush()
    nid = f"test_{state}_{county}_{notice_date}_{employer}_{layoff_count}"
    n = Notice(
        notice_id=nid,
        state=state,
        employer=employer,
        notice_date=notice_date,
        layoff_count=layoff_count,
        location_id=loc.id,
        is_superseded=is_superseded,
    )
    db.add(n)
    db.flush()
    return n


# ---------------------------------------------------------------------------
# /stats/county-impact
# ---------------------------------------------------------------------------

def test_empty(api_client, db, cbp):
    db.commit()
    resp = api_client.get("/api/stats/county-impact")
    assert resp.status_code == 200
    assert resp.json() == []


def test_ratio_math_and_ordering(api_client, db, cbp):
    # Riley: 300 / 30 000 = 1% — smaller absolute count, bigger local impact.
    # Sedgwick: 1 000 / 200 000 = 0.5%.
    _notice(db, state="KS", county="Sedgwick", layoff_count=600)
    _notice(db, state="KS", county="Sedgwick", layoff_count=400, employer="Beta")
    _notice(db, state="KS", county="Riley", layoff_count=300)
    db.commit()

    body = api_client.get("/api/stats/county-impact").json()
    assert [r["county"] for r in body] == ["Riley", "Sedgwick"]
    riley, sedgwick = body
    assert riley["impact_pct"] == 1.0
    assert riley["employment_base"] == 30_000
    assert riley["notice_count"] == 1
    assert sedgwick["impact_pct"] == 0.5
    assert sedgwick["layoff_total"] == 1000
    assert sedgwick["notice_count"] == 2
    assert sedgwick["cbp_year"] == 2023


def test_suffix_variants_merge(api_client, db, cbp):
    # Scrapers report the same county with and without the legal-type suffix.
    _notice(db, state="KS", county="Sedgwick", layoff_count=600)
    _notice(db, state="KS", county="Sedgwick County", layoff_count=400, employer="Beta")
    db.commit()

    body = api_client.get("/api/stats/county-impact").json()
    assert len(body) == 1
    assert body[0]["county"] == "Sedgwick"
    assert body[0]["layoff_total"] == 1000
    assert body[0]["notice_count"] == 2


def test_superseded_and_null_county_excluded(api_client, db, cbp):
    _notice(db, state="KS", county="Sedgwick", layoff_count=500)
    _notice(
        db, state="KS", county="Sedgwick", layoff_count=900,
        employer="Beta", is_superseded=True,
    )
    _notice(db, state="KS", county=None, layoff_count=800, employer="Gamma")
    db.commit()

    body = api_client.get("/api/stats/county-impact").json()
    assert len(body) == 1
    assert body[0]["layoff_total"] == 500
    assert body[0]["notice_count"] == 1


def test_county_without_cbp_match_omitted(api_client, db, cbp):
    _notice(db, state="KS", county="Sedgwick", layoff_count=100)
    _notice(db, state="KS", county="Atlantis", layoff_count=9999, employer="Beta")
    db.commit()

    body = api_client.get("/api/stats/county-impact").json()
    assert [r["county"] for r in body] == ["Sedgwick"]


def test_min_layoffs_floor(api_client, db, cbp):
    # 5 reported layoffs in tiny Loving TX is a 1% share, but below the
    # default floor of 10 — visible only when the floor is lowered.
    _notice(db, state="TX", county="Loving", layoff_count=5)
    _notice(db, state="KS", county="Sedgwick", layoff_count=100, employer="Beta")
    db.commit()

    body = api_client.get("/api/stats/county-impact").json()
    assert [r["county"] for r in body] == ["Sedgwick"]

    body = api_client.get("/api/stats/county-impact?min_layoffs=0").json()
    assert [r["county"] for r in body] == ["Loving", "Sedgwick"]


def test_state_and_date_filters_and_limit(api_client, db, cbp):
    _notice(db, state="KS", county="Sedgwick", layoff_count=100, notice_date=date(2026, 3, 1))
    _notice(db, state="KS", county="Riley", layoff_count=100, notice_date=date(2025, 1, 1))
    _notice(db, state="TX", county="Loving", layoff_count=100)
    db.commit()

    body = api_client.get("/api/stats/county-impact?state=ks&after=2020-01-01").json()
    assert {r["state"] for r in body} == {"KS"}
    assert len(body) == 2

    body = api_client.get("/api/stats/county-impact?state=KS&after=2026-01-01").json()
    assert [r["county"] for r in body] == ["Sedgwick"]

    body = api_client.get("/api/stats/county-impact?limit=1").json()
    assert len(body) == 1
    assert body[0]["county"] == "Loving"  # 100/500 = 20%, the top impact


def test_default_window_is_trailing_year(api_client, db, cbp):
    # Layoffs are a flow against a point-in-time employment stock: without a
    # window, decades of notices accumulate into >100% shares. The default
    # window is the 12 months before _today() (pinned to 2026-07-01 here).
    _notice(db, state="KS", county="Sedgwick", layoff_count=100, notice_date=date(2026, 3, 1))
    _notice(db, state="KS", county="Riley", layoff_count=100, notice_date=date(2025, 1, 1))
    db.commit()

    body = api_client.get("/api/stats/county-impact").json()
    assert [r["county"] for r in body] == ["Sedgwick"]

    body = api_client.get("/api/stats/county-impact?after=2024-01-01").json()
    assert len(body) == 2


def test_null_layoff_counts_do_not_crash(api_client, db, cbp):
    # Counties where every notice lacks a layoff count sum to 0 and fall
    # under the min_layoffs floor rather than erroring.
    _notice(db, state="KS", county="Sedgwick", layoff_count=None)
    db.commit()

    body = api_client.get("/api/stats/county-impact").json()
    assert body == []


# ---------------------------------------------------------------------------
# geo/county_employment helpers
# ---------------------------------------------------------------------------

def test_normalize_key_and_display_name():
    assert county_employment.normalize_key("ks", " Sedgwick County ") == "KS|sedgwick"
    assert county_employment.normalize_key("LA", "Orleans Parish") == "LA|orleans"
    assert county_employment.normalize_key("KS", None) is None
    assert county_employment.normalize_key(None, "Sedgwick") is None
    assert county_employment.display_name("McLean County") == "McLean"
    assert county_employment.display_name("DeKalb") == "DeKalb"


def test_lookup_uses_seeded_data(cbp):
    assert county_employment.lookup("KS", "Sedgwick County") == 200_000
    assert county_employment.lookup("KS", "sedgwick") == 200_000
    assert county_employment.lookup("KS", "Nowhere") is None
    assert county_employment.data_year() == 2023


# ---------------------------------------------------------------------------
# scripts/fetch_county_employment parsing (no network)
# ---------------------------------------------------------------------------

_GAZ_TSV = (
    "USPS\tGEOID\tANSICODE\tNAME\tALAND\tAWATER\tALAND_SQMI\tAWATER_SQMI\tINTPTLAT\tINTPTLONG\n"
    "KS\t20173\t00485011\tSedgwick County\t2603719624\t29360221\t1005.3\t11.3\t37.68\t-97.46\n"
    "LA\t22071\t00558118\tOrleans Parish\t438804517\t468060911\t169.4\t180.7\t30.03\t-89.93\n"
)

_CBP_CSV = (
    '"fipstate","fipscty","naics","emp_nf","emp","qp1_nf","qp1","ap_nf","ap","est"\n'
    '"20","173","------","G",237173,"G",1,"G",1,968\n'
    '"20","173","31----","G",30000,"G",1,"G",1,100\n'  # sector row: skipped
    '"22","071","------","G",177086,"G",1,"G",1,500\n'
    '"99","999","------","G",123,"G",1,"G",1,1\n'  # no gazetteer match
    '"20","174","------","D",0,"D",0,"D",0,1\n'  # withheld: emp 0
)


def test_fetch_parsers():
    geo = _parse_gazetteer(_GAZ_TSV)
    assert geo["20173"] == ("KS", "Sedgwick County")

    counties = _parse_cbp(_CBP_CSV, geo)
    assert counties == {"KS|sedgwick": 237173, "LA|orleans": 177086}
