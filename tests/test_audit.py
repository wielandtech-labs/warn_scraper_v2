"""Tests for the per-state data-quality audit."""
from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

from warn_v2.db.models import Company, Location, Notice, ScraperRun
from warn_v2.scripts.audit import audit_states, render_markdown, render_table

# A fixed reference "today" so date-sensitive assertions don't depend on the
# real clock.
REF = date(2026, 6, 15)


def _notice(db, *, nid, state="CA", **kw) -> Notice:
    defaults = dict(employer="Acme", notice_date=date(2026, 1, 1))
    defaults.update(kw)
    n = Notice(notice_id=nid, state=state, **defaults)
    db.add(n)
    db.flush()
    return n


def _one(audits, state):
    return next(a for a in audits if a.state == state)


# ---------------------------------------------------------------------------
# Counts, supersede, fill-rates
# ---------------------------------------------------------------------------

def test_active_vs_superseded(db) -> None:
    _notice(db, nid="a1", state="CA")
    _notice(db, nid="a2", state="CA", is_superseded=True)
    db.commit()

    ca = _one(audit_states(db, state_filter="CA", today=REF), "CA")
    assert ca.active == 1
    assert ca.superseded == 1
    assert "has_superseded" in ca.flags


def test_fill_rates_counted(db) -> None:
    _notice(
        db, nid="f1", state="CA",
        effective_date=date(2026, 3, 1), layoff_count=100,
        closure_type="Closure", address="1 Main St", raw_notice_url="http://x/1.pdf",
    )
    _notice(db, nid="f2", state="CA")  # mostly null
    db.commit()

    ca = _one(audit_states(db, state_filter="CA", today=REF), "CA")
    assert ca.fill["effective_date"] == 1
    assert ca.fill["layoff_count"] == 1
    assert ca.fill["closure_type"] == 1
    assert ca.fill["address"] == 1
    assert ca.fill["raw_notice_url"] == 1
    d = ca.to_dict()
    assert d["fill_rates"]["effective_date"] == 0.5


# ---------------------------------------------------------------------------
# Estimated-date detection (notice_date + 60d)
# ---------------------------------------------------------------------------

def test_estimated_date_ratio(db) -> None:
    nd = date(2026, 1, 1)
    _notice(db, nid="e1", state="CA", notice_date=nd, effective_date=nd + timedelta(days=60))
    _notice(db, nid="e2", state="CA", notice_date=nd, effective_date=nd + timedelta(days=90))
    db.commit()

    ca = _one(audit_states(db, state_filter="CA", today=REF), "CA")
    assert ca.estimated_dates == 1
    assert ca.to_dict()["estimated_date_ratio"] == 0.5


def test_mostly_estimated_dates_flag(db) -> None:
    nd = date(2026, 1, 1)
    for i in range(3):
        _notice(db, nid=f"m{i}", state="CA", notice_date=nd,
                effective_date=nd + timedelta(days=60))
    db.commit()

    ca = _one(audit_states(db, state_filter="CA", today=REF), "CA")
    assert "mostly_estimated_dates" in ca.flags


# ---------------------------------------------------------------------------
# PDF coverage
# ---------------------------------------------------------------------------

def test_pdf_coverage_and_flag(db) -> None:
    _notice(db, nid="p1", state="CA", raw_notice_url="http://x/1.pdf", pdf_path="ca/p1.pdf")
    _notice(db, nid="p2", state="CA", raw_notice_url="http://x/2.pdf")  # missing pdf
    db.commit()

    ca = _one(audit_states(db, state_filter="CA", today=REF), "CA")
    assert ca.pdf_eligible == 2
    assert ca.pdf_have == 1
    assert ca.to_dict()["pdf_coverage"] == 0.5
    assert "missing_pdf" in ca.flags


# ---------------------------------------------------------------------------
# Geocoding: coverage, null coords, out-of-state
# ---------------------------------------------------------------------------

def test_geo_coverage_and_out_of_state(db) -> None:
    in_state = Location(state="CA", city="Oakland", lat=37.8, lon=-122.27)
    out_state = Location(state="CA", city="Bad", lat=40.0, lon=-89.0)  # in IL bbox
    no_coords = Location(state="CA", city="Nowhere")
    db.add_all([in_state, out_state, no_coords])
    db.flush()
    _notice(db, nid="g1", state="CA", location_id=in_state.id)
    _notice(db, nid="g2", state="CA", location_id=out_state.id)
    _notice(db, nid="g3", state="CA", location_id=no_coords.id)
    db.commit()

    ca = _one(audit_states(db, state_filter="CA", today=REF), "CA")
    assert ca.geocoded == 2
    assert ca.null_coords == 1
    assert ca.out_of_state == 1
    assert "out_of_state_coords" in ca.flags
    assert "low_geo" in ca.flags


def test_geo_by_source_breakdown(db) -> None:
    """geo_by_source counts geocoded notices by tier; null source → 'unknown'."""
    loc_zip = Location(state="CA", city="Oakland", lat=37.8, lon=-122.27, geocode_source="zip")
    loc_city = Location(state="CA", city="LA", lat=34.0, lon=-118.2, geocode_source="city")
    loc_old = Location(state="CA", city="SF", lat=37.77, lon=-122.41)  # pre-migration, no source
    db.add_all([loc_zip, loc_city, loc_old])
    db.flush()
    _notice(db, nid="gs1", state="CA", location_id=loc_zip.id)
    _notice(db, nid="gs2", state="CA", location_id=loc_city.id)
    _notice(db, nid="gs3", state="CA", location_id=loc_old.id)
    db.commit()

    ca = _one(audit_states(db, state_filter="CA", today=REF), "CA")
    assert ca.geocoded == 3
    assert ca.geo_by_source == {"zip": 1, "city": 1, "unknown": 1}
    d = ca.to_dict()
    assert d["geo_by_source"] == {"zip": 1, "city": 1, "unknown": 1}


