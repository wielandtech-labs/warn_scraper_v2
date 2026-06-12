"""Integration tests for the FastAPI read-only API."""
from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from warn_v2.db.models import Company, Location, Notice, ScraperRun

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def api_client(db):
    """TestClient wired to the in-memory SQLite DB via dependency override."""
    from warn_v2.api import app
    from warn_v2.api.deps import get_db

    def _override():
        yield db

    app.dependency_overrides[get_db] = _override
    client = TestClient(app, raise_server_exceptions=True)
    yield client
    app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _company(db, name: str = "Acme Inc", **kw) -> Company:
    c = Company(name=name, **kw)
    db.add(c)
    db.flush()
    return c


def _notice(
    db,
    company: Company | None = None,
    state: str = "CA",
    employer: str = "Acme Inc",
    notice_date: date = date(2026, 1, 15),
    layoff_count: int = 100,
    closure_category: str | None = None,
) -> Notice:
    nid = f"test_{state}_{notice_date}_{employer[:8]}"
    n = Notice(
        notice_id=nid,
        state=state,
        employer=employer,
        notice_date=notice_date,
        layoff_count=layoff_count,
        closure_category=closure_category,
        company_id=company.id if company else None,
    )
    db.add(n)
    db.flush()
    return n


def _run(db, state: str = "CA", status: str = "ok") -> ScraperRun:
    r = ScraperRun(
        state=state,
        started_at=datetime.now(UTC),
        status=status,
    )
    db.add(r)
    db.flush()
    return r


# ---------------------------------------------------------------------------
# /healthz
# ---------------------------------------------------------------------------

def test_healthz(api_client):
    resp = api_client.get("/healthz")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


# ---------------------------------------------------------------------------
# /notices
# ---------------------------------------------------------------------------

def test_notices_empty(api_client, db):
    db.commit()
    resp = api_client.get("/api/notices")
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 0
    assert body["items"] == []


def test_notices_returns_data(api_client, db):
    _notice(db, state="CA")
    _notice(db, state="TX", employer="Texas Co", notice_date=date(2026, 2, 1))
    db.commit()

    resp = api_client.get("/api/notices")
    assert resp.status_code == 200
    assert resp.json()["total"] == 2


def test_notices_state_filter(api_client, db):
    _notice(db, state="CA")
    _notice(db, state="TX", employer="Texas Co", notice_date=date(2026, 2, 1))
    db.commit()

    resp = api_client.get("/api/notices?state=CA")
    body = resp.json()
    assert body["total"] == 1
    assert body["items"][0]["state"] == "CA"


def test_notices_employer_filter_ilike(api_client, db):
    _notice(db, employer="Acme Robotics Inc")
    _notice(db, employer="Other Corp", notice_date=date(2026, 2, 1))
    db.commit()

    resp = api_client.get("/api/notices?employer=acme")
    body = resp.json()
    assert body["total"] == 1
    assert "Acme" in body["items"][0]["employer"]


def test_notices_closure_category_filter(api_client, db):
    _notice(db, employer="Closing Co", closure_category="Closure")
    _notice(
        db,
        employer="Layoff Co",
        notice_date=date(2026, 2, 1),
        closure_category="Layoff",
    )
    _notice(db, employer="Unknown Co", notice_date=date(2026, 3, 1))
    db.commit()

    resp = api_client.get("/api/notices?closure_category=Closure")
    body = resp.json()
    assert body["total"] == 1
    assert body["items"][0]["employer"] == "Closing Co"
    assert body["items"][0]["closure_category"] == "Closure"


def test_notices_pagination(api_client, db):
    for i in range(5):
        _notice(db, employer=f"Corp {i}", notice_date=date(2026, 1, i + 1))
    db.commit()

    resp = api_client.get("/api/notices?limit=2&offset=0")
    body = resp.json()
    assert body["total"] == 5
    assert len(body["items"]) == 2
    assert body["limit"] == 2
    assert body["offset"] == 0


