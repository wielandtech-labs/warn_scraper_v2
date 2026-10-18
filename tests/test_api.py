"""Integration tests for the FastAPI read-only API."""
from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
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


def test_notice_surfaces_location_city_and_county(api_client, db):
    """The notice view exposes location.city and location.county.

    Regression guard for the NV zip-less shape (city + county, no ZIP): the
    fields are parsed and persisted (see test_storage::
    test_city_and_county_persist_without_zip); this asserts LocationOut surfaces
    both through /api/notices/{id} rather than dropping them to null.
    """
    loc = Location(state="NV", city="Winnemucca", county="Humboldt")
    db.add(loc)
    db.flush()
    n = _notice(db, state="NV", employer="Hycroft Mining")
    n.location_id = loc.id
    db.commit()

    body = api_client.get(f"/api/notices/{n.notice_id}").json()
    assert body["location"]["city"] == "Winnemucca"
    assert body["location"]["county"] == "Humboldt"
    assert body["location"]["state"] == "NV"


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


def test_companies_has_unique_id_filter(api_client, db):
    _company(db, name="No ID", enriched_at=datetime.now(UTC))  # enriched, but id-less
    _company(db, name="With ID", unique_id="123456789", enriched_at=datetime.now(UTC))
    db.commit()

    body = api_client.get("/api/companies?has_unique_id=true").json()
    assert body["total"] == 1
    assert body["items"][0]["name"] == "With ID"

    body = api_client.get("/api/companies?has_unique_id=false").json()
    assert body["total"] == 1
    assert body["items"][0]["name"] == "No ID"

    # enriched=true alone includes both — has_unique_id is the narrower filter
    assert api_client.get("/api/companies?enriched=true").json()["total"] == 2
    assert api_client.get("/api/companies?enriched=true&has_unique_id=true").json()["total"] == 1


