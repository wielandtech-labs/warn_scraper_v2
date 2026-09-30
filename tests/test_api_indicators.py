"""Tests for /stats/indicators — the BLS context behind the companion charts."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from warn_v2.db.models import BlsSeries
from warn_v2.labor import catalog


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


def _points(db, series_id: str, points: dict[str, float]) -> None:
    for period, value in points.items():
        db.add(BlsSeries(series_id=series_id, period=period, value=value))
    db.commit()


def test_empty_table_returns_empty_list(api_client):
    """Before the first fetch-bls run the cards must render nothing, not error."""
    resp = api_client.get("/api/stats/indicators?dataset=unemployment")
    assert resp.status_code == 200
    assert resp.json() == []


def test_national_unemployment_pairs_u3_and_u6(api_client, db):
    _points(db, catalog.US_U3_SERIES, {"2026-05": 4.1, "2026-06": 4.2})
    _points(db, catalog.US_U6_SERIES, {"2026-05": 7.7, "2026-06": 7.8})

    body = api_client.get("/api/stats/indicators?dataset=unemployment").json()
    assert body == [
        {"period": "2026-05", "values": {"u3": 4.1, "u6": 7.7}},
        {"period": "2026-06", "values": {"u3": 4.2, "u6": 7.8}},
    ]


def test_state_unemployment_has_no_u6(api_client, db):
    """BLS publishes no monthly state U-6, so the measure must be absent
    rather than null — the chart drops the line instead of drawing a gap."""
    _points(db, catalog.laus_state_series("CA"), {"2026-06": 5.1})
    _points(db, catalog.US_U6_SERIES, {"2026-06": 7.8})

    body = api_client.get("/api/stats/indicators?dataset=unemployment&state=CA").json()
    assert body == [{"period": "2026-06", "values": {"u3": 5.1}}]


def test_state_code_is_case_insensitive(api_client, db):
    _points(db, catalog.laus_state_series("CA"), {"2026-06": 5.1})
    body = api_client.get("/api/stats/indicators?dataset=unemployment&state=ca").json()
    assert body == [{"period": "2026-06", "values": {"u3": 5.1}}]


def test_jolts_measures(api_client, db):
    _points(db, catalog.jolts_series("layoffs"), {"2026-06": 1666.0})
    _points(db, catalog.jolts_series("openings"), {"2026-06": 7200.0})
    _points(db, catalog.jolts_series("quits"), {"2026-06": 3056.0})

    body = api_client.get("/api/stats/indicators?dataset=jolts").json()
    assert body == [
        {
            "period": "2026-06",
            "values": {"layoffs": 1666.0, "openings": 7200.0, "quits": 3056.0},
        }
    ]


def test_payrolls_follow_the_industry_filter(api_client, db):
    _points(db, catalog.NATIONAL_PAYROLL_SERIES, {"2026-06": 159075.0})
    _points(db, catalog.SECTOR_CES_SERIES["31-33"][0], {"2026-06": 12638.0})

    national = api_client.get("/api/stats/indicators?dataset=payrolls").json()
    assert national == [{"period": "2026-06", "values": {"employment": 159075.0}}]

    mfg = api_client.get(
        "/api/stats/indicators?dataset=payrolls&industry=31-33"
    ).json()
    assert mfg == [{"period": "2026-06", "values": {"employment": 12638.0}}]


def test_sector_without_ces_coverage_returns_empty(api_client, db):
    """NAICS 11 (Agriculture) has no CES series at all."""
    _points(db, catalog.NATIONAL_PAYROLL_SERIES, {"2026-06": 159075.0})
    body = api_client.get("/api/stats/indicators?dataset=payrolls&industry=11").json()
    assert body == []


def test_year_bucket_averages_months(api_client, db):
    _points(db, catalog.US_U3_SERIES, {"2025-01": 4.0, "2025-02": 4.2, "2026-01": 5.0})
    body = api_client.get(
        "/api/stats/indicators?dataset=unemployment&bucket=year"
    ).json()
    assert body == [
        {"period": "2025", "values": {"u3": 4.1}},
        {"period": "2026", "values": {"u3": 5.0}},
    ]


def test_year_bucket_averages_flows_too(api_client, db):
    """Layoffs are a monthly flow an annual *total* would summarise better, but
    the all-time range always ends on a partial year — a sum would plot that as
    a collapse. The mean stays comparable across complete and partial years."""
    _points(
        db,
        catalog.jolts_series("layoffs"),
        {"2025-01": 1500.0, "2025-02": 1700.0, "2026-01": 1600.0},
    )
    body = api_client.get("/api/stats/indicators?dataset=jolts&bucket=year").json()
    assert body == [
        {"period": "2025", "values": {"layoffs": 1600.0}},
        {"period": "2026", "values": {"layoffs": 1600.0}},
    ]


def test_date_filters_bound_the_span(api_client, db):
    _points(
        db,
        catalog.US_U3_SERIES,
        {"2025-11": 4.0, "2025-12": 4.1, "2026-01": 4.2, "2026-02": 4.3},
    )
    body = api_client.get(
        "/api/stats/indicators?dataset=unemployment"
        "&after=2025-12-01&before=2026-01-31"
    ).json()
    assert [r["period"] for r in body] == ["2025-12", "2026-01"]


def test_unknown_dataset_is_rejected(api_client):
    assert api_client.get("/api/stats/indicators?dataset=nonsense").status_code == 422


def test_day_bucket_is_rejected(api_client):
    """Every series here is monthly; a daily axis can't be populated."""
    resp = api_client.get("/api/stats/indicators?dataset=unemployment&bucket=day")
    assert resp.status_code == 422


def test_unknown_state_returns_empty(api_client, db):
    _points(db, catalog.US_U3_SERIES, {"2026-06": 4.2})
    body = api_client.get("/api/stats/indicators?dataset=unemployment&state=ZZ").json()
    assert body == []
