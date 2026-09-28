"""Tests for the BLS ingester (warn-v2 fetch-bls)."""
from __future__ import annotations

import json

import httpx
import pytest
import respx
from sqlalchemy import func, select

from warn_v2.db.models import BlsSeries
from warn_v2.labor import ingest
from warn_v2.labor.bls_api import BLS_API_URL

SERIES_A = "LNS14000000"
SERIES_B = "JTS000000000000000LDL"


@pytest.fixture(autouse=True)
def _catalog_subset(monkeypatch: pytest.MonkeyPatch):
    """Keep the fake API surface small and explicit."""
    monkeypatch.setattr(ingest, "all_series", lambda: [SERIES_A, SERIES_B])
    monkeypatch.delenv("BLS_API_KEY", raising=False)


def _series(series_id: str, points: dict[str, str]) -> dict:
    return {
        "seriesID": series_id,
        "data": [
            {"year": m[:4], "period": f"M{m[5:]}", "value": v}
            for m, v in points.items()
        ],
    }


def _ok(series: list[dict]) -> dict:
    return {"status": "REQUEST_SUCCEEDED", "Results": {"series": series}}


@respx.mock
def test_refresh_writes_rows(db):
    respx.post(BLS_API_URL).respond(
        json=_ok(
            [
                _series(SERIES_A, {"2026-05": "4.1", "2026-06": "4.2"}),
                _series(SERIES_B, {"2026-05": "1600", "2026-06": "1650"}),
            ]
        )
    )
    result = ingest.refresh_bls(db, start_year=2026, end_year=2026)

    assert result.requested == 2
    assert result.with_data == 2
    assert result.coverage == 1.0
    assert result.empty_series == []
    assert result.rows_written == 4
    stored = dict(
        db.execute(
            select(BlsSeries.period, BlsSeries.value).where(
                BlsSeries.series_id == SERIES_A
            )
        ).all()
    )
    assert stored == {"2026-05": 4.1, "2026-06": 4.2}


@respx.mock
def test_refresh_upserts_revised_values(db):
    """BLS re-benchmarks, so a refetch must update in place, not duplicate."""
    respx.post(BLS_API_URL).respond(
        json=_ok([_series(SERIES_A, {"2026-05": "4.1"}), _series(SERIES_B, {"2026-05": "1600"})])
    )
    ingest.refresh_bls(db, start_year=2026, end_year=2026)

    respx.post(BLS_API_URL).respond(
        json=_ok([_series(SERIES_A, {"2026-05": "4.3"}), _series(SERIES_B, {"2026-05": "1600"})])
    )
    ingest.refresh_bls(db, start_year=2026, end_year=2026)

    rows = db.execute(
        select(BlsSeries.value).where(
            BlsSeries.series_id == SERIES_A, BlsSeries.period == "2026-05"
        )
    ).all()
    assert rows == [(4.3,)]
    total = db.execute(select(func.count()).select_from(BlsSeries)).scalar_one()
    assert total == 2


@respx.mock
def test_annual_average_rows_are_skipped(db):
    """M13 is the annual average, not a month — it must not become a period."""
    respx.post(BLS_API_URL).respond(
        json=_ok(
            [
                {
                    "seriesID": SERIES_A,
                    "data": [
                        {"year": "2026", "period": "M13", "value": "4.0"},
                        {"year": "2026", "period": "M06", "value": "4.2"},
                    ],
                },
                _series(SERIES_B, {"2026-06": "1650"}),
            ]
        )
    )
    ingest.refresh_bls(db, start_year=2026, end_year=2026)
    periods = db.execute(
        select(BlsSeries.period).where(BlsSeries.series_id == SERIES_A)
    ).scalars().all()
    assert periods == ["2026-06"]


@respx.mock
def test_low_coverage_raises(db):
    """A wrong series id returns an empty `data` list, never an error — so the
    job has to fail on coverage or it would silently write nothing."""
    respx.post(BLS_API_URL).respond(
        json=_ok([_series(SERIES_A, {}), _series(SERIES_B, {})])
    )
    with pytest.raises(RuntimeError, match="0/2 series"):
        ingest.refresh_bls(db, start_year=2026, end_year=2026)
    assert db.execute(select(func.count()).select_from(BlsSeries)).scalar_one() == 0


@respx.mock
def test_partial_coverage_is_tolerated(db, monkeypatch):
    """State JOLTS lags the national series by months, so some series being
    empty in a narrow window is normal."""
    monkeypatch.setattr(ingest, "MIN_EXPECTED_COVERAGE", 0.5)
    respx.post(BLS_API_URL).respond(
        json=_ok([_series(SERIES_A, {"2026-06": "4.2"}), _series(SERIES_B, {})])
    )
    result = ingest.refresh_bls(db, start_year=2026, end_year=2026)
    assert result.with_data == 1
    assert result.empty_series == [SERIES_B]


@respx.mock
def test_api_failure_raises(db):
    """Unlike reports/bls.py this must NOT fail open — fetching is the job."""
    respx.post(BLS_API_URL).mock(side_effect=httpx.ConnectError("down"))
    with pytest.raises(httpx.ConnectError):
        ingest.refresh_bls(db, start_year=2026, end_year=2026)


@respx.mock
def test_api_error_status_raises(db):
    respx.post(BLS_API_URL).respond(
        json={"status": "REQUEST_NOT_PROCESSED", "message": ["daily threshold"]}
    )
    with pytest.raises(RuntimeError, match="REQUEST_NOT_PROCESSED"):
        ingest.refresh_bls(db, start_year=2026, end_year=2026)


@respx.mock
def test_long_span_is_split_into_api_sized_windows(db):
    """Unkeyed requests cap at 10 years, so a full backfill must be chunked."""
    route = respx.post(BLS_API_URL).respond(
        json=_ok([_series(SERIES_A, {"2026-06": "4.2"}), _series(SERIES_B, {"2026-06": "1650"})])
    )
    ingest.refresh_bls(db, start_year=2000, end_year=2026)
    assert route.call_count == 3  # 2000-2009, 2010-2019, 2020-2026
    for call in route.calls:
        body = json.loads(call.request.content)
        assert int(body["endyear"]) - int(body["startyear"]) < 10


def test_reversed_year_range_rejected(db):
    with pytest.raises(ValueError):
        ingest.refresh_bls(db, start_year=2026, end_year=2020)