def test_notices_date_filter(api_client, db):
    _notice(db, notice_date=date(2026, 1, 1))
    _notice(db, employer="Late Corp", notice_date=date(2026, 6, 1))
    db.commit()

    resp = api_client.get("/api/notices?after=2026-03-01")
    body = resp.json()
    assert body["total"] == 1
    assert body["items"][0]["employer"] == "Late Corp"


def test_notice_detail_found(api_client, db):
    c = _company(db)
    n = _notice(db, company=c)
    db.commit()

    resp = api_client.get(f"/api/notices/{n.notice_id}")
    assert resp.status_code == 200
    body = resp.json()
    assert body["notice_id"] == n.notice_id
    assert body["company"]["id"] == c.id


def test_notice_detail_not_found(api_client, db):
    db.commit()
    resp = api_client.get("/api/notices/does-not-exist")
    assert resp.status_code == 404


def test_notices_excludes_superseded(api_client, db):
    """is_superseded=True notices must not appear in list results or totals."""
    _notice(db, state="IA", employer="Active Co", notice_date=date(2026, 1, 10))
    sup = _notice(db, state="IA", employer="Dup Co", notice_date=date(2026, 1, 11))
    sup.is_superseded = True
    db.commit()

    resp = api_client.get("/api/notices?state=IA")
    body = resp.json()
    assert body["total"] == 1
    assert body["items"][0]["employer"] == "Active Co"


def test_notices_superseded_still_fetchable_by_id(api_client, db):
    """A superseded record can still be fetched directly by notice_id."""
    n = _notice(db, state="IA", employer="Dup Co")
    n.is_superseded = True
    db.commit()

    resp = api_client.get(f"/api/notices/{n.notice_id}")
    assert resp.status_code == 200
    assert resp.json()["employer"] == "Dup Co"


# ---------------------------------------------------------------------------
# /companies
# ---------------------------------------------------------------------------

def test_companies_empty(api_client, db):
    db.commit()
    resp = api_client.get("/api/companies")
    assert resp.status_code == 200
    assert resp.json()["total"] == 0


def test_companies_list(api_client, db):
    _company(db, name="Alpha Inc")
    _company(db, name="Beta Corp")
    db.commit()

    resp = api_client.get("/api/companies")
    assert resp.json()["total"] == 2


def test_companies_enriched_filter_false(api_client, db):
    _company(db, name="Unenriched")
    _company(
        db,
        name="Enriched",
        enriched_at=datetime.now(UTC),
        enrichment_confidence=Decimal("0.9"),
    )
    db.commit()

    resp = api_client.get("/api/companies?enriched=false")
    body = resp.json()
    assert body["total"] == 1
    assert body["items"][0]["name"] == "Unenriched"


def test_companies_enriched_filter_true(api_client, db):
    _company(db, name="Unenriched")
    _company(
        db,
        name="Enriched",
        enriched_at=datetime.now(UTC),
        enrichment_confidence=Decimal("0.9"),
    )
    db.commit()

    resp = api_client.get("/api/companies?enriched=true")
    body = resp.json()
    assert body["total"] == 1
    assert body["items"][0]["name"] == "Enriched"


def test_companies_has_duns_filter(api_client, db):
    _company(db, name="No DUNS", enriched_at=datetime.now(UTC))  # enriched, but DUNS-less
    _company(db, name="With DUNS", duns="123456789", enriched_at=datetime.now(UTC))
    db.commit()

    body = api_client.get("/api/companies?has_duns=true").json()
    assert body["total"] == 1
    assert body["items"][0]["name"] == "With DUNS"

    body = api_client.get("/api/companies?has_duns=false").json()
    assert body["total"] == 1
    assert body["items"][0]["name"] == "No DUNS"

    # enriched=true alone includes both — has_duns is the narrower filter
    assert api_client.get("/api/companies?enriched=true").json()["total"] == 2
    assert api_client.get("/api/companies?enriched=true&has_duns=true").json()["total"] == 1