# ---------------------------------------------------------------------------
# Per-year gap detection
# ---------------------------------------------------------------------------

def test_year_gap_detection(db) -> None:
    _notice(db, nid="y1", state="CA", notice_date=date(2022, 5, 1))
    _notice(db, nid="y2", state="CA", notice_date=date(2024, 5, 1))  # 2023 missing
    db.commit()

    ca = _one(audit_states(db, state_filter="CA", today=REF), "CA")
    assert ca.first_year == 2022
    assert ca.last_year == 2024
    assert ca.empty_years == [2023]
    assert "year_gaps" in ca.flags


# ---------------------------------------------------------------------------
# Sanity flags
# ---------------------------------------------------------------------------

def test_sanity_flags(db) -> None:
    # s1 is in the future relative to REF (2026-06-15); s2's dates are both in the
    # past, with effective < notice.
    _notice(db, nid="s1", state="CA", notice_date=date(2027, 1, 1))
    _notice(db, nid="s2", state="CA", notice_date=date(2026, 3, 1),
            effective_date=date(2026, 1, 1))  # effective before notice
    _notice(db, nid="s3", state="CA", notice_date=date(2026, 1, 1), layoff_count=0)
    _notice(db, nid="s4", state="CA", notice_date=date(2026, 1, 1), layoff_count=999999)
    db.commit()

    ca = _one(audit_states(db, state_filter="CA", today=REF), "CA")
    assert ca.future_dates == 1
    assert ca.eff_before_notice == 1
    assert ca.count_outliers == 2
    assert "date_sanity" in ca.flags
    assert "count_outliers" in ca.flags


# ---------------------------------------------------------------------------
# Scraper health: status + row drift
# ---------------------------------------------------------------------------

def test_scraper_status_and_row_drift(db) -> None:
    # GA's expected_row_range is (100, 500); a 25-row "ok" run is silent drift.
    now = datetime.now(UTC)
    db.add(ScraperRun(state="GA", started_at=now - timedelta(hours=2),
                      status="ok", rows_scraped=400))
    db.add(ScraperRun(state="GA", started_at=now, status="ok", rows_scraped=25))
    db.add(Notice(notice_id="ga1", state="GA", employer="X", notice_date=date(2026, 1, 1)))
    db.commit()

    ga = _one(audit_states(db, state_filter="GA", today=REF), "GA")
    assert ga.last_rows == 25  # newest run wins
    assert "row_drift" in ga.flags


def test_scraper_failure_flag(db) -> None:
    now = datetime.now(UTC)
    db.add(ScraperRun(state="GA", started_at=now, status="fetch_failed",
                      error="blocked", rows_scraped=None))
    db.add(Notice(notice_id="ga2", state="GA", employer="X", notice_date=date(2026, 1, 1)))
    db.commit()

    ga = _one(audit_states(db, state_filter="GA", today=REF), "GA")
    assert "scraper_fetch_failed" in ga.flags


# ---------------------------------------------------------------------------
# Enrichment
# ---------------------------------------------------------------------------

def test_enrichment_counted(db) -> None:
    c = Company(name="Acme", enriched_at=datetime.now(UTC), naics_code="3361")
    db.add(c)
    db.flush()
    _notice(db, nid="c1", state="CA", company_id=c.id)
    _notice(db, nid="c2", state="CA")  # no company
    _notice(db, nid="c3", state="CA")  # no company -> 1/3 enriched < 0.5
    db.commit()

    ca = _one(audit_states(db, state_filter="CA", today=REF), "CA")
    assert ca.company_enriched == 1
    assert ca.fill["naics_code"] == 1
    assert "low_enrichment" in ca.flags


def test_no_data_flag_for_registered_state_without_notices(db) -> None:
    # AK is a registered scraper; with no notices it should surface as no_data.
    db.commit()
    ak = _one(audit_states(db, state_filter="AK", today=REF), "AK")
    assert "no_data" in ak.flags


def test_blocked_flag_when_blocked_state_has_rows(db) -> None:
    # Blocked states (AR/NH/OK/TN/WY) aren't registered, so they only appear in
    # the audit if legacy notices exist (e.g. TN, whose scraper was built before
    # the IP block). When they do appear, the blocked flag must fire.
    _notice(db, nid="tn1", state="TN", notice_date=date(2026, 1, 1))
    db.commit()
    tn = _one(audit_states(db, today=REF), "TN")
    assert "blocked" in tn.flags


# ---------------------------------------------------------------------------
# Rendering smoke tests
# ---------------------------------------------------------------------------

def test_render_outputs(db) -> None:
    _notice(db, nid="r1", state="CA", notice_date=date(2026, 1, 1), layoff_count=10)
    db.commit()
    audits = audit_states(db, state_filter="CA", today=REF)
    table = render_table(audits)
    md = render_markdown(audits)
    assert "CA" in table
    assert "| CA |" in md
    assert "Status" in md