def test_companies_sort_by_confidence(api_client, db):
    _company(db, name="NoConf")  # never enriched — NULL confidence
    _company(
        db, name="Low", enriched_at=datetime.now(UTC), enrichment_confidence=Decimal("0.40")
    )
    _company(
        db, name="High", enriched_at=datetime.now(UTC), enrichment_confidence=Decimal("0.95")
    )
    db.commit()

    body = api_client.get(
        "/api/companies?sort_by=enrichment_confidence&sort_dir=desc"
    ).json()
    assert [c["name"] for c in body["items"]] == ["High", "Low", "NoConf"]  # NULLs last

    body = api_client.get(
        "/api/companies?sort_by=enrichment_confidence&sort_dir=asc"
    ).json()
    assert [c["name"] for c in body["items"]] == ["Low", "High", "NoConf"]  # NULLs still last

    # unknown column falls back to the default name sort
    body = api_client.get("/api/companies?sort_by=bogus").json()
    assert [c["name"] for c in body["items"]] == ["High", "Low", "NoConf"]


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
    """provider-sourced fields are stored but must not be exposed by the public API.

    Redistribution of unique ids / employee counts / corporate hierarchy is restricted
    by the provider's terms, so CompanyOut deliberately omits them.
    """
    c = _company(
        db,
        name="Enriched Co",
        unique_id="123456789",
        employee_count=5000,
        parent_company_name="Parent Holdings",
        parent_unique_id="987654321",
        global_ultimate_name="Global Ultimate Ltd",
        hq_address="1 Main St, Anytown, USA",
        website="https://enriched.example.com",
        sic_code="3559",
    )
    db.commit()

    body = api_client.get(f"/api/companies/{c.id}").json()
    for hidden in (
        "unique_id",
        "employee_count",
        "parent_company_name",
        "parent_unique_id",
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


def test_scraper_status_empty(api_client, db):
    db.commit()
    resp = api_client.get("/api/scraper-runs/status")
    assert resp.status_code == 200
    assert resp.json() == []


def test_scraper_status_aggregates(api_client, db):
    now = datetime.now(UTC)

    def _at(state, status, ago, **kw):
        db.add(
            ScraperRun(
                state=state,
                started_at=now - timedelta(days=ago),
                finished_at=now - timedelta(days=ago),
                status=status,
                **kw,
            )
        )

    # CA: two successes — latest run and last success are both the newer one.
    _at("CA", "ok", 3, rows_scraped=100, rows_new=5)
    _at("CA", "ok", 1, rows_scraped=120, rows_new=8)
    # TX: succeeded once, then its latest run failed — last success is the older ok.
    _at("TX", "ok", 4, rows_scraped=50, rows_new=2)
    _at("TX", "parse_failed", 1, error="bad table")
    # NV: never succeeded.
    _at("NV", "fetch_failed", 2, error="403")
    # CA notice coverage 2010-2026; a superseded row outside that range must
    # not widen it. TX/NV have runs but no notices.
    _notice(db, state="CA", notice_date=date(2010, 6, 1), employer="Old Co")
    _notice(db, state="CA", notice_date=date(2026, 2, 1), employer="New Co")
    superseded = _notice(db, state="CA", notice_date=date(1999, 1, 1), employer="Dupe Co")
    superseded.is_superseded = True
    db.commit()

    body = api_client.get("/api/scraper-runs/status").json()
    assert [r["state"] for r in body] == ["CA", "NV", "TX"]  # sorted, one per state
    rows = {r["state"]: r for r in body}

    ca = rows["CA"]
    assert ca["last_status"] == "ok"
    assert ca["rows_new"] == 8 and ca["rows_scraped"] == 120
    assert ca["last_run_at"] == ca["last_success_at"]
    assert ca["first_notice_date"] == "2010-06-01"  # superseded 1999 row excluded
    assert ca["last_notice_date"] == "2026-02-01"
    # Neither 2010 nor 2011 is followed by a year with notices; 2026 is the latest.
    assert ca["coverage_start"] == "2026-02-01"

    tx = rows["TX"]
    assert tx["last_status"] == "parse_failed"
    assert tx["error"] == "bad table"
    assert tx["last_success_at"] is not None
    assert tx["last_success_at"] < tx["last_run_at"]  # success predates the failure
    assert tx["first_notice_date"] is None and tx["last_notice_date"] is None
    assert tx["coverage_start"] is None

    nv = rows["NV"]
    assert nv["last_status"] == "fetch_failed"
    assert nv["last_success_at"] is None


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


def test_companies_list_layoff_total_rolls_up_and_excludes_superseded(api_client, db):
    canon, dupe = _merged_pair(db)
    _notice(db, company=canon, employer="Acme Inc", layoff_count=100,
            notice_date=date(2026, 1, 1))
    _notice(db, company=dupe, employer="Acme LLC", layoff_count=50,
            notice_date=date(2026, 2, 1))
    sup = _notice(db, company=dupe, employer="Acme LLC", layoff_count=999,
                  notice_date=date(2026, 3, 1))
    sup.is_superseded = True
    db.commit()

    body = api_client.get("/api/companies").json()
    acme = next(i for i in body["items"] if i["name"] == "Acme Inc")
    assert acme["layoff_total"] == 150  # canon's + dupe's active; superseded excluded


def test_companies_sort_by_layoff_total(api_client, db):
    a = _company(db, name="Big Co")
    b = _company(db, name="Small Co")
    _company(db, name="Zero Co")  # no notices → 0, sorts last on desc
    _notice(db, company=a, employer="Big", layoff_count=500, notice_date=date(2026, 1, 1))
    _notice(db, company=b, employer="Small", layoff_count=5, notice_date=date(2026, 1, 2))
    db.commit()

    body = api_client.get("/api/companies?sort_by=layoff_total&sort_dir=desc").json()
    assert [i["name"] for i in body["items"]] == ["Big Co", "Small Co", "Zero Co"]
    assert [i["layoff_total"] for i in body["items"]] == [500, 5, 0]


def test_companies_include_merged_dupes_show_zero(api_client, db):
    _canon, dupe = _merged_pair(db)
    _notice(db, company=dupe, employer="Acme LLC", layoff_count=50,
            notice_date=date(2026, 2, 1))
    db.commit()

    body = api_client.get("/api/companies?include_merged=true").json()
    by_name = {i["name"]: i["layoff_total"] for i in body["items"]}
    # The dupe's notices roll up to its canonical; the dupe row itself shows 0.
    assert by_name == {"Acme Inc": 50, "Acme LLC": 0}


def test_company_detail_layoff_total_not_computed(api_client, db):
    a = _company(db, name="Acme Inc")
    _notice(db, company=a, employer="Acme", layoff_count=10, notice_date=date(2026, 1, 1))
    db.commit()

    # Only the list route computes the rollup; detail returns null, not zero.
    body = api_client.get(f"/api/companies/{a.id}").json()
    assert body["layoff_total"] is None


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


def test_notices_min_layoffs_filter(api_client, db):
    _notice(db, employer="Big Co", notice_date=date(2026, 1, 1), layoff_count=500)
    _notice(db, employer="Small Co", notice_date=date(2026, 1, 2), layoff_count=20)
    # No reported headcount — excluded by any threshold (NULL fails >=).
    _notice(db, employer="Unknown Co", notice_date=date(2026, 1, 3), layoff_count=None)
    db.commit()

    body = api_client.get("/api/notices?min_layoffs=100").json()
    assert body["total"] == 1  # the count query applies the same filter
    assert [i["employer"] for i in body["items"]] == ["Big Co"]
    assert api_client.get("/api/notices?min_layoffs=0").status_code == 422


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


def test_map_pins_float_coords_and_cache_header(api_client, db):
    _geocoded_notice(db, None, "LA Co", lat=34.05212, lon=-118.24399)
    db.commit()

    resp = api_client.get("/api/map-pins")
    # Scrapes land a few fixed times a day; 5 minutes of staleness is invisible.
    assert resp.headers["cache-control"] == "public, max-age=300"
    pin = resp.json()[0]
    # lat/lon are real JSON numbers at 5 dp — not Decimal-as-string — matching
    # the frontend's `lat: number` type.
    assert pin["lat"] == 34.05212
    assert pin["lon"] == -118.24399
    assert pin["notice_date"] == "2026-01-01"


def test_map_places_aggregates_colocated_notices(api_client, db):
    # Two notices at one (city-centroid) point, one elsewhere, one superseded.
    a = _geocoded_notice(db, None, "Alpha Co", lat=34.05212, lon=-118.24399)
    b = _geocoded_notice(db, None, "Beta Co", lat=34.05213, lon=-118.24401)
    b.layoff_count = None  # counts as a notice, adds no workers
    _geocoded_notice(db, None, "Gamma Co", lat=40.7, lon=-74.0)
    sup = _geocoded_notice(db, None, "Delta Co", lat=40.7, lon=-74.0)
    sup.is_superseded = True
    db.get(Location, a.location_id).city = "Los Angeles"
    db.commit()

    resp = api_client.get("/api/map-places")
    assert resp.headers["cache-control"] == "public, max-age=300"
    body = resp.json()
    places = sorted(zip(
        body["lat"], body["lon"], body["notices"], body["workers"], body["label"], strict=True
    ))
    # Busiest place first in the payload; points 1e-5 apart merge at 4 dp.
    assert body["notices"] == [2, 1]
    assert places == [
        (34.0521, -118.244, 2, 100, "Los Angeles, CA"),
        (40.7, -74.0, 1, 100, "CA"),
    ]


def test_map_places_filters(api_client, db):
    _geocoded_notice(db, None, "Closing Co", closure_category="Closure", lat=34.0, lon=-118.0)
    _geocoded_notice(db, None, "Layoff Co", closure_category="Layoff", lat=40.7, lon=-74.0)
    db.commit()

    body = api_client.get("/api/map-places?closure_category=Closure").json()
    assert (body["lat"], body["notices"]) == ([34.0], [1])
    assert api_client.get("/api/map-places?after=2027-01-01").json()["lat"] == []
    # _notice() reports 100 workers per notice.
    assert len(api_client.get("/api/map-places?min_layoffs=100").json()["lat"]) == 2
    assert api_client.get("/api/map-places?min_layoffs=101").json()["lat"] == []


def test_status_coverage_start_skips_stray_early_rows(api_client, db):
    _run(db, "CA")
    _notice(db, state="CA", notice_date=date(1997, 3, 1), employer="Stray Co")
    _notice(db, state="CA", notice_date=date(2000, 2, 9), employer="A Co")
    _notice(db, state="CA", notice_date=date(2000, 5, 1), employer="B Co")
    _notice(db, state="CA", notice_date=date(2001, 1, 3), employer="C Co")
    db.commit()

    ca = api_client.get("/api/scraper-runs/status").json()[0]
    assert ca["first_notice_date"] == "1997-03-01"
    assert ca["coverage_start"] == "2000-02-09"


def test_map_places_timeline_buckets_and_sparse_cells(api_client, db):
    la = _geocoded_notice(db, None, "Alpha Co", lat=34.05212, lon=-118.24399)
    la.notice_date = date(2020, 2, 10)
    db.get(Location, la.location_id).city = "Los Angeles"
    la2 = _geocoded_notice(db, None, "Beta Co", lat=34.05213, lon=-118.24401)
    la2.notice_date = date(2020, 3, 5)
    la2.layoff_count = None  # a notice, no workers
    ny = _geocoded_notice(db, None, "Gamma Co", lat=40.7, lon=-74.0)
    ny.notice_date = date(2020, 11, 1)
    sup = _geocoded_notice(db, None, "Delta Co", lat=40.7, lon=-74.0)
    sup.notice_date = date(2020, 11, 2)
    sup.is_superseded = True
    rr = _geocoded_notice(db, None, "Rapid Co", closure_category="Non-WARN", lat=40.7, lon=-74.0)
    rr.notice_date = date(2020, 11, 3)
    db.commit()

    resp = api_client.get("/api/map-places/timeline")
    assert resp.headers["cache-control"] == "public, max-age=300"
    body = resp.json()
    # Quarterly by default, contiguous: the empty Q2/Q3 are still frames.
    assert body["periods"] == ["2020-Q1", "2020-Q2", "2020-Q3", "2020-Q4"]
    cells = {
        (body["label"][p], body["periods"][t], n, w)
        for p, t, n, w in zip(
            body["place"], body["period"], body["notices"], body["workers"], strict=True
        )
    }
    # Feb + Mar at one point merge into one Q1 cell; Non-WARN and superseded
    # notices are left out.
    assert cells == {("Los Angeles, CA", "2020-Q1", 2, 100), ("CA", "2020-Q4", 1, 100)}

    months = api_client.get("/api/map-places/timeline?bucket=month").json()
    assert months["periods"][0] == "2020-02" and months["periods"][-1] == "2020-11"
    assert len(months["periods"]) == 10
    assert len(months["notices"]) == 3
    assert api_client.get("/api/map-places/timeline?bucket=year").json()["periods"] == ["2020"]
    # Non-WARN only when asked for.
    nw = api_client.get("/api/map-places/timeline?closure_category=Non-WARN").json()
    assert nw["notices"] == [1]
    assert api_client.get("/api/map-places/timeline?bucket=week").status_code == 422


def test_map_places_timeline_filters(api_client, db):
    mfg = _company(db, "Mfg", naics_code="311999")
    ret = _company(db, "Ret", naics_code="445110")
    _geocoded_notice(db, mfg, "Mfg Co", lat=34.0, lon=-118.0)
    _geocoded_notice(db, ret, "Ret Co", lat=40.7, lon=-74.0)
    _geocoded_notice(db, None, "Unknown Co", lat=41.8, lon=-87.6)
    db.commit()

    body = api_client.get("/api/map-places/timeline?industry=31-33").json()
    assert (body["lat"], body["notices"]) == ([34.0], [1])
    assert api_client.get("/api/map-places/timeline?after=2027-01-01").json() == {
        "lat": [], "lon": [], "label": [], "periods": [],
        "place": [], "period": [], "notices": [], "workers": [],
    }


def test_industries_timeline_includes_unclassified(api_client, db):
    mfg = _company(db, "Mfg", naics_code="311999")
    junk = _company(db, "Junk", naics_code="99")  # in no sector
    bare = _company(db, "Bare")  # enriched without a NAICS code
    _notice(db, company=mfg, employer="Mfg A", notice_date=date(2024, 1, 5), layoff_count=40)
    _notice(db, company=mfg, employer="Mfg B", notice_date=date(2024, 12, 5), layoff_count=60)
    _notice(db, company=junk, employer="Junk Co", notice_date=date(2024, 2, 1), layoff_count=7)
    _notice(db, company=bare, employer="Bare Co", notice_date=date(2024, 2, 2), layoff_count=None)
    _notice(db, employer="Nobody", notice_date=date(2024, 3, 1), layoff_count=3)
    _notice(db, employer="Rapid", notice_date=date(2024, 3, 2), closure_category="Non-WARN")
    gone = _notice(db, company=mfg, employer="Mfg Old", notice_date=date(2024, 6, 1))
    gone.is_superseded = True
    db.commit()

    body = api_client.get("/api/stats/industries/timeline").json()
    assert body["periods"] == ["2024-Q1", "2024-Q2", "2024-Q3", "2024-Q4"]
    rows = {r["sector"]: r for r in body["sectors"]}
    assert list(rows) == ["31-33", "unclassified"]  # NAICS order, unclassified last
    assert rows["31-33"]["name"] == "Manufacturing"
    assert rows["31-33"]["notices"] == [1, 0, 0, 1]
    assert rows["31-33"]["workers"] == [40, 0, 0, 60]
    assert rows["unclassified"]["name"] == "Unclassified"
    assert rows["unclassified"]["notices"] == [3, 0, 0, 0]
    assert rows["unclassified"]["workers"] == [10, 0, 0, 0]

    year = api_client.get("/api/stats/industries/timeline?bucket=year&state=TX").json()
    assert year == {"periods": [], "sectors": []}
    month = api_client.get("/api/stats/industries/timeline?bucket=month&before=2024-01-31").json()
    assert month["periods"] == ["2024-01"]
    assert [r["sector"] for r in month["sectors"]] == ["31-33"]



@pytest.fixture()
def timeline_clock(monkeypatch):
    """A settable clock for the timeline caches' expiry."""
    import types

    from warn_v2.api import timeline

    now = [1000.0]
    monkeypatch.setattr(timeline, "time", types.SimpleNamespace(monotonic=lambda: now[0]))
    return now


def test_map_places_timeline_cache_hit_returns_identical_json(api_client, db):
    _geocoded_notice(db, None, "Alpha Co", lat=34.0, lon=-118.0)
    db.commit()
    first = api_client.get("/api/map-places/timeline")
    assert first.headers["content-type"] == "application/json"

    # A notice landing inside the TTL isn't seen: the cached bytes are served.
    _geocoded_notice(db, None, "Beta Co", lat=40.7, lon=-74.0)
    db.commit()
    second = api_client.get("/api/map-places/timeline")
    assert second.content == first.content
    assert second.json()["notices"] == [1]
    assert second.headers["cache-control"] == "public, max-age=300"

    # Other buckets roll up from the cached month grouping: no new query.
    assert api_client.get("/api/map-places/timeline?bucket=year").json()["notices"] == [1]


def test_map_places_timeline_cache_misses_on_a_different_filter(api_client, db):
    mfg = _company(db, "Mfg", naics_code="311999")
    _geocoded_notice(db, mfg, "Alpha Co", lat=34.0, lon=-118.0)
    db.commit()
    assert api_client.get("/api/map-places/timeline").json()["notices"] == [1]

    _geocoded_notice(db, mfg, "Beta Co", lat=40.7, lon=-74.0)
    db.commit()
    assert api_client.get("/api/map-places/timeline?industry=31-33").json()["notices"] == [1, 1]
    assert len(api_client.get("/api/map-places/timeline?after=2025-01-01").json()["lat"]) == 2
    # The unfiltered entry is untouched.
    assert api_client.get("/api/map-places/timeline").json()["notices"] == [1]


def test_map_places_timeline_cache_expiry_refetches(api_client, db, timeline_clock):
    from warn_v2.api.timeline import TTL_S

    _geocoded_notice(db, None, "Alpha Co", lat=34.0, lon=-118.0)
    db.commit()
    assert api_client.get("/api/map-places/timeline").json()["notices"] == [1]
    _geocoded_notice(db, None, "Beta Co", lat=40.7, lon=-74.0)
    db.commit()

    timeline_clock[0] += TTL_S - 1
    assert api_client.get("/api/map-places/timeline").json()["notices"] == [1]
    timeline_clock[0] += 2
    assert api_client.get("/api/map-places/timeline").json()["notices"] == [1, 1]


def test_industries_timeline_cache_hit_miss_and_expiry(api_client, db, timeline_clock):
    from warn_v2.api.timeline import TTL_S

    _notice(db, employer="Alpha", notice_date=date(2024, 1, 5), layoff_count=10)
    db.commit()
    first = api_client.get("/api/stats/industries/timeline")
    assert first.json()["sectors"][0]["notices"] == [1]

    _notice(db, employer="Beta", notice_date=date(2024, 1, 6), layoff_count=20)
    db.commit()
    assert api_client.get("/api/stats/industries/timeline").content == first.content
    by_state = api_client.get("/api/stats/industries/timeline?state=CA").json()
    assert by_state["sectors"][0]["notices"] == [2]

    timeline_clock[0] += TTL_S + 1
    assert api_client.get("/api/stats/industries/timeline").json()["sectors"][0]["workers"] == [30]


@pytest.mark.parametrize(
    "url", ["/api/map-places/timeline", "/api/stats/industries/timeline?bucket=month"]
)
def test_timeline_serves_cached_gzip_or_plain_json(api_client, db, url):
    import gzip

    # Enough places and months that the gzip bytes clear GZipMiddleware's
    # 1 KiB minimum, so a second compression would show.
    for k in range(300):
        n = _geocoded_notice(db, None, f"Co {k}", lat=30 + k * 0.0137, lon=-120 + k * 0.0291)
        n.notice_date = date(2000 + k // 12, k % 12 + 1, 1)
        n.layoff_count = k * 7 % 500
    db.commit()
    plain = api_client.get(url, headers={"Accept-Encoding": "identity"})
    assert "content-encoding" not in plain.headers
    assert plain.headers["vary"] == "Accept-Encoding"  # from GZipMiddleware
    assert plain.json()["periods"]

    with api_client.stream("GET", url, headers={"Accept-Encoding": "gzip"}) as resp:
        raw = b"".join(resp.iter_raw())
    assert resp.headers["content-encoding"] == "gzip"
    assert resp.headers["vary"] == "Accept-Encoding"
    assert len(raw) > 1024
    # One gzip layer -- GZipMiddleware didn't compress the cached bytes again.
    assert gzip.decompress(raw) == plain.content
    # And they are the cached copy (mtime=0), not the middleware's (timestamped).
    assert raw == gzip.compress(plain.content, compresslevel=6, mtime=0)


def test_timeline_cache_byte_cap_counts_raw_and_gzip():
    from warn_v2.api.timeline import Body, TTLCache

    body = Body(b"x" * 600, b"y" * 400)
    cache = TTLCache(max_entries=10, max_bytes=1500)
    calls = []
    for key in ("a", "b", "a"):
        cache.get_or_compute(key, lambda k=key: calls.append(k) or body)
    # 2 x 1,000 bytes > 1,500, so "b" evicted "a".
    assert calls == ["a", "b", "a"]


def test_timeline_cache_evicts_least_recently_used():
    from warn_v2.api.timeline import TTLCache

    cache = TTLCache(max_entries=2)
    calls = []

    def get(key):
        return cache.get_or_compute(key, lambda: calls.append(key) or key)

    get("default"), get("tap1")
    get("default")  # a hit keeps the hot entry
    get("tap2")  # evicts tap1, not default
    get("default")
    get("tap1")
    assert calls == ["default", "tap1", "tap2", "tap1"]


def test_timeline_warmer_fills_and_refreshes_the_defaults(api_client, db, db_session_factory):
    from warn_v2.api import timeline_warm

    _geocoded_notice(db, None, "Alpha Co", lat=34.0, lon=-118.0)
    db.commit()
    timeline_warm.warm_once()
    _geocoded_notice(db, None, "Beta Co", lat=40.7, lon=-74.0)
    db.commit()

    # /timelapse's default request is served from the warmed entry...
    url = "/api/map-places/timeline?bucket=quarter&after=2015-01-01"
    assert api_client.get(url).json()["notices"] == [1]
    assert api_client.get(
        "/api/stats/industries/timeline?bucket=month&after=1999-01-01"
    ).json()["sectors"][0]["notices"] == [1]
    # ...and the next warm-up replaces it with fresh data.
    timeline_warm.warm_once()
    assert api_client.get(url).json()["notices"] == [1, 1]


def test_notices_bbox_filter(api_client, db):
    _geocoded_notice(db, None, "LA Co", lat=34.0, lon=-118.2)
    _geocoded_notice(db, None, "NYC Co", lat=40.7, lon=-74.0)
    _notice(db, employer="Nowhere Co")  # not geocoded
    db.commit()

    def employers(q: str) -> tuple[set[str], int]:
        body = api_client.get("/api/notices" + q).json()
        return {n["employer"] for n in body["items"]}, body["total"]

    assert employers("") == ({"LA Co", "NYC Co", "Nowhere Co"}, 3)
    assert employers("?min_lat=40&max_lat=41&min_lon=-75&max_lon=-73") == ({"NYC Co"}, 1)
    # Partial box is ignored, not half-applied.
    assert employers("?min_lat=40&max_lat=41&min_lon=-75")[1] == 3


def test_gzip_enabled_for_large_responses(api_client):
    # Any body ≥1 KiB qualifies; openapi.json is always large enough.
    resp = api_client.get("/openapi.json", headers={"Accept-Encoding": "gzip"})
    assert resp.headers["content-encoding"] == "gzip"


def test_company_summary_rolls_up_merged_and_excludes_superseded(api_client, db):
    canon, dupe = _merged_pair(db)
    _notice(db, company=canon, employer="Acme Inc", state="CA", layoff_count=100,
            notice_date=date(2025, 3, 1))
    _notice(db, company=dupe, employer="Acme LLC", state="TX", layoff_count=50,
            notice_date=date(2026, 2, 1))
    _notice(db, company=canon, employer="Acme Inc", state="CA", layoff_count=None,
            notice_date=date(2026, 4, 1))
    gone = _notice(db, company=canon, employer="Acme Old", state="CA", layoff_count=999,
                   notice_date=date(2026, 5, 1))
    gone.is_superseded = True
    db.commit()

    body = api_client.get(f"/api/companies/{canon.id}/summary").json()
    assert body["notice_count"] == 3
    assert body["layoff_total"] == 150
    assert body["counted_notices"] == 2  # the None-count notice isn't counted
    assert body["first_notice"] == "2025-03-01"
    assert body["last_notice"] == "2026-04-01"
    assert body["by_year"] == [
        {"year": 2025, "notice_count": 1, "layoff_total": 100},
        {"year": 2026, "notice_count": 2, "layoff_total": 50},
    ]
    assert body["by_state"] == [
        {"state": "CA", "notice_count": 2, "layoff_total": 100},
        {"state": "TX", "notice_count": 1, "layoff_total": 50},
    ]


def test_company_summary_empty_and_not_found(api_client, db):
    c = _company(db)
    db.commit()
    body = api_client.get(f"/api/companies/{c.id}/summary").json()
    assert body == {
        "notice_count": 0, "layoff_total": 0, "counted_notices": 0, "first_notice": None,
        "last_notice": None, "by_year": [], "by_state": [],
    }
    assert api_client.get("/api/companies/999999/summary").status_code == 404