def test_company_detail_found(api_client, db):
    c = _company(db)
    db.commit()

    resp = api_client.get(f"/api/companies/{c.id}")
    assert resp.status_code == 200
    assert resp.json()["name"] == c.name


def test_company_detail_not_found(api_client, db):
    db.commit()
    resp = api_client.get("/api/companies/99999")
    assert resp.status_code == 404


def test_company_detail_hides_internal_enrichment_fields(api_client, db):
    """D&B-sourced fields are stored but must not be exposed by the public API.

    Redistribution of DUNS / employee counts / corporate hierarchy is restricted
    by D&B terms, so CompanyOut deliberately omits them.
    """
    c = _company(
        db,
        name="Enriched Co",
        duns="123456789",
        employee_count=5000,
        parent_company_name="Parent Holdings",
        parent_duns="987654321",
        global_ultimate_name="Global Ultimate Ltd",
        hq_address="1 Main St, Anytown, USA",
        website="https://enriched.example.com",
        sic_code="3559",
    )
    db.commit()

    body = api_client.get(f"/api/companies/{c.id}").json()
    for hidden in (
        "duns",
        "employee_count",
        "parent_company_name",
        "parent_duns",
        "global_ultimate_name",
        "hq_address",
    ):
        assert hidden not in body, f"{hidden} must not be exposed publicly"
    # Low-risk fields are still surfaced.
    assert body["website"] == "https://enriched.example.com"
    assert body["sic_code"] == "3559"


def test_company_notices(api_client, db):
    c = _company(db)
    _notice(db, company=c)
    _notice(db, company=c, notice_date=date(2026, 3, 1), employer="Acme Inc")
    db.commit()

    resp = api_client.get(f"/api/companies/{c.id}/notices")
    assert resp.status_code == 200
    assert resp.json()["total"] == 2


# ---------------------------------------------------------------------------
# /scraper-runs
# ---------------------------------------------------------------------------

def test_scraper_runs_empty(api_client, db):
    db.commit()
    resp = api_client.get("/api/scraper-runs")
    assert resp.status_code == 200
    assert resp.json()["total"] == 0


def test_scraper_runs_list(api_client, db):
    _run(db, state="CA", status="ok")
    _run(db, state="TX", status="parse_failed")
    db.commit()

    resp = api_client.get("/api/scraper-runs")
    assert resp.json()["total"] == 2


def test_scraper_runs_status_filter(api_client, db):
    _run(db, state="CA", status="ok")
    _run(db, state="TX", status="parse_failed")
    db.commit()

    resp = api_client.get("/api/scraper-runs?status=ok")
    body = resp.json()
    assert body["total"] == 1
    assert body["items"][0]["status"] == "ok"


def test_scraper_runs_state_filter(api_client, db):
    _run(db, state="CA", status="ok")
    _run(db, state="TX", status="ok")
    db.commit()

    resp = api_client.get("/api/scraper-runs?state=TX")
    body = resp.json()
    assert body["total"] == 1
    assert body["items"][0]["state"] == "TX"


# ---------------------------------------------------------------------------
# company consolidation rollup
# ---------------------------------------------------------------------------

def _merged_pair(db):
    canon = _company(db, name="Acme Inc")
    db.flush()
    dupe = _company(db, name="Acme LLC")
    dupe.canonical_company_id = canon.id
    db.flush()
    return canon, dupe


def test_companies_hide_merged_by_default(api_client, db):
    _merged_pair(db)
    db.commit()

    body = api_client.get("/api/companies").json()
    names = [i["name"] for i in body["items"]]
    assert body["total"] == 1
    assert "Acme Inc" in names and "Acme LLC" not in names

    allbody = api_client.get("/api/companies?include_merged=true").json()
    assert allbody["total"] == 2


def test_top_employers_rolls_up_duplicates(api_client, db):
    canon, dupe = _merged_pair(db)
    _notice(db, company=canon, employer="Acme Inc", layoff_count=100,
            notice_date=date(2026, 1, 1))
    _notice(db, company=dupe, employer="Acme LLC", layoff_count=50,
            notice_date=date(2026, 2, 1))
    db.commit()

    body = api_client.get("/api/stats/top-employers").json()
    rows = [r for r in body if r["company_id"] == canon.id]
    assert len(rows) == 1
    assert rows[0]["notice_count"] == 2
    assert rows[0]["layoff_total"] == 150
    assert rows[0]["employer"] == "Acme Inc"  # canonical name, not the dupe's


def test_company_notices_rolls_up_merged_and_excludes_superseded(api_client, db):
    canon, dupe = _merged_pair(db)
    _notice(db, company=canon, employer="Acme Inc", notice_date=date(2026, 1, 1))
    _notice(db, company=dupe, employer="Acme LLC", notice_date=date(2026, 2, 1))
    sup = _notice(db, company=dupe, employer="Acme LLC", notice_date=date(2026, 3, 1))
    sup.is_superseded = True
    db.commit()

    body = api_client.get(f"/api/companies/{canon.id}/notices").json()
    assert body["total"] == 2  # canon's + dupe's active notice; superseded excluded


# ---------------------------------------------------------------------------
# parent/sibling family rollup  (/companies/{id}/family)
# ---------------------------------------------------------------------------

def test_company_family_returns_siblings_sorted(api_client, db):
    a = _company(db, name="Pixar", parent_group_key="ult:disney")
    b = _company(db, name="Marvel Studios", parent_group_key="ult:disney")
    c = _company(db, name="Lucasfilm", parent_group_key="ult:disney")
    _notice(db, company=a, employer="Pixar", layoff_count=100, notice_date=date(2026, 1, 1))
    _notice(db, company=b, employer="Marvel", layoff_count=300, notice_date=date(2026, 1, 2))
    _notice(db, company=c, employer="Lucasfilm", layoff_count=50, notice_date=date(2026, 1, 3))
    db.commit()

    body = api_client.get(f"/api/companies/{a.id}/family").json()
    assert [m["name"] for m in body] == ["Marvel Studios", "Pixar", "Lucasfilm"]
    self_rows = [m for m in body if m["is_self"]]
    assert len(self_rows) == 1 and self_rows[0]["name"] == "Pixar"
    pixar = next(m for m in body if m["name"] == "Pixar")
    assert pixar["notice_count"] == 1 and pixar["layoff_total"] == 100


def test_company_family_rolls_up_member_dupes_and_excludes_superseded(api_client, db):
    a = _company(db, name="Pixar", parent_group_key="ult:disney")
    b = _company(db, name="Marvel Studios", parent_group_key="ult:disney")
    # A dupe merged into Pixar — dupes carry no parent_group_key of their own.
    dupe = _company(db, name="Pixar Animation")
    dupe.canonical_company_id = a.id
    db.flush()
    _notice(db, company=a, employer="Pixar", layoff_count=100, notice_date=date(2026, 1, 1))
    _notice(db, company=dupe, employer="PixarAnim", layoff_count=40, notice_date=date(2026, 1, 2))
    sup = _notice(db, company=dupe, employer="PixarAnim", layoff_count=999,
                  notice_date=date(2026, 1, 3))
    sup.is_superseded = True
    _notice(db, company=b, employer="Marvel", layoff_count=10, notice_date=date(2026, 1, 4))
    db.commit()

    body = api_client.get(f"/api/companies/{a.id}/family").json()
    # Only canonical members are listed; the dupe folds into Pixar's totals.
    assert sorted(m["name"] for m in body) == ["Marvel Studios", "Pixar"]
    pixar = next(m for m in body if m["name"] == "Pixar")
    assert pixar["notice_count"] == 2  # canon's + dupe's active; superseded excluded
    assert pixar["layoff_total"] == 140


def test_company_family_self_or_no_key_is_empty(api_client, db):
    a = _company(db, name="Solo Co", parent_group_key="self:solo co")
    b = _company(db, name="No Key Co")  # parent_group_key is None
    db.commit()

    assert api_client.get(f"/api/companies/{a.id}/family").json() == []
    assert api_client.get(f"/api/companies/{b.id}/family").json() == []


def test_company_family_singleton_returns_self_only(api_client, db):
    a = _company(db, name="Lonely Sub", parent_group_key="ult:lonelyparent")
    db.commit()

    body = api_client.get(f"/api/companies/{a.id}/family").json()
    assert len(body) == 1
    assert body[0]["name"] == "Lonely Sub" and body[0]["is_self"]


def test_company_family_from_merged_dupe_resolves_to_canonical(api_client, db):
    a = _company(db, name="Pixar", parent_group_key="ult:disney")
    _company(db, name="Marvel Studios", parent_group_key="ult:disney")
    dupe = _company(db, name="Pixar Animation")
    dupe.canonical_company_id = a.id
    db.flush()
    db.commit()

    # Requesting the dupe's id resolves through canonical to Pixar's family.
    body = api_client.get(f"/api/companies/{dupe.id}/family").json()
    assert sorted(m["name"] for m in body) == ["Marvel Studios", "Pixar"]
    self_rows = [m for m in body if m["is_self"]]
    assert len(self_rows) == 1 and self_rows[0]["name"] == "Pixar"


def test_company_family_404(api_client, db):
    db.commit()
    assert api_client.get("/api/companies/999999/family").status_code == 404


# ---------------------------------------------------------------------------
# industry (NAICS sector) filter
# ---------------------------------------------------------------------------

def test_notices_industry_filter(api_client, db):
    mfg = _company(db, name="Mfg Co", naics_code="311999")
    ret = _company(db, name="Ret Co", naics_code="445110")
    _notice(db, company=mfg, employer="Mfg Co", notice_date=date(2026, 1, 1))
    _notice(db, company=ret, employer="Ret Co", notice_date=date(2026, 1, 2))
    db.commit()

    body = api_client.get("/api/notices?industry=31-33").json()
    assert body["total"] == 1
    assert body["items"][0]["employer"] == "Mfg Co"


def test_notices_industry_filter_unknown_sector_ignored(api_client, db):
    mfg = _company(db, name="Mfg Co", naics_code="311999")
    _notice(db, company=mfg, employer="Mfg Co", notice_date=date(2026, 1, 1))
    db.commit()
    # An unknown sector id is ignored (no filter applied), not an error.
    body = api_client.get("/api/notices?industry=bogus").json()
    assert body["total"] == 1


def test_companies_industry_filter(api_client, db):
    _company(db, name="Mfg Co", naics_code="332710")
    _company(db, name="Ret Co", naics_code="448140")
    db.commit()

    body = api_client.get("/api/companies?industry=31-33").json()
    assert body["total"] == 1
    assert body["items"][0]["name"] == "Mfg Co"


def test_notices_subsector_filter(api_client, db):
    food = _company(db, name="Food Co", naics_code="311999")
    bev = _company(db, name="Bev Co", naics_code="312111")  # 312, same sector 31-33
    _notice(db, company=food, employer="Food Co", notice_date=date(2026, 1, 1))
    _notice(db, company=bev, employer="Bev Co", notice_date=date(2026, 1, 2))
    db.commit()

    body = api_client.get("/api/notices?subsector=311").json()
    assert body["total"] == 1
    assert body["items"][0]["employer"] == "Food Co"


def test_notices_subsector_overrides_industry(api_client, db):
    food = _company(db, name="Food Co", naics_code="311999")
    bev = _company(db, name="Bev Co", naics_code="312111")  # same sector, diff subsector
    _notice(db, company=food, employer="Food Co", notice_date=date(2026, 1, 1))
    _notice(db, company=bev, employer="Bev Co", notice_date=date(2026, 1, 2))
    db.commit()

    # Both are sector 31-33; the 311 subsector narrows to Food only.
    body = api_client.get("/api/notices?industry=31-33&subsector=311").json()
    assert body["total"] == 1
    assert body["items"][0]["employer"] == "Food Co"


def test_companies_subsector_filter(api_client, db):
    _company(db, name="Food Co", naics_code="311999")
    _company(db, name="Bev Co", naics_code="312111")
    db.commit()

    body = api_client.get("/api/companies?subsector=311").json()
    assert body["total"] == 1
    assert body["items"][0]["name"] == "Food Co"


def _geocoded_notice(db, company, employer, closure_category=None, lat=34.0, lon=-118.0):
    """A notice with a geocoded Location so it appears on /api/map-pins."""
    loc = Location(state="CA", lat=lat, lon=lon)
    db.add(loc)
    db.flush()
    n = _notice(
        db,
        company=company,
        employer=employer,
        notice_date=date(2026, 1, 1),
        closure_category=closure_category,
    )
    n.location_id = loc.id
    return n


def test_map_pins_bbox_filter(api_client, db):
    # Three pins across the country: LA, NYC, Chicago.
    _geocoded_notice(db, None, "LA Co", lat=34.0, lon=-118.2)
    _geocoded_notice(db, None, "NYC Co", lat=40.7, lon=-74.0)
    _geocoded_notice(db, None, "CHI Co", lat=41.8, lon=-87.6)
    db.commit()

    # No bbox -> all three.
    assert {p["employer"] for p in api_client.get("/api/map-pins").json()} == {
        "LA Co", "NYC Co", "CHI Co"
    }
    # East/Midwest box excludes LA.
    emps = {p["employer"] for p in api_client.get(
        "/api/map-pins?min_lat=39&max_lat=43&min_lon=-90&max_lon=-70").json()}
    assert emps == {"NYC Co", "CHI Co"}
    # Tight box around NYC only.
    emps = {p["employer"] for p in api_client.get(
        "/api/map-pins?min_lat=40&max_lat=41&min_lon=-75&max_lon=-73").json()}
    assert emps == {"NYC Co"}
    # Partial box (missing max_lon) is ignored, not half-applied -> all three.
    assert len(api_client.get(
        "/api/map-pins?min_lat=39&max_lat=43&min_lon=-90").json()) == 3


def test_map_pins_industry_filter(api_client, db):
    mfg = _company(db, name="Mfg Co", naics_code="311999")
    bev = _company(db, name="Bev Co", naics_code="312111")  # 312, same sector 31-33
    ret = _company(db, name="Ret Co", naics_code="445110")
    _geocoded_notice(db, mfg, "Mfg Co")
    _geocoded_notice(db, bev, "Bev Co")
    _geocoded_notice(db, ret, "Ret Co")
    db.commit()

    # No filter: all three geocoded pins.
    assert {p["employer"] for p in api_client.get("/api/map-pins").json()} == {
        "Mfg Co", "Bev Co", "Ret Co"
    }
    # Sector filter: only the two manufacturing pins.
    assert {p["employer"] for p in
            api_client.get("/api/map-pins?industry=31-33").json()} == {"Mfg Co", "Bev Co"}
    # Subsector narrows to one; and wins over a conflicting sector.
    assert [p["employer"] for p in
            api_client.get("/api/map-pins?subsector=311").json()] == ["Mfg Co"]
    assert [p["employer"] for p in api_client.get(
        "/api/map-pins?industry=44-45&subsector=311").json()] == ["Mfg Co"]


def test_map_pins_closure_category_filter(api_client, db):
    _geocoded_notice(db, None, "Closing Co", closure_category="Closure")
    _geocoded_notice(db, None, "Layoff Co", closure_category="Layoff")
    _geocoded_notice(db, None, "Unknown Co")
    db.commit()

    # No filter: all three geocoded pins.
    assert {p["employer"] for p in api_client.get("/api/map-pins").json()} == {
        "Closing Co", "Layoff Co", "Unknown Co"
    }
    # Closure filter: only the matching pin.
    assert [p["employer"] for p in
            api_client.get("/api/map-pins?closure_category=Closure").json()] == ["Closing Co"]
